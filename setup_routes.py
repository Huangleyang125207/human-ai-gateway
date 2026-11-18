"""Local setup for DeepSeek BYOK and optional Baidu cutout."""

from fastapi import APIRouter, HTTPException, Request

from config_store import (
    DEEPSEEK_DIRECT_LABEL, DEEPSEEK_DIRECT_MODEL, DEEPSEEK_DIRECT_URL,
    direct_deepseek_profile, valid_deepseek_key,
)

router = APIRouter(tags=["setup"])

_LOAD_CONFIG = None
_SAVE_CONFIG = None
_SYNC_ENV_SECRETS = None
_CONFIG_PATH = None
_OPENAI_AVAILABLE = None

_MODEL = {
    "id": DEEPSEEK_DIRECT_MODEL,
    "label": DEEPSEEK_DIRECT_LABEL,
    "model": DEEPSEEK_DIRECT_MODEL,
    "tag": "统一对话 · 工具 · 视觉",
    "default": True,
}
_CUTOUT_KEYS = ("baidu_cutout_api_key", "baidu_cutout_secret_key")


def configure_effects(*, load_config, save_config, sync_env_secrets, config_path,
                      openai_available) -> None:
    global _LOAD_CONFIG, _SAVE_CONFIG, _SYNC_ENV_SECRETS, _CONFIG_PATH, _OPENAI_AVAILABLE
    _LOAD_CONFIG = load_config
    _SAVE_CONFIG = save_config
    _SYNC_ENV_SECRETS = sync_env_secrets
    _CONFIG_PATH = config_path
    _OPENAI_AVAILABLE = openai_available


def _require_local_settings_request(req: Request):
    loopback_hosts = {"127.0.0.1", "::1", "localhost"}
    if (req.client is None or req.client.host not in loopback_hosts
            or req.url.hostname not in loopback_hosts):
        raise HTTPException(403, "只能从本机访问设置")
    origin = req.headers.get("origin")
    if origin and origin != f"{req.url.scheme}://{req.url.netloc}":
        raise HTTPException(403, "不接受跨站设置请求")


def _save_settings(body, *, require_key):
    if not isinstance(body, dict):
        raise HTTPException(400, "配置必须是对象")
    if any(field in body for field in ("gateway_url", "gateway_device_token", "base_url", "models")):
        raise HTTPException(400, "仅支持 DeepSeek 官方直连，不接受自定义地址或设备令牌")
    cfg = dict(_LOAD_CONFIG() or {})
    updates = {}
    if "api_key" in body:
        value = body["api_key"]
        key = value.strip() if isinstance(value, str) else None
        if not valid_deepseek_key(key):
            raise HTTPException(400, "请填写有效的 DeepSeek API Key")
        cfg["api_key"] = key
        cfg["base_url"] = DEEPSEEK_DIRECT_URL
        cfg["model"] = DEEPSEEK_DIRECT_MODEL
        updates.update(api_key=key, base_url=DEEPSEEK_DIRECT_URL)
    if require_key and not direct_deepseek_profile(cfg):
        raise HTTPException(400, "请先填写 DeepSeek API Key")

    for field in _CUTOUT_KEYS:
        if field not in body:
            continue
        value = body[field]
        if value is not None and not isinstance(value, str):
            raise HTTPException(400, "抠图密钥必须是文本")
        if value:
            cfg[field] = value
        else:
            cfg.pop(field, None)
        updates[field] = value or ""
    for field in ("gateway_url", "gateway_device_token"):
        cfg.pop(field, None)
    cfg["_comment"] = "AI 请求使用本机配置的 DeepSeek API Key，直连 DeepSeek 官方 API。"
    _SAVE_CONFIG(cfg)
    if updates:
        _SYNC_ENV_SECRETS(updates)


@router.get("/api/config-status")
def config_status():
    if not direct_deepseek_profile(_LOAD_CONFIG()):
        return {"ok": False, "reason": "DeepSeek API key not set"}
    if not _OPENAI_AVAILABLE():
        return {"ok": False, "reason": "OpenAI SDK unavailable"}
    return {"ok": True, "model": DEEPSEEK_DIRECT_MODEL, "provider": DEEPSEEK_DIRECT_URL}


@router.get("/api/setup-status")
def setup_status():
    if not direct_deepseek_profile(_LOAD_CONFIG()):
        return {"configured": False, "reason": "请配置自己的 DeepSeek API Key"}
    return {"configured": True, "profile_count": 1}


@router.get("/api/setup/templates")
def setup_templates():
    return {"deepseek": {"label": "DeepSeek 直连", "base_url": DEEPSEEK_DIRECT_URL,
                          "models": [_MODEL]}, "templates": []}


@router.get("/api/setup/current")
def setup_current(req: Request):
    _require_local_settings_request(req)
    cfg = _LOAD_CONFIG() or {}
    return {
        "has_deepseek_api_key": bool(direct_deepseek_profile(cfg)),
        "model": DEEPSEEK_DIRECT_MODEL,
        **{field: cfg.get(field, "") for field in _CUTOUT_KEYS},
    }


@router.post("/api/setup/save-partial")
async def setup_save_partial(req: Request):
    _require_local_settings_request(req)
    _save_settings(await req.json(), require_key=False)
    return {"ok": True}


@router.post("/api/setup/save")
async def setup_save(req: Request):
    _require_local_settings_request(req)
    _save_settings(await req.json(), require_key=True)
    return {"ok": True, "saved_to": str(_CONFIG_PATH())}


@router.get("/api/models")
def list_models():
    if not direct_deepseek_profile(_LOAD_CONFIG()):
        return {"models": [], "default_id": None}
    return {"models": [_MODEL], "default_id": DEEPSEEK_DIRECT_MODEL}
