# PATTERN: config — gateway-config.json 读写 + env overlay + 多 model profile 解析
# USE WHEN: 改 config 加载优先级 / profile 兼容分支 / client factory 出口
# COPY THIS: 无 — 本模块是 server.py §3(清册01)的搬迁体,契约在 server re-export
#
# 抽出记录(2026-07-22, 清册01-§3,Parallel Change expand):
# - 原址 server.py §3 配置层段(_save_config.._get_vision_model),函数体逐字节照搬。
# - 路径、writer、logger、reporter、model factory 通过窄参数注入;server.py 保留
#   兼容适配器和 call-time patch 语义，本模块不导入应用组装根。
# - 既有调用继续经 server 兼容适配器保持 patch-where-used 语义；新代码可直接调用
#   本模块并显式传入边界依赖。
import json
import logging
import os
from pathlib import Path

import httpx

from runtime_paths import CONFIG_DIR, GATEWAY_DIR
from safe_io import _safe_write_text as _safe_write_text_leaf


log = logging.getLogger("gateway")
CONFIG_PATH = CONFIG_DIR / "gateway-config.json"


# ── env loader ───────────────────────────────────────────────────────
# 把 secret 从 gateway-config.json 抽出来,搬到 .env 文件 — config.json 只放
# 结构(models / base URLs / defaults),.env 放 key。两个 .env 候选位置:
#   1. APP_STATE_DIR/config/.env  — 用户机的 production(.app 安装后用)
#   2. <gateway dir>/.env         — dev 时
# 读优先级:os.environ > .env 文件 > gateway-config.json > 默认值

def _load_env_file(path: Path, *, logger=None) -> dict:
    """简易 .env 解析:KEY=value 一行一条,#注释 / 空行跳过。引号包裹的去引号。"""
    logger = logger or log
    if not path.exists():
        return {}
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k:
                out[k] = v
    except Exception as e:
        logger.warning(f".env load failed at {path}: {e}")
    return out


def _env_overlay(*, gateway_dir=GATEWAY_DIR, config_dir=CONFIG_DIR, logger=None) -> dict:
    """合并 env 来源 → 字典。优先级:os.environ > APP_STATE .env > gateway/.env"""
    logger = logger or log
    merged = {}
    for p in (gateway_dir / ".env", config_dir / ".env"):
        merged.update(_load_env_file(p, logger=logger))
    for k in (
        "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_DEFAULT_MODEL",
        "DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL", "DASHSCOPE_VISION_MODEL",
        "BAIDU_OCR_API_KEY", "BAIDU_OCR_SECRET_KEY",
        "BAIDU_CUTOUT_API_KEY", "BAIDU_CUTOUT_SECRET_KEY",
        "GEMINI_API_KEY",
        "FEEDBACK_SINK_URL",
    ):
        ev = os.environ.get(k)
        if ev:
            merged[k] = ev
    return merged


# ── env write-through ────────────────────────────────────────────────
# 7.22 事故:setup UI 把 key 存进 gateway-config.json,却被 .env 里同名变量静默
# 覆盖(load_config 优先级 env > json),用户在 UI 里改 key 永远不生效且无感知。
# 修:保存 secret 时,若已有 .env 文件里存在同名 KEY,同步改写该行 — 两层不再打架。
# 只改写已存在的 KEY 行,不新建文件/新增行(不把 json 单真源用户升级成双真源)。
_CFG_ENV_MAP = {
    "api_key": "DEEPSEEK_API_KEY",
    "base_url": "DEEPSEEK_BASE_URL",
    "model": "DEEPSEEK_DEFAULT_MODEL",
    "dashscope_api_key": "DASHSCOPE_API_KEY",
    "dashscope_base_url": "DASHSCOPE_BASE_URL",
    "dashscope_vision_model": "DASHSCOPE_VISION_MODEL",
    "baidu_cutout_api_key": "BAIDU_CUTOUT_API_KEY",
    "baidu_cutout_secret_key": "BAIDU_CUTOUT_SECRET_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
}


