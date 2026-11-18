"""chat_routes — APIRouter for /api/chat + /api/chat/upload-image (LLM 对话引擎).

Extract Module(ctrl-c-v § 9):本 session 最高风险抽取(extract-with-caveats)。chat 编排器 +
流式 chokepoint 从 server.py 搬出 —— DSML 泄漏闸 / SSE 契约 / 可变状态 / claim 审计这些
Cannot-break 代码随之搬来,15 条 characterization(test_chat_routes.py)守红线。

由组装根注入:_dispatch_tool/_active_tools/_build_action_context/TOOL_IMPL 等
tool 引擎(reaches authorship 核心,绝不搬)、build_system_prompt、get_client/profile/model、LLM core、
attachments 索引簇、vision/ocr。re-export:_audit_unauthorized_claim(test_claim_audit 直调)。
DSML 正则字节脆弱(U+FF5C)→ 本文件由 server.py 源码逐字提取,非手抄。lazy import 经 AST 精确探测。
"""
import asyncio
import hashlib
import json
import re
import secrets
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from attachment_service import resolve_attachment_url
from attachments_index import is_ai_visible_attachment
from image_service_errors import ImageServiceError

router = APIRouter(tags=["chat"])

_LOAD_ATTACHMENTS_INDEX = None
_ATTACHMENTS_DIR = None
_OCR_TEXT = None
_INDEX_UPSERT = None
_VISION_CLASSIFY_IMAGE = None
_REPORT_FAILURE = None
_LOGGER = None
_DISPATCH_TOOL = None
_ACTIVE_TOOLS = None
_LOG_CACHE_USAGE = None
_ALLOWED_IMAGE_EXT = None
_MAX_IMAGE_BYTES = None
_FIND_BY_HASH = None
_INDEX_ATTACHMENT = None
_COMPUTE_TIME_HINT = None
_BUILD_ACTION_CONTEXT = None
_STRIP_OCR_HISTORY = None
_TODAY_DATE_STR = None
_BUILD_SYSTEM_PROMPT = None
_IMAGE_DATA_URL = None
_GET_CLIENT = None
_GET_MODEL = None
_GET_PROFILE = None


def configure_effects(
    *,
    load_attachments_index,
    attachments_dir,
    ocr_text,
    index_upsert,
    vision_classify_image,
    report_failure,
    logger,
    dispatch_tool,
    active_tools,
    log_cache_usage,
    allowed_image_ext,
    max_image_bytes,
    find_by_hash,
    index_attachment,
    compute_time_hint,
    build_action_context,
    strip_ocr_history,
    today_date_str,
    build_system_prompt,
    image_data_url,
    get_client,
    get_model,
    get_profile,
) -> None:
    global _LOAD_ATTACHMENTS_INDEX, _ATTACHMENTS_DIR, _OCR_TEXT, _INDEX_UPSERT
    global _VISION_CLASSIFY_IMAGE, _REPORT_FAILURE, _LOGGER, _DISPATCH_TOOL
    global _ACTIVE_TOOLS, _LOG_CACHE_USAGE, _ALLOWED_IMAGE_EXT, _MAX_IMAGE_BYTES
    global _FIND_BY_HASH, _INDEX_ATTACHMENT, _COMPUTE_TIME_HINT
    global _BUILD_ACTION_CONTEXT, _STRIP_OCR_HISTORY, _TODAY_DATE_STR
    global _BUILD_SYSTEM_PROMPT, _GET_CLIENT, _GET_MODEL, _GET_PROFILE, _IMAGE_DATA_URL
    _LOAD_ATTACHMENTS_INDEX = load_attachments_index
    _ATTACHMENTS_DIR = attachments_dir
    _OCR_TEXT = ocr_text
    _INDEX_UPSERT = index_upsert
    _VISION_CLASSIFY_IMAGE = vision_classify_image
    _REPORT_FAILURE = report_failure
    _LOGGER = logger
    _DISPATCH_TOOL = dispatch_tool
    _ACTIVE_TOOLS = active_tools
    _LOG_CACHE_USAGE = log_cache_usage
    _ALLOWED_IMAGE_EXT = allowed_image_ext
    _MAX_IMAGE_BYTES = max_image_bytes
    _FIND_BY_HASH = find_by_hash
    _INDEX_ATTACHMENT = index_attachment
    _COMPUTE_TIME_HINT = compute_time_hint
    _BUILD_ACTION_CONTEXT = build_action_context
    _STRIP_OCR_HISTORY = strip_ocr_history
    _TODAY_DATE_STR = today_date_str
    _BUILD_SYSTEM_PROMPT = build_system_prompt
    _GET_CLIENT = get_client
    _GET_MODEL = get_model
    _GET_PROFILE = get_profile
    _IMAGE_DATA_URL = image_data_url


def _materialize_user_content(text: str, refs) -> tuple[str | list, list[dict]]:
    """当前轮图片只在传输时物化；History/model_content 永不保存 base64。"""
    blocks = [{"type": "text", "text": text}]
    visible = []
    for ref in refs or []:
        if not isinstance(ref, dict) or ref.get("kind") != "image":
            continue
        payload = ref.get("payload", ref) if isinstance(ref, dict) else {}
        url = payload.get("url", "") if isinstance(payload, dict) else ""
        if not url or not is_ai_visible_attachment({"filename": url.rsplit("/", 1)[-1]}):
            continue
        try:
            path = resolve_attachment_url(_ATTACHMENTS_DIR(), url)
            blocks.append({"type": "image_url", "image_url": {"url": _IMAGE_DATA_URL(path)}})
            visible.append(ref)
        except (ImageServiceError, OSError):
            continue
    return (blocks if len(blocks) > 1 else text), visible


def _multimodal_user_content(text: str, refs) -> str | list:
    return _materialize_user_content(text, refs)[0]


_ATTACHMENT_URL_RE = re.compile(r"/attachments/\d{4}-\d{2}-\d{2}/[^\s\"'<>\\]+")
_CONTEXT_JSON_RE = re.compile(r"<context>\s*(\{[\s\S]*?\})\s*</context>")


def _logical_image_refs_from_text(text: str) -> list[dict]:
    match = _CONTEXT_JSON_RE.search(text or "")
    if not match:
        return []
    try:
        context = json.loads(match.group(1))
    except (TypeError, ValueError):
        return []
    return [ref for ref in (context.get("refs") or [])
            if isinstance(ref, dict) and ref.get("kind") == "image"]


def _multimodal_history_content(text: str) -> str | list:
    """Re-materialize persisted logical attachment refs for byte-stable replay."""
    return _multimodal_user_content(text, _logical_image_refs_from_text(text))
