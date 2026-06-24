"""setup_routes — APIRouter for /api/setup* + /api/models (config wizard).

Extract Module(ctrl-c-v § 9):把 setup / config 簇从 server.py monolith 抽出。
thin wrapper —— 每个 handler 仍调 server.py 现有 helper(function-level lazy
import 避循环),业务逻辑零变化。

为什么 helper 留 server.py:
  load_config / _save_config / get_client / list_model_profiles / _profile_from_top_level
  + 常量(CONFIG_PATH / DEEPSEEK_* / BAILIAN_*)被全项目共用,不属于 setup 簇。
  setup_routes 只持有 10 个 endpoint;helper lazy `from server import` 拉。

re-export(Parallel Change, Sato 2014):server.py 末尾 `from setup_routes import ...`
让任何直接 `server.setup_save()` 的调用方 + 测试 patch 跨阶段都生效。

characterization 守门:tests/test_setup_routes.py(21 GREEN-LOCK,§ T7)。
"""
import re

import requests
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["setup"])


# ── GET /api/setup-status ────────────────────────────────────────────
@router.get("/api/setup-status")
def setup_status():
    """决定是否要弹 setup 向导:无 config / 全 placeholder key / 没 models 数组都算未配置。"""
    from server import load_config, _profile_from_top_level
    cfg = load_config()
    if not cfg:
        return {"configured": False, "reason": "config 文件不存在"}
    profiles = cfg.get("models") or ([_profile_from_top_level(cfg)] if cfg.get("api_key") else [])
    if not profiles:
        return {"configured": False, "reason": "config 里没有 models 数组也没 top-level api_key"}
    has_real = any(
        p.get("api_key") and not p["api_key"].startswith("YOUR_") for p in profiles
    )
    if not has_real:
        return {"configured": False, "reason": "所有 api_key 都是 YOUR_* 占位符"}
    return {"configured": True, "profile_count": len(profiles)}


# ── GET /api/setup/templates ─────────────────────────────────────────
@router.get("/api/setup/templates")
def setup_templates():
    """新 setup UI 分两段(ritual):
    · deepseek: 主对话(说话的那个)— api.deepseek.com 直连
    · bailian: 视觉助手(给 deepseek 装眼睛)— 阿里云百炼,仅 vision model
    """
    from server import (DEEPSEEK_BASE_URL, DEEPSEEK_MODELS,
                        BAILIAN_BASE_URL, BAILIAN_VISION_MODELS)
    return {
        "deepseek": {
            "base_url": DEEPSEEK_BASE_URL,
            "label": "DeepSeek 直连",
            "models": DEEPSEEK_MODELS,
        },
        "bailian": {
            "base_url": BAILIAN_BASE_URL,
            "label": "阿里云百炼(视觉助手)",
            "models": BAILIAN_VISION_MODELS,
        },
        "custom_templates": [],
        "templates": [
            {"label": f"DeepSeek · {m['label']}", "base_url": DEEPSEEK_BASE_URL, "model": m["id"]}
            for m in DEEPSEEK_MODELS
        ],
    }


# ── POST /api/setup/test ─────────────────────────────────────────────
@router.post("/api/setup/test")
async def setup_test(req: Request):
    """对单个 profile 发一次最小 chat 调用,验证 key+endpoint+model 三元组真的能通。"""
    from server import get_client
    body = await req.json()
    profile = {
        "id": body.get("id") or "test",
        "label": body.get("label") or "test",
        "base_url": body.get("base_url") or "",
        "api_key": body.get("api_key") or "",
        "model": body.get("model") or "",
    }
    if not profile["api_key"] or profile["api_key"].startswith("YOUR_"):
        return {"ok": False, "reason": "api_key 是占位符或为空"}
    if not profile["model"] or not profile["base_url"]:
        return {"ok": False, "reason": "model 或 base_url 为空"}
    try:
        client = get_client(profile)
        if client is None:
            return {"ok": False, "reason": "OpenAI SDK 未装或 key 格式错"}
        resp = client.chat.completions.create(
            model=profile["model"],
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=8,
        )
        reply = (resp.choices[0].message.content or "")[:80]
        return {"ok": True, "reply": reply, "model": profile["model"]}
    except Exception as e:
        err = str(e)
        # 截短常见 OAI SDK 长 error
        m = re.search(r"Error code:\s*(\d+).*?'message':\s*'([^']+)'", err)
        short = f"HTTP {m.group(1)}: {m.group(2)}" if m else err[:200]
        return {"ok": False, "reason": short}


# ── POST /api/setup/test-baidu ───────────────────────────────────────
@router.post("/api/setup/test-baidu")
async def setup_test_baidu(req: Request):
    """测百度 OCR / Cutout key 是否能拿 token。"""
    body = await req.json()
    api = body.get("api_key", "")
    sec = body.get("secret_key", "")
    if not api or not sec or api.startswith("YOUR_") or sec.startswith("YOUR_"):
        return {"ok": False, "reason": "key 是占位符或为空"}
    try:
        from ocr import _get_access_token
        token = _get_access_token(api, sec)
        if not token:
            return {"ok": False, "reason": "拿不到 access_token (key 错或被禁)"}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": str(e)[:200]}


# ── GET /api/setup/current ───────────────────────────────────────────
@router.get("/api/setup/current")
def setup_current():
    """返当前 config(给 settings 面板 preload 用)。本地服务,不脱敏。"""
    from server import load_config
    cfg = load_config() or {}
    return {
        "models": cfg.get("models", []),
        "default_model_id": cfg.get("default_model_id", ""),
        "dashscope_api_key": cfg.get("dashscope_api_key", ""),
        "dashscope_base_url": cfg.get("dashscope_base_url", ""),
        "dashscope_vision_model": cfg.get("dashscope_vision_model", ""),
        "baidu_cutout_api_key": cfg.get("baidu_cutout_api_key", ""),
        "baidu_cutout_secret_key": cfg.get("baidu_cutout_secret_key", ""),
    }


