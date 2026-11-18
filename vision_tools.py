# PATTERN: api — DeepSeek vision / uploads 检索 / photo curator extracted from god module (Parallel Change)
# USE WHEN: 图片分类/vision 压缩/上传检索/LLM 语义找图相关改动
# COPY THIS: 无 — 本模块是 server.py §7(清册01)的搬迁体,契约在 server re-export
#
# 抽出记录(2026-07-21, 清册01-§7):
# - 原址 server.py L1130–1483;server.py 保留同名 re-export(Parallel Change expand 阶段)。
#   server.py 暂保同名 re-export 兼容调用方；本模块已不再反向导入组装根。
# - load_config/get_client/get_profile/路径与索引 I/O 由组装根以具名 provider 注入；
#   模块自身函数直接调用，不使用可访问任意属性的 service locator。
# - v4-flash reasoning 吃 max_tokens 疤(L1416-1419 原注)随函数体整段带走。
import base64
import json
import logging
import re

from pathlib import Path

from attachment_service import resolve_attachment_url
from attachments_index import is_ai_visible_attachment
from image_service_errors import ImageServiceError

_LOAD_CONFIG = None
_REPORT_FAILURE = None
_LOGGER = logging.getLogger("vision_tools")
_OPENAI_FACTORY = None
_PICK_ATTACHMENT_URL = None
_ATTACHMENTS_DIR = None
_LOAD_ATTACHMENTS_INDEX = None
_CURATOR_SYSTEM_PATH = None
_REBUILD_CURATOR_PROMPT = None
_GET_PROFILE = None
_GET_CLIENT = None
_LOG_CACHE_USAGE = None
_INDEX_UPSERT = None


def configure_effects(
    *,
    load_config,
    report_failure,
    logger,
    openai_factory,
    pick_attachment_url,
    attachments_dir,
    load_attachments_index,
    curator_system_path,
    rebuild_curator_prompt,
    get_profile,
    get_client,
    log_cache_usage,
    index_upsert,
) -> None:
    global _LOAD_CONFIG, _REPORT_FAILURE, _LOGGER, _OPENAI_FACTORY
    global _PICK_ATTACHMENT_URL, _ATTACHMENTS_DIR, _LOAD_ATTACHMENTS_INDEX
    global _CURATOR_SYSTEM_PATH, _REBUILD_CURATOR_PROMPT
    global _GET_PROFILE, _GET_CLIENT, _LOG_CACHE_USAGE, _INDEX_UPSERT
    _LOAD_CONFIG = load_config
    _REPORT_FAILURE = report_failure
    _LOGGER = logger
    _OPENAI_FACTORY = openai_factory
    _PICK_ATTACHMENT_URL = pick_attachment_url
    _ATTACHMENTS_DIR = attachments_dir
    _LOAD_ATTACHMENTS_INDEX = load_attachments_index
    _CURATOR_SYSTEM_PATH = curator_system_path
    _REBUILD_CURATOR_PROMPT = rebuild_curator_prompt
    _GET_PROFILE = get_profile
    _GET_CLIENT = get_client
    _LOG_CACHE_USAGE = log_cache_usage
    _INDEX_UPSERT = index_upsert