# WORKFLOW 文案外置(2026-07-22,与 baseline/protocol_index/tool_catalog 同批 Extract Module):
# gateway/prompts/vision_workflow.md,{view_date} 占位符渲染。RN 端 chatPretext.ts 的
# buildVisionHint 部分内容由 promptContract.json(见 gateway/scripts/generate_prompt_contract.py)
# 生成同步,RN-only 分支(doc OCR 特例措辞等,见 PARITY_HARNESS_2026-07-19.md)保留手写。
from prompt_builder import _read_prompt as _read_prompt_file


# 旧值仅保留给升级中 canonical History / 测试回放的协议识别；运行时 profile
# 已由 composition root 强制迁到 vision-exp，不再把这些值暴露给 picker。
_DEEPSEEK_V4_MODELS = {
    "deepseek-v4-flash-vision-exp", "deepseek-v4-flash", "deepseek-v4-pro",
}


def _thinking_request_kwargs(active_model: str) -> dict:
    """DeepSeek V4 主对话固定开启 high 思考；其他兼容 provider 不接收私有参数。"""
    if active_model not in _DEEPSEEK_V4_MODELS:
        return {}
    return {
        "reasoning_effort": "high",
        "extra_body": {"thinking": {"type": "enabled"}},
    }


def _log_reasoning_observation(reasoning: str, source: str, active_model: str) -> None:
    """只记录思考是否返回及长度，绝不记录 reasoning_content 正文。"""
    if active_model not in _DEEPSEEK_V4_MODELS:
        return
    try:
        chars = len(reasoning or "")
        _LOGGER().info(
            "[reasoning:%s] requested=enabled effort=high received=%s chars=%d",
            source, str(chars > 0).lower(), chars,
        )
    except Exception:
        pass


def _build_vision_workflow_block(view_date: str) -> str:
    """渲染 <vision-pre-router> WORKFLOW 段(prompts/vision_workflow.md {view_date} 占位符)。
    抽自 chat() 内联 f-string(Extract Module,字节级不变 — 见 tests/test_prompt_extraction.py)。
    """
    return _read_prompt_file("vision_workflow.md").format(view_date=view_date)

# history 里 thread.js 把 ref 拼成 `[image] filename`(或其他 kind),抓 image 那条
_HISTORY_IMG_LABEL_RE = re.compile(r'\[image\]\s+([^\n]+?)(?=\n|$)')

def _trim_history_tool_volume(history: list, max_tool_chars: int) -> list:
    """从最早往后,把超过 max_tool_chars 总量的 tool result 段砍掉。
    被砍的 tool 同步去掉它对应 assistant.tool_calls 里的条目 (避免 schema 孤儿)。
    """
    # 1. 统计所有 tool 段总字符
    total = sum(len(m.get("content") or "") for m in history if m.get("role") == "tool")
    if total <= max_tool_chars:
        return history
    # 2. 从前往后扫,把 tool 段标记为待删,直到剩余总量 <= cap
    overflow = total - max_tool_chars
    dropped_tool_ids: set = set()
    out = []
    for m in history:
        if m.get("role") == "tool" and overflow > 0:
            tcid = m.get("tool_call_id") or ""
            overflow -= len(m.get("content") or "")
            dropped_tool_ids.add(tcid)
            continue   # 丢这条 tool
        out.append(m)
    # 3. 扫所有 assistant.tool_calls,去掉孤儿条目;若整 assistant 的 tool_calls 全孤儿,
    #    保留 content 但删 tool_calls 字段(变成普通文字回复)
    final = []
    for m in out:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            kept = [tc for tc in m["tool_calls"] if (tc.get("id") or "") not in dropped_tool_ids]
            if kept:
                final.append({**m, "tool_calls": kept})
            else:
                # 全部 tool 段被砍了,这条 assistant 也去掉 tool_calls
                stripped = {k: v for k, v in m.items() if k != "tool_calls"}
                # 文本空且无 tool_calls = 没价值,跳过
                if (stripped.get("content") or "").strip():
                    final.append(stripped)
        else:
            final.append(m)
    return final

def _history_image_brief_block(history: list) -> str:
    """history 里 thread.js 把图 ref 拼成 `[image] filename.jpg`,filename 通常是 hash —
    AI 看不出内容,回头引用旧图时容易凭空捏造话题(5.20 长鑫存储被答成 HK 虚拟货币)。

    旧方案(_enrich_history_image_labels,7.23 审计 B2 裁决废弃)是逐 turn 用当下 vision
    cache **改写历史消息里的 label** —— cache 后到会让同一段历史在下一 turn 序列化出
    不同字节,从该消息起 KV 缓存前缀全废。

    新方案:历史字节冻结,一律不改写;为出现在 history 里的图片生成一个 brief 索引块,
    由调用方追加进**本 turn 新 user message 尾部**(尾部本来就是新字节,零缓存代价)。
    cache miss 的图不出现在索引里,下一 turn cache 到了自然补上——只影响尾块,不动前缀。
    """
    if not history:
        return ""
    labels: list = []
    seen = set()
    for m in history:
        content = m.get("content")
        if isinstance(content, list):
            content = next((b.get("text", "") for b in content
                            if isinstance(b, dict) and b.get("type") == "text"), "")
        if isinstance(content, str) and "[image]" in content:
            for mt in _HISTORY_IMG_LABEL_RE.finditer(content):
                label = mt.group(1).strip()
                if label not in seen:
                    seen.add(label)
                    labels.append(label)
        if isinstance(content, str):
            for ref in _logical_image_refs_from_text(content):
                url = str((ref.get("payload") or {}).get("url") or "")
                if not url:
                    continue
                label = url.rstrip(".,，。)]}").rsplit("/", 1)[-1]
                if label not in seen:
                    seen.add(label)
                    labels.append(label)
    if not labels:
        return ""
    idx = [x for x in _LOAD_ATTACHMENTS_INDEX() if is_ai_visible_attachment(x)]
    by_original = {x.get("original"): x for x in idx if x.get("original")}
    by_filename = {x.get("filename"): x for x in idx if x.get("filename")}
    lines = []
    for label in labels:
        entry = by_original.get(label) or by_filename.get(label)
        if not entry:
            continue
        vision = entry.get("vision") or {}
        kind = vision.get("kind")
        desc = vision.get("description", "")
        ocr = (entry.get("ocr_text") or vision.get("ocr_text") or vision.get("ocr") or "")[:120].replace("\n", " ").strip()
        bits = [f"- {label}"]
        if kind and desc:
            bits.append(f"({kind}: {desc})")
        elif desc:
            bits.append(f"({desc})")
        if ocr:
            bits.append(f"OCR前 120 字: {ocr}")
        lines.append("  ".join(bits))
    if not lines:
        return ""
    return "<历史图片索引>(系统注入:历史消息里 [image] 文件名对应的内容,引用旧图以此为准,别凭文件名猜)\n" + "\n".join(lines) + "\n</历史图片索引>"