def sync_env_secrets(
    updates: dict,
    *,
    gateway_dir=GATEWAY_DIR,
    config_dir=CONFIG_DIR,
    writer=_safe_write_text_leaf,
    logger=None,
) -> None:
    """config 保存后调用:把 updates 里的 secret 同步进已存在的 .env 覆盖层。
    空值 → 注释掉该行(让 json 层重新生效);os.environ 里若也有同名变量,
    进程内一并更新(下次重启前也生效)。文件不存在/无该 KEY = 无事发生。
    """
    logger = logger or log
    env_updates = {}
    for cfg_k, v in (updates or {}).items():
        env_k = _CFG_ENV_MAP.get(cfg_k)
        if env_k:
            env_updates[env_k] = (v or "").strip() if isinstance(v, str) else (v or "")
    if not env_updates:
        return
    for env_k, v in env_updates.items():
        if v and os.environ.get(env_k):
            os.environ[env_k] = v
        elif not v:
            # 本应用进程不应继续保有已退役的 provider key。父 shell 的环境
            # 变量无法跨进程删除，但当前 sidecar 必须立即停止读取它。
            os.environ.pop(env_k, None)
    for env_path in (gateway_dir / ".env", config_dir / ".env"):
        if not env_path.exists():
            continue
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            logger.warning(f".env read failed at {env_path}: {e}")
            continue
        changed = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            k = stripped.split("=", 1)[0].strip()
            if k not in env_updates:
                continue
            v = env_updates[k]
            new_line = f"{k}={v}" if v else f"# {stripped}"
            if line != new_line:
                lines[i] = new_line
                changed = True
        if changed:
            try:
                writer(env_path, "\n".join(lines) + "\n")
            except Exception as e:
                logger.warning(f".env write-through failed at {env_path}: {e}")
                continue
            try:
                os.chmod(env_path, 0o600)
            except Exception:
                pass  # 非 POSIX — 最大努力


# ── config ───────────────────────────────────────────────────────────
def _save_config(
    cfg: dict,
    *,
    config_path=CONFIG_PATH,
    writer=_safe_write_text_leaf,
) -> None:
    """CONFIG_PATH 写盘统一入口:atomic + 5-rotate bak + chmod 0600。
    持有 API key,中途崩 = 用户秘钥不可恢复;明文权限松 = 拷 .app 漏 key。
    """
    content = json.dumps(cfg, ensure_ascii=False, indent=2)
    writer(config_path, content, rotate=True)
    try:
        os.chmod(config_path, 0o600)
        for i in range(1, 6):
            bak = Path(f"{config_path}.bak.{i}")
            if bak.exists():
                os.chmod(bak, 0o600)
    except Exception:
        pass  # 非 POSIX 或 perm 错 — 最大努力