def _compress_for_vision(file_path: Path, max_dim: int = 1024, quality: int = 85) -> bytes:
    """只为 vision API 入口做一次性压缩 — 不改原文件,只返压缩后的 JPEG bytes。
    原图永远在 attachments/ 完整保留(给用户日记图档案用)。
    一张 4000×3000 手机相 ≈ 8 MB → 1024×768 ≈ 100-200 KB,vision token 几乎线性下降。
    """
    from PIL import Image
    import io
    img = Image.open(file_path)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((max_dim, max_dim), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def attachment_to_data_url(file_path: Path) -> str:
    """把本地附件物化为仅存在于本次请求内的压缩 data URL。"""
    try:
        data = _compress_for_vision(file_path)
        mime = "image/jpeg"
    except Exception:
        data = file_path.read_bytes()
        ext = file_path.suffix.lower()
        mime = {".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _deepseek_classify_image(file_path: Path, extra_q: str = "") -> dict:
    """调 DeepSeek V4 Flash Vision 看图,返结构化 JSON。失败返 {error}。
    与主对话共用 gateway-config.json 的 api_key/base_url,不读取旧 Dashscope key。
    入口压缩:1024px max + JPEG q=85,vision token 大降但识别率不掉。
    """
    profile = _GET_PROFILE("deepseek-v4-flash-vision-exp") or {}
    if not profile:
        _REPORT_FAILURE("vision_no_key", "DeepSeek api_key 为空")
        return {"error": "no_deepseek_key",
                "hint": "请去设置填写 DeepSeek API key,对话和识图共用这一把钥匙"}
    base_url = (profile.get("base_url") or "").rstrip("/")
    if base_url not in {
        "https://api.deepseek.com", "https://api.deepseek.com/v1",
    }:
        _REPORT_FAILURE("vision_provider_incompatible",
            "当前主模型 base_url 不是 DeepSeek 官方端点",
            context={"base_url": base_url[:80]})
        return {"error": "vision_provider_incompatible",
                "hint": "DeepSeek 视觉只能使用 DeepSeek 官方直连"}
    if not file_path.exists():
        _REPORT_FAILURE("vision_file_missing",
            f"attachment 文件不存在: {file_path.name}")
        return {"error": f"file not found: {file_path}"}
    # 入口压缩(只动 vision 传输,不动原图)
    use_compressed = True
    try:
        b64 = base64.b64encode(_compress_for_vision(file_path)).decode("ascii")
    except Exception as e:
        _LOGGER().warning(f"compress failed for {file_path}, fallback to raw: {e}")
        use_compressed = False
        try:
            b64 = base64.b64encode(file_path.read_bytes()).decode("ascii")
        except Exception as e2:
            return {"error": f"read file failed: {e2}"}
    if use_compressed:
        mime = "image/jpeg"
    else:
        ext = file_path.suffix.lower().lstrip(".")
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/png")
    data_url = f"data:{mime};base64,{b64}"

    prompt = (
        "看这张图,严格返 JSON 不要任何前后说明,不要 markdown fence。字段:\n"
        "- kind: supplement | food | place | object | selfie | doc | other\n"
        "- description: 中文一句话(20字内)\n"
        "- ocr_likely: bool, 图里是否有显著文字\n"
        "- ocr_text: 看清的文字原文,没有则空字串\n"
        "- suggested_action: scrapbook_paste | supplement_track | ocr | none\n"
        "- brand: 商品品牌(若是商品,不知则空字串)\n"
        "- pill_count: 整数, 若图上明确有颗数(如 60 capsules);否则 0\n"
    )
    if extra_q:
        prompt += f"- extra: {extra_q}\n"

    model_id = "deepseek-v4-flash-vision-exp"

    try:
        client = _GET_CLIENT(profile)
        resp = client.chat.completions.create(
            model=model_id,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
            timeout=120.0,
        )
    except Exception as e:
        # 区分 auth vs 其他(401/403 跟用户配置直接相关,priority 排高)
        err_kind = "vision_classify_auth" if "401" in str(e) or "403" in str(e) else "vision_classify_call_failed"
        _REPORT_FAILURE(err_kind,
            f"{type(e).__name__}: {str(e)[:150]}",
            context={"model_id": model_id})
        return {"error": f"deepseek vision call failed: {type(e).__name__}: {e}"}

    text = (resp.choices[0].message.content or "").strip()
    # 容忍 ``` fence
    text = re.sub(r"^```(json)?\s*", "", text).strip()
    text = re.sub(r"\s*```\s*$", "", text).strip()
    try:
        parsed = json.loads(text)
    except Exception:
        _REPORT_FAILURE("vision_classify_non_json",
            f"deepseek 返了非 JSON: {text[:100]}",
            context={"model_id": model_id})
        return {"error": f"deepseek returned non-JSON: {text[:200]}"}
    return {"ok": True, **parsed}


def tool_vision_classify(args):
    url = _PICK_ATTACHMENT_URL(args)
    extra_q = (args.get("extra_question") or "").strip()
    if not url:
        return {"error": "need attachment_url"}
    if not is_ai_visible_attachment({"filename": url.rsplit("/", 1)[-1]}):
        return {"error": "derived attachment is not available to AI photo history"}
    try:
        f = resolve_attachment_url(_ATTACHMENTS_DIR(), url)
    except ImageServiceError as exc:
        return {"error": exc.detail}
    return _deepseek_classify_image(f, extra_q)


def tool_record_image_observation(args):
    """把主模型本轮看到的图片语义并入附件索引。

    附件登记/哈希/OCR 属确定性真源；模型只能补 ``vision`` 子对象，不能覆盖它们。
    先走统一 resolver，确保工具不能为不存在或越界的逻辑 URL 凭空造索引。
    """
    url = (args.get("attachment_url") or "").strip()
    if not url:
        return {"error": "need attachment_url"}
    if not is_ai_visible_attachment({"filename": url.rsplit("/", 1)[-1]}):
        return {"error": "derived attachment is not available to AI photo history"}
    try:
        f = resolve_attachment_url(_ATTACHMENTS_DIR(), url)
    except ImageServiceError as exc:
        return {"error": exc.detail}
    existing = next((x for x in _LOAD_ATTACHMENTS_INDEX()
                     if x.get("date") == f.parent.name and x.get("filename") == f.name), None)
    if existing is None:
        return {"error": "attachment is not registered in index"}
    old_vision = existing.get("vision") or {}
    vision = {**old_vision,
        "kind": str(args.get("kind") or "photo")[:40],
        "description": str(args.get("description") or "")[:500],
    }
    for key, limit in (("brand", 120), ("suggested_action", 80), ("ocr_text", 1000)):
        value = str(args.get(key) or "").strip()
        if value:
            vision[key] = value[:limit]
    if args.get("pill_count") is not None:
        try:
            vision["pill_count"] = max(0, int(args["pill_count"]))
        except (TypeError, ValueError):
            pass
    if args.get("ocr_likely") is not None:
        vision["ocr_likely"] = bool(args["ocr_likely"])
    _INDEX_UPSERT(f.parent.name, f.name, vision=vision, url=url, vision_pending=False)
    return {"ok": True, "indexed": url}


def tool_list_my_uploads(args):
    arr = [x for x in _LOAD_ATTACHMENTS_INDEX() if is_ai_visible_attachment(x)]
    df = (args.get("date_from") or "").strip()
    dt = (args.get("date_to") or "").strip()
    if df:
        arr = [x for x in arr if x.get("date", "") >= df]
    if dt:
        arr = [x for x in arr if x.get("date", "") <= dt]
    arr = sorted(arr, key=lambda x: (x.get("date", ""), x.get("filename", "")), reverse=True)
    limit = max(1, min(int(args.get("limit") or 30), 200))
    return {
        "items": [
            {
                "date": x.get("date"),
                "filename": x.get("filename"),
                "url": x.get("url"),
                "original": x.get("original", ""),
                "description": (x.get("vision") or {}).get("description", ""),
                "ocr_preview": (x.get("ocr_text", "") or "")[:120],
            }
            for x in arr[:limit]
        ],
        "total_in_index": len(arr),
    }


def tool_search_my_uploads(args):
    q = (args.get("query") or "").strip()
    if not q:
        return {"error": "need query"}
    arr = [x for x in _LOAD_ATTACHMENTS_INDEX() if is_ai_visible_attachment(x)]
    ql = q.lower()
    hits = []
    for x in arr:
        v = x.get("vision") or {}
        # 关键:haystack 加 vision 描述/kind/brand —— 否则没文字的照片(食物/玩偶/宠物)
        # 永远搜不到(filename 是 hash)。5.27 论证的根因。
        hay = " ".join([
            x.get("filename", ""), x.get("original", ""), x.get("ocr_text", "") or "",
            v.get("description", "") or "", v.get("kind", "") or "", v.get("brand", "") or "",
            v.get("ocr_text", "") or "", v.get("ocr", "") or "",
        ]).lower()
        if ql in hay:
            hits.append(x)
    hits = sorted(hits, key=lambda x: x.get("date", ""), reverse=True)
    limit = max(1, min(int(args.get("limit") or 15), 100))
    return {
        "items": [
            {
                "date": x.get("date"),
                "filename": x.get("filename"),
                "url": x.get("url"),
                "original": x.get("original", ""),
                "description": (x.get("vision") or {}).get("description", ""),
                "ocr_preview": (x.get("ocr_text") or (x.get("vision") or {}).get("ocr_text") or "")[:200],
            }
            for x in hits[:limit]
        ],
        "matched": len(hits),
    }


def _curator_fallback(q: str):
    """子 agent 挂时降级 grep,主 agent 仍有结果。"""
    r = tool_search_my_uploads({"query": q, "limit": 15})
    r["source"] = "fallback_grep"
    return r


def tool_ask_photo_curator(args):
    """图书管理员子 agent — 自然语言找照片。

    用 deepseek-v4-flash 官方直连,system 装全部照片描述 (frozen 文件 cache 友好),
    user 装自然语言 query。返 {items:[...], matched, source}。

    silent-failure 时降级 search_my_uploads。
    """
    q = (args.get("query") or "").strip()
    if not q:
        return {"error": "need query"}

    # ensure system prompt 存在 (冷启 / 索引刚迁移)
    curator_system_path = _CURATOR_SYSTEM_PATH()
    if not curator_system_path.exists():
        _REBUILD_CURATOR_PROMPT()
    curator_system_path = _CURATOR_SYSTEM_PATH()
    if not curator_system_path.exists():
        return _curator_fallback(q)
    try:
        sys_prompt = curator_system_path.read_text(encoding="utf-8")
    except Exception as e:
        _REPORT_FAILURE("curator_system_read_failed",
            f"{type(e).__name__}: {str(e)[:120]}")
        return _curator_fallback(q)

    profile = _GET_PROFILE("deepseek-v4-flash-vision-exp")
    if not profile:
        _REPORT_FAILURE("curator_no_profile",
            "deepseek-v4-flash-vision-exp profile 不存在 — 检查 DeepSeek API key")
        return _curator_fallback(q)
    client = _GET_CLIENT(profile)
    if client is None:
        return _curator_fallback(q)

    # v4-flash 实测先 reasoning 再生 content,thinking 占大头。
    # 样本: in=2120 out=1715 content 458 chars (~250 tokens) → 1400+ token 在 reasoning。
    # 试 extra_body 关 thinking 被 endpoint 拒(BadRequest),不省那一两毛钱,
    # 给 max_tokens=3000 兜住 reasoning + content 即可。
    try:
        resp = client.chat.completions.create(
            model=profile.get("model", "deepseek-v4-flash-vision-exp"),
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": q},
            ],
            response_format={"type": "json_object"},
            max_tokens=3000,
            temperature=0.1,
            timeout=30,
        )
    except Exception as e:
        err_kind = "curator_call_auth" if ("401" in str(e) or "403" in str(e)) else "curator_call_failed"
        _REPORT_FAILURE(err_kind,
            f"{type(e).__name__}: {str(e)[:150]}",
            context={"query": q[:60]})
        return _curator_fallback(q)

    _LOG_CACHE_USAGE(resp, "curator")
    text = (resp.choices[0].message.content or "").strip()
    # 空 content (reasoning 烧完 max_tokens 是常见因) → fallback,不当 0 matches 处理
    if not text:
        _REPORT_FAILURE("curator_empty_content",
            "v4-flash content 空 (可能 reasoning 吃完 max_tokens)",
            context={"query": q[:60]})
        return _curator_fallback(q)
    # 容忍 ``` fence(v4-flash 偶尔加)
    text = re.sub(r"^```(json)?\s*", "", text).strip()
    text = re.sub(r"\s*```\s*$", "", text).strip()
    try:
        parsed = json.loads(text)
    except Exception:
        _REPORT_FAILURE("curator_non_json",
            f"返非 JSON: {text[:120]}",
            context={"query": q[:60]})
        return _curator_fallback(q)

    # stem → full record 映射,把主 agent 想要的 url + description 拼回去
    arr = _LOAD_ATTACHMENTS_INDEX()
    by_stem = {}
    for x in arr:
        fn = x.get("filename", "")
        stem = fn.rsplit(".", 1)[0] if "." in fn else fn
        by_stem[f"{x.get('date')}/{stem}"] = x

    matches = parsed.get("matches") or []
    items = []
    for m in matches[:30]:
        x = by_stem.get(m)
        if not x:
            continue
        items.append({
            "date": x["date"],
            "filename": x["filename"],
            "url": x.get("url"),
            "description": (x.get("vision") or {}).get("description", "") or "",
        })
    return {
        "items": items,
        "matched": len(items),
        "curator_note": parsed.get("note", "") or "",
        "source": "curator",
    }