def _refs_to_image_blocks(refs):
    """从 context.refs 抽 image,跑 OCR,返回 [{filename, ocr_text}] 列表。
    上层把这个嵌进 user message 文本里给 LLM。
    走 _ocr_text 统一出口(端侧优先,baidu 兜底)。
    """
    out = []
    for r in refs or []:
        if r.get("kind") != "image":
            continue
        url = (r.get("payload") or {}).get("url") or ""
        if not is_ai_visible_attachment({"filename": url.rsplit("/", 1)[-1]}):
            continue
        try:
            f = resolve_attachment_url(_ATTACHMENTS_DIR(), url)
        except ImageServiceError:
            continue
        out.append({
            "filename": (r.get("payload") or {}).get("original") or f.name,
            "ocr_text": _OCR_TEXT(f),
        })
    return out

def _refs_to_vision_hints(refs):
    """upload-side vision router 的第二步:
    chat 收到 image refs 时,从索引拿 cache vision 结果;cache miss / vision 空 → 现场 sync
    call 一次 DeepSeek Vision 补上,并回写索引(下次 hit)。
    返 [{filename, url, vision_dict}],上层拼成 hint 注入 user message。
    """
    out = []
    idx = _LOAD_ATTACHMENTS_INDEX()
    by_url = {x.get("url"): x for x in idx if x.get("url")}
    for r in refs or []:
        if r.get("kind") != "image":
            continue
        url = (r.get("payload") or {}).get("url") or ""
        if not is_ai_visible_attachment({"filename": url.rsplit("/", 1)[-1]}):
            continue
        try:
            f = resolve_attachment_url(_ATTACHMENTS_DIR(), url)
        except ImageServiceError:
            continue
        entry = by_url.get(url)
        vision = (entry or {}).get("vision") or {}
        # cache miss(没索引 或 vision 字段空)→ 现场补 + upsert 回索引
        # 用 upsert 而非直接 mutate+save,避免和后台 OCR task 互相 read-modify-write
        # 覆盖对方的字段(原来的 bug:OCR 跑得慢,等它写完时把 vision 冲了)
        if not vision:
            try:
                vc = _VISION_CLASSIFY_IMAGE(f)
                if isinstance(vc, dict) and not vc.get("error"):
                    vision = vc
                    _INDEX_UPSERT(
                        f.parent.name, f.name,
                        vision=vision,
                        vision_pending=False,
                        url=url,
                        original=(r.get("payload") or {}).get("original") or f.name,
                        size=f.stat().st_size,
                    )
            except Exception as e:
                _LOGGER().warning(f"sync vision failed for {url}: {e}")
                # vision call 抛 — 不只是返 error,是裸异常逃出。
                # vision provider 内部已 hook 各类 return error,这一条
                # 抓的是 import 失败 / SDK 崩 / cache lock 异常这种。
                _REPORT_FAILURE("vision_hint_inline_exception",
                    f"{type(e).__name__}: {str(e)[:120]}",
                    context={"url": url[-40:] if url else ""})
        if vision:
            if (entry or {}).get("vision_pending"):
                _INDEX_UPSERT(f.parent.name, f.name, vision_pending=False)
            # 用户 chip 上的"抠/原"开关传过来的偏好(default true)
            cutout_pref = (r.get("payload") or {}).get("cutout")
            if cutout_pref is None:
                cutout_pref = True
            out.append({
                "filename": (r.get("payload") or {}).get("original") or f.name,
                "url": url,
                "vision": vision,
                "user_cutout_pref": bool(cutout_pref),
            })
    return out


def _mark_vision_pending(refs) -> list[dict]:
    image_refs = []
    for ref in refs or []:
        if not isinstance(ref, dict) or ref.get("kind") != "image":
            continue
        url = (ref.get("payload") or {}).get("url") or ""
        try:
            f = resolve_attachment_url(_ATTACHMENTS_DIR(), url)
        except ImageServiceError:
            continue
        _INDEX_UPSERT(f.parent.name, f.name, url=url, vision_pending=True)
        image_refs.append(ref)
    return image_refs


def retry_pending_vision(limit: int = 3, preferred_urls=None) -> int:
    """Retry a bounded pending batch; current-turn photos take priority."""
    preferred = set(preferred_urls or [])
    pending = [item for item in _LOAD_ATTACHMENTS_INDEX()
               if is_ai_visible_attachment(item) and item.get("vision_pending") and item.get("url")]
    pending.sort(key=lambda item: (item.get("url") not in preferred,
                                   item.get("date", ""), item.get("filename", "")))
    refs = []
    for item in pending[:max(0, int(limit))]:
        if item.get("vision_pending") and item.get("url"):
            refs.append({"kind": "image", "payload": {
                "url": item["url"], "original": item.get("original", ""),
            }})
    if refs:
        _refs_to_vision_hints(refs)
    return len(refs)

# ── chat SSE streaming generator ────────────────────────────────────
# 事件类型:
#   {"type":"action","name":"...","args":{...},"result":{...}}  — 工具执行完
#   {"type":"delta","text":"..."}                                — 文本片段
#   {"type":"done","actions":[...]}                              — 收尾
#   {"type":"error","text":"..."}                                — 异常
def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

# ── synthetic-tool-call fallback ────────────────────────────────────
# 目击于 deepseek-v4-pro:模型把 tool 调用当 content 文本吐,不用 OpenAI 的
# tool_calls 字段。格式 mimic Claude 的 antml,但带 ｜｜DSML｜｜ 命名空间
# (｜ = U+FF5C 全角竖线,见过 1-2 个;偶尔也见纯 ASCII | 或省略 DSML)。
# 不解析的话前端会看见 <｜｜DSML｜｜tool_calls>...</> 这一坨原文,journal 也没落。
_DSML_NS = r'<[｜|]{1,2}(?:DSML[｜|]{1,2})?'
_SYNTH_INVOKE_RE = re.compile(
    r'<[｜|]{1,2}DSML[｜|]{1,2}invoke\s+name="([^"]+)"\s*>(.*?)</[｜|]{1,2}DSML[｜|]{1,2}invoke>',
    re.DOTALL,
)
_SYNTH_PARAM_RE = re.compile(
    r'<[｜|]{1,2}DSML[｜|]{1,2}parameter\s+name="([^"]+)"[^>]*>(.*?)</[｜|]{1,2}DSML[｜|]{1,2}parameter>',
    re.DOTALL,
)
_SYNTH_WRAPPER_RE = re.compile(
    r'<[｜|]{1,2}DSML[｜|]{1,2}tool_calls>.*?</[｜|]{1,2}DSML[｜|]{1,2}tool_calls>',
    re.DOTALL,
)
# orphan 兜底:wrapper 缺失时单独的 <invoke>...</invoke> 整块剥掉
_SYNTH_INVOKE_STRIP_RE = re.compile(
    r'<[｜|]{1,2}DSML[｜|]{1,2}invoke[^>]*?>.*?</[｜|]{1,2}DSML[｜|]{1,2}invoke>',
    re.DOTALL,
)
# 最后一道防线:任何残留的 <｜｜DSML｜｜foo> 或 </｜｜DSML｜｜foo> 孤立标签
_DSML_TAG_RE = re.compile(r'</?[｜|]{1,2}DSML[｜|]{1,2}[^>]*?>', re.DOTALL)