def load_config(
    *,
    config_path=CONFIG_PATH,
    env_overlay=None,
    logger=None,
    reporter=None,
):
    """读 gateway-config.json,然后用 env 覆盖 secret 字段。
    返合并后的 dict。env 不存在的字段沿用 config.json。
    主文件损坏 → 尝试 bak.1 回滚;再不行返空 dict 让 setup wizard 接管。
    """
    logger = logger or log
    cfg = {}
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"CONFIG_PATH 损坏 ({type(e).__name__}: {e}),尝试 bak.1 回滚")
            bak1 = Path(f"{config_path}.bak.1")
            if bak1.exists():
                try:
                    cfg = json.loads(bak1.read_text(encoding="utf-8"))
                    logger.warning(f"CONFIG_PATH 已从 bak.1 回滚")
                    try:
                        if reporter is not None:
                            reporter(
                                "config_restored_from_bak1",
                                f"主 config 损坏,bak.1 回滚成功",
                                context={"err": str(e)[:120]},
                            )
                    except Exception:
                        pass
                except Exception as e2:
                    logger.error(f"CONFIG_PATH bak.1 也无法解析: {e2}")
                    try:
                        if reporter is not None:
                            reporter(
                                "config_corrupt_no_recovery",
                                f"主+bak.1 双损,fallback 空 dict",
                                context={"err": str(e)[:120], "bak_err": str(e2)[:120]},
                            )
                    except Exception:
                        pass
            else:
                try:
                    if reporter is not None:
                        reporter(
                            "config_corrupt_no_bak",
                            f"主 config 损坏且无 bak.1",
                            context={"err": str(e)[:120]},
                        )
                except Exception:
                    pass
    env = env_overlay() if env_overlay is not None else _env_overlay()
    # 顶层 chat 主 key
    if env.get("DEEPSEEK_API_KEY"):
        cfg["api_key"] = env["DEEPSEEK_API_KEY"]
    if env.get("DEEPSEEK_BASE_URL"):
        cfg["base_url"] = env["DEEPSEEK_BASE_URL"]
    if env.get("DEEPSEEK_DEFAULT_MODEL"):
        cfg["model"] = env["DEEPSEEK_DEFAULT_MODEL"]
        cfg.setdefault("default_model_id", env["DEEPSEEK_DEFAULT_MODEL"])
    # vision 路
    if env.get("DASHSCOPE_API_KEY"):
        cfg["dashscope_api_key"] = env["DASHSCOPE_API_KEY"]
    if env.get("DASHSCOPE_BASE_URL"):
        cfg["dashscope_base_url"] = env["DASHSCOPE_BASE_URL"]
    if env.get("DASHSCOPE_VISION_MODEL"):
        cfg["dashscope_vision_model"] = env["DASHSCOPE_VISION_MODEL"]
    # 百度 / Gemini 可选
    for env_k, cfg_k in [
        ("BAIDU_OCR_API_KEY", "baidu_ocr_api_key"),
        ("BAIDU_OCR_SECRET_KEY", "baidu_ocr_secret_key"),
        ("BAIDU_CUTOUT_API_KEY", "baidu_cutout_api_key"),
        ("BAIDU_CUTOUT_SECRET_KEY", "baidu_cutout_secret_key"),
        ("GEMINI_API_KEY", "gemini_api_key"),
    ]:
        if env.get(env_k):
            cfg[cfg_k] = env[env_k]
    # models[].api_key — 若顶层 deepseek/dashscope key 给了 env,同步覆盖匹配 base_url 的 profile
    if cfg.get("models"):
        ds_key = env.get("DEEPSEEK_API_KEY")
        ds_url = env.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
        bl_key = env.get("DASHSCOPE_API_KEY")
        bl_url = env.get("DASHSCOPE_BASE_URL") or "dashscope.aliyuncs.com"
        for p in cfg["models"]:
            pb = (p.get("base_url") or "")
            if ds_key and "deepseek" in pb:
                p["api_key"] = ds_key
            elif bl_key and "dashscope" in pb:
                p["api_key"] = bl_key
    return cfg or None

# ── model profiles (多模型切换) ─────────────────────────────────────
DEEPSEEK_DIRECT_URL = "https://api.deepseek.com/v1"
DEEPSEEK_DIRECT_MODEL = "deepseek-v4-flash-vision-exp"
DEEPSEEK_DIRECT_LABEL = "DeepSeek V4 Flash Vision"
DEEPSEEK_OFFICIAL_URLS = {"https://api.deepseek.com", DEEPSEEK_DIRECT_URL}


class DeepSeekTransport(httpx.BaseTransport):
    """Keep raw upstream errors (which may echo credentials) out of UI and logs."""

    def __init__(self, transport=None):
        self._transport = transport if transport is not None else httpx.HTTPTransport()

    def handle_request(self, request):
        if request.url.scheme != "https" or request.url.host != "api.deepseek.com" or request.url.port not in (None, 443):
            raise httpx.ConnectError("DeepSeek requires its official HTTPS endpoint", request=request)
        response = self._transport.handle_request(request)
        if response.status_code < 400:
            return response
        response.close()
        return httpx.Response(
            response.status_code,
            headers={key: response.headers[key] for key in ("retry-after", "retry-after-ms") if key in response.headers},
            json={"error": {"message": "DeepSeek declined the request."}},
        )

    def close(self):
        self._transport.close()


def valid_deepseek_key(key):
    return isinstance(key, str) and bool(key) and not (
        key.startswith("YOUR_") or any(ch.isspace() or ord(ch) < 32 or ord(ch) > 126 for ch in key)
    )