# ── POST /api/setup/save-partial ─────────────────────────────────────
@router.post("/api/setup/save-partial")
async def setup_save_partial(req: Request):
    """部分更新 config:body 里有什么字段就改什么,其他保持。
    支持 models(整列表替换)/ baidu_* / gemini_api_key / default_model_id。
    """
    from server import load_config, _save_config
    body = await req.json()
    cfg = load_config() or {}
    if "models" in body:
        cfg["models"] = body["models"]
    if "default_model_id" in body and body["default_model_id"]:
        cfg["default_model_id"] = body["default_model_id"]
    for k in ("dashscope_api_key", "dashscope_base_url", "dashscope_vision_model",
              "baidu_cutout_api_key", "baidu_cutout_secret_key"):
        if k in body:
            v = body[k]
            if v == "" or v is None:
                cfg.pop(k, None)
            else:
                cfg[k] = v
    _save_config(cfg)
    return {"ok": True}


# ── POST /api/setup/save-gemini ──────────────────────────────────────
@router.post("/api/setup/save-gemini")
async def setup_save_gemini(req: Request):
    """单独存 Gemini key,不动其他 config(避免 wizard 不预加载导致整体覆盖)。"""
    from server import load_config, _save_config
    body = await req.json()
    key = (body.get("api_key") or "").strip()
    if not key or key.startswith("YOUR_"):
        raise HTTPException(400, "key 为空或占位符")
    cfg = load_config() or {}
    cfg["gemini_api_key"] = key
    _save_config(cfg)
    return {"ok": True}


# ── POST /api/setup/test-gemini ──────────────────────────────────────
@router.post("/api/setup/test-gemini")
async def setup_test_gemini(req: Request):
    """测 Gemini key 是否能调通(发个最小请求)。"""
    body = await req.json()
    key = (body.get("api_key") or "").strip()
    if not key or key.startswith("YOUR_"):
        return {"ok": False, "reason": "key 为空或占位符"}
    try:
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent",
            headers={"Content-Type": "application/json", "X-goog-api-key": key},
            json={"contents": [{"parts": [{"text": "reply with: pong"}]}]},
            timeout=20,
        )
        if r.status_code != 200:
            return {"ok": False, "reason": f"http {r.status_code}: {r.text[:200]}"}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": str(e)[:200]}


# ── POST /api/setup/save ─────────────────────────────────────────────
@router.post("/api/setup/save")
async def setup_save(req: Request):
    """保存完整 config 到磁盘。前端必须先把 LLM profiles 都 test 通过才能调本接口。"""
    from server import _save_config, CONFIG_PATH, BAILIAN_BASE_URL
    body = await req.json()
    profiles = body.get("models") or []
    if not profiles:
        raise HTTPException(400, "至少配一个 LLM provider")
    real = [p for p in profiles if p.get("api_key") and not p["api_key"].startswith("YOUR_")]
    if not real:
        raise HTTPException(400, "所有 api_key 都是占位符,无效")

    # 自动生成 id (label + 序号),如果用户没指定
    seen_ids = set()
    for i, p in enumerate(profiles):
        if not p.get("id"):
            base = re.sub(r"\W+", "-", (p.get("label") or "p").lower()).strip("-") or f"p{i}"
            p["id"] = base if base not in seen_ids else f"{base}-{i}"
        seen_ids.add(p["id"])

    cfg_out = {
        "_comment": "由 setup 向导生成。secret 优先走 .env,这里是 fallback。手动改也 OK,跑 gateway 时会重读。",
        "default_model_id": body.get("default_model_id") or profiles[0]["id"],
        "models": profiles,
    }
    # 顶层 chat 主 key/url(取 default profile 的)
    def_profile = next((p for p in profiles if p.get("id") == cfg_out["default_model_id"]), profiles[0])
    cfg_out["api_key"] = def_profile.get("api_key", "")
    cfg_out["base_url"] = def_profile.get("base_url", "")
    cfg_out["model"]    = def_profile.get("model", def_profile.get("id"))
    # 视觉助手(百炼)单独存,跟 chat 主 key 隔开
    dk = body.get("dashscope_api_key")
    if dk and not dk.startswith("YOUR_"):
        cfg_out["dashscope_api_key"] = dk
        cfg_out["dashscope_base_url"] = body.get("dashscope_base_url", BAILIAN_BASE_URL)
        cfg_out["dashscope_vision_model"] = body.get("dashscope_vision_model", "qwen3-vl-flash")
    # 百度可选段
    for k in ("baidu_ocr_api_key", "baidu_ocr_secret_key", "baidu_cutout_api_key", "baidu_cutout_secret_key"):
        v = body.get(k)
        if v and not v.startswith("YOUR_"):
            cfg_out[k] = v
    # Gemini key — UI 不再露,但若有人通过 env 注入这里也接(向后兼容)
    gk = body.get("gemini_api_key")
    if gk and not gk.startswith("YOUR_"):
        cfg_out["gemini_api_key"] = gk

    _save_config(cfg_out)
    return {"ok": True, "saved_to": str(CONFIG_PATH)}


# ── GET /api/models ──────────────────────────────────────────────────
@router.get("/api/models")
def list_models():
    """前端 picker 用,返 [{id,label,model,base_url,...}] 列表 + 当前 default_id。"""
    from server import load_config, list_model_profiles
    cfg = load_config() or {}
    profiles = list_model_profiles()
    default_id = cfg.get("default_model_id") or (profiles[0]["id"] if profiles else None)
    return {"models": profiles, "default_id": default_id}