def _extract_synthetic_tool_calls(content: str):
    """提 content 里 Claude-antml 风格的伪 tool_calls。
    返回 (stripped_content, [{"id","name","args"}])。无匹配则 (content, [])。

    3 层清理:
      1) 先抠 invoke 块得 calls
      2) wrapper / invoke / 任何 DSML 残留标签全 strip
      3) 即使 calls 为空,只要原文含 DSML 残骸也清掉(防 5.22 msg 9 那种漏)
    """
    if not content or "DSML" not in content:
        return content, []
    calls = []
    for m in _SYNTH_INVOKE_RE.finditer(content):
        name = m.group(1).strip()
        body = m.group(2)
        args = {pm.group(1).strip(): pm.group(2).strip()
                for pm in _SYNTH_PARAM_RE.finditer(body)}
        calls.append({
            "id": f"call_synth_{secrets.token_hex(12)}",
            "name": name,
            "args": args,
        })
    # 即使没抠到 calls 也做清理 — 防 regex 没认出的变体把原文 DSML 漏到 history
    stripped = _SYNTH_WRAPPER_RE.sub("", content)
    stripped = _SYNTH_INVOKE_STRIP_RE.sub("", stripped)
    stripped = _DSML_TAG_RE.sub("", stripped).strip()
    return stripped, calls

def _exec_synth_calls(synth_calls, messages, last_actions, action_context, quota_used):
    """执行 synth_calls,把 tool result 写进 messages + last_actions。"""
    for c in synth_calls:
        result = _DISPATCH_TOOL(c["name"], c["args"], action_context, quota_used)
        last_actions.append({"id": c["id"], "name": c["name"], "args": c["args"], "result": result})
        messages.append({
            "role": "tool",
            "tool_call_id": c["id"],
            "content": _truncate_tool_result(json.dumps(result, ensure_ascii=False)),
        })

# ── claim audit(Path X:防 AI 口头声称已写入但没真 tool call)─────────
# 5.22 msg 5/7 事故:用户"帮我记一下" → AI 回"记进 17:30 了" → last_actions 空,
# journal 文件没动。CC 的解法是 tool_use 结构化 block(说=做绑死);
# 我们用 server 出口审计:claim 措辞 + actions 空 → 自动加 disclaimer,
# 用户看到这条就知道"AI 在撒谎"。
# 7.5 事故(mobile 实锤,PC 同源):AI 回"帮你加到打卡里啦/打卡成功/勾上啦"但零 tool call。
# 原正则漏了 加到/打卡成功/勾上 等完成态(guard 是 actions 空,可放心拓宽)。mobile-api.js 同步。
_CLAIM_PHRASE_RE = re.compile(
    r'(记进|写进|搞定|已写[入好]|已加入|已添加|已保存|已记录|已贴|已落|已 ?patch|'
    r'写好了|写完了|加好了|加完了|落进|帮你加[到上进]|已.{0,4}勾[上选]|打卡成功|已打卡|'
    r'设置好[了啦]|已设置好|创建好[了啦]|已创建|已更新|更新好[了啦]|加上去了|加进去了|'
    r'saved|recorded|wrote|patched|done|added|checked|created|updated)',
    re.IGNORECASE,
)
_CLAIM_DISCLAIMER = (
    "\n\n*(server audit:本回合未触发任何 tool 调用,上面的「已写入/记进了」等措辞"
    "未对应真实动作 — 日记 / 聚合页没改。要真落请说『重试』或换一句指令。)*"
)

def _audit_unauthorized_claim(content: str, actions: list) -> str:
    if actions or not content:
        return content
    if not _CLAIM_PHRASE_RE.search(content):
        return content
    return content + _CLAIM_DISCLAIMER

# tool result 上限:multi-round 时同一 result 跨轮重发,大 JSON 会把 token 拉爆。
# 3000 char ≈ 1500 token,普通 read 类够用;真要全文 model 可再调一次同 tool。
_TOOL_RESULT_CAP = 5000

def _truncate_tool_result(content: str) -> str:
    if len(content) <= _TOOL_RESULT_CAP:
        return content
    keep = content[:_TOOL_RESULT_CAP]
    omitted = len(content) - _TOOL_RESULT_CAP
    return f"{keep}\n…(truncated, {omitted} chars omitted; re-call tool with narrower args if needed)"