def direct_deepseek_profile(cfg):
    """Read a BYOK credential; never reuse a cloud or custom-provider token."""
    cfg = cfg or {}
    top_url = str(cfg.get("base_url") or "").strip().rstrip("/")
    key = cfg.get("api_key") if not top_url or top_url in DEEPSEEK_OFFICIAL_URLS else None
    if not valid_deepseek_key(key):
        for profile in cfg.get("models") or []:
            if (isinstance(profile, dict)
                    and str(profile.get("base_url") or "").rstrip("/") in DEEPSEEK_OFFICIAL_URLS
                    and valid_deepseek_key(profile.get("api_key"))):
                key = profile["api_key"]
                break
    if not valid_deepseek_key(key):
        return None
    return {
        "id": DEEPSEEK_DIRECT_MODEL, "label": DEEPSEEK_DIRECT_LABEL,
        "model": DEEPSEEK_DIRECT_MODEL, "base_url": DEEPSEEK_DIRECT_URL,
        "api_key": key,
    }


# config 支持 `models: [{id, label, base_url, api_key, model, vision_model?}]` 数组,
# `default_model_id` 指定默认。无 models 数组时,top-level api_key/base_url/model 当唯一 profile。
def _profile_from_top_level(cfg):
    return {
        "id": cfg.get("model", "default"),
        "label": cfg.get("model", "default"),
        "base_url": cfg.get("base_url", "https://api.deepseek.com/v1"),
        "api_key": cfg.get("api_key", ""),
        "model": cfg.get("model", "deepseek-chat"),
        "vision_model": cfg.get("vision_model"),
    }

def list_profiles_full(*, load_config_fn=load_config):
    cfg = load_config_fn() or {}
    profiles = list(cfg.get("models") or [])
    if not profiles and cfg.get("api_key"):
        profiles = [_profile_from_top_level(cfg)]
    return profiles

def list_model_profiles(*, list_profiles_fn=list_profiles_full):
    """前端 picker 用,去掉 api_key。"""
    return [{k: v for k, v in p.items() if k != "api_key"} for p in list_profiles_fn()]


def get_profile(
    model_id=None,
    *,
    list_profiles_fn=list_profiles_full,
    load_config_fn=load_config,
):
    profiles = list_profiles_fn()
    if not profiles:
        return None
    if model_id:
        for p in profiles:
            if p.get("id") == model_id:
                return p
    cfg = load_config_fn() or {}
    default_id = cfg.get("default_model_id")
    if default_id:
        for p in profiles:
            if p.get("id") == default_id:
                return p
    return profiles[0]

def get_client(profile=None, *, get_profile_fn=get_profile, openai_factory=None):
    p = profile or get_profile_fn()
    if not p or not p.get("api_key") or p["api_key"].startswith("YOUR_"):
        return None
    if openai_factory is None:
        return None
    access_token_provider = p.get("access_token_provider")
    api_key = access_token_provider() if callable(access_token_provider) else p["api_key"]
    kwargs = {
        "api_key": api_key,
        "base_url": p.get("base_url", "https://api.deepseek.com/v1"),
        "timeout": 120.0,     # 单次 HTTP 最多 120s。DeepSeek V4 Pro thinking 阶段不出 token,
                          # 长 context synthesis 实测 30-60s,30/60s 太紧会切死。
                          # 防 worker hang 死(过去靠 SIGKILL 救场)+ 给 reasoning 余地。
        "max_retries": 1,    # tool loop 已有重试,这里只兜一次
    }
    if p.get("default_headers"):
        kwargs["default_headers"] = p["default_headers"]
    return openai_factory(**kwargs)

def get_model(profile=None, *, get_profile_fn=get_profile):
    p = profile or get_profile_fn()
    return p.get("model", "deepseek-chat") if p else "deepseek-chat"

def get_vision_model(*, get_profile_fn=get_profile):
    p = get_profile_fn()
    if not p:
        return "deepseek-chat"
    return p.get("vision_model") or p.get("model", "deepseek-chat")