def _stream_final_reply(client, active_model, messages, action_context, quota_used, last_actions,
                        turn_start_index=None):
    """单一 chokepoint:流式产出最终回复 + done。**所有**流给前端的模型文本都过这。

    内建 DSML 防漏:任一轮 stream 里冒出 ｜｜DSML 假 tool-call,一律 suppress
    (绝不把 raw DSML yield 给前端)→ extract → execute → 继续下一轮 stream 让模型
    看到 tool result 补回复。循环到拿干净文本 / DSML 抠不出 / 撞迭代上限为止。

    取代旧的两处裸奔 stream 出口(last-round bonus + 模型不要 tool 的重流)——它们
    各自 yield delta.content 无检测,是 DSML 泄漏进聊天的真因(5.27)。
    """
    LOOKAHEAD = 8          # 末尾留 8 char 等 ｜｜DSML 完整出现再判,防 marker 被切两半漏出
    MAX_DSML_ITERS = 4     # DSML→执行→又 DSML 的循环上限,防死循环
    reasoning_buf = ""
    last_buffer = ""
    emitted = False
    hit_cap = True         # for 正常 break 会置 False;跑满循环没 break = 撞上限
    if turn_start_index is None:
        turn_start_index = len(messages)

    for _it in range(MAX_DSML_ITERS):
        round_reasoning = ""
        # ping 保活:thinking 模式下首个 delta 可能要等几十秒,客户端 90s 没字节就 abort
        yield _sse({"type": "ping"})
        try:
            # tools 同形传入 + tool_choice="none":与 tool round 保持同一段 tools JSON,
            # 前缀不因"删字段"打废(7.23 审计 A1);行为不变 —— none 下模型只能出文本,
            # DSML 假 tool-call 照旧走本函数的 extract 兜底。
            stream_resp = client.chat.completions.create(
                model=active_model, messages=messages, stream=True,
                tools=_ACTIVE_TOOLS(action_context), tool_choice="none",
                stream_options={"include_usage": True},
                **_thinking_request_kwargs(active_model),
            )
        except Exception as e:
            yield _sse({"type": "error", "text": f"{type(e).__name__}: {str(e)[:300]}"})
            # #1 用户功能:聊天 LLM 初始调用失败(网络/quota/auth)— 高频且现在只吐 UI 不上报
            _REPORT_FAILURE("chat_llm_call_failed",
                f"{type(e).__name__}: {str(e)[:120]}",
                context={"model": active_model, "phase": "stream_start"})
            return

        buffer = ""
        yielded_len = 0
        suppress = False
        # workflow B #1 闭合:chunk 迭代裸奔会被 httpx 层的 ReadTimeout / RemoteProtocolError /
        # ChunkedEncodingError 撕断 generator,FastAPI 把 SSE 流关闭但不发 error 事件,前端干等到
        # 90s timer 才 abort。包 try/except → 发 error 事件 + 报 silent-failure 分桶。
        try:
            for chunk in stream_resp:
                if getattr(chunk, "usage", None):
                    _LOG_CACHE_USAGE(chunk, "chat/stream-final")
                if not chunk.choices: continue
                delta = chunk.choices[0].delta
                if not delta: continue
                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    reasoning_buf += rc
                    round_reasoning += rc
                if not delta.content: continue
                buffer += delta.content
                if suppress: continue
                if "｜｜DSML" in buffer or "<function_calls" in buffer:
                    suppress = True
                    continue
                safe_end = max(yielded_len, len(buffer) - LOOKAHEAD)
                if safe_end > yielded_len:
                    text = buffer[yielded_len:safe_end]
                    yielded_len = safe_end
                    emitted = True
                    yield _sse({"type": "delta", "text": text})
        except Exception as e:
            err_msg = f"stream torn: {type(e).__name__}: {str(e)[:200]}"
            yield _sse({"type": "error", "text": err_msg})
            _REPORT_FAILURE("chat_stream_torn_down",
                str(e)[:150],
                context={"model": active_model, "emitted_chars": yielded_len,
                         "buffer_chars": len(buffer)})
            return
        _log_reasoning_observation(round_reasoning, "chat/stream-final", active_model)
        last_buffer = buffer

        if not suppress:
            # 无 DSML — flush 末尾 lookahead 留的尾巴,完成
            if yielded_len < len(buffer):
                tail = buffer[yielded_len:]
                if tail:
                    emitted = True
                    yield _sse({"type": "delta", "text": tail})
            hit_cap = False
            break

        # suppress:buffer 含 DSML → 抠 call
        stripped, synth_calls = _extract_synthetic_tool_calls(buffer)
        if not synth_calls:
            # 抠不出(畸形/变体 DSML)→ 至少 yield 清理后的干净文本,**绝不漏 raw DSML**
            if stripped:
                emitted = True
                yield _sse({"type": "delta", "text": stripped})
            hit_cap = False
            break

        # 有 call:登记 asst + 执行(yield action)+ 写 tool result → 下一轮 stream 补回复
        asst_msg = {"role": "assistant", "content": stripped,
                    "tool_calls": [{
                        "id": c["id"], "type": "function",
                        "function": {"name": c["name"],
                                     "arguments": json.dumps(c["args"], ensure_ascii=False)},
                    } for c in synth_calls]}
        if round_reasoning:
            asst_msg["reasoning_content"] = round_reasoning
        messages.append(asst_msg)
        for c in synth_calls:
            result = _DISPATCH_TOOL(c["name"], c["args"], action_context, quota_used)
            last_actions.append({"id": c["id"], "name": c["name"], "args": c["args"], "result": result})
            yield _sse({"type": "action", "id": c["id"], "name": c["name"], "args": c["args"], "result": result})
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": _truncate_tool_result(json.dumps(result, ensure_ascii=False))})
        # 继续循环 → 下一轮 stream

    if hit_cap and last_actions:
        names = ", ".join(a.get("name", "?") for a in last_actions)
        yield _sse({"type": "delta", "text": f"✓ 完成: {names}（工具调用上限,已停止再调）"})
        emitted = True

    # 收尾:fallback + claim audit + done(跟旧两处出口一致)
    if not emitted and last_actions:
        names = ", ".join(a.get("name", "?") for a in last_actions)
        yield _sse({"type": "delta", "text": f"✓ 完成: {names}"})
    if not last_actions and last_buffer and _CLAIM_PHRASE_RE.search(last_buffer):
        yield _sse({"type": "delta", "text": _CLAIM_DISCLAIMER})
    done_payload = {"type": "done", "actions": last_actions, "model_id": active_model}
    if reasoning_buf:
        done_payload["reasoning_content"] = reasoning_buf
    final_model_message = {"role": "assistant", "content": last_buffer}
    if round_reasoning:
        final_model_message["reasoning_content"] = round_reasoning
    done_payload["model_messages"] = messages[turn_start_index:] + [final_model_message]
    yield _sse(done_payload)

def _chat_stream_generator(client, active_model, messages, action_context, quota_used,
                           model_content=None):
    """跑跟非 stream 一样的 tool loop,但最后一轮(无 tool_calls 那一次)
    用 stream=True 把 text 一段段 yield 出去。tool 调用之间 yield action 事件。
    tools schema 每轮保持稳定；ActionPolicy 使用本轮不可变的用户请求上下文。
    所有流式文本出口统一走 _stream_final_reply(单一 chokepoint,DSML 防漏)。
    """
    if model_content is not None:
        yield _sse({"type": "request_meta", "model_content": model_content})
    turn_start_index = len(messages)
    last_actions = []
    MAX_ROUNDS = 10
    for round_idx in range(MAX_ROUNDS):
        is_last_round = (round_idx == MAX_ROUNDS - 1)
        # 非最后轮:先非 stream 让模型决定要不要 tool。
        # 最后一轮:不再给 tool,模型必须出文本收尾 —— 统一走 chokepoint 流(内建 DSML 防漏)。
        if is_last_round:
            yield from _stream_final_reply(client, active_model, messages, action_context, quota_used,
                                           last_actions, turn_start_index)
            return

        # tool round:非 stream;tools schema 保持稳定
        # 先发个 SSE ping —— 客户端 90s 没新字节就 abort(thread.js:591);
        # 一个轮的 model 阻塞调用可能 30-60s,多轮串起来很容易撞 90s。
        # ping 给 client 一个 byte 重置那个 timer。客户端未知 type 静默忽略,安全。
        yield _sse({"type": "ping"})
        try:
            resp = client.chat.completions.create(
                model=active_model, messages=messages,
                tools=_ACTIVE_TOOLS(action_context), tool_choice="auto",
                **_thinking_request_kwargs(active_model),
            )
        except Exception as e:
            yield _sse({"type": "error", "text": f"{type(e).__name__}: {str(e)[:300]}"})
            _REPORT_FAILURE("chat_llm_call_failed",
                f"{type(e).__name__}: {str(e)[:120]}",
                context={"model": active_model, "phase": "tool_loop"})
            return

        msg = resp.choices[0].message
        _log_reasoning_observation(
            getattr(msg, "reasoning_content", None) or "", "chat/stream-tool-round", active_model
        )
        _LOG_CACHE_USAGE(resp, "chat/stream-tool-round")
        asst_msg = msg.model_dump(exclude_none=True)
        asst_msg["role"] = "assistant"
        if not msg.tool_calls:
            asst_msg.pop("tool_calls", None)
        if asst_msg.get("content") is None:
            asst_msg["content"] = ""

        # ── DSML fallback(同非 stream 路径)──
        synth_calls = []
        if not msg.tool_calls and asst_msg["content"]:
            asst_msg["content"], synth_calls = _extract_synthetic_tool_calls(asst_msg["content"])
            if synth_calls:
                asst_msg["tool_calls"] = [{
                    "id": c["id"], "type": "function",
                    "function": {"name": c["name"],
                                 "arguments": json.dumps(c["args"], ensure_ascii=False)},
                } for c in synth_calls]

        messages.append(asst_msg)

        if synth_calls:
            for c in synth_calls:
                result = _DISPATCH_TOOL(c["name"], c["args"], action_context, quota_used)
                last_actions.append({"id": c["id"], "name": c["name"], "args": c["args"], "result": result})
                yield _sse({"type": "action", "id": c["id"], "name": c["name"], "args": c["args"], "result": result})
                messages.append({
                    "role": "tool",
                    "tool_call_id": c["id"],
                    "content": _truncate_tool_result(json.dumps(result, ensure_ascii=False)),
                })
            continue  # 下一轮让 model 补 reply

        if not msg.tool_calls:
            # 模型不要 tool 了 — pop 出空 asst,改用 chokepoint 真流(内建 DSML 防漏:
            # 模型这轮若反悔又想调工具 → 吐 DSML 也不会裸漏给前端,会被抠出执行)
            messages.pop()
            yield from _stream_final_reply(client, active_model, messages, action_context, quota_used,
                                           last_actions, turn_start_index)
            return

        # 执行 tools,逐个 yield action 事件
        for tc in msg.tool_calls:
            if getattr(tc, "type", "function") != "function" or not getattr(tc, "function", None):
                continue
            fn = tc.function.name
            args = {}
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                pass
            result = _DISPATCH_TOOL(fn, args, action_context, quota_used)
            action_payload = {"id": tc.id, "name": fn, "args": args, "result": result}
            last_actions.append(action_payload)
            yield _sse({"type": "action", **action_payload})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": _truncate_tool_result(json.dumps(result, ensure_ascii=False)),
            })

    # MAX_ROUNDS 用完都没出文本
    yield _sse({"type": "done", "actions": last_actions, "warning": "hit max rounds"})

@router.post("/api/chat/upload-image")
async def chat_upload_image(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    """侧栏拖图上传 — 存到 数据库/valut/attachments/YYYY-MM-DD/。

    返回 {url, filename, size}:
      - url: 用 /attachments/... 通过 GET /attachments/{date}/{name} 取
      - filename: 服务端生成的稳定文件名(原名 + 时间戳 hash 防碰)
    decision: 当前 LLM(deepseek-chat)无视觉,图本身 AI 看不到 — 只保留路径
    + 文件名,留作日记图文档案 + 给 AI 一个"知道你贴了图"的 reference。
    """
    if not file.filename:
        raise HTTPException(400, "no filename")
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    allowed_image_ext = _ALLOWED_IMAGE_EXT()
    if ext not in allowed_image_ext:
        raise HTTPException(400, f"unsupported ext '.{ext}'. allowed: {sorted(allowed_image_ext)}")
    data = await file.read()
    max_image_bytes = _MAX_IMAGE_BYTES()
    if len(data) > max_image_bytes:
        raise HTTPException(413, f"file too large ({len(data)} bytes > {max_image_bytes})")
    if len(data) == 0:
        raise HTTPException(400, "empty file")

    # sha256 去重:同字节图(用户重传 / vision-pre-router race / drag 重操作)直接复用既有
    # url + 跳过 OCR/vision call,既省空间也避免 curator 把同图返多次("找狗"返 5 张
    # 一模一样客厅照那条 5.16 bug 的根治)。
    sha = hashlib.sha256(data).hexdigest()
    existing = _FIND_BY_HASH(sha)
    if existing and existing.get("url"):
        return {
            "url": existing["url"],
            "filename": existing.get("filename", ""),
            "original": file.filename,
            "size": existing.get("size", len(data)),
            "deduped": True,
            "deduped_to": f"{existing.get('date','')}/{existing.get('filename','')}",
        }

    today = datetime.now().strftime("%Y-%m-%d")
    day_dir = _ATTACHMENTS_DIR() / today
    day_dir.mkdir(parents=True, exist_ok=True)
    # 文件名:时间戳-rand.ext,保留原名做备注但不进路径(避免奇怪字符)
    stamp = datetime.now().strftime("%H%M%S")
    rand = secrets.token_hex(3)
    saved_name = f"{stamp}-{rand}.{ext}"
    (day_dir / saved_name).write_bytes(data)
    # 同步 upsert 最小 record(hash + url + size):防同字节连续 upload 的 race —
    # 不然 #2 在 #1 的后台 OCR 还没跑完时去 _find_by_hash 找不到东西就误判 新图。
    # OCR 仍走后台不阻塞响应。
    _INDEX_UPSERT(
        today, saved_name,
        url=f"/attachments/{today}/{saved_name}",
        hash=sha,
        size=len(data),
        original=file.filename,
    )
    if background_tasks is not None:
        background_tasks.add_task(
            _INDEX_ATTACHMENT, today, saved_name, file.filename, len(data), sha
        )
    return {
        "url": f"/attachments/{today}/{saved_name}",
        "filename": saved_name,
        "original": file.filename,
        "size": len(data),
        "deduped": False,
    }

@router.post("/api/chat")
async def chat(req: Request, background_tasks: BackgroundTasks):
    body = await req.json()
    context = body.get("context", {})
    user_msg = body.get("message", "")
    history = body.get("history", []) or []
    model_id = body.get("model_id")  # 前端 picker 选的 profile id
    stream_mode = bool(body.get("stream"))

    profile = _GET_PROFILE(model_id)
    client = _GET_CLIENT(profile)
    if client is None:
        raise HTTPException(503, "API client not configured. See /api/config-status.")
    active_model = _GET_MODEL(profile)
    thinking_history = bool(_thinking_request_kwargs(active_model))

    time_hint = _COMPUTE_TIME_HINT()
    # 用户当前浏览的日期(从 thread.js context.view_date 来)。fallback 到 today。
    # AI 落 scrapbook / patch_journal_block 默认必须用这一天 — 不是 today,
    # 不是 hint 里的"now"日期(可能 user 在历史天浏览,now 跟 view_date 不同)。
    view_date = (context or {}).get("view_date") or _TODAY_DATE_STR()
    view_date_hint = f"[view-date] 用户当前浏览: {view_date}(YYYY-MM-DD) — scrapbook / patch_journal_block 的 date 参数默认必传这个,不是 today。"

    refs = context.get("refs", [])
    image_refs = _mark_vision_pending(refs)
    # The persisted/renderable attachment set may also contain cutout caches.  They
    # stay available to UI tools, but must not be disclosed in an AI turn context.
    safe_context = {
        **context,
        "refs": [ref for ref in refs if not isinstance(ref, dict) or ref.get("kind") != "image"] + image_refs,
    }
    ctx_str = json.dumps(safe_context, ensure_ascii=False, indent=2)
    # 主模型会直接看本轮图片并调用 record_image_observation；响应完成后每轮只
    # 清 3 个 pending。本轮图片优先，剩余额度顺带渐进补齐升级前的存量照片。
    background_tasks.add_task(
        retry_pending_vision, 3,
        [(ref.get("payload") or {}).get("url") for ref in image_refs],
    )
    workflow = (_build_vision_workflow_block(view_date) + "\n\n") if image_refs else ""
    full_user_text = (
        f"{time_hint}\n{view_date_hint}\n\n"
        f"<context>\n{ctx_str}\n</context>\n\n"
        f"{workflow}"
        f"{user_msg}"
    )

    # ── history processing: strip OCR + sliding-window summarize ──
    # 0.1.4 起 tool 段也保留 (assistant.tool_calls + role:tool 结果) —
    # 之前丢这些导致 AI 每轮 re-call read_today_schedule 等只读工具,cache 频繁 miss。
    # 上限: TOOL_HISTORY_CAP 个 tool result 字符总量,超了从最早的开始扔。
    cleaned_history = []
    retired_tool_call_ids = set()
    for m in history:
        role = m.get("role")
        if role == "user":
            content = m.get("content")
            if not content:
                continue
            if not m.get("_canonical"):
                content = _STRIP_OCR_HISTORY(content)
            cleaned_history.append({"role": "user", "content": _multimodal_history_content(content)})
        elif role == "assistant":
            content = m.get("content") or ""
            entry = {"role": "assistant", "content": content}
            if m.get("_canonical") and m.get("reasoning_content"):
                entry["reasoning_content"] = m.get("reasoning_content")
            # 保 tool_calls — 没它,下条 tool 消息会被 DeepSeek 拒(must follow tool_calls)
            tcs = m.get("tool_calls")
            if tcs and isinstance(tcs, list):
                kept = []
                for tc in tcs:
                    fn = ((tc or {}).get("function") or {}).get("name") if isinstance(tc, dict) else ""
                    if fn == "load_tool_group":
                        retired_tool_call_ids.add((tc or {}).get("id", ""))
                    else:
                        kept.append(tc)
                # V4 thinking 的工具轮必须带首次返回的原始 reasoning_content。
                # 升级前/非 canonical 历史没有它，整组降级为普通 assistant 文本并跳过
                # 对应 tool result，不能伪造 CoT 或把残缺协议发给 provider。
                replay_safe = (
                    not thinking_history
                    or (
                        bool(m.get("_canonical"))
                        and isinstance(m.get("reasoning_content"), str)
                        and bool(m.get("reasoning_content"))
                    )
                )
                if kept and replay_safe:
                    entry["tool_calls"] = kept
                elif kept:
                    retired_tool_call_ids.update(
                        (tc or {}).get("id", "") for tc in kept if isinstance(tc, dict)
                    )
            cleaned_history.append(entry)
        elif role == "tool":
            content = m.get("content") or ""
            tcid = m.get("tool_call_id") or ""
            if not tcid or tcid in retired_tool_call_ids:
                continue   # 没 id 关联不上 assistant.tool_calls,DeepSeek 拒
            # 每条 tool 结果再 truncate 一次 (避免历史里堆几条 5K MD 的)
            content = _truncate_tool_result(content)
            cleaned_history.append({
                "role": "tool", "tool_call_id": tcid, "content": content,
            })

    # 历史 tool 总量限额: 从最早开始扔超额的 tool result 字符。
    # 注意不能扔单独的 assistant.tool_calls (会孤儿)— 跟它配对的 tool 一起扔。
    cleaned_history = _trim_history_tool_volume(cleaned_history, max_tool_chars=24000)

    # 历史图片 brief:7.23 起不再改写历史消息(B2,历史字节冻结保 KV 前缀),
    # 改为把索引块追加进本 turn 新 user message 尾部(尾缀注入铁律)。
    img_index_block = _history_image_brief_block(cleaned_history)
    if img_index_block:
        full_user_text = f"{full_user_text}\n\n{img_index_block}"

    sys_prompt = _BUILD_SYSTEM_PROMPT(context, model_id=active_model)

    # decision: chat 路径不再做 sliding-window 摘要；client 由 Compact checkpoint
    # 派生“摘要 + 最近原始轮次”，不截断用户可回看的完整 History。
    # DeepSeek prompt cache hit input ~$0.0036/M token,no-compress 全发用稳定 prefix
    # 比 compress 重算 summary 便宜 ~17×。详细论证 see 5.21 21:18 实测命中率。
    # _summarize_history fn 留着给 eval/board 路径用。
    recent = cleaned_history

    messages = [{"role": "system", "content": sys_prompt}]
    for m in recent:
        messages.append(m)
    current_content, visible_image_refs = _materialize_user_content(full_user_text, image_refs)
    messages.append({"role": "user", "content": current_content})

    # ActionPolicy 只做宿主完整性检查（例如图片必须本轮可见）；领域写入不再从
    # 用户措辞推断授权。tool output 不得伪造可见图片引用。
    recent_user_texts = []
    for m in cleaned_history:
        if m.get("role") != "user":
            continue
        content = m.get("content", "")
        if isinstance(content, list):
            content = next((b.get("text", "") for b in content
                            if isinstance(b, dict) and b.get("type") == "text"), "")
        recent_user_texts.append(content)
    policy_context = {**context, "refs": visible_image_refs}
    action_context = _BUILD_ACTION_CONTEXT(user_msg, policy_context, recent_user_texts)
    quota_used = {}  # per-chat-turn tool 用量

    # ── streaming 模式:SSE 事件流(action / delta / done / error)──
    if stream_mode:
        return StreamingResponse(
            _chat_stream_generator(client, active_model, messages, action_context, quota_used,
                                   model_content=full_user_text),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # multi-turn tool loop (max 6 rounds);最后一轮 force-no-tool 逼出文本回复,
    # 避免某些模型(如 DeepSeek)search 完仍想继续 search 撞 loop 上限返空 reply。
    last_actions = []
    MAX_ROUNDS = 10
    for round_idx in range(MAX_ROUNDS):
        is_last_round = (round_idx == MAX_ROUNDS - 1)
        try:
            # tools 数组每轮同形传入；宿主策略在 dispatch 前独立检查 side effect。
            # 最后一轮不删 tools 字段而是 tool_choice="none" 逼文本 —— 删整段 tools JSON
            # 会把该轮请求前缀从 tools 起全部打废(KV 缓存失效),"none" 只动几个字节。
            # 行为等价:模型同样无法调用工具(7.23 前缀稳定性审计 A1)。
            kwargs = {"model": active_model, "messages": messages,
                      "tools": _ACTIVE_TOOLS(action_context),
                      "tool_choice": "auto" if not is_last_round else "none",
                      **_thinking_request_kwargs(active_model)}
            # sync OpenAI 调用丢 threadpool — 不阻塞 asyncio event loop,
            # eval/board 类同时跑的 endpoint 不再被锁死(详 5.21 21:30 事故)
            resp = await asyncio.to_thread(client.chat.completions.create, **kwargs)
        except Exception as e:
            # 把 OpenAI/Anthropic 等 client 异常转成结构化 JSON,前端能解析
            err_text = str(e)
            status_match = re.search(r"Error code:\s*(\d+)", err_text)
            code = int(status_match.group(1)) if status_match else 500
            short = err_text[:300]
            return JSONResponse(
                status_code=200,  # 200 让前端正常 parse;reply 字段说明错
                content={
                    "reply": f"⚠ AI 调用失败 ({code}): {short}",
                    "actions": [],
                    "error": True,
                    "error_code": code,
                },
            )
        msg = resp.choices[0].message
        _log_reasoning_observation(
            getattr(msg, "reasoning_content", None) or "", "chat/non-stream", active_model
        )
        _LOG_CACHE_USAGE(resp, "chat/non-stream")
        # 用 model_dump 完整转,保留所有 provider 特有字段(尤其 DeepSeek V4 Pro 的
        # reasoning_content,thinking 模式下下一轮必须回传,否则 400)
        asst_msg = msg.model_dump(exclude_none=True)
        asst_msg["role"] = "assistant"
        # 严格按 OAI spec:tool_calls 空时不带这个 field(部分 provider 收 [] 会卡住)
        if not msg.tool_calls:
            asst_msg.pop("tool_calls", None)
        # content 不能是 None
        if asst_msg.get("content") is None:
            asst_msg["content"] = ""

        # ── DSML fallback:model 把 tool_call 当文本吐时,提取 + 升级成真 tool_calls ──
        synth_calls = []
        if not msg.tool_calls and asst_msg["content"]:
            asst_msg["content"], synth_calls = _extract_synthetic_tool_calls(asst_msg["content"])
            if synth_calls:
                asst_msg["tool_calls"] = [{
                    "id": c["id"], "type": "function",
                    "function": {"name": c["name"],
                                 "arguments": json.dumps(c["args"], ensure_ascii=False)},
                } for c in synth_calls]

        messages.append(asst_msg)

        if synth_calls:
            _exec_synth_calls(synth_calls, messages, last_actions, action_context, quota_used)
            continue

        if not msg.tool_calls:
            # 防 reply 空 + 有 action 时前端啥都不显示
            reply = msg.content or ""
            # MiniMax / 部分 reasoner 模型把 chain-of-thought 当 content 一起返回,strip 掉
            reply = re.sub(r"<think>.*?</think>\s*", "", reply, flags=re.DOTALL).strip()
            if not reply and last_actions:
                names = ", ".join(a.get("name", "?") for a in last_actions)
                reply = f"✓ 完成: {names}"
            reply = _audit_unauthorized_claim(reply, last_actions)
            return {"reply": reply, "actions": last_actions}

        tool_results = []
        for tc in msg.tool_calls:
            # 跳过非 function 类型(如内置 web_search)——上游已自处理,结果直接折进消息流
            if getattr(tc, "type", "function") != "function" or not getattr(tc, "function", None):
                continue
            fn = tc.function.name
            args = json.loads(tc.function.arguments or "{}")
            result = _DISPATCH_TOOL(fn, args, action_context, quota_used)
            tool_results.append({"id": tc.id, "name": fn, "args": args, "result": result})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": _truncate_tool_result(json.dumps(result, ensure_ascii=False)),
            })

        # save side-effect summary for the client
        # NOTE: 0.1.4 起 = 而非 extend,导致只看见最后一轮的工具调用 — known bug,
        # 见 6.2 测试 trace 漏 actions。先不改避免破坏 actions array contract,
        # client 拿 tool 历史的真路径是 stream "action" 事件累积,不是 done.actions。
        if tool_results:
            last_actions = tool_results

    # last round 若 synth 兜底执行了 tool,messages 末尾是 tool result,
    # msg.content 还含原始 DSML 文本 → 多打一次 bonus 拿干净 reply
    if messages and messages[-1].get("role") == "tool":
        try:
            # 同一批 A1 修复:这个 bonus 收尾调用之前漏了 tools/tool_choice,是删字段打废
            # 前缀的原样漏网(跟主 loop 末轮同一个 messages 前缀,同样得同形传 tools + none)。
            bonus = await asyncio.to_thread(client.chat.completions.create,
                                            model=active_model, messages=messages,
                                            tools=_ACTIVE_TOOLS(action_context), tool_choice="none",
                                            **_thinking_request_kwargs(active_model))
            _log_reasoning_observation(
                getattr(bonus.choices[0].message, "reasoning_content", None) or "",
                "chat/non-stream-bonus",
                active_model,
            )
            _LOG_CACHE_USAGE(bonus, "chat/non-stream-bonus")
            final_reply = (bonus.choices[0].message.content or "").strip()
        except Exception as e:
            final_reply = f"(tool loop 用完;synthesis call 失败:{type(e).__name__})"
    else:
        final_reply = msg.content or ""
    final_reply = re.sub(r"<think>.*?</think>\s*", "", final_reply, flags=re.DOTALL).strip()
    final_reply = _audit_unauthorized_claim(final_reply, last_actions)
    return {"reply": final_reply or "(no reply, tool loop hit max iterations)", "actions": last_actions}
