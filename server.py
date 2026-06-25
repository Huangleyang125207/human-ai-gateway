"""gateway v0.4 server

Python FastAPI server that:
1. Serves the static gateway/ files (index.html, widgets/, shared/, ...)
2. Proxies chat to DeepSeek (OpenAI-compat) with gateway-extension SKILL injected
3. Executes 3 widget tools the AI can call: list_widgets, add_widget, patch_widget

Run:
    cd agents创作平台/gateway
    python -m pip install fastapi uvicorn openai
    cp .gateway-config.example.json .gateway-config.json
    # edit .gateway-config.json — put your DeepSeek api_key
    python server.py
    # open http://localhost:4321
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import platform as _platform
import random
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, date
from pathlib import Path

import secrets

# ── frozen-sidecar 双执行 guard(2026-06-24 实测必需)─────────────────────
# PyInstaller onefile 把 server.py 当入口 → 运行时 __name__=='__main__',sys.modules 没有 'server'。
# 抽出的模块(pulse_io / pulse_eval / 各 route 模块)做 `from server import X`,没这条 alias 会把
# server.py 当新模块 'server' 二次执行 → 双 app/双锁/双 startup,且 pulse_io 顶层 from-server-import
# 触发循环 import 直接崩(frozen build 启动即 ImportError)。alias 让 'server' = 正在跑的 __main__。
# dev/pytest 下 server 以 'server' 名导入 → sys.modules['server'] 已存在 → setdefault 不动,安全。
sys.modules.setdefault("server", sys.modules[__name__])

log = logging.getLogger("gateway")
log.setLevel(logging.INFO)  # 让 log.info 真的能出来,默认 WARNING 把 cache/quota 等观测吃掉
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s:gateway: %(message)s"))
    log.addHandler(_h)
    log.propagate = False  # 不再 bubble 到 root,避免 uvicorn 重复打
import requests
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# ── paths ────────────────────────────────────────────────────────────
# 代码 vs 用户数据严格分离:
#   代码: ~/human-ai-dev/ (将来 GitHub 仓库)
#   数据: ~/.human-ai/  (XDG 风格,跟代码解耦, 不进 git)
# 优先级: $HUMAN_AI_HOME env var → ~/.human-ai/ → 历史 fallback
# PyInstaller frozen 时,静态资源被解到 sys._MEIPASS。
# 非 frozen(dev / 源码跑)时,GATEWAY_DIR 就是 server.py 所在目录。
#
# macOS .app 特殊处理:--windowed 出来的 bundle 里,_MEIPASS = Contents/Frameworks,
# 但数据文件(html/js/css)实际在 Contents/Resources/,Frameworks 那边全是符号链接
# 指向 Resources(为了 ad-hoc 代码签名)。StaticFiles 安全检查会拒接 "符号链接
# 指向 mount dir 外" 的文件 → 全部 404。
# 解法:直接把 GATEWAY_DIR 指 Resources(真文件所在),mount serve 就不踩坑。
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _meipass = Path(sys._MEIPASS)
    if sys.platform == "darwin" and _meipass.name == "Frameworks":
        _real_resources = _meipass.parent / "Resources"
        if _real_resources.is_dir():
            GATEWAY_DIR = _real_resources.resolve()
        else:
            GATEWAY_DIR = _meipass.resolve()
    else:
        GATEWAY_DIR = _meipass.resolve()
else:
    GATEWAY_DIR = Path(__file__).parent.resolve()
CODE_ROOT = GATEWAY_DIR.parent          # = ~/human-ai-dev/ (代码 root,放 skill/scripts/etc)

import vault_config
import vault_git
DATA_HOME = vault_config.resolve_vault_root()
VAULT_DIR = DATA_HOME / "vault"


# ── APP_STATE_DIR(OS-标准 Application Support / AppData / XDG)──
# 所有 app-owned 状态(thread-history / daily-task-meta / images / config 等)
# 放到 OS 标准的隐藏位置,跟 user-owned vault 解耦。用户在 vault 里整理文件
# 不会动到这些。同时:Application Support 默认隐藏(macOS Finder 不显示),
# 用户不会误删。Time Machine 自动备份覆盖。
def _default_app_state_dir() -> Path:
    """返当前 OS 的标准 app-state 目录。环境变量 $HUMAN_AI_STATE 覆盖。"""
    env = os.environ.get("HUMAN_AI_STATE")
    if env:
        return Path(env).expanduser()
    plat = sys.platform
    home = Path.home()
    if plat == "darwin":
        return home / "Library" / "Application Support" / "HumanAI"
    if plat.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "HumanAI"
        return home / "AppData" / "Roaming" / "HumanAI"
    # Linux / 其他:XDG
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "HumanAI"
    return home / ".local" / "share" / "HumanAI"

APP_STATE_DIR = _default_app_state_dir()
DATA_DIR = APP_STATE_DIR / "data"
CONFIG_DIR = APP_STATE_DIR / "config"

# PULSE LARGE refactor P2: 数据/IO/解析/校验 抽到 pulse_io.py。re-export 在此
# 让 server.X 命名空间仍持有这些符号(P0+ 测试 fixture 走 server.X patch + 现存
# server.py 代码大量直接引用)。pulse_io 自己 from server import VAULT_DIR/APP_STATE_DIR
# 都已在前面定义,partial import 安全。
from pulse_io import (  # noqa: E402,F401
    _USER_PULSE_PATH, _PROJECT_PULSE_PATH, _AGENT_CONTEXT_PATH,
    PULSE_DIR, PULSE_BUDGET_CHARS, PULSE_STALE_DAYS,
    _TS_RE, _FROZEN_RE, _PLACEHOLDER_RE, _SCHEMA_VERSION_RE,
    _extract_frozen, _count_placeholders,
    _get_schema_version, _ensure_schema_version_header,
    _pulse_validate, _parse_pulse_md,
    _SELF_EVOLVE_TARGETS,
)

# PULSE LARGE refactor P3: eval 子系统抽到 pulse_eval.py。re-export 11 函数 +
# EVAL_LOG_DIR + 2 prompt(P0+ 测试 + 现存 server.py 直接引用都靠这层)。
# pulse_eval 内部依赖 server.X(find_today_journal/build_system_prompt/...)走
# 函数体内 lazy import,避循环。
from pulse_eval import (  # noqa: E402,F401
    EVAL_LOG_DIR,
    _eval_load_recent_md, _eval_load_project_claude_md, _eval_load_pulse_all,
    _eval_scan_feature_signals, _classify_eval_err, _eval_load_past_boards,
    _eval_build_messages, _eval_build_feature_intro_messages,
    _eval_persist, _eval_notify, _eval_compress_past_logs,
    _EVAL_INJECTION, _FEATURE_INTRO_PROMPT, _FEATURE_INTRO_OPTIONS,
)

# PULSE LARGE refactor P4: _self_evolve_run + 2 prompt + EVOLVE_LOCKS 抽到
# pulse_evolve.py(silent corruption 红线集中地,40 P0+ 测试守)。
from pulse_evolve import (  # noqa: E402,F401
    _self_evolve_run, _get_evolve_lock,
    _EVOLVE_LOCKS, _EVOLVE_LOCKS_GUARD,
    _PULSE_UPDATE_PROMPT, _AGENT_CONTEXT_EVOLVE_PROMPT,
)

SKILL_DIR_LOCAL = CODE_ROOT / "skill"
WIDGETS_DIR = GATEWAY_DIR / "widgets"
# user-widgets.json 是 writable 状态(用户挑了哪些 widget 落在哪个 slot),
# 必须落 APP_STATE_DIR — 不然 PyInstaller frozen 下 _MEIPASS 只读,写不进去。
USER_WIDGETS_PATH = DATA_DIR / "user-widgets.json"
# 旧位置(开发模式下放在 gateway/ 旁边)兼容:首次启动若新位置无文件,从旧位置拷
_LEGACY_USER_WIDGETS = Path(__file__).parent / ".user-widgets.json"
if _LEGACY_USER_WIDGETS.exists() and not USER_WIDGETS_PATH.exists():
    try:
        # 模块加载期(line 121),_safe_write_text 还没定义,内联 tmp+replace
        USER_WIDGETS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _legacy_text = _LEGACY_USER_WIDGETS.read_text(encoding="utf-8")
        _tmp_widgets = USER_WIDGETS_PATH.with_suffix(USER_WIDGETS_PATH.suffix + ".tmp")
        _tmp_widgets.write_text(_legacy_text, encoding="utf-8")
        _tmp_widgets.replace(USER_WIDGETS_PATH)
    except Exception:
        pass
CONFIG_PATH = CONFIG_DIR / "gateway-config.json"
JOURNAL_DIR = VAULT_DIR / "半小时复盘"
# attachments + PULSE 镜像 是 app-owned(URL 服务 / 单向同步),搬出 vault → APP_STATE_DIR
# 防用户在 vault 里整理文件时误删 / 改名,断 md 链接 / 失去 PULSE 状态
ATTACHMENTS_DIR = APP_STATE_DIR / "attachments"
# 标签聚合.md 保持 vault 暴露(用户保留 Obsidian 反链体验)
TAG_AGGREGATE_PATH = VAULT_DIR / "标签聚合.md"
# 兼容(早期代码引用 PLATFORM_ROOT 当某个 root 用 — 跟新 image 路径一起用)
PLATFORM_ROOT = APP_STATE_DIR


# ── 一次性迁移:旧路径 → APP_STATE_DIR ──
# 包括:
#   ~/.human-ai/data + config   → APP_STATE_DIR/data + config(Phase 1)
#   vault/PULSE/                → APP_STATE_DIR/pulse-mirror/  (Phase 2)
#   vault/attachments/          → APP_STATE_DIR/attachments/   (Phase 2)
# COPY 不删 — 老位置留作 fallback。新位置有同名跳过。
def _migrate_old_state():
    moved = 0
    migrations = [
        (DATA_HOME / "data",   DATA_DIR),
        (DATA_HOME / "config", CONFIG_DIR),
        (VAULT_DIR / "PULSE",       PULSE_DIR),
        (VAULT_DIR / "attachments", ATTACHMENTS_DIR),
    ]
    for legacy, target in migrations:
        if not legacy.exists() or legacy.resolve() == target.resolve():
            continue
        target.mkdir(parents=True, exist_ok=True)
        for src in legacy.rglob("*"):
            if src.is_dir():
                continue
            rel = src.relative_to(legacy)
            dst = target / rel
            if dst.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                dst.write_bytes(src.read_bytes())
                moved += 1
            except Exception:
                pass
    return moved


# ── 安全写(原子 tmpfile+rename + 可选 5-rotate 备份)──
# A-H3: tmp 文件名固定 .tmp → 同 path 并发写者撞;模块级 path-keyed lock + uuid tmp 名
# A-M5: tmp fd fsync + parent dir fsync → 断电后 atomic rename 才真到盘
# A-H2/H12: _rotate_backup bak.1 走 tmp+replace;catch-all 改 silent-failure 上报
import threading as _threading_wg
_WRITE_GUARD_LOCKS: dict[str, "_threading_wg.Lock"] = {}
_WRITE_GUARD_LOCKS_GUARD = _threading_wg.Lock()


def _get_write_guard_lock(path_str: str) -> "_threading_wg.Lock":
    with _WRITE_GUARD_LOCKS_GUARD:
        lk = _WRITE_GUARD_LOCKS.get(path_str)
        if lk is None:
            lk = _threading_wg.Lock()
            _WRITE_GUARD_LOCKS[path_str] = lk
        return lk


def _fsync_parent(path: Path) -> None:
    """fsync 父目录:保证 atomic rename 在断电后真持久(POSIX 必需,Win 无效)。"""
    try:
        dfd = os.open(str(path.parent), os.O_DIRECTORY) if hasattr(os, "O_DIRECTORY") else None
        if dfd is not None:
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    except Exception:
        pass  # Win 没 O_DIRECTORY,或权限不够 — 跳过(rename 自身仍 atomic)


def _rotate_backup(path: Path, keep: int = 5):
    """把 path 旋转出去:bak.{N-1} → bak.N(老的先掉),原 path 内容写进 bak.1。
    用于写之前调一次,即使下次写出错或被错数据覆盖,bak.1..bak.5 还能 rollback。
    """
    if not path.exists():
        return
    try:
        # 老的最旧那份清掉
        oldest = Path(f"{path}.bak.{keep}")
        if oldest.exists():
            oldest.unlink()
        # bak.{N-1} → bak.N 从大到小依次推
        for i in range(keep, 1, -1):
            src = Path(f"{path}.bak.{i-1}")
            if src.exists():
                src.rename(Path(f"{path}.bak.{i}"))
        # 当前文件 → bak.1 走 atomic tmp+replace(A-H2)
        bak1 = Path(f"{path}.bak.1")
        bak1_tmp = Path(f"{path}.bak.1.{os.getpid()}.tmp")
        bak1_tmp.write_bytes(path.read_bytes())
        bak1_tmp.replace(bak1)
    except Exception as e:
        # A-H2: catch-all 改可观测;rotate 自身崩了应当报出来
        try:
            _report_silent_failure(
                "rotate_backup_failed",
                f"{type(e).__name__}: {str(e)[:120]}",
                context={"op": "rotate_backup"},
            )
        except Exception:
            pass


def _pretty_rel(p: Path) -> str:
    """Display-friendly 相对路径。Phase 1/2 后 vault 和 app-state 分属不同 root,
    单一 PLATFORM_ROOT 不够用。逐个尝试合理 base,落空返绝对 path。
    URL 构造也走它(APP_STATE_DIR 命中 → `data/...`,可直接接前缀 `/`)。
    """
    p = Path(p)
    for base in (APP_STATE_DIR, DATA_HOME, CODE_ROOT):
        try:
            return str(p.relative_to(base))
        except ValueError:
            continue
    return str(p)


def _safe_write_text(path: Path, content: str, rotate: bool = False, encoding: str = "utf-8"):
    """原子写文本。rotate=True 先把旧的旋转成 bak.1..bak.5 再写。
    用 tmpfile + rename 实现原子(POSIX:os.rename 是 atomic;Windows 用 os.replace)。
    A-H3:tmp 文件名 uuid + path-keyed lock 防同 path 并发写者撞 tmp。
    A-M5:tmp fd fsync + parent dir fsync 保证断电场景内容到盘。
    """
    import uuid as _uuid
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path_str = str(path)
    with _get_write_guard_lock(path_str):
        if rotate:
            _rotate_backup(path)
        tmp = Path(f"{path}.{os.getpid()}.{_uuid.uuid4().hex[:8]}.tmp")
        try:
            with tmp.open("w", encoding=encoding) as fh:
                fh.write(content)
                fh.flush()
                try:
                    os.fsync(fh.fileno())  # A-M5: 内容真落盘
                except Exception:
                    pass
            tmp.replace(path)
            _fsync_parent(path)  # A-M5: rename 的方向真持久
        finally:
            # 异常退出时残留 tmp 清掉
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass

ALLOWED_IMAGE_EXT = {"jpg", "jpeg", "png", "gif", "webp", "heic"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB

# ── env loader ───────────────────────────────────────────────────────
# 把 secret 从 gateway-config.json 抽出来,搬到 .env 文件 — config.json 只放
# 结构(models / base URLs / defaults),.env 放 key。两个 .env 候选位置:
#   1. APP_STATE_DIR/config/.env  — 用户机的 production(.app 安装后用)
#   2. <gateway dir>/.env         — dev 时
# 读优先级:os.environ > .env 文件 > gateway-config.json > 默认值

def _load_env_file(path: Path) -> dict:
    """简易 .env 解析:KEY=value 一行一条,#注释 / 空行跳过。引号包裹的去引号。"""
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
        log.warning(f".env load failed at {path}: {e}")
    return out


def _env_overlay() -> dict:
    """合并 env 来源 → 字典。优先级:os.environ > APP_STATE .env > gateway/.env"""
    merged = {}
    for p in (GATEWAY_DIR / ".env", CONFIG_DIR / ".env"):
        merged.update(_load_env_file(p))
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


# ── config ───────────────────────────────────────────────────────────
def _save_config(cfg: dict) -> None:
    """CONFIG_PATH 写盘统一入口:atomic + 5-rotate bak + chmod 0600。
    持有 API key,中途崩 = 用户秘钥不可恢复;明文权限松 = 拷 .app 漏 key。
    """
    content = json.dumps(cfg, ensure_ascii=False, indent=2)
    _safe_write_text(CONFIG_PATH, content, rotate=True)
    try:
        os.chmod(CONFIG_PATH, 0o600)
        for i in range(1, 6):
            bak = Path(f"{CONFIG_PATH}.bak.{i}")
            if bak.exists():
                os.chmod(bak, 0o600)
    except Exception:
        pass  # 非 POSIX 或 perm 错 — 最大努力


def load_config():
    """读 gateway-config.json,然后用 env 覆盖 secret 字段。
    返合并后的 dict。env 不存在的字段沿用 config.json。
    主文件损坏 → 尝试 bak.1 回滚;再不行返空 dict 让 setup wizard 接管。
    """
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            log.error(f"CONFIG_PATH 损坏 ({type(e).__name__}: {e}),尝试 bak.1 回滚")
            bak1 = Path(f"{CONFIG_PATH}.bak.1")
            if bak1.exists():
                try:
                    cfg = json.loads(bak1.read_text(encoding="utf-8"))
                    log.warning(f"CONFIG_PATH 已从 bak.1 回滚")
                    try:
                        _report_silent_failure(
                            "config_restored_from_bak1",
                            f"主 config 损坏,bak.1 回滚成功",
                            context={"err": str(e)[:120]},
                        )
                    except Exception:
                        pass
                except Exception as e2:
                    log.error(f"CONFIG_PATH bak.1 也无法解析: {e2}")
                    try:
                        _report_silent_failure(
                            "config_corrupt_no_recovery",
                            f"主+bak.1 双损,fallback 空 dict",
                            context={"err": str(e)[:120], "bak_err": str(e2)[:120]},
                        )
                    except Exception:
                        pass
            else:
                try:
                    _report_silent_failure(
                        "config_corrupt_no_bak",
                        f"主 config 损坏且无 bak.1",
                        context={"err": str(e)[:120]},
                    )
                except Exception:
                    pass
    env = _env_overlay()
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

def list_profiles_full():
    cfg = load_config() or {}
    profiles = list(cfg.get("models") or [])
    if not profiles and cfg.get("api_key"):
        profiles = [_profile_from_top_level(cfg)]
    return profiles

def list_model_profiles():
    """前端 picker 用,去掉 api_key。"""
    return [{k: v for k, v in p.items() if k != "api_key"} for p in list_profiles_full()]


# ── silent failure 反馈通道 (P1:本地落 jsonl,P3 加 cloud sender) ─────
# 用途:在任何"返 error 但 silently swallow 不告诉 user"的代码路径调用
# `_report_silent_failure(error_type, message, context)`。本地 jsonl ring
# buffer 保留最近 _SILENT_FAILURES_RING_MAX 条,/api/silent-failures/recent
# 返查。client_id 持久化(~/.human-ai/data/client-id.txt),匿名 UUID,跟用户
# 身份无关 — 没邮箱 / IP / 系统识别,只为同设备纵向去重(同 client 多天反复
# 触发 X 类 failure → 优先修)。
# 永远不在 hook 里上报 vault 内容 / API key / 用户文件名。
APP_VERSION = "0.1.39"  # 跟 tauri.conf.json sync;bump 时两处一起改

SILENT_FAILURES_LOG = DATA_DIR / "silent-failures.jsonl"
CLIENT_ID_PATH = DATA_DIR / "client-id.txt"
_SILENT_FAILURES_RING_MAX = 5000
_CLIENT_ID_CACHE = None


def _load_or_create_client_id() -> str:
    """读持久化 client_id,不存在则 UUID4 生成 + 写入。
    匿名 ID:跨 .app 启动稳定,但跟用户身份无关。
    """
    try:
        if CLIENT_ID_PATH.exists():
            cid = CLIENT_ID_PATH.read_text(encoding="utf-8").strip()
            uuid.UUID(cid)  # 验格式
            return cid
    except Exception:
        pass
    new_id = str(uuid.uuid4())
    try:
        # A-M2: PULSE "client_id 文件不能动" 硬合同 — atomic + rotate=True 兜底
        _safe_write_text(CLIENT_ID_PATH, new_id, rotate=True)
    except Exception as e:
        log.warning(f"client_id 持久化失败,本次启动用内存版: {e}")
    return new_id


def get_client_id() -> str:
    global _CLIENT_ID_CACHE
    if _CLIENT_ID_CACHE is None:
        _CLIENT_ID_CACHE = _load_or_create_client_id()
    return _CLIENT_ID_CACHE


def _telemetry_consent() -> dict:
    """返当前 cloud_telemetry 同意状态。
    无 config / 无字段 → 视为未同意(默认全关,直到 consent modal 写入)。
    """
    cfg = load_config() or {}
    ct = cfg.get("cloud_telemetry") or {}
    return {
        "failures": bool(ct.get("failures", False)),
        "heartbeat": bool(ct.get("heartbeat", False)),
        "consented_at": ct.get("consented_at"),  # ISO string or None
    }


def _telemetry_save(failures: bool, heartbeat: bool):
    """写 consent 状态,记录 consented_at 戳子。"""
    cfg = load_config() or {}
    cfg["cloud_telemetry"] = {
        "failures": bool(failures),
        "heartbeat": bool(heartbeat),
        "consented_at": datetime.now().isoformat(),
    }
    _save_config(cfg)


# consent.js 明文承诺只收"错误码、调用元数据(模型标识、文件尺寸、网络层标记)"。
# 任何 caller 误塞用户原文(task name / curator query / patch preview / LLM eval 输出)
# 必须在入口被 drop,避免逐处审。 _dropped_keys 留作 drift 信号。
_SF_CONTEXT_ALLOWLIST = frozenset({
    "model", "model_id", "fallback_to", "fallback_from",
    "network_marker", "status_code", "http_status",
    "file_size_kb", "text_len", "cleaned_len", "lines",
    "attempt", "retry_count", "dropped_count",
    "err", "bak_err", "err_class",
    "op", "phase",
    # #2 折叠:同一指纹时间窗内重复次数(coalesced 汇总条带)
    "occurrences", "coalesced", "window_sec",
})
_SF_CONTEXT_VALUE_MAX_LEN = 120

# #1 隐私:home 路径含 OS 登录名(/Users/<name>/、/home/<name>/、C:\Users\<name>\)。
# message 是 raw git stderr / 异常串,不走 context 白名单,会把用户名带上服务器。
# 上送前统一塌成 ~。context 的字符串值(err/bak_err 等)同样过一道。
_PII_UNIX_PATH_RE = re.compile(r'/(?:Users|home)/[^/\s\'"]+')
_PII_WIN_PATH_RE = re.compile(r'[A-Za-z]:\\Users\\[^\\\s\'"]+', re.IGNORECASE)


def _scrub_pii(text):
    """把 home 目录路径(含用户名)塌成 ~。非字符串原样返回。"""
    if not text or not isinstance(text, str):
        return text
    text = _PII_UNIX_PATH_RE.sub('~', text)
    text = _PII_WIN_PATH_RE.sub('~', text)
    return text


def _sanitize_sf_context(ctx) -> dict:
    """白名单过滤 + 标量类型限制 + 字符串截断 + home 路径脱敏。
    dict/list/object 一律 drop(可能嵌套用户内容)。"""
    if not ctx or not isinstance(ctx, dict):
        return {}
    out = {}
    dropped = []
    for k, v in ctx.items():
        if not isinstance(k, str) or k not in _SF_CONTEXT_ALLOWLIST:
            dropped.append(str(k)[:40])
            continue
        if isinstance(v, bool) or isinstance(v, (int, float)) or v is None:
            out[k] = v
        elif isinstance(v, (str, bytes)):
            s = v.decode("utf-8", errors="replace") if isinstance(v, bytes) else v
            out[k] = _scrub_pii(s[:_SF_CONTEXT_VALUE_MAX_LEN])
        else:
            dropped.append(k)
    if dropped:
        out["_dropped_keys"] = ",".join(sorted(set(dropped)))[:_SF_CONTEXT_VALUE_MAX_LEN]
    return out


# A-H6+H11: silent-failures.jsonl 3 写者(append / trim / cursor)+ sender drain
# 同进程互不撞;append+trim 用同一个 lock,cursor 独立 lock(cursor 是 byte-size 不会撞 line)。
_SF_FILE_LOCK = threading.Lock()

# #2 折叠:同指纹失败在时间窗内"首条立即落盘(保即时信号)+ 窗内其余只内存累加",
# 窗口过期(下一条触发 rollover 或 sender tick)落一条 coalesced 汇总
# (occurrences = 被折叠掉的额外次数,首条已单独落)。把"1 个 bug 刷 26 行"
# 压成"1 即时 + 1 汇总"。回归 feedback-sink 26 条 index.lock 噪音。
_SF_DEDUP_WINDOW_SEC = 300
_SF_DEDUP_MAX = 500  # dedup 表上限,无 sink 时兜底防无界增长
_sf_dedup_lock = threading.Lock()
_sf_dedup: dict = {}  # fp -> {first, last, count, error_type, message, context}
_SF_FP_NUM_RE = re.compile(r'\d+')


def _sf_fingerprint(error_type: str, message: str) -> str:
    """error_type + 归一化 message(数字塌成 #,取前 80 字)。
    同根因不同实例(行号/时间/字节数变化)归同一指纹。"""
    norm = _SF_FP_NUM_RE.sub('#', message or '')
    return f"{error_type}|{norm[:80]}"


def _sf_make_entry(error_type, message, context, occurrences=1, coalesced=False):
    ctx = dict(context or {})
    if coalesced or occurrences > 1:
        ctx["occurrences"] = occurrences
        ctx["coalesced"] = coalesced
        ctx["window_sec"] = _SF_DEDUP_WINDOW_SEC
    return {
        "ts": datetime.now().isoformat(),
        "client_id": get_client_id(),
        "error_type": error_type,
        "message": message,
        "context": ctx,
        "app_version": APP_VERSION,
        "platform": f"{sys.platform}-{_platform.machine()}",
    }


def _sf_write_entry(entry: dict):
    """锁内 append + flush + fsync 单条。A-H6+H11 写盘契约。"""
    SILENT_FAILURES_LOG.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _SF_FILE_LOCK:
        with SILENT_FAILURES_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            try:
                os.fsync(f.fileno())  # 反馈通道本身崩了最不该悄无声息
            except Exception:
                pass
    # 偶尔 trim(每 100 条采样一次,均摊 IO)
    if random.random() < 0.01:
        _trim_silent_failures()


def _sf_flush_dedup(force: bool = False):
    """sender tick 调:窗口静默过期(或 force)且 count>1 → 落 coalesced 汇总。
    burst 停止后由这条兜底(rollover 路径只在下一条同指纹到达时触发)。"""
    now = time.time()
    to_emit = []
    with _sf_dedup_lock:
        for fp, rec in list(_sf_dedup.items()):
            if force or (now - rec["last"] >= _SF_DEDUP_WINDOW_SEC):
                if rec["count"] > 1:
                    to_emit.append((rec["error_type"], rec["message"],
                                    rec["context"], rec["count"] - 1))
                del _sf_dedup[fp]
    for et, msg, ctx, extra in to_emit:
        try:
            _sf_write_entry(_sf_make_entry(et, msg, ctx, occurrences=extra, coalesced=True))
        except Exception:
            pass


def _report_silent_failure(error_type: str, message: str = "", context: dict = None):
    """记一条 silent failure 进本地 ring buffer。fire-and-forget,自身永不 raise。

    error_type: 枚举 snake_case,server 侧分类用
                例: vision_classify_auth / cutout_all_failed / web_search_degraded
    message:    最长 200 字截断,不放用户内容;入口走 _scrub_pii 塌 home 路径(#1)
    context:    可选 dict,入口走 _sanitize_sf_context 白名单过滤,
                consent.js 承诺范围外的 key 直接 drop(记 _dropped_keys 作 drift 信号)

    折叠(#2): 同指纹窗内首条立即落,其余内存累加,过期落 coalesced 汇总。

    consent: 用户未同意"错误上报"时**连本地 jsonl 都不写**(C-#4 收口)。
    现在:撤回期间通道完全静音,本地不增长,云端不回灌。
    """
    try:
        # consent gate(C-#4):撤回期间连本地都不写。
        # try/except 兜:_telemetry_consent → load_config → 损坏路径理论上会回拨
        # _report_silent_failure;若 config + bak.1 双损则递归。挂了直接静音。
        try:
            if not _telemetry_consent().get("failures", False):
                return
        except Exception:
            return
        # #1 隐私:message 是 raw stderr,塌 home 路径去用户名;context 在 sanitize 内塌
        msg = _scrub_pii((message or "")[:200])
        sanitized = _sanitize_sf_context(context)
        # #2 折叠:同指纹窗内只首条落盘,其余累加
        fp = _sf_fingerprint(error_type, msg)
        now = time.time()
        flush = None
        emit_first = True
        with _sf_dedup_lock:
            rec = _sf_dedup.get(fp)
            if rec and (now - rec["first"] < _SF_DEDUP_WINDOW_SEC):
                rec["count"] += 1
                rec["last"] = now
                emit_first = False
            else:
                # 新窗口:旧窗口若累加过 extra,rollover 落汇总
                if rec and rec["count"] > 1:
                    flush = (rec["error_type"], rec["message"],
                             rec["context"], rec["count"] - 1)
                _sf_dedup[fp] = {"first": now, "last": now, "count": 1,
                                 "error_type": error_type, "message": msg,
                                 "context": sanitized}
                # 兜底:无 sink 配置时 sender flush 不跑,dedup 不会被清。
                # 超上限淘汰最旧(按 last)条目,防长 session 无界增长。
                if len(_sf_dedup) > _SF_DEDUP_MAX:
                    oldest = min(_sf_dedup, key=lambda k: _sf_dedup[k]["last"])
                    _sf_dedup.pop(oldest, None)
        # 落盘在 dedup lock 外(避免与 _SF_FILE_LOCK 嵌套)
        if flush:
            et, m, c, extra = flush
            _sf_write_entry(_sf_make_entry(et, m, c, occurrences=extra, coalesced=True))
        if emit_first:
            _sf_write_entry(_sf_make_entry(error_type, msg, sanitized))
    except Exception as e:
        # 反馈通道自己挂了不能反复上报(避免递归),只 warn
        try:
            log.warning(f"silent_failure 记录失败: {e}")
        except Exception:
            pass


def _trim_silent_failures():
    """保留最近 _SILENT_FAILURES_RING_MAX 条。
    A-H6+H11: lock + atomic write;trim 时通过 cursor 调整(drop_count)避免漏发。
    """
    try:
        with _SF_FILE_LOCK:
            if not SILENT_FAILURES_LOG.exists():
                return
            lines = SILENT_FAILURES_LOG.read_text(encoding="utf-8").splitlines()
            if len(lines) <= _SILENT_FAILURES_RING_MAX:
                return
            drop_count = len(lines) - _SILENT_FAILURES_RING_MAX
            kept = lines[-_SILENT_FAILURES_RING_MAX:]
            _safe_write_text(SILENT_FAILURES_LOG, "\n".join(kept) + "\n", rotate=False)
            # 同步调整 cursor 避免漏发(drain 是按行号续上的,trim 后行号往左挪)
            try:
                old_cursor = _sf_cursor_read()
                new_cursor = max(0, old_cursor - drop_count)
                _sf_cursor_write(new_cursor)
            except Exception:
                pass
    except Exception as e:
        try:
            log.warning(f"silent_failures trim 失败: {e}")
        except Exception:
            pass


# ── P3: silent-failure 上送 cloud sink (feedback-sink 接收端) ────
# 上送 cursor 记录"上送到哪一行了",下次启动从这里 +1 续上。
# 失败重试 N 次后丢弃(不阻塞主流程),本地 jsonl 永远兜底,出问题事后能回灌。
_SF_CURSOR_PATH = DATA_DIR / "silent-failures.cursor"
_SF_SENDER_THREAD = None
_SF_SENDER_STOP = threading.Event()
SF_SENDER_INTERVAL = 60       # 秒,每分钟扫一次
SF_SENDER_BATCH_MAX = 50      # 每批最多多少条(跟 server 端 BatchIn.max_length 对齐)
SF_SENDER_HTTP_TIMEOUT = 10   # 秒


def _sf_cursor_read() -> int:
    try:
        return int(_SF_CURSOR_PATH.read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def _sf_cursor_write(line_no: int):
    try:
        # A-M3: atomic;cursor 损坏 → 整 ring buffer 重发(空 cursor = 从 0 开始)
        _safe_write_text(_SF_CURSOR_PATH, str(line_no), rotate=False)
    except Exception:
        pass  # cursor 丢失最坏后果:下次重发已发条目(server 不去重也无伤大雅)


# Prod default — 跟自更新通道同思路(yanpai box 长期不下线作 hardcoded fallback)。
# 6.17 发现 .env 没打进 PyInstaller bundle,真用户 sidecar 启动一直拿不到 URL
# → events 卡本地从未上送(5.29 通道上线起整个 prod 反馈通道哑了三周半)。
# dev 用 .env override 切 staging/mock;prod 用户直接拿到默认值开始上报。
DEFAULT_FEEDBACK_SINK_URL = "http://101.42.108.30:18080"


def _sf_sender_loop():
    """后台 thread:每 SF_SENDER_INTERVAL 秒读 jsonl 未发条目 → batch POST。
    server 端 URL 来自 env FEEDBACK_SINK_URL,默认走 DEFAULT_FEEDBACK_SINK_URL。
    """
    # 走 _env_overlay() — 这样 .env 文件里的 FEEDBACK_SINK_URL 也能读到
    # (os.environ.get 直读只能拿 process env,装机后 .app 没显式 export 就拿不到)
    env_url = (_env_overlay().get("FEEDBACK_SINK_URL", "")
               or os.environ.get("FEEDBACK_SINK_URL", "")).strip().rstrip("/")
    url_base = env_url or DEFAULT_FEEDBACK_SINK_URL
    log.info(f"[sf-sender] started, target={url_base}{' (env override)' if env_url else ' (prod default)'}, interval={SF_SENDER_INTERVAL}s")
    while not _SF_SENDER_STOP.wait(SF_SENDER_INTERVAL):
        try:
            # #2 折叠:先 flush 静默过期窗口的 coalesced 汇总进 jsonl,再 drain 上送
            _sf_flush_dedup()
            # consent gate — 用户没同意"错误上报"则 drain 跳过(本地 jsonl 兜底仍在,
            # toggle 打开后历史失败可回灌)
            if not _telemetry_consent().get("failures"):
                continue
            _sf_drain_once(url_base)
        except Exception as e:
            log.warning(f"[sf-sender] drain failed: {type(e).__name__}: {e}")


# ── 日活心跳 sender (0.1.3 加) ──────────────────────────────────────
_HB_SENDER_THREAD = None
_HB_SENDER_STOP = threading.Event()
_HB_LAST_SENT_PATH = DATA_DIR / "heartbeat.last"
# 即刻反馈:启动 15s 就首发(原 30min 太久,内测 tester 探几分钟就关 → 一次心跳都不发 → DAU 永远 0)。
# 每天去重(_hb_last_sent_day)保证不刷屏,所以"避开开机 spike"不再靠延迟,靠去重。
HB_STARTUP_DELAY = 15        # 启动后 15s 首发
HB_RETRY_INTERVAL = 120      # 没发成(consent 没开 / 网络抖 / 晚勾同意)→ 2min 后重试,抓短会话
HB_IDLE_INTERVAL = 3600      # 当天已发 → 1h 醒一次看是否跨天
HB_HTTP_TIMEOUT = 10


def _hb_last_sent_day() -> str:
    try:
        return _HB_LAST_SENT_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _hb_mark_sent(day: str):
    try:
        # A-M3: atomic;heartbeat 戳子损坏 → 当日 DAU 多算一次,小代价
        _safe_write_text(_HB_LAST_SENT_PATH, day, rotate=False)
    except Exception:
        pass


def _hb_sender_loop():
    """日活心跳 — 每天一次。同 silent-failure sender 一样 fire-and-forget。
    consent 关闭则只 sleep 不发;开启时 day 已发过也跳过。
    """
    # 同 sf-sender:env override > prod default;原"未配就 return"导致 prod 心跳全程沉默
    # (5.29 起 unique_clients 永远 0,你看不到"装机但没出错"的活体内测用户)
    env_url = (_env_overlay().get("FEEDBACK_SINK_URL", "")
               or os.environ.get("FEEDBACK_SINK_URL", "")).strip().rstrip("/")
    url_base = env_url or DEFAULT_FEEDBACK_SINK_URL
    # 启动延迟,避开开机 spike(用户重启 app / 重启电脑都不应立刻 ping)
    if _HB_SENDER_STOP.wait(HB_STARTUP_DELAY):
        return
    log.info(f"[hb-sender] started, target={url_base}{' (env override)' if env_url else ' (prod default)'}, daily")
    while True:
        sent_today = False
        try:
            if not _telemetry_consent().get("heartbeat"):
                pass  # consent 关,本周期不发(下个 retry 周期再看,用户可能晚点才勾)
            else:
                today = datetime.utcnow().strftime("%Y-%m-%d")
                if _hb_last_sent_day() == today:
                    sent_today = True  # 今天发过了,转 idle 间隔
                else:
                    tz_off = int(-time.timezone / 60)  # local UTC offset(分钟)
                    payload = {
                        "client_id": get_client_id(),
                        "version": APP_VERSION,
                        "platform": f"{sys.platform}-{_platform.machine()}",
                        "tz_offset_min": tz_off,
                    }
                    r = requests.post(f"{url_base}/heartbeat", json=payload,
                                      timeout=HB_HTTP_TIMEOUT)
                    if r.status_code == 200:
                        _hb_mark_sent(today)
                        sent_today = True
                    elif r.status_code != 429:
                        log.warning(f"[hb-sender] HTTP {r.status_code}: {r.text[:120]}")
        except Exception as e:
            log.warning(f"[hb-sender] tick failed: {type(e).__name__}: {e}")
        # 没发成(consent 没开 / 网络 / 晚勾同意)→ 2min 后重试,抓住短会话;发成了 → 1h 看跨天
        if _HB_SENDER_STOP.wait(HB_IDLE_INTERVAL if sent_today else HB_RETRY_INTERVAL):
            break


def _sf_drain_once(url_base: str):
    """读 jsonl 从 cursor 开始的未发条目,POST 上去,成功后推进 cursor。"""
    if not SILENT_FAILURES_LOG.exists():
        return
    cursor = _sf_cursor_read()
    try:
        lines = SILENT_FAILURES_LOG.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    if cursor >= len(lines):
        return  # 都发过了
    pending = lines[cursor:cursor + SF_SENDER_BATCH_MAX]
    if not pending:
        return
    # 解析 jsonl → events
    events = []
    for line in pending:
        try:
            obj = json.loads(line)
            # cursor advance 不依赖单条 parse 成功,坏行也算"处理过了"
            events.append(obj)
        except Exception:
            continue
    if not events:
        # 全坏行,推进 cursor 防卡死
        _sf_cursor_write(cursor + len(pending))
        return
    try:
        r = requests.post(
            f"{url_base}/silent-failure/batch",
            json={"events": events},
            timeout=SF_SENDER_HTTP_TIMEOUT,
        )
        if r.status_code == 200:
            _sf_cursor_write(cursor + len(pending))
            _sf_sink_4xx_reset()  # 成功 = 通道恢复
        elif r.status_code == 429:
            # rate limited — 下次再试,不推进 cursor
            log.info("[sf-sender] rate-limited, will retry next interval")
        elif r.status_code in (401, 403, 404):
            # B-#4: 鉴权 / endpoint 路径错 — 不推进 cursor 防把所有 pending 倒进 /dev/null
            # 累计 streak,阈值后 push notification 让用户能看到反馈通道挂了
            log.warning(f"[sf-sender] HTTP {r.status_code}: {r.text[:120]}")
            streak = _sf_sink_4xx_bump()
            if streak >= _SF_SINK_4XX_THRESHOLD:
                _maybe_push_sink_broken(r.status_code, r.text[:120])
        elif 400 <= r.status_code < 500:
            # B-#4: 400/422 schema/payload 错 — 单条不可上送,advance 1 条防整批卡死
            # 不是整批 advance(那样把后面的 OK 条目也吞了)
            log.warning(f"[sf-sender] HTTP {r.status_code} (schema?): {r.text[:120]}")
            _sf_cursor_write(cursor + 1)
        else:
            log.warning(f"[sf-sender] HTTP {r.status_code}: {r.text[:120]}")
            # 5xx 不推进等下次
    except Exception as e:
        log.warning(f"[sf-sender] POST failed: {type(e).__name__}: {e}")
        # 网络 / DNS / 超时 — 不推进 cursor,下次再试


# B-#4: sink 4xx streak 跟踪。401/403/404 连续 ≥ 阈值 → push notification 让用户看到
# 反馈通道挂了。文件持久化避免 sidecar 重启 streak 归零。
_SF_SINK_4XX_PATH = DATA_DIR / "silent-failures-sink-4xx-streak"
_SF_SINK_4XX_THRESHOLD = 3
_SF_SINK_BROKEN_NOTIFIED_PATH = DATA_DIR / "silent-failures-sink-broken-notified"


def _sf_sink_4xx_bump() -> int:
    try:
        prev = 0
        if _SF_SINK_4XX_PATH.exists():
            try:
                prev = int(_SF_SINK_4XX_PATH.read_text(encoding="utf-8").strip())
            except Exception:
                prev = 0
        new = prev + 1
        _safe_write_text(_SF_SINK_4XX_PATH, str(new), rotate=False)
        return new
    except Exception:
        return 0


def _sf_sink_4xx_reset() -> None:
    try:
        if _SF_SINK_4XX_PATH.exists():
            _SF_SINK_4XX_PATH.unlink()
        if _SF_SINK_BROKEN_NOTIFIED_PATH.exists():
            _SF_SINK_BROKEN_NOTIFIED_PATH.unlink()
    except Exception:
        pass


def _maybe_push_sink_broken(status_code: int, body_snippet: str) -> None:
    """到阈值后只弹一次,直到通道恢复才再弹下一波(避免每 60s 一条骚扰)。"""
    if _SF_SINK_BROKEN_NOTIFIED_PATH.exists():
        return
    try:
        _push_notification(
            "sink-broken",
            f"反馈通道挂了(HTTP {status_code}) — 内测期诊断数据上送暂停。"
            f"检查 FEEDBACK_SINK_URL 配置或 deploy key。",
            {"status_code": status_code, "body_snippet": body_snippet[:200]},
        )
        _safe_write_text(_SF_SINK_BROKEN_NOTIFIED_PATH, str(int(time.time())), rotate=False)
    except Exception:
        pass

def get_profile(model_id=None):
    profiles = list_profiles_full()
    if not profiles:
        return None
    if model_id:
        for p in profiles:
            if p.get("id") == model_id:
                return p
    cfg = load_config() or {}
    default_id = cfg.get("default_model_id")
    if default_id:
        for p in profiles:
            if p.get("id") == default_id:
                return p
    return profiles[0]

def get_client(profile=None):
    p = profile or get_profile()
    if not p or not p.get("api_key") or p["api_key"].startswith("YOUR_"):
        return None
    if OpenAI is None:
        return None
    return OpenAI(
        api_key=p["api_key"],
        base_url=p.get("base_url", "https://api.deepseek.com/v1"),
        timeout=120.0,     # 单次 HTTP 最多 120s。DeepSeek V4 Pro thinking 阶段不出 token,
                          # 长 context synthesis 实测 30-60s,30/60s 太紧会切死。
                          # 防 worker hang 死(过去靠 SIGKILL 救场)+ 给 reasoning 余地。
        max_retries=1,    # tool loop 已有重试,这里只兜一次
    )

def get_model(profile=None):
    p = profile or get_profile()
    return p.get("model", "deepseek-chat") if p else "deepseek-chat"

def get_vision_model():
    p = get_profile()
    if not p:
        return "deepseek-chat"
    return p.get("vision_model") or p.get("model", "deepseek-chat")

PROTOCOLS_DIR = GATEWAY_DIR / "protocols"

# protocol 文件名 → 索引描述,baseline preamble 给 AI 看的目录
PROTOCOLS = {
    "schedule": "编辑日记格式 / 时间块 / 标签 / commit 双签 / 1-year test 等规则",
    # 未来再加:"vision", "widgets", "forensics" — 当前 vision 是 per-msg 注入,widgets 走 _wants_widget_skill
}


def _wants_widget_skill(context: dict) -> bool:
    """是否需要装载 widget skill。default 不装(省 ~6.7K tokens)。
    触发条件:context 明示 widget-edit 类型 OR 引用了 widget DOM 元素。
    """
    if not context:
        return False
    if context.get("type") in ("widget-edit", "widget"):
        return True
    for r in context.get("refs") or []:
        if r.get("kind") in ("widget", "widget-element"):
            return True
    return False


def load_protocol(name: str, model_id: str = None) -> str:
    """读 protocols/{name}.md 并返内容。{model_id} 占位符会被替换为传入的 model_id。
    AI 通过 load_protocol tool 触发;build_system_prompt 也可以预 load 某 protocol。
    """
    if name not in PROTOCOLS:
        return f"(unknown protocol: {name}. available: {', '.join(PROTOCOLS.keys())})"
    f = PROTOCOLS_DIR / f"{name}.md"
    if not f.exists():
        return f"(protocol file missing: {f})"
    text = f.read_text(encoding="utf-8")
    if model_id:
        text = text.replace("{model_id}", model_id)
    return text


# ── system prompt builder ────────────────────────────────────────────
# 三份自演化 md 注入 system prompt:USER_PULSE / 项目 PULSE / AGENT_CONTEXT
# compact 完成后 LLM 重写文件,mtime 变 → cache 失效 → 下次 chat 自动读最新
# memory dir + USER_PULSE 路径走 env(陌生用户没 → 默认 None,不 inject)
import os as _os
# _USER_PULSE_PATH / _PROJECT_PULSE_PATH / _AGENT_CONTEXT_PATH 已搬到 pulse_io.py
# (P2,顶部 re-export 进 server 命名空间)
# workflow #8 PII 防护:_MEMORY_DIR 默认 None,绝不再硬编开发者绝对路径。
# 我自己机器走 env GATEWAY_MEMORY_DIR 指向私人 memory dir;陌生用户 / VM 镜像 / username
# 撞名一律读不到 — 防 PII 灌进陌生用户 system prompt。
_GATEWAY_MEMORY_DIR_ENV = _os.environ.get("GATEWAY_MEMORY_DIR", "").strip()
_MEMORY_DIR = Path(_GATEWAY_MEMORY_DIR_ENV) if _GATEWAY_MEMORY_DIR_ENV else None
_USER_CTX_CACHE: dict = {"sig": None, "content": ""}

def _load_user_context() -> str:
    """合并 vault/AGENT_CONTEXT + 项目 PULSE + USER_PULSE + memory/*.md(排除索引)。
    任何文件改了 mtime 变 → cache 失效 → 下次 chat 自动重读。
    陌生用户场景:USER_PULSE/memory env 没设默认 None,只读 vault 旁 AGENT_CONTEXT + 项目 PULSE(若有)。
    """
    files = []
    if _AGENT_CONTEXT_PATH.exists():
        files.append(_AGENT_CONTEXT_PATH)
    if _PROJECT_PULSE_PATH.exists():
        files.append(_PROJECT_PULSE_PATH)
    if _USER_PULSE_PATH.exists():
        files.append(_USER_PULSE_PATH)
    if _MEMORY_DIR is not None and _MEMORY_DIR.exists():
        files.extend(sorted(p for p in _MEMORY_DIR.glob("*.md") if p.name != "MEMORY.md"))
    sig = tuple((str(p), p.stat().st_mtime) for p in files)
    if _USER_CTX_CACHE["sig"] == sig:
        return _USER_CTX_CACHE["content"]
    parts = []
    if _AGENT_CONTEXT_PATH.exists():
        try:
            ac_text = _AGENT_CONTEXT_PATH.read_text(encoding='utf-8')
            # workflow #4 闭合:placeholder 字段是空槽,严禁 LLM 从对话反推填进
            # 提示词层加硬约束。frozen 段是协议手册,user-region 是用户区。
            parts.append(
                "\n\n=== AGENT_CONTEXT(vault 协作约定 + 用户角色)===\n"
                "**注意**:文件里 `<!-- placeholder: XXX -->` 注释下方的空字段(冒号后空白)"
                "是用户**未填**的槽。严禁从对话反推内容填进去,也不要假设这条已知。"
                "用户主动告诉你他的角色 / 关心点 时才用,否则一律视为未知。\n\n"
                + ac_text
            )
        except Exception:
            pass
    if _PROJECT_PULSE_PATH.exists():
        try:
            parts.append(f"\n\n=== 项目 PULSE(项目当下状态)===\n{_PROJECT_PULSE_PATH.read_text(encoding='utf-8')}")
        except Exception:
            pass
    if _USER_PULSE_PATH.exists():
        try:
            parts.append(f"\n\n=== USER_PULSE(用户当下快照)===\n{_USER_PULSE_PATH.read_text(encoding='utf-8')}")
        except Exception:
            pass
    mem_parts = []
    for p in files:
        if p in (_AGENT_CONTEXT_PATH, _PROJECT_PULSE_PATH, _USER_PULSE_PATH):
            continue
        try:
            mem_parts.append(f"--- {p.stem} ---\n{p.read_text(encoding='utf-8')}")
        except Exception:
            pass
    if mem_parts:
        parts.append("\n\n=== 协作 memory(具体规则 / 用户事实 / 项目决策)===\n" + "\n\n".join(mem_parts))
    content = "".join(parts)
    _USER_CTX_CACHE["sig"] = sig
    _USER_CTX_CACHE["content"] = content
    return content


def build_system_prompt(context: dict = None, model_id: str = None) -> str:
    """构造 system prompt。Lean baseline + protocol 索引;具体协议 AI 用
    load_protocol tool 按需拉。model_id 用于替换 prompt 模板里的 {model_id}。
    """
    parts = [
        "你是这个 vault 的 AI 协作者。vault 是「半小时复盘」日记 — markdown 文件,"
        "Obsidian / gateway 双端 render,不是聊天框。该用 markdown / wiki-link 语法就用。\n"
        "\n"
        "**tool 是为了记录,不是为了存在感** — 你有很多 tool 可以调,但那些都不重要,"
        "工具只是把对话里值得记的部分落进日记,不要为了记录而记录。\n"
        "\n"
        "默认行为(协议层):\n"
        "· **不写默认** — 用户没明说「记一下 / 写进去 / append」→ 不调 patch_journal_block / insert_journal_block。\n"
        "· **不贴默认** — 用户没传图 → 不调 place_scrapbook_image。\n"
        "· 觉得「这条值得记」→ 一句话问「要记进 X 块吗?」,别先写后通知。\n"
        "· 做完事 reply 别复述写了啥,一句话点过 + 接着聊。\n"
        "· **web_search 最多调 2 次** — 死循环 narrow 是最大坑。\n"
        "\n"
        "vault 协议手册(tag / #协作 / #commit / 聚合页用法)在 vault 的 AGENT_CONTEXT.md,"
        "需要写 entry 时先看。"
    ]

    # user 视图 inject(USER_PULSE + 全部 memory)— 放在身份段后、protocol 目录前
    user_ctx = _load_user_context()
    if user_ctx:
        parts.append(user_ctx)

    # protocol 目录 — AI 知道有这些协议可 load
    protocol_index = "\n\n=== 可用 protocols(用 load_protocol(name=...) 按需拉详细规则)===\n"
    for name, desc in PROTOCOLS.items():
        protocol_index += f"· {name}: {desc}\n"
    protocol_index += (
        "\n何时调 load_protocol:\n"
        "· 要 patch_journal_block / insert_journal_block / 写 #commit 之前 → 先 load 'schedule'\n"
        "· 普通聊天 / 拖图回复 / 简单 read_today_schedule → 不必 load\n"
        "· vision 工作流 hint 在用户消息里 server 已注入,不必单独 load\n"
    )
    parts.append(protocol_index)

    # tool group 目录 — 默认 bootstrap(read+meta),write 类按需 load
    tool_catalog = (
        "\n=== 工具按需加载 ===\n"
        "默认能用(read + 搜):read_today_schedule / list_recent_days / "
        "list_my_uploads / search_my_uploads / ask_photo_curator / web_search / vision_classify / "
        "load_protocol / load_tool_group\n"
        "  · **找照片硬规则**:用户要'回顾/找/汇总/带上 X 的照片' → 先 ask_photo_curator(单 call 返完整集),**别凭记忆/凭训练数据 cite filename**。\n"
        "    精确 OCR 关键词(发票号/截图文字)才走 search_my_uploads。跨称呼(狗=哈士奇=茅茅) / 模糊语义 / 长期回顾都走 curator。\n"
        "    cite filename 前必须经过 list_my_uploads 或 ask_photo_curator 返回 — 没出现在结果里就不存在,不能脑补。\n"
        "  · **找照片回复硬规则**:拿到 items 后每条都要 `![描述](url)` inline 贴出来,文字叙事里可以引用描述,但照片本身必须在 reply 里看得到。光写文字不贴图 = 失败。\n"
        "\n要写 / 改东西,先 load_tool_group(group_name=...):\n"
        "· write_journal — patch_journal_block / insert_journal_block / check_daily_task\n"
        "· images — place_scrapbook_image / delete_attachment / set_*_image\n"
        "· widgets_and_tasks — widget 增删改 / task 改名改剂量\n"
        "\n注意:server 见到图 ref → 自动 load 'images';见到「记一下/写进去」类关键词 → 自动 load 'write_journal'。"
        "其他场景你想用 write 工具 → 必须先调 load_tool_group。\n"
    )
    parts.append(tool_catalog)

    # widget skill — 按需装载(省 6.7K tokens / 普通对话)
    if _wants_widget_skill(context):
        for fname in ["SKILL.md", "WIDGET_AUTHORING.md", "STYLE_GUIDE.md"]:
            f = SKILL_DIR / fname
            if f.exists():
                parts.append(f"\n\n=== {fname} ===\n{f.read_text(encoding='utf-8')}")
        if USER_WIDGETS_PATH.exists():
            parts.append(f"\n\n=== current .user-widgets.json ===\n{USER_WIDGETS_PATH.read_text(encoding='utf-8')}")
        refs = []
        if WIDGETS_DIR.exists():
            for d in sorted(WIDGETS_DIR.iterdir()):
                if d.is_dir() and (d / "manifest.json").exists():
                    refs.append(d.name)
        parts.append(f"\n\n=== existing widget folders ===\n{', '.join(refs)}")

    return "\n".join(parts)


_TIMEBLOCK_HOOK_PATH = Path.home() / ".claude" / "scripts" / "timeblock-stamp.sh"


def _compute_time_block_hint() -> str:
    """source CC 那边的 ~/.claude/scripts/timeblock-stamp.sh — single source of truth。
    CC 和 deepseek 看到完全一致的 [time-block] / [schedule-voice] baseline,
    未来在 bash 里改 hook,两边自动同步,不必两份维护。

    cwd 设到 JOURNAL_DIR 父级,让 hook 里的 has_schedule_dir gate 通过(否则空输出)。
    `[skill-required]` 行对 deepseek 没意义(它不能 invoke Skill),过滤掉。

    fallback:bash 没装 / 文件缺 / 超时 → 内联 Python 算最小版,保证 chat 不挂。
    """
    if _TIMEBLOCK_HOOK_PATH.exists():
        try:
            result = subprocess.run(
                ["bash", str(_TIMEBLOCK_HOOK_PATH)],
                cwd=str(VAULT_DIR if VAULT_DIR.exists() else Path.home()),
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0 and result.stdout.strip():
                lines = [l for l in result.stdout.splitlines()
                         if not l.startswith("[skill-required]")]
                return "\n".join(lines).rstrip()
        except (subprocess.SubprocessError, OSError) as e:
            log.warning(f"timeblock-stamp.sh failed ({e}), inline fallback")
    return _compute_time_block_hint_inline()


def _compute_time_block_hint_inline() -> str:
    """fallback:hook 不可用时的最小内联实现。"""
    now = datetime.now()
    block_minute = 30 if now.minute >= 30 else 0
    block_label = f"{now.hour}：{block_minute:02d}"
    end_minute = 59 if block_minute == 30 else 29
    weekday_cn = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"][now.weekday()]
    return (
        f"[time-block] now={now.strftime('%H:%M')} CST {now.strftime('%Y-%m-%d')}({weekday_cn}) "
        f"→ current block: {block_label} (covers {now.hour:02d}:{block_minute:02d}-{now.hour:02d}:{end_minute:02d})\n"
        f"[time-block] H1 use: `# {block_label}` (full-width colon). For PAST events, ASK user."
    )

# ── tool definitions for DeepSeek ───────────────────────────────────
# TOOLS schema(纯数据)抽到 tool_specs.py;re-export 给 _active_tools + 全文件用。
from tool_specs import TOOLS  # noqa: E402,F401

# ── tool implementations ─────────────────────────────────────────────
def tool_list_widgets():
    user_widgets = json.loads(USER_WIDGETS_PATH.read_text(encoding="utf-8")) if USER_WIDGETS_PATH.exists() else {}
    active = set(user_widgets.get("active", []))
    folders = []
    if WIDGETS_DIR.exists():
        for d in sorted(WIDGETS_DIR.iterdir()):
            if d.is_dir() and (d / "manifest.json").exists():
                folders.append({"name": d.name, "active": d.name in active})
    return {"widgets": folders, "user_widgets_file": _pretty_rel(USER_WIDGETS_PATH)}

def tool_add_widget(args):
    name = args["name"]
    folder = WIDGETS_DIR / name
    if folder.exists():
        return {"error": f"widget '{name}' already exists. use patch_widget instead."}
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(args["manifest_json"], encoding="utf-8")
    (folder / "widget.html").write_text(args["widget_html"], encoding="utf-8")
    (folder / "widget.js").write_text(args["widget_js"], encoding="utf-8")

    # A-H9: read 端加 try 防 json.loads 跑挂 endpoint;write 走 atomic + rotate
    cfg = {"active": []}
    if USER_WIDGETS_PATH.exists():
        try:
            cfg = json.loads(USER_WIDGETS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            _report_silent_failure("user_widgets_parse_failed",
                f"{type(e).__name__}: {str(e)[:120]}")
            cfg = {"active": []}
    if name not in cfg.setdefault("active", []):
        cfg["active"].append(name)
    _safe_write_text(USER_WIDGETS_PATH,
        json.dumps(cfg, indent=2, ensure_ascii=False), rotate=True)
    return {"created": name, "active": cfg["active"]}

def tool_patch_widget(args):
    name = args["name"]
    folder = WIDGETS_DIR / name
    if not folder.exists():
        return {"error": f"widget '{name}' not found"}
    target = folder / args["file"]
    target.write_text(args["new_content"], encoding="utf-8")
    return {"patched": f"{name}/{args['file']}"}

def _resolve_date_arg(date_arg: str, days_back_max: int = 7):
    """统一 date 参数解析 + sanity 校验。
    无 date → today;格式错 / 未来 / 距今 > N 天 → error。
    返回 (datetime, error_str)。error_str 空表示通过。
    """
    today = datetime.now()
    if not date_arg:
        return today, ""
    try:
        d = datetime.strptime(date_arg.strip(), "%Y-%m-%d")
    except ValueError:
        return None, f"bad date format: {date_arg!r} (need YYYY-MM-DD)"
    delta_days = (today.date() - d.date()).days
    if delta_days < 0:
        return None, f"date {date_arg} 在未来,拒"
    if delta_days > days_back_max:
        return None, (f"date {date_arg} 距今 {delta_days} 天太远,拒(超过 {days_back_max} 天保护线)。"
                      f"想编辑老 entry 请用户在最近消息里明示日期,或直接走 obsidian。")
    return d, ""


def tool_patch_journal_block(args):
    target, err = _resolve_date_arg((args.get("date") or "").strip())
    if err:
        return {"error": err}
    f = find_today_journal(target)
    if not f:
        return {"error": f"no journal file for {target.strftime('%Y-%m-%d')}"}
    return _patch_block(f, args["time"], args["new_md"], author="ai",
                        allow_h2_rename=bool(args.get("allow_h2_rename", False)))

def tool_read_today_schedule(args):
    return _journal_for_date(args.get("date"))

def tool_list_recent_days(args):
    n = int(args.get("n") or 7)
    days = _list_journal_files()
    return {"days": days[-n:][::-1]}  # 倒序,最新在前

def tool_insert_journal_block(args):
    time_str = (args.get("time") or "").strip()
    tag = (args.get("tag") or "").strip()
    title = (args.get("title") or "").strip()
    body = (args.get("body") or "").strip()
    # 兜底:没指定 time 用当前半小时
    if not time_str:
        now = datetime.now()
        time_str = f"{now.hour}:{0 if now.minute < 30 else 30:02d}"
    target, err = _resolve_date_arg((args.get("date") or "").strip())
    if err:
        return {"error": err}
    f = find_today_journal(target)
    if not f:
        return {"error": f"no journal file for {target.strftime('%Y-%m-%d')}"}
    out = _insert_block(f, time_str, tag=tag, title=title, author="ai", body=body)
    # 钉子(兜旧习惯):标题-only 条目违反日记协议,在 tool result 里压模型立刻补正文
    if isinstance(out, dict) and out.get("ok") and not body:
        out["warning"] = ("⚠ 只写了标题没写正文,违反日记协议(每条 entry 必须有"
                          "result + significance 的散文)。请立即用 patch_journal_block 补上正文。")
    return out


def tool_append_journal_comment(args):
    """append-only AI 评论:在指定时间块 body 末尾 append 一段,**不动原 H2 / 原 body**。
    撞 @user 块时 patch_journal_block 会拒绝 → 用这个工具留评论"穿线/回看/AI 注"。"""
    time_str = (args.get("time") or "").strip()
    comment = (args.get("comment_md") or "").strip()
    if not time_str:
        return {"error": "need time HH:MM"}
    if not comment:
        return {"error": "need comment_md"}
    target, err = _resolve_date_arg((args.get("date") or "").strip())
    if err:
        return {"error": err}
    f = find_today_journal(target)
    if not f:
        return {"error": f"no journal file for {target.strftime('%Y-%m-%d')}"}
    return _append_comment_to_block(f, time_str, comment)


def _list_today_tasks():
    """读今天 md 顶部 - [ ] 行,返完整任务名列表 + 文件 + lines + bounds。
    供 _resolve_task_name 和 tool_check_daily_task 共用。"""
    f = find_today_journal()
    if not f:
        return None, None, None, None, "no today journal"
    text = f.read_text(encoding="utf-8")
    bounds = _top_section_bounds(text)
    if not bounds:
        return f, text, None, None, "no top section"
    lines = text.splitlines()
    tasks = []
    for i in range(bounds[0], bounds[1]):
        m = re.match(r"^(-\s*\[)([ x])(\]\s*)(.+)", lines[i])
        if m:
            tasks.append(m.group(4).strip())
    return f, text, lines, tasks, None

def _resolve_task_name(name):
    """模糊解析 daily-task 名 → 完整规范名。
    AI 实测倾向用'语义全名'省 suffix(如'南非醉茄 KSM-66（Nature Love）' 漏'，90粒新版'),
    严格匹配会全失败。这里兜:子串包含(任一方向)唯一命中 → 用全名。多/无 → 报错带候选。
    返 (full_name, None) 或 (None, error_dict)。"""
    name = (name or "").strip()
    if not name:
        return None, {"error": "need task_name"}
    _, _, _, tasks, err = _list_today_tasks()
    if err:
        return None, {"error": err}
    if not tasks:
        return None, {"error": "no tasks in today's checklist"}
    # 1) 精确
    for t in tasks:
        if t == name:
            return t, None
    # 2) 子串(name in task 或 task in name) — 唯一命中算解析成功
    matches = [t for t in tasks if (name in t) or (t in name)]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, {"error": f"task '{name}' 模糊匹配多条,请用更精确名",
                      "candidates": matches}
    # 3) 归一化(去掉中英括号内容 + 去空格 + 小写)再比 —— 兜 AI 漏 suffix
    #    例:"南非醉茄 KSM-66（Nature Love）" vs "南非醉茄 KSM-66（Nature Love，90粒新版）"
    #    步2 不命中(位置 25 处 `）` vs `，` 卡),步3 归一化后两边都是"南非醉茄ksm-66" → 命中
    def _norm(s):
        return re.sub(r"[\(（][^\)）]*[\)）]", "", s or "").lower().replace(" ", "").strip()
    nn = _norm(name)
    if nn:
        nmatches = [t for t in tasks if _norm(t) == nn or nn in _norm(t) or _norm(t) in nn]
        if len(nmatches) == 1:
            return nmatches[0], None
        if len(nmatches) > 1:
            return None, {"error": f"task '{name}' 归一化后多条,请用更精确名",
                          "candidates": nmatches}
    return None, {"error": f"task '{name}' 不在今天的清单里", "candidates": tasks}


def tool_check_daily_task(args):
    """打卡。task_name 支持模糊匹配——传短名/缺 suffix 也能定位到全名行。"""
    full, err = _resolve_task_name(args.get("task_name"))
    if err:
        return err
    checked = bool(args.get("checked"))
    f, text, lines, _, lerr = _list_today_tasks()
    if lerr:
        return {"error": lerr}
    box = "x" if checked else " "
    for i in range(*_top_section_bounds(text)):
        m = re.match(r"^(-\s*\[)([ x])(\]\s*)(.+)", lines[i])
        if m and m.group(4).strip() == full:
            lines[i] = f"{m.group(1)}{box}{m.group(3)}{m.group(4)}"
            new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
            _safe_write_text(f, new_text, rotate=True)
            return {"ok": True, "task_name": full, "checked": checked,
                    **({"resolved_from": args.get("task_name")} if args.get("task_name") != full else {})}
    return {"error": f"task '{full}' 解析后仍未找到对应行(罕见,可能 md 顶部刚改动)"}


def _pick_attachment_url(args):
    """容错:模型偶尔把 attachment_url 写成 image_path/url/image_url/path/attachment
    (5.27 实测 deepseek 用了 image_path → 整个 set_daily_task_image 失败)。都认,挑第一个非空。"""
    for k in ("attachment_url", "image_path", "image_url", "url", "attachment", "path"):
        v = args.get(k)
        if v and str(v).strip():
            return str(v).strip()
    return ""


def tool_set_water_cup_image(args):
    url = _pick_attachment_url(args)
    if not url:
        return {"error": "need attachment_url"}
    processed, err = _get_or_create_processed_attachment(url)
    if err:
        return {"error": err}
    DAILY_TASK_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    out = DAILY_TASK_IMAGES_DIR / "_water_cup.png"
    out.write_bytes(processed.read_bytes())
    rel = _pretty_rel(out)
    image_map = _load_task_image_map()
    image_map[WATER_CUP_KEY] = rel
    _save_task_image_map(image_map)
    return {"ok": True, "image_url": f"/{rel}"}


def tool_set_daily_task_image(args):
    url = _pick_attachment_url(args)
    if not url:
        return {"error": "need attachment_url (or image_path/url alias)"}
    # 模糊解析 task_name → 全名;否则 image_map 键跟任务行对不上,图标不显示(5.28 实测的坑)
    full, name_err = _resolve_task_name(args.get("task_name"))
    if name_err:
        return name_err
    processed, err = _get_or_create_processed_attachment(url)
    if err:
        return {"error": err}
    DAILY_TASK_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    stem = _sanitize_task_filename(full)
    out = DAILY_TASK_IMAGES_DIR / f"{stem}.png"
    out.write_bytes(processed.read_bytes())
    rel = _pretty_rel(out)
    image_map = _load_task_image_map()
    image_map[full] = rel
    _save_task_image_map(image_map)
    return {"ok": True, "task_name": full, "image_url": f"/{rel}",
            **({"resolved_from": args.get("task_name")} if args.get("task_name") != full else {})}


def tool_manage_daily_task(args):
    action = args.get("action")
    if action not in ("add", "edit", "del"):
        return {"error": "action must be add|edit|del"}
    text = (args.get("text") or "").strip()
    old_text = (args.get("old_text") or "").strip()
    targets = []
    if SCHEDULE_TEMPLATE_PATH.exists():
        targets.append(SCHEDULE_TEMPLATE_PATH)
    today_f = find_today_journal()
    if today_f:
        targets.append(today_f)
    md_results = [_apply_task_op(f, action, text, old_text) for f in targets]

    # rename safety:edit / del 时把 meta + image map 的 key 一并迁移 / 清掉
    # 否则旧 key 变孤儿:intake history、图片、库存全失联
    side_effects = {}
    if action == "edit" and old_text and text and old_text != text and any(r.get("ok") for r in md_results):
        side_effects = _migrate_task_keys(old_text, text)
    elif action == "del" and old_text and any(r.get("ok") for r in md_results):
        side_effects = _purge_task_keys(old_text)

    return {"ok": True, "results": md_results, "side_effects": side_effects}


def _migrate_task_keys(old_name: str, new_name: str) -> dict:
    """edit 时把 daily-task-meta + daily-task-images 的 key 从 old 改 new。
    幂等:new key 已存在就保留 new、不覆盖。返做了什么。
    """
    out = {"meta_migrated": False, "image_migrated": False}
    try:
        meta = _load_task_meta_map()
        if old_name in meta and new_name not in meta:
            meta[new_name] = meta.pop(old_name)
            _save_task_meta_map(meta)
            out["meta_migrated"] = True
    except Exception as e:
        out["meta_error"] = str(e)
        # 改名后 intake_log 历史变孤儿,UI 看不出问题但数据断 — 必须响铃
        _report_silent_failure("task_rename_meta_migrate_failed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"old": old_name[:40], "new": new_name[:40]})
    try:
        img_map = _load_task_image_map()
        if old_name in img_map and new_name not in img_map:
            img_map[new_name] = img_map.pop(old_name)
            _save_task_image_map(img_map)
            out["image_migrated"] = True
    except Exception as e:
        out["image_error"] = str(e)
        _report_silent_failure("task_rename_image_migrate_failed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"old": old_name[:40], "new": new_name[:40]})
    return out


def _purge_task_keys(name: str) -> dict:
    """del 时清理 daily-task-meta + daily-task-images 的对应 key + 删图文件。
    跟现有 daily-tasks/delete 端点逻辑保持一致(单一真相)。
    """
    out = {"meta_purged": False, "image_purged": False, "image_file_removed": False}
    try:
        meta = _load_task_meta_map()
        if name in meta:
            del meta[name]
            _save_task_meta_map(meta)
            out["meta_purged"] = True
    except Exception as e:
        out["meta_error"] = str(e)
        _report_silent_failure("task_delete_meta_purge_failed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"name": name[:40]})
    try:
        img_map = _load_task_image_map()
        if name in img_map:
            rel = img_map.pop(name)
            _save_task_image_map(img_map)
            out["image_purged"] = True
            try:
                p = PLATFORM_ROOT / rel
                if p.exists():
                    p.unlink()
                    out["image_file_removed"] = True
            except Exception:
                pass
    except Exception as e:
        out["image_error"] = str(e)
        _report_silent_failure("task_delete_image_purge_failed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"name": name[:40]})
    return out


def tool_place_scrapbook_image(args):
    """AI 把照片 absolute 浮在 .page 之上(v3 自由位置)。失败返 {error}。"""
    import random
    url = _pick_attachment_url(args)
    date = (args.get("date") or "").strip()
    anchor_time = (args.get("anchor_time") or "").strip()
    # 新 schema:x_pct / y_px。容忍 legacy align/position 字段,转换。
    x_pct = args.get("x_pct")
    y_px = args.get("y_px")
    if x_pct is None:
        legacy_align = args.get("align") or args.get("position")
        x_pct = 3 if legacy_align == "left" else 75
    # auto_y 表示"AI 没指定纵坐标 → 由客户端按 anchor_time 算到对应 entry 旁边"。
    # 之前默认 y_px=0 + 注释说"前端会重算",但前端 applyPos 老老实实读 0,图就贴
    # 到了页面顶。补 auto_y 字段让 scrapbook.js 触发 computeYFromAnchor。
    auto_y = (y_px is None)
    if y_px is None:
        y_px = 0
    x_pct = max(0, min(95, float(x_pct)))
    y_px = max(0, float(y_px))
    do_cutout = args.get("cutout", True)
    rot = args.get("rotation")
    if rot is None:
        rot = round(random.uniform(-4, 4), 1)
    if not url or not date or not anchor_time:
        return {"error": "need attachment_url + date + anchor_time"}
    m = re.match(r"^/attachments/([^/]+)/([^/]+)$", url)
    if not m:
        return {"error": f"bad attachment_url: {url}"}
    src_file = ATTACHMENTS_DIR / m.group(1) / m.group(2)
    if not src_file.exists():
        return {"error": f"attachment not found: {url}"}

    SCRAPBOOK_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    out_stem = f"{date}_{_scrapbook_id()}"
    if do_cutout:
        # 把用户意图传下去 — 函数内部还会再 fallback 一次(无 key 直接返原图),
        # 这里 do_cutout=True 表"用户希望抠",有 key 才真抠,没 key 静默原图。
        processed, err = _get_or_create_processed_attachment(url, cutout=True)
        if err:
            return {"error": err + " (要不要 cutout=false 重试?)"}
        out_file = SCRAPBOOK_IMAGES_DIR / f"{out_stem}.png"
        out_file.write_bytes(processed.read_bytes())
    else:
        ext = src_file.suffix or ".png"
        out_file = SCRAPBOOK_IMAGES_DIR / f"{out_stem}{ext}"
        out_file.write_bytes(src_file.read_bytes())

    rel = "/" + _pretty_rel(out_file)

    items = _load_scrapbook(date)
    item = {
        "id": _scrapbook_id(),
        "src": rel,
        "anchor_time": anchor_time,
        "x_pct": x_pct,
        "y_px": y_px,
        "w": 220,
        "h": 220,
        "rotation": float(rot),
        "auto_y": auto_y,  # True → 客户端 render 时按 anchor_time 算 y;用户拖完后 upsert 会清掉
    }
    items.append(item)
    _save_scrapbook(date, items)
    return {"ok": True, "item": item, "image_url": rel}


def _gemini_classify_image(file_path: Path, extra_q: str = "") -> dict:
    """调 Gemini Flash 看图,返结构化 JSON。失败返 {error}。
    需 gateway-config.json 里有 gemini_api_key。
    """
    cfg = load_config() or {}
    key = cfg.get("gemini_api_key", "")
    if not key:
        return {"error": "no_gemini_key", "hint": "请去 setup 面板填 Gemini API key 才能用 vision 路由"}
    if not file_path.exists():
        return {"error": f"file not found: {file_path}"}
    try:
        b64 = base64.b64encode(file_path.read_bytes()).decode("ascii")
    except Exception as e:
        return {"error": f"read file failed: {e}"}
    ext = file_path.suffix.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/png")
    prompt = (
        "看这张图,严格返 JSON 不要任何前后说明。字段:\n"
        "- kind: supplement | food | place | object | selfie | doc | other\n"
        "- description: 中文一句话(20字内)\n"
        "- ocr_likely: bool, 图里是否有显著文字\n"
        "- suggested_action: scrapbook_paste | supplement_track | ocr | none\n"
        "- brand: 商品品牌(若是商品,不知则空字串)\n"
        "- pill_count: 整数, 若图上明确有颗数(如 60 capsules);否则 0\n"
    )
    if extra_q:
        prompt += f"- extra: {extra_q}\n"
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    try:
        r = requests.post(
            url,
            headers={"Content-Type": "application/json", "X-goog-api-key": key},
            json={
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": mime, "data": b64}},
                    ]
                }],
                "generationConfig": {"responseMimeType": "application/json"},
            },
            timeout=30,
        )
        if r.status_code != 200:
            return {"error": f"gemini http {r.status_code}: {r.text[:200]}"}
        data = r.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        try:
            parsed = json.loads(text)
        except Exception:
            return {"error": f"gemini returned non-JSON: {text[:200]}"}
        return {"ok": True, **parsed}
    except Exception as e:
        return {"error": f"gemini call failed: {type(e).__name__}: {e}"}


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


def _qwen_classify_image(file_path: Path, extra_q: str = "") -> dict:
    """调 Qwen-VL (Dashscope OpenAI-compat) 看图,返结构化 JSON。失败返 {error}。
    需 gateway-config.json 里有 dashscope_api_key。
    默认 qwen3-vl-flash(便宜+快;classify 任务足够;质量需求更高可换 qwen-vl-plus / qwen-vl-max-latest)。
    取代 Gemini(国内网络环境 Gemini 不稳)。
    入口压缩:1024px max + JPEG q=85,vision token 大降但识别率不掉。
    """
    cfg = load_config() or {}
    # 优先 dashscope_api_key;空时 fallback 主 api_key(百炼迁移后顶层 key 就是 dashscope)
    key = cfg.get("dashscope_api_key", "") or cfg.get("api_key", "")
    base_for_check = (cfg.get("base_url") or "")
    if not key or (cfg.get("dashscope_api_key") == "" and "dashscope" not in base_for_check):
        # 没专用 dashscope key,顶层 base_url 也不是 dashscope → 不能保证 key 是百炼的
        if not key:
            _report_silent_failure("vision_no_key",
                "no dashscope_api_key + fallback api_key 也空")
            return {"error": "no_dashscope_key",
                    "hint": "请去 setup 面板填 Dashscope API key (Qwen-VL),才能用 vision 路由"}
        # key 存在但 base_url 不是 dashscope — 5.29 prod 401 的真因(prod .env 漏 key)
        # B-#5: 上报 + 直接返,**别**继续走 OpenAI client 用错家 key 打错家 endpoint
        # (每张图 401 + 烧 latency + silent-failure 2 条/张)
        _report_silent_failure("vision_key_config_inconsistent",
            "dashscope_api_key 空,fallback 顶层 api_key 但 base_url 不是 dashscope endpoint",
            context={"network_marker": "non_dashscope_base_url"})
        return {"error": "vision_key_config_inconsistent",
                "hint": "顶层 api_key 跟 base_url 不是 dashscope endpoint;请在 setup 填 dashscope_api_key 或把 base_url 改成 dashscope"}
    if not file_path.exists():
        _report_silent_failure("vision_file_missing",
            f"attachment 文件不存在: {file_path.name}")
        return {"error": f"file not found: {file_path}"}
    # 入口压缩(只动 vision 传输,不动原图)
    use_compressed = True
    try:
        b64 = base64.b64encode(_compress_for_vision(file_path)).decode("ascii")
    except Exception as e:
        log.warning(f"compress failed for {file_path}, fallback to raw: {e}")
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
        "- suggested_action: scrapbook_paste | supplement_track | ocr | none\n"
        "- brand: 商品品牌(若是商品,不知则空字串)\n"
        "- pill_count: 整数, 若图上明确有颗数(如 60 capsules);否则 0\n"
    )
    if extra_q:
        prompt += f"- extra: {extra_q}\n"

    model_id = cfg.get("dashscope_vision_model", "qwen3-vl-flash")
    base_url = cfg.get("dashscope_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    try:
        client = OpenAI(api_key=key, base_url=base_url, timeout=120.0, max_retries=1)
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
            timeout=120.0,
        )
    except Exception as e:
        # 区分 auth vs 其他(401/403 跟用户配置直接相关,priority 排高)
        err_kind = "vision_classify_auth" if "401" in str(e) or "403" in str(e) else "vision_classify_call_failed"
        _report_silent_failure(err_kind,
            f"{type(e).__name__}: {str(e)[:150]}",
            context={"model_id": model_id})
        return {"error": f"qwen vision call failed: {type(e).__name__}: {e}"}

    text = (resp.choices[0].message.content or "").strip()
    # 容忍 ``` fence
    text = re.sub(r"^```(json)?\s*", "", text).strip()
    text = re.sub(r"\s*```\s*$", "", text).strip()
    try:
        parsed = json.loads(text)
    except Exception:
        _report_silent_failure("vision_classify_non_json",
            f"qwen 返了非 JSON: {text[:100]}",
            context={"model_id": model_id})
        return {"error": f"qwen returned non-JSON: {text[:200]}"}
    return {"ok": True, **parsed}


def tool_vision_classify(args):
    url = _pick_attachment_url(args)
    extra_q = (args.get("extra_question") or "").strip()
    if not url:
        return {"error": "need attachment_url"}
    m = re.match(r"^/attachments/([^/]+)/([^/]+)$", url)
    if not m:
        return {"error": f"bad attachment_url: {url}"}
    f = ATTACHMENTS_DIR / m.group(1) / m.group(2)
    return _qwen_classify_image(f, extra_q)


def tool_list_my_uploads(args):
    arr = _load_attachments_index()
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
    arr = _load_attachments_index()
    ql = q.lower()
    hits = []
    for x in arr:
        v = x.get("vision") or {}
        # 关键:haystack 加 vision 描述/kind/brand —— 否则没文字的照片(食物/玩偶/宠物)
        # 永远搜不到(filename 是 hash)。5.27 论证的根因。
        hay = " ".join([
            x.get("filename", ""), x.get("original", ""), x.get("ocr_text", "") or "",
            v.get("description", "") or "", v.get("kind", "") or "", v.get("brand", "") or "",
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
                "ocr_preview": (x.get("ocr_text", "") or "")[:200],
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
    if not CURATOR_SYSTEM_PATH.exists():
        _rebuild_curator_system_prompt()
    if not CURATOR_SYSTEM_PATH.exists():
        return _curator_fallback(q)
    try:
        sys_prompt = CURATOR_SYSTEM_PATH.read_text(encoding="utf-8")
    except Exception as e:
        _report_silent_failure("curator_system_read_failed",
            f"{type(e).__name__}: {str(e)[:120]}")
        return _curator_fallback(q)

    profile = get_profile("deepseek-v4-flash")
    if not profile:
        _report_silent_failure("curator_no_profile",
            "deepseek-v4-flash profile 不存在 — 检查 .env DEEPSEEK_API_KEY")
        return _curator_fallback(q)
    client = get_client(profile)
    if client is None:
        return _curator_fallback(q)

    # v4-flash 实测先 reasoning 再生 content,thinking 占大头。
    # 样本: in=2120 out=1715 content 458 chars (~250 tokens) → 1400+ token 在 reasoning。
    # 试 extra_body 关 thinking 被 endpoint 拒(BadRequest),不省那一两毛钱,
    # 给 max_tokens=3000 兜住 reasoning + content 即可。
    try:
        resp = client.chat.completions.create(
            model=profile.get("model", "deepseek-v4-flash"),
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
        _report_silent_failure(err_kind,
            f"{type(e).__name__}: {str(e)[:150]}",
            context={"query": q[:60]})
        return _curator_fallback(q)

    _log_cache_usage(resp, "curator")
    text = (resp.choices[0].message.content or "").strip()
    # 空 content (reasoning 烧完 max_tokens 是常见因) → fallback,不当 0 matches 处理
    if not text:
        _report_silent_failure("curator_empty_content",
            "v4-flash content 空 (可能 reasoning 吃完 max_tokens)",
            context={"query": q[:60]})
        return _curator_fallback(q)
    # 容忍 ``` fence(v4-flash 偶尔加)
    text = re.sub(r"^```(json)?\s*", "", text).strip()
    text = re.sub(r"\s*```\s*$", "", text).strip()
    try:
        parsed = json.loads(text)
    except Exception:
        _report_silent_failure("curator_non_json",
            f"返非 JSON: {text[:120]}",
            context={"query": q[:60]})
        return _curator_fallback(q)

    # stem → full record 映射,把主 agent 想要的 url + description 拼回去
    arr = _load_attachments_index()
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


def tool_search_journal(args):
    """全文搜 vault 所有 md。case-insensitive,多关键词 AND。
    跳过 attachments/ + .git/ + dotfiles。按 mtime desc(最新优先)。
    """
    q = (args.get("query") or "").strip()
    if not q:
        return {"error": "need query"}
    terms = [t.lower() for t in q.split() if t.strip()]
    if not terms:
        return {"error": "need query"}
    limit = max(1, min(int(args.get("limit") or 20), 100))
    if not VAULT_DIR.exists():
        return {"error": f"vault not found: {VAULT_DIR}"}

    hits = []
    for f in VAULT_DIR.rglob("*.md"):
        # 跳过附件 / git / dotfile
        parts = set(f.parts)
        if "attachments" in parts or ".git" in parts:
            continue
        if any(p.startswith(".") for p in f.relative_to(VAULT_DIR).parts):
            continue
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        mtime = f.stat().st_mtime
        for i, line in enumerate(lines):
            low = line.lower()
            if all(t in low for t in terms):
                ctx_start = max(0, i - 2)
                ctx_end = min(len(lines), i + 3)
                ctx = "\n".join(lines[ctx_start:ctx_end])
                hits.append({
                    "file": str(f.relative_to(VAULT_DIR)),
                    "line": i + 1,
                    "context": ctx,
                    "_mtime": mtime,
                })
    hits.sort(key=lambda h: -h["_mtime"])
    for h in hits:
        h.pop("_mtime", None)
    return {"matches": hits[:limit], "total_hits": len(hits), "truncated": len(hits) > limit}


def tool_delete_attachment(args):
    date = (args.get("date") or "").strip()
    filename = (args.get("filename") or "").strip()
    if not date or not filename or "/" in filename or ".." in filename:
        return {"error": "need {date, filename} (no path traversal)"}
    f = ATTACHMENTS_DIR / date / filename
    if f.exists():
        try:
            f.unlink()
        except Exception as e:
            return {"error": f"delete failed: {e}"}
    arr = _load_attachments_index()
    arr = [x for x in arr if not (x.get("date") == date and x.get("filename") == filename)]
    _save_attachments_index(arr)
    return {"ok": True, "removed": filename}


def tool_set_daily_task_meta(args):
    name = (args.get("task_name") or "").strip()
    if not name:
        return {"error": "need task_name"}
    meta_map = _load_task_meta_map()
    entry = dict(meta_map.get(name) or {})
    if "total_pills" in args and args["total_pills"] not in (None, "", 0):
        try:
            entry["total_pills"] = max(1, int(args["total_pills"]))
        except (TypeError, ValueError):
            return {"error": "total_pills must be int"}
    if "daily_dose" in args and args["daily_dose"] is not None:
        try:
            entry["daily_dose"] = max(1, int(args["daily_dose"]))
        except (TypeError, ValueError):
            return {"error": "daily_dose must be int"}
    meta_map[name] = entry
    _save_task_meta_map(meta_map)
    return {"ok": True, "task_name": name, **_task_meta_state(name, meta_map)}


# ── web_search / fetch_url 工具 ─ 抽到 web_tools.py(行为零变化,仅搬迁) ──
# 历史:此处原是 ~250 行 web_search 后端(360/百炼/ddgs/搜狗微信/B站)+ fetch_url + _html_to_text
# 现在:见 web_tools.py。这一对工具是 chat tool-dispatch 的纯 vertical,无模块级锁/线程/状态,
# 抽出后 TOOL_IMPL 直接引用同名函数,API 一字不变。
from web_tools import (
    tool_web_search, tool_fetch_url,
    _resolve_dashscope_creds, _bailian_web_search,
    _sogou_wechat_search, _bilibili_search, _360_search,
    _do_web_search, _ddgs_search, _html_to_text,
)


def tool_load_protocol(args):
    """读 protocols/{name}.md 给 AI。延迟加载详细协议规则,baseline prompt 保持精简。"""
    name = (args.get("name") or "").strip()
    if not name:
        return {"error": "need name", "available": list(PROTOCOLS.keys())}
    content = load_protocol(name)
    return {"name": name, "content": content}


TOOL_IMPL = {
    "list_widgets":         lambda args: tool_list_widgets(),
    "add_widget":           tool_add_widget,
    "patch_widget":         tool_patch_widget,
    "patch_journal_block":  tool_patch_journal_block,
    "read_today_schedule":  tool_read_today_schedule,
    "list_recent_days":     tool_list_recent_days,
    "insert_journal_block": tool_insert_journal_block,
    "append_journal_comment": tool_append_journal_comment,
    "manage_daily_task":    tool_manage_daily_task,
    "check_daily_task":     tool_check_daily_task,
    "set_daily_task_image": tool_set_daily_task_image,
    "set_water_cup_image":  tool_set_water_cup_image,
    "set_daily_task_meta":  tool_set_daily_task_meta,
    "place_scrapbook_image":tool_place_scrapbook_image,
    "list_my_uploads":      tool_list_my_uploads,
    "search_my_uploads":    tool_search_my_uploads,
    "ask_photo_curator":    tool_ask_photo_curator,
    "search_journal":       tool_search_journal,
    "delete_attachment":    tool_delete_attachment,
    "vision_classify":      tool_vision_classify,
    "web_search":           tool_web_search,
    "fetch_url":            tool_fetch_url,
    "load_protocol":        tool_load_protocol,
}


# ── lazy tool loading ───────────────────────────────────────────────
# 19 个 tool 一次性甩给 model 会有"affordance bias" — 看见 write 工具就想写。
# 改成:bootstrap(read + meta)默认在,write/mutating 工具按 group 按需加载。
# 触发方式 2 种:(a) server 根据 user_msg/context 自动 load(图片→images,
# "记一下"→write_journal),(b) model 主动调 load_tool_group(name)。
TOOL_GROUPS = {
    "write_journal": [
        "patch_journal_block", "insert_journal_block", "append_journal_comment", "check_daily_task",
    ],
    "images": [
        "place_scrapbook_image", "delete_attachment",
        "set_water_cup_image", "set_daily_task_image",
        # check_daily_task 也放这:拖补剂图 = 打卡(设图标 + 勾选)的一体动作,
        # 不带它的话 AI 只能设图标、勾不上今天的打卡(它另外也在 write_journal 组)。
        "check_daily_task",
    ],
    "widgets_and_tasks": [
        "list_widgets", "add_widget", "patch_widget",
        "manage_daily_task", "set_daily_task_meta",
    ],
}

BOOTSTRAP_TOOL_NAMES = {
    # read-only / meta — 任意 chat 都该能用
    "read_today_schedule", "list_recent_days",
    "list_my_uploads", "search_my_uploads", "ask_photo_curator",
    "search_journal", "vision_classify",
    "web_search", "fetch_url", "load_protocol", "load_tool_group",
}

_INITIAL_LOAD_KEYWORDS = re.compile(
    r'(记一下|记一笔|记下|写进|写到|加进|append|更新.*?日记|改.*?日记'
    r'|打卡|打个卡|勾选|勾上|勾掉|勾了|标记完成|标为完成)'  # 打卡类 → 要 check_daily_task(在 write_journal 组)
)

def _initial_groups(user_msg: str, context: dict) -> set:
    """server 端预判要哪些 group。降低 model 必须先调 load_tool_group 的轮数。"""
    groups = set()
    refs = (context or {}).get("refs", []) if isinstance(context, dict) else []
    if any((r or {}).get("kind") == "image" for r in refs):
        groups.add("images")
    if user_msg and _INITIAL_LOAD_KEYWORDS.search(user_msg):
        groups.add("write_journal")
    return groups

def _active_tools(loaded_groups: set) -> list:
    """根据已加载 group 算出本轮要传给 API 的 tools 列表。"""
    names = set(BOOTSTRAP_TOOL_NAMES)
    for g in loaded_groups:
        names.update(TOOL_GROUPS.get(g, []))
    return [t for t in TOOLS if t.get("function", {}).get("name") in names]

# PATTERN: api — per-tool quota with hard cap per chat turn
# USE WHEN: model 容易死循环调同一 tool(web_search loop, list 类反复 read)
# COPY THIS: 改 TOOL_QUOTA 数字 / 加新 tool 进 dict
# 没在 dict 里的 tool = 无限(write/admin 类用户授权过的别卡)
TOOL_QUOTA = {
    "web_search":          3,
    "fetch_url":           5,   # 比 search 多 — 一次 search 可能 fetch 2-3 个有料的
    "append_journal_comment": 5,  # 留评论本来就该克制,5 次/turn 够了
    "read_today_schedule": 5,
    "list_recent_days":    2,
    "list_my_uploads":     2,
    "search_my_uploads":   3,
    "ask_photo_curator":   1,  # 单 call 返完整集,quota 给 1 就够;主 agent 应优先调它做语义检索
    "search_journal":      5,  # 比 uploads 高一档 — vault 大,可能要 refine query 多搜几次
    "vision_classify":     3,
    "load_protocol":       3,
    "load_tool_group":     5,
}

# PATTERN: util — observability log for LLM cache hit rate
# USE WHEN: 想看 DeepSeek prompt_cache_hit_tokens 实际命中率(stable prefix 假设验证)
# COPY THIS: 改 source 字符串区分调用位置
def _log_cache_usage(resp, source: str):
    """log DeepSeek cache hit metrics. fail silently if SDK 不返这字段(老 API / 其他 provider)。"""
    try:
        usage = getattr(resp, "usage", None)
        if not usage:
            return
        hit  = getattr(usage, "prompt_cache_hit_tokens", 0) or 0
        miss = getattr(usage, "prompt_cache_miss_tokens", 0) or 0
        total = hit + miss
        if total == 0:
            return
        ratio = hit / total * 100
        log.info(f"[cache:{source}] hit={hit} miss={miss} ratio={ratio:.0f}% (total prompt={total})")
    except Exception:
        pass  # observability 不能因为它崩

def _dispatch_tool(fn: str, args: dict, loaded_groups: set, quota_used: dict):
    """统一 tool 调用入口。
    - 特判 load_tool_group(改 loaded_groups state)
    - 检查 TOOL_QUOTA 配额,超了返 error 让 model 用已有 result 凑活
    """
    cap = TOOL_QUOTA.get(fn)
    if cap is not None:
        used = quota_used.get(fn, 0)
        if used >= cap:
            return {"error": f"{fn} 本轮 chat 已用 {used}/{cap} 次,quota 用完。用已有 result 答,别再调。"}
        quota_used[fn] = used + 1
    if fn == "load_tool_group":
        g = (args or {}).get("group_name", "").strip()
        if g in TOOL_GROUPS:
            loaded_groups.add(g)
            return {"loaded": g, "now_available": TOOL_GROUPS[g]}
        return {"error": f"unknown group: {g}; available: {list(TOOL_GROUPS.keys())}"}
    try:
        return TOOL_IMPL[fn](args)
    except KeyError:
        return {"error": f"unknown tool: {fn}"}
    except Exception as e:
        # tool 真崩了 — LLM 会拿 error 串往下走,常常导致幻觉回复("我已经做了 X")。
        # claim audit 会兜底 detect,但根因丢了不利后续修。
        _report_silent_failure("tool_dispatch_exception",
            f"{fn}: {type(e).__name__}: {str(e)[:150]}",
            context={"tool": fn})
        return {"error": str(e)}

# ── app ──────────────────────────────────────────────────────────────
app = FastAPI(title="gateway v0.4")

# PULSE LARGE refactor P1:7 /api/pulse/* endpoint 已搬到 pulse_routes.py(thin
# wrapper,内部 from server import 调 helper)。本 include 后下方 PULSE endpoint
# 装饰器全删,业务逻辑(_self_evolve_run / _eval_* / _pulse_validate 等)P2-P4 续。
# 7 个 handler 同时 re-export 到 server 命名空间(P0+ 测试如 test_pulse_refresh_mirror
# 直调 server.pulse_refresh_mirror(),re-export 保契约)。
from pulse_routes import (  # noqa: E402,F401
    router as _pulse_router,
    pulse_dashboard, pulse_detail,
    pulse_user_update, pulse_project_update, pulse_agent_context_update,
    pulse_compact_summary, pulse_refresh_mirror,
)
app.include_router(_pulse_router)

# Extract Module(ctrl-c-v § 9):setup / config 簇(10 endpoint:/api/setup-status
# /api/setup/* /api/models)搬到 setup_routes.py(thin wrapper,helper 仍 lazy
# from server import)。零直接调用方(HTTP-only)→ 不 re-export,只 include_router。
# helper(load_config / _save_config / get_client / list_model_profiles /
# _profile_from_top_level + CONFIG_PATH / DEEPSEEK_* / BAILIAN_*)留 server.py。
from setup_routes import router as _setup_router  # noqa: E402
app.include_router(_setup_router)

# Extract Module(ctrl-c-v § 9):daily-tasks 簇(8 endpoint:/api/daily-tasks/* +
# /api/water-cup GET+POST)搬到 daily_tasks_routes.py(thin wrapper,helper lazy
# from server import)。io-map/_apply_task_op/LLM tools/WATER_CUP_KEY 等全留 server.py
# (P0+ tripwire 测试 T9/T11/T12/T13 守"必须留")。零直接调用方 → 不 re-export。
from daily_tasks_routes import router as _daily_tasks_router  # noqa: E402
app.include_router(_daily_tasks_router)

# Extract Module(ctrl-c-v § 9):thread-history 持久化(3 endpoint:/api/thread/history
# + restore-from-bak + save)搬到 thread_routes.py(chat 簇降风险拆解第一刀,不碰 SSE 流式)。
# helper(_thread_history_mtime_ms/_thread_save_is_stale)+ THREAD_HISTORY_PATH + _THREAD_LOCK
# 留 server(test_thread_cas 直调 + 测试 patch)。零直接调用方 → 不 re-export。
from thread_routes import router as _thread_router  # noqa: E402
app.include_router(_thread_router)

# Extract Module(ctrl-c-v § 9):eval/留言板(4 endpoint:/api/eval/list,today,test,run)
# 搬到 board_routes.py(纯 handler 搬迁,_eval_* helper + EVAL_LOG_DIR 早在 pulse_eval,
# server re-export;handler lazy from server import)。零直接调用方 → 不 re-export。
from board_routes import router as _board_router  # noqa: E402
app.include_router(_board_router)

# Extract Module(ctrl-c-v § 9):journal 读/写 + tag-aggregate(10 endpoint)搬到
# journal_routes.py。**危险 helper 全留 server**(_patch_block/_insert_block/_append_comment/
# _check_author = authorship 边界 + sha-lock + H2-guard;被 LLM tools + test_authorship 直调)
# → 只搬 thin handler,authorship 核心一字不动。handler lazy from server import。不 re-export。
from journal_routes import router as _journal_router  # noqa: E402
app.include_router(_journal_router)

# Extract Module(ctrl-c-v § 9):chat 对话引擎(/api/chat + /api/chat/upload-image)搬到
# chat_routes.py(本 session 最高风险 — DSML 泄漏闸/SSE 契约/可变状态/claim 审计随之搬走,
# 15 条 characterization 守红线)。tool 引擎(TOOL_IMPL/_dispatch_tool/build_system_prompt/
# LLM core/attachments 索引)+ authorship 核心全留 server,chat lazy from server import。
# re-export _audit_unauthorized_claim:test_claim_audit.py 直调 server._audit_unauthorized_claim。
from chat_routes import (  # noqa: E402,F401
    router as _chat_router, _audit_unauthorized_claim,
)
app.include_router(_chat_router)

# Extract Module(ctrl-c-v § 9):图像簇(/api/attachments* + /api/cutout + /api/vision/classify,
# 7 端点)搬到 image_routes.py。双份回报:缩 server + characterization 兼移动 parity N4-N8 oracle。
# 索引/vision/cutout helper(_load/_save_attachments_index/_index_attachment/_gemini_classify_image/
# _get_or_create_processed_attachment/io-map)留 server(chat_routes 也共用),image lazy from server import。
from image_routes import router as _image_router  # noqa: E402
app.include_router(_image_router)

# Extract Module(ctrl-c-v § 9):MD/schema 迁移编排 glue(横幅状态机 + SSE + 启动 hook +
# legacy rewriter,17 区 ~470 行)搬到 migration_routes.py。engine 早已外置 migration_plan.py。
# _VAULT_REFERENCE_TARGETS(lambda 闭包绑 server 全局)留 server;migration_routes lazy from server import。
# re-export 三个 startup 函数 → server @app.on_event startup hook 的裸名调用(create_task 等)仍 resolve。
from migration_routes import router as _migration_router  # noqa: E402
from migration_routes import (  # noqa: E402,F401
    _ensure_vault_reference_files, _run_schema_migration_if_needed, _startup_v0125_md_migration,
)
app.include_router(_migration_router)


# ── UI 文件禁缓存:WKWebView 会按 URL 缓存 html/js/css,改了代码不 bump ?v= 就吃旧版
# (2026-06-15 踩过:补建逻辑改了、重构建了,WebView 还服务 Build-1 缓存的旧 JS)。
# local-first app 文件本就在盘上,no-store 零成本换"永远拉新"。字体 woff2 不在此列,照常缓存。
@app.middleware("http")
async def _no_cache_ui(request, call_next):
    resp = await call_next(request)
    p = request.url.path
    if p == "/" or p.endswith((".html", ".js", ".css")):
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


# ── 自动建当天文件:启动 + 每分钟轮询(过 02:00 且文件缺) ──
AUTO_CREATE_AFTER_HOUR = 2  # 02:00 之后才建,避免半夜熬夜还在写昨天的日记被切

def _silent_run_new_day(today_iso=None):
    """跑 scripts/new-day.sh,不抛错(后台任务用)。已存在视为成功。"""
    script = CODE_ROOT / "scripts" / "new-day.sh"
    if not script.exists():
        return
    cmd = ["bash", str(script)]
    if today_iso:
        cmd.append(today_iso)
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except Exception:
        pass

def _today_journal_missing() -> bool:
    return find_today_journal() is None

@app.on_event("startup")
async def _startup_auto_create():
    """server 启动时:若当前时间 ≥ 02:00 且今天文件缺,补建一次。
    再起一个后台 task,每 60 秒检查一次,过点自动建。
    """
    now = datetime.now()
    if now.hour >= AUTO_CREATE_AFTER_HOUR and _today_journal_missing():
        _silent_run_new_day()
    asyncio.create_task(_auto_create_loop())


@app.on_event("startup")
async def _startup_vault_reference_and_migration():
    """启动时:
    ① 确保 vault 里 reference 文件存在,缺则从 bundle 拷(byte-equal 不动已有)
    ② bundle schema-version 比 vault 高 → 后台 async LLM 重组 vault 文件
    ③ Rust updater 上次留下的 pending 通知(sidecar 没起来时落的)→ 自补
    """
    try:
        _ensure_vault_reference_files()
    except Exception as e:
        log.warning(f"_ensure_vault_reference_files: {e}")
    # 迁移走 async background,LLM call 不阻塞 startup
    asyncio.create_task(_run_schema_migration_if_needed())
    # v0.1.25 起:LLM 弹性 MD 迁移(scope 不预设);走 /api/migration/stream SSE 通报进度
    asyncio.create_task(_startup_v0125_md_migration())
    # 接 Rust updater 落的 pending(review #18)
    try:
        _consume_updater_pending()
    except Exception as e:
        log.warning(f"_consume_updater_pending: {e}")
    # 接上轮没消费的持久化 notification(workflow #17)
    try:
        _consume_pending_notifications()
    except Exception as e:
        log.warning(f"_consume_pending_notifications: {e}")
    # B-#6: 把 silent-failure 通道挂进 library 模块(ocr.py / cutout.py),
    # 避免它们 silent swallow 网络/quota 失败 — 5.29 加的 37 hooks 全在 server.py,
    # 没覆盖 library 层。注入 callable 走 import-time 避免循环依赖。
    try:
        from ocr import set_failure_sink as _ocr_set_sink
        _ocr_set_sink(_report_silent_failure)
    except Exception as e:
        log.warning(f"ocr set_failure_sink: {e}")
    try:
        from cutout import set_failure_sink as _cutout_set_sink
        _cutout_set_sink(_report_silent_failure)
    except Exception:
        pass  # cutout 可能还没装上报针脚,先 best-effort
    try:
        from cutout_local import set_failure_sink as _cutout_local_set_sink
        _cutout_local_set_sink(_report_silent_failure)
    except Exception as e:
        log.warning(f"cutout_local set_failure_sink: {e}")


def _consume_updater_pending():
    """Rust updater 在 sidecar 没起来时落 ~/.human-ai/.updater-pending.json。
    sidecar 启动时读它 → push notification → 消费后删文件。
    A-H4: unlink 挪出 try — 损坏的 pending 也得删掉,否则永远卡 banner。
    """
    pending = Path.home() / ".human-ai" / ".updater-pending.json"
    if not pending.exists():
        return
    pushed = False
    try:
        data = json.loads(pending.read_text(encoding="utf-8"))
        version = data.get("version") or "新版"
        _push_notification(
            "updater-installed",
            f"Gateway {version} 已下载,重启 app 生效",
            {"version": version, "source": "pending-file"},
        )
        log.info(f"消费 updater pending 文件 -> notification: v{version}")
        pushed = True
    except Exception as e:
        # 损坏文件 — 不再 push,但仍 unlink 解卡
        log.warning(f"读 updater pending 失败(损坏文件): {e}")
        _report_silent_failure(
            "updater_pending_corrupt",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"op": "consume_updater_pending"},
        )
    # 无论 push 成不成功都把文件 unlink 掉(损坏的不删 = 每次启动都报 + 永远卡 banner)
    try:
        pending.unlink()
    except Exception:
        pass
    _ = pushed  # 留一个变量调试时看


# ─── v0.1.25 MD 迁移 SSE 通道 (T-C) ────────────────────────────────
# 跟旧 _run_schema_migration_if_needed 的 schema-version 机制并存:那个是
# 单文件 marker 驱动;这个是 LLM 弹性扫描所有 MD,scope 不预设。前端 banner
# 监听 /api/migration/stream 实时显 Step 3 进度。
#
# 设计:
#   _migration_log    缓存所有已发生的事件,新 client 接入立即 replay
#   _migration_consumers 当前监听的 SSE 客户端队列,broadcast 推新事件
#   _migration_done   true 后 SSE 自动 close
#
# 异步 lock 必须懒构(asyncio.Lock 绑当前 loop),所以走 _migration_lock_get()。


# ─── v0.1.25 MD 迁移 LLM 客户端 + startup hook (T-E) ─────────────────
# 走 get_client() / get_model() 复用主聊天链(单 API 入口铁律)。
# 没配置 key → factory 返 None → startup 跳过迁移(graceful)。
# 同步 OpenAI client 用 asyncio.to_thread 包成 async,不阻 event loop。


async def _auto_create_loop():
    while True:
        try:
            now = datetime.now()
            if now.hour >= AUTO_CREATE_AFTER_HOUR and _today_journal_missing():
                _silent_run_new_day()
        except Exception:
            pass
        await asyncio.sleep(60)


@app.get("/api/config-status")
def config_status():
    cfg = load_config()
    if not cfg:
        return {"ok": False, "reason": "no .gateway-config.json"}
    if not cfg.get("api_key") or cfg["api_key"].startswith("YOUR_"):
        return {"ok": False, "reason": "api_key not set"}
    if OpenAI is None:
        return {"ok": False, "reason": "openai package not installed (pip install openai)"}
    return {"ok": True, "model": get_model(), "provider": cfg.get("base_url", "https://api.deepseek.com/v1")}


# ── attachments 索引 + 文件管理 ──────────────────────────────────────
# 每次上传 → 后台 OCR → 写 _index.json
# AI 工具能 list / search / delete,做"持续文件管理"
ATTACHMENTS_INDEX = ATTACHMENTS_DIR / "_index.json"
# Curator 子 agent 的 frozen system prompt — 月分块 (老月在前)。
# 写在 upload 路径 (_index_upsert),读在 ask_photo_curator tool。
# 分离文件而非内存:多 worker / restart 后立即可用。
CURATOR_SYSTEM_PATH = ATTACHMENTS_DIR / "_curator_system.txt"


def _load_attachments_index() -> list:
    if not ATTACHMENTS_INDEX.exists():
        return []
    try:
        return json.loads(ATTACHMENTS_INDEX.read_text(encoding="utf-8"))
    except Exception as e:
        _report_silent_failure("attachments_index_parse_failed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"file_size_kb": ATTACHMENTS_INDEX.stat().st_size // 1024})
        return []


def _save_attachments_index(arr: list):
    # A-H1: atomic + rotate;BackgroundTasks 跟 _index_upsert 是已知并发路径
    _safe_write_text(
        ATTACHMENTS_INDEX,
        json.dumps(arr, indent=2, ensure_ascii=False),
        rotate=True,
    )


# ── Curator system prompt 重建 ──────────────────────────────────────
# 月分块 + 老月在前 = DeepSeek implicit prefix cache 友好。
# 加 1 张新图只 invalidate 当月段以后(几乎全部历史月份 hit)。
# 行格式 CSV-like 压缩(~30 token/张 vs JSON ~100):date|stem|kind|desc

def _format_curator_line(x: dict) -> str:
    date = x.get("date", "")
    fn = x.get("filename", "")
    stem = fn.rsplit(".", 1)[0] if "." in fn else fn
    v = x.get("vision") or {}
    kind = (v.get("kind", "") or "?").replace("|", " ")
    desc = (v.get("description", "") or "").replace("\n", " ").replace("|", " ")[:80]
    # 没 vision 时 ocr 兜 — curator 找截图里的字也需要
    if not desc:
        ocr = (x.get("ocr_text", "") or "").replace("\n", " ").replace("|", " ")[:40]
        if ocr:
            desc = f"ocr:{ocr}"
    return f"{date}|{stem}|{kind}|{desc}"


def _rebuild_curator_system_prompt():
    """读全部索引 → 按 YYYY-MM 分块 (老月在前) → 写 frozen system prompt 文件。
    在 _index_upsert 里调一次 (upload / vision 完成时)。chat 时只读文件,不重建。
    """
    arr = _load_attachments_index()
    by_month: dict = {}
    for x in arr:
        m = (x.get("date", "") or "")[:7]
        if not m:
            continue
        by_month.setdefault(m, []).append(x)

    lines = [
        "你是相册管理员 (curator)。下面是用户全部照片元数据,每行格式:",
        "date | filename_stem | kind | description",
        "",
        "任务: 用户问什么,你只返匹配的 stem 列表,date 拼接成 'YYYY-MM-DD/stem'。",
        '严格 JSON: {"matches":["2026-05-16/115227-6002ea", ...],"total":N,"note":""}',
        "结果 > 15 时按时间倒序截到 15,note 写 'truncated, total=N'。无匹配返 matches=[]。",
        "不解释。不复述描述。不评论。**仅 JSON**。",
        "",
        "跨 terminology 推理: '狗'='哈士奇'='茅茅' (用户家狗) 等需要从 description 推出来。",
        "",
    ]
    for month in sorted(by_month.keys()):  # 老在前 = cache 友好
        photos = sorted(by_month[month], key=lambda x: (x.get("date", ""), x.get("filename", "")))
        lines.append(f"--- {month} ({len(photos)} 张) ---")
        for x in photos:
            lines.append(_format_curator_line(x))
        lines.append("")
    txt = "\n".join(lines)
    try:
        # A-H1: curator prompt 可重建,rotate=False(节省 IO)
        _safe_write_text(CURATOR_SYSTEM_PATH, txt, rotate=False)
    except Exception as e:
        _report_silent_failure("curator_system_rebuild_failed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"entries": len(arr)})


# Lock + upsert 化解 race:后台 OCR task 和 chat 触发的 vision call 都要写索引,
# 各自 load → mutate → save 会互相覆盖(后写的赢)— 现象:OCR 覆盖了 vision,
# 或反过来。upsert 只 merge 显式传的字段,不动其他;lock 串行化 read-modify-write。
import threading as _threading
_attachments_index_lock = _threading.Lock()


def _find_by_hash(sha256_hex: str):
    """同字节 upload 去重的关键:扫 index 查 hash。命中返既有 record,没命中返 None。
    O(N) 扫;index 体量 < 几百条,无需建额外索引。
    """
    if not sha256_hex:
        return None
    for x in _load_attachments_index():
        if x.get("hash") == sha256_hex:
            return x
    return None


def _index_upsert(date: str, filename: str, **fields):
    """Find-or-create by (date, filename),只 merge 传进来的字段;不动其余。
    在 lock 下做完整 read-modify-write 防并发覆盖。
    """
    with _attachments_index_lock:
        arr = _load_attachments_index()
        idx = next((i for i, x in enumerate(arr)
                    if x.get("date") == date and x.get("filename") == filename), -1)
        if idx < 0:
            arr.append({"date": date, "filename": filename, **fields})
        else:
            arr[idx].update(fields)
        _save_attachments_index(arr)
        # 同步刷新 curator system prompt — 几 ms 字符串拼接,值得为 cache 友好换
        _rebuild_curator_system_prompt()


# ── OCR dispatcher + 文本工具 ─ 抽到 ocr.py(行为零变化,仅搬迁) ──
# _ocr_text / _strip_ocr_from_history / _parse_pill_count_from_ocr 三个 helper +
# 配套 _OCR_BLOCK_RE / _OCR_FILENAME_RE / _PILL_COUNT_RE 三个正则 一起搬到 ocr.py。
# silent-failure 走 ocr 模块自己的 _emit_failure(server.py 启动时已注入 sink)。
from ocr import (
    _ocr_text, _strip_ocr_from_history, _parse_pill_count_from_ocr,
    _OCR_BLOCK_RE, _OCR_FILENAME_RE, _PILL_COUNT_RE,
)


def _index_attachment(date: str, filename: str, original: str, size: int, sha256_hex: str = ""):
    """后台跑 OCR + 写索引。失败也不抛(索引降级)。
    vision 分类不在这里跑(成本考虑):upload 即跑 vision 对"上传多但不讨论"
    场景白花钱。lazy 策略 — chat 时 _refs_to_vision_hints 现场 sync call 一次
    + 回写索引,后续命中 cache。
    sha256_hex 由 upload 入口算好传进来,用于后续 _find_by_hash 同字节去重。
    """
    f = ATTACHMENTS_DIR / date / filename
    ocr_text = ""
    try:
        ocr_text = _ocr_text(f)
    except Exception as e:
        log.warning(f"index OCR failed for {filename}: {e}")
    fields = {
        "original": original,
        "size": size,
        "ocr_text": ocr_text[:2000],
        "url": f"/attachments/{date}/{filename}",
    }
    if sha256_hex:
        fields["hash"] = sha256_hex
    # upsert 而非 append:若 vision call 先到、已建好 entry,这里只补 OCR / 元数据,
    # 不动已有的 vision 字段(原来 append + skip-if-exists 的逻辑碰上 race 会丢 vision)
    _index_upsert(date, filename, **fields)


# ── sliding-window summarization (B 包) ──────────────────────────────
RECENT_KEEP = 20            # 最近 N 条原文保留
SUMMARY_MIN_OLD = 5         # 旧消息少于这个数量不触发摘要
_SUMMARY_CACHE: dict = {}   # hash → summary string
_SUMMARY_CACHE_MAX = 64

def _summarize_history(old_messages: list, client, model: str) -> str:
    """把超过 RECENT_KEEP 的旧消息压成 1 段摘要。
    cache by sha256 of concatenated content,避免每轮重算。
    失败返空字符串(调用方 fallback 到不摘要直接发)。
    """
    if not old_messages:
        return ""
    chunk = "\n".join(f"[{m.get('role')}] {m.get('content','')}" for m in old_messages)
    key = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
    if key in _SUMMARY_CACHE:
        return _SUMMARY_CACHE[key]

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content":
                    "你把对话历史压成 1 段中文摘要(~150 字)。"
                    "保留:用户的目标 / 决定 / 关键事实 / 待办。"
                    "丢掉:寒暄 / 流程细节 / 工具名 / 文件路径。"
                    "只输出摘要本身,不加前缀。"},
                {"role": "user", "content": f"压缩以下对话:\n\n{chunk}\n\n摘要:"},
            ],
            max_tokens=400,
        )
        summary = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.warning(f"summary failed: {type(e).__name__}: {e}")
        return ""

    if len(_SUMMARY_CACHE) >= _SUMMARY_CACHE_MAX:
        _SUMMARY_CACHE.pop(next(iter(_SUMMARY_CACHE)))
    _SUMMARY_CACHE[key] = summary
    return summary


# _OCR_BLOCK_RE / _OCR_FILENAME_RE 已搬到 ocr.py(顶部 from ocr import 进来)


# _strip_ocr_from_history 已搬到 ocr.py(顶部 from ocr import 进来)


# ── journal parser ───────────────────────────────────────────────────
TIME_H1_RE = re.compile(r'^# (\d{1,2})[：:](\d{2})\s*$')

# PATTERN: util — authorship boundary marker parse
# USE WHEN: any tool that patches existing H2 needs to check who owns it
# COPY THIS: marker syntax is `@user` / `@ai`(行内任何位置都认)
_AUTHOR_RE = re.compile(r"@(user|ai)\b")

def _check_author(h2_line: str) -> str:
    """parse '## #tag title @user' → 'user' / 'ai'。
    无 marker → 'user'(失败安全:旧 entry 默认受保护,AI 不能改)。"""
    m = _AUTHOR_RE.search(h2_line or "")
    return m.group(1) if m else "user"

def find_today_journal(today=None):
    today = today or datetime.now()
    # filename pattern: 26.5.12(第十天).md  → prefix 26.5.12
    prefix = f"{str(today.year)[-2:]}.{today.month}.{today.day}"
    matches = list(JOURNAL_DIR.glob(f"{prefix}*.md"))
    return matches[0] if matches else None

def parse_journal(text):
    """parse a 半小时复盘 md into [{time, h2s: [{tags, title, body, commits}]}]
    Empty blocks (no h2 content) filtered.
    Sorted chronologically by time.
    """
    blocks = []
    cur = None
    for line in text.splitlines():
        m = TIME_H1_RE.match(line)
        if m:
            if cur:
                blocks.append(cur)
            cur = {"time": f"{int(m.group(1)):02d}:{m.group(2)}",
                   "h1_raw": f"{int(m.group(1))}：{m.group(2)}",
                   "raw": []}
            continue
        if cur is None:
            continue
        cur["raw"].append(line)
    if cur:
        blocks.append(cur)

    for b in blocks:
        h2s = []
        ch = None
        for line in b["raw"]:
            if line.startswith("## "):
                if ch:
                    h2s.append(ch)
                content = line[3:].strip()
                tags = re.findall(r'#(\S+)', content)
                title = re.sub(r'#\S+\s*', '', content).strip()
                ch = {"tags": tags, "title": title, "body_lines": [], "commits": []}
                continue
            if ch is None:
                continue
            if line.strip() == "---":
                continue  # block separator residue — never part of any h2 body
            if re.match(r'^\s*-\s*#commit', line) or "#commit" in line[:30]:
                ch["commits"].append(line.strip())
            else:
                ch["body_lines"].append(line)
        if ch:
            h2s.append(ch)
        for h in h2s:
            h["body"] = "\n".join(h["body_lines"]).strip()
            del h["body_lines"]
        b["h2"] = h2s
        del b["raw"]

    # 留下:任一 h2 有 tag/title/body/commits 中任意一个。
    # 模板预创建的裸 ## 仍被过滤,但 insert-block 写的 ## #新 (有 tag) 会留下。
    blocks = [b for b in blocks if b["h2"] and any(
        h["tags"] or h["title"] or h["body"] or h["commits"] for h in b["h2"]
    )]
    blocks.sort(key=lambda b: b["time"])
    return blocks

def _list_journal_files():
    """List all schedule MD files, parse date stem (26.M.D), sort chronologically."""
    if not JOURNAL_DIR.exists():
        return []
    items = []
    for f in JOURNAL_DIR.glob("*.md"):
        m = re.match(r'^(\d{2})\.(\d{1,2})\.(\d{1,2})', f.stem)
        if not m:
            continue
        yy, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        iso = f"20{yy:02d}-{mm:02d}-{dd:02d}"
        items.append({"date": iso, "stem": f.stem, "file": _pretty_rel(f)})
    items.sort(key=lambda x: x["date"])
    return items

def _journal_for_date(date_iso=None):
    """Render payload for a specific date (YYYY-MM-DD). None = today."""
    if date_iso:
        try:
            target = datetime.strptime(date_iso, "%Y-%m-%d")
        except ValueError:
            return {"error": f"bad date format: {date_iso}"}
    else:
        target = datetime.now()
    f = find_today_journal(target)
    if not f:
        return {"error": f"no journal file for {target.strftime('%Y-%m-%d')}"}
    return {
        "file": _pretty_rel(f),
        "date": target.strftime("%Y-%m-%d"),
        "blocks": parse_journal(f.read_text(encoding="utf-8")),
    }

@app.post("/api/quit")
def quit_gateway():
    """优雅退出。bundled .app 时(LSUIElement=true 无 Dock 图标)是用户唯一的"退出"出口。
    先返响应,delay 后 os._exit(避免 uvicorn 抢在 response 前关连接)。"""
    def _shutdown():
        import time as _t
        _t.sleep(0.4)
        os._exit(0)
    threading.Thread(target=_shutdown, daemon=True).start()
    return {"ok": True, "message": "gateway shutting down"}


@app.post("/api/abort")
def abort_worker():
    """panic 按钮:worker hang 时强制重启。
    实现细节:--reload 模式下 uvicorn parent 不会 respawn 崩溃的 worker
    (只响应文件变化)。所以这里 touch 自己一下触发 file watcher,然后再 exit。
    跟 /api/quit 区别:quit 干掉整个 server;abort 只杀当前 worker,几秒自愈。"""
    server_file = Path(__file__)
    def _kill():
        import time as _t
        _t.sleep(0.3)
        # 1) touch 触发 uvicorn file watcher → 它会准备 spawn 新 worker
        server_file.touch()
        _t.sleep(0.2)
        # 2) 再 exit 让当前(hung)worker 死掉,新 worker 接管
        os._exit(1)
    threading.Thread(target=_kill, daemon=True).start()
    return {"ok": True, "message": "worker aborting; server will respawn in ~2s"}


@app.get("/api/user-widgets")
def get_user_widgets():
    """返 user-widgets.json 内容。前端 widget-loader.js 用。
    历史前端走 GET /.user-widgets.json 静态文件,搬到 APP_STATE_DIR 后改走这里。"""
    if not USER_WIDGETS_PATH.exists():
        return {"active": []}
    try:
        return json.loads(USER_WIDGETS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"active": []}


# "第N天" baseline:新用户用自己 vault 里最早的 schedule 日为 day-one,
# 没有 schedule 文件就是当天 = 第一天。葱鸭自己的 vault 最早是 26.5.3,所以
# 他的 day-one 仍是 5.3,backward compat;陌生新用户装机当天就是第一天。
# 也可以在 .gateway-config.json 里写 "vault_day_one": "YYYY-MM-DD" 显式覆盖。
_DAY_CN = ["零","一","二","三","四","五","六","七","八","九","十",
           "十一","十二","十三","十四","十五","十六","十七","十八","十九","二十",
           "二十一","二十二","二十三","二十四","二十五","二十六","二十七","二十八","二十九","三十"]


def _get_day_one(today_iso: str) -> datetime:
    """动态算 day-one。优先级:config 显式 > vault 最早 schedule > 今天。"""
    cfg = load_config() or {}
    explicit = cfg.get("vault_day_one")
    if explicit:
        try:
            return datetime.strptime(explicit, "%Y-%m-%d")
        except ValueError:
            pass  # bad format → 走 fallback
    # 扫 vault 最早 schedule 文件
    try:
        days = _list_journal_files()
        if days:
            earliest_iso = days[0].get("date", today_iso)
            return datetime.strptime(earliest_iso, "%Y-%m-%d")
    except Exception:
        pass
    # 兜底:今天就是第一天
    return datetime.strptime(today_iso, "%Y-%m-%d")


def _new_day_create(date_iso: str) -> dict:
    """Python 原生 new-day(替代 scripts/new-day.sh;frozen 模式下脚本不在,改这里)。
    返 {ok, created, file, message}。已存在返 created=False。"""
    try:
        target = datetime.strptime(date_iso, "%Y-%m-%d")
    except ValueError:
        return {"ok": False, "error": f"bad date: {date_iso}"}
    day_one = _get_day_one(date_iso)
    day_num = (target - day_one).days + 1
    day_cn = _DAY_CN[day_num] if 0 <= day_num <= 30 else str(day_num)
    yy = target.strftime("%y")
    mm = target.month  # 不补零
    dd = target.day
    filename = f"{yy}.{mm}.{dd}(第{day_cn}天).md"
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    filepath = JOURNAL_DIR / filename
    if filepath.exists():
        return {"ok": True, "created": False, "file": _pretty_rel(filepath),
                "message": f"already exists: {filename}"}
    # 顶部 daily-task section:从 vault/daily-tasks.md 第一个 --- 前抓
    daily_tasks_src = VAULT_DIR / "daily-tasks.md"
    if daily_tasks_src.exists():
        src = daily_tasks_src.read_text(encoding="utf-8")
        top = []
        for line in src.splitlines():
            if line.strip() == "---":
                break
            top.append(line)
        top_section = "\n".join(top).rstrip()
    else:
        top_section = (
            "# 每日打卡\n\n"
            "<!-- 在 vault/daily-tasks.md 加你自己的 - [ ] 项目(喝水 / 运动 / 阅读 / 冥想 / 补剂...) -->\n"
            "<!-- 不想要这段?设置 → 插件市场 → 关闭每日打卡 -->\n\n"
            "- [ ] (添加你的第一个打卡项)"
        )
    # 时间格(7:30 - 23:00,半小时一块,7:00 没有)
    parts = [top_section, "\n---"]
    for h in range(7, 23):
        for m in ("00", "30"):
            if h == 7 and m == "00":
                continue
            parts.append(f"\n# {h}：{m}\n\n##\n\n---")
    parts.append("\n# 23：00\n\n##\n")
    filepath.write_text("\n".join(parts), encoding="utf-8")
    return {"ok": True, "created": True, "file": _pretty_rel(filepath),
            "message": f"created: {filename}"}


# ── scrapbook (手账浮层照片) ─────────────────────────────────────────
# 每天一个 json: data/scrapbook/{YYYY-MM-DD}.json
# 数组: [{id, src, x, y, w, h, rotation, anchor_time, z}]
# - src 是相对 / 开头的 url(/data/scrapbook-images/xxx.png 或 /attachments/yyy)
# - x,y 是相对 stream 容器左上的 px(整数)
# - rotation 是度数(可负)
# - anchor_time 是 "HH:MM" 字串,用于"贴在哪个时间块附近"的语义锚点
SCRAPBOOK_DIR = DATA_DIR / "scrapbook"
SCRAPBOOK_IMAGES_DIR = DATA_DIR / "scrapbook-images"


# scrapbook 4 helper 已搬到 scrapbook.py(行为零变化),endpoint 留下面
from scrapbook import _scrapbook_path, _load_scrapbook, _save_scrapbook, _scrapbook_id


@app.get("/api/scrapbook")
def scrapbook_get(date: str):
    """取某天的 scrapbook items。无则空数组。"""
    return {"date": date, "items": _load_scrapbook(date)}


@app.post("/api/scrapbook/upsert")
async def scrapbook_upsert(req: Request):
    """新增 / 更新一项 (传 id 表示更新)。v3:用 x_pct/y_px;兼容旧 x/y/align 写入也保留(读端会迁移)。
    body: {date, id?, src, x_pct, y_px, w, h, rotation?, anchor_time?, z?, align?, x?, y?}
    返:{ok, item}
    """
    body = await req.json()
    date = (body.get("date") or "").strip()
    if not date:
        raise HTTPException(400, "need date")
    items = _load_scrapbook(date)
    if body.get("id"):
        # update — 新老字段都接,客户端写啥保留啥
        idx = next((i for i, x in enumerate(items) if x.get("id") == body["id"]), -1)
        if idx < 0:
            raise HTTPException(404, f"id {body['id']} not found")
        item = items[idx]
        for k in ("src", "x_pct", "y_px", "w", "h", "rotation", "anchor_time", "z", "align", "x", "y"):
            if k in body:
                item[k] = body[k]
        # 用户拖完后传上来的 y_px 是真实值 → 清掉 auto_y,
        # 之后 reload 不再用 anchor 重算覆盖用户的拖拽
        if "y_px" in body:
            item["auto_y"] = False
        items[idx] = item
    else:
        # create — 新数据默认用 x_pct/y_px;legacy 字段不再写
        item = {
            "id": _scrapbook_id(),
            "src": body.get("src", ""),
            "x_pct": float(body.get("x_pct", 75)),
            "y_px": float(body.get("y_px", 0)),
            "w": int(body.get("w", 200)),
            "h": int(body.get("h", 200)),
            "rotation": float(body.get("rotation", 0)),
            "anchor_time": body.get("anchor_time", ""),
            "z": int(body.get("z", 1)),
        }
        items.append(item)
    _save_scrapbook(date, items)
    return {"ok": True, "item": item}


@app.post("/api/scrapbook/delete")
async def scrapbook_delete(req: Request):
    body = await req.json()
    date = (body.get("date") or "").strip()
    item_id = (body.get("id") or "").strip()
    if not date or not item_id:
        raise HTTPException(400, "need date + id")
    items = _load_scrapbook(date)
    items = [x for x in items if x.get("id") != item_id]
    _save_scrapbook(date, items)
    return {"ok": True, "removed": item_id}


# ── daily-task images (个人化打卡图) ──────────────────────────────────
DAILY_TASK_IMAGES_DIR = DATA_DIR / "daily-task-images"
DAILY_TASK_IMAGES_MAP = DATA_DIR / "daily-task-images.json"
DAILY_TASK_META_MAP = DATA_DIR / "daily-task-meta.json"

# _PILL_COUNT_RE / _parse_pill_count_from_ocr 已搬到 ocr.py(顶部 from ocr import 进来)


def _sanitize_task_filename(name: str) -> str:
    """task name → 文件名安全的 stem。'鱼油（Swisse）' → '鱼油_Swisse_'"""
    safe = re.sub(r"[^\w一-鿿]+", "_", name).strip("_")
    return safe or "task"


# ── 图像处理 dispatcher ─ 抽到 cutout.py(行为零变化,仅搬迁) ──
# 历史:此处原是 ~73 行 attachment → 端侧/百度/原图 三层 dispatcher。
# 现在:见 cutout.py。silent-failure 走 cutout 模块自己的 _emit_failure(server 启动时
# 已注入 sink,L2984-2985)。外部依赖(ATTACHMENTS_DIR/load_config)函数体内 lazy import。
from cutout import _cutout_keys, _get_or_create_processed_attachment


def _load_task_image_map() -> dict:
    if not DAILY_TASK_IMAGES_MAP.exists():
        return {}
    try:
        return json.loads(DAILY_TASK_IMAGES_MAP.read_text(encoding="utf-8"))
    except Exception as e:
        # P0:parse 失败 silently 返 {} 会被后续 save 覆盖,损坏可恢复文件 → 数据丢
        # 短期上报让 dashboard 看到;长期考虑 refuse_to_save guard。
        _report_silent_failure("task_image_map_parse_failed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"file_size_kb": DAILY_TASK_IMAGES_MAP.stat().st_size // 1024 if DAILY_TASK_IMAGES_MAP.exists() else 0})
        return {}


def _save_task_image_map(m: dict):
    _safe_write_text(
        DAILY_TASK_IMAGES_MAP,
        json.dumps(m, indent=2, ensure_ascii=False),
        rotate=True,  # 5 份滚动备份 — 误删 / 改名漂移可 rollback
    )


def _load_task_meta_map() -> dict:
    if not DAILY_TASK_META_MAP.exists():
        return {}
    try:
        return json.loads(DAILY_TASK_META_MAP.read_text(encoding="utf-8"))
    except Exception as e:
        # P0:同上 — intake_log 不可再生数据,parse 失败要响铃
        _report_silent_failure("task_meta_map_parse_failed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"file_size_kb": DAILY_TASK_META_MAP.stat().st_size // 1024 if DAILY_TASK_META_MAP.exists() else 0})
        return {}


def _save_task_meta_map(m: dict):
    _safe_write_text(
        DAILY_TASK_META_MAP,
        json.dumps(m, indent=2, ensure_ascii=False),
        rotate=True,  # 5 份备份 — intake_log 历史是宝贵的不可重生数据
    )


def _today_date_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# 补卡窗口 — 今天总在;次日 12:00 前还能补昨天。
# 用户语:"至少到第二天 12 点前可以补吧"(5.31 凌晨补 5.30 打卡)。
# 12 点是宽容线,过了就让数据保持当时的样子,别再倒填污染。
def _writable_dates_set() -> set:
    out = {_today_date_str()}
    now = datetime.now()
    if now.hour < 12:
        out.add((now - timedelta(days=1)).strftime("%Y-%m-%d"))
    return out


def _task_meta_state(name: str, meta_map: dict, target_date=None) -> dict:
    """单 task 的剂量/库存状态。无 meta 返默认。
    target_date=None → 今天 intake;target_date=datetime → 该日 intake。
    """
    m = meta_map.get(name) or {}
    total_pills = m.get("total_pills")  # int | None
    daily_dose = int(m.get("daily_dose") or 1)
    if daily_dose < 1:
        daily_dose = 1
    intake_log = m.get("intake_log") or {}
    date_key = (target_date.strftime("%Y-%m-%d") if target_date is not None
                else _today_date_str())
    today_intake = int(intake_log.get(date_key, 0) or 0)
    consumed = sum(int(v or 0) for v in intake_log.values())
    remaining = (total_pills - consumed) if isinstance(total_pills, int) else None
    return {
        "total_pills": total_pills,
        "daily_dose": daily_dose,
        "today_intake": today_intake,
        "remaining": remaining,
    }


def _bump_intake(name: str, delta: int = 1, set_to=None, for_date=None) -> dict:
    """改 intake_log[date_key]。delta 累加,set_to 直接置数(优先 set_to)。
    for_date=None → 今天;datetime → 该日。补卡窗口管控在 caller(_writable_dates_set)。
    返回该日的 meta state。
    """
    meta_map = _load_task_meta_map()
    entry = dict(meta_map.get(name) or {})
    daily_dose = int(entry.get("daily_dose") or 1)
    if daily_dose < 1:
        daily_dose = 1
    intake_log = dict(entry.get("intake_log") or {})
    date_key = (for_date.strftime("%Y-%m-%d") if for_date is not None
                else _today_date_str())
    cur = int(intake_log.get(date_key, 0) or 0)
    if set_to is not None:
        new = max(0, int(set_to))
    else:
        new = cur + int(delta)
    new = max(0, min(new, daily_dose))
    if new == 0:
        intake_log.pop(date_key, None)
    else:
        intake_log[date_key] = new
    entry["daily_dose"] = daily_dose
    entry["intake_log"] = intake_log
    meta_map[name] = entry
    _save_task_meta_map(meta_map)
    return _task_meta_state(name, meta_map, target_date=for_date)


def _read_daily_tasks_from_md(target_date=None) -> list:
    """从指定日 md 顶部读 daily task 清单 (- [ ] xxx 行,任意 checkbox 状态)。
    target_date=None → 今天(没今天 fallback 模板)。
    target_date=datetime → 该日;没文件返 []。
    返 [{name, checked}, ...]
    """
    if target_date is not None:
        f = find_today_journal(target_date)
        if not f:
            return []
        text = f.read_text(encoding="utf-8")
    else:
        f = find_today_journal()
        if not f:
            tpl = SCHEDULE_TEMPLATE_PATH if SCHEDULE_TEMPLATE_PATH.exists() else None
            if not tpl:
                return []
            text = tpl.read_text(encoding="utf-8")
        else:
            text = f.read_text(encoding="utf-8")
    bounds = _top_section_bounds(text)
    if bounds is None:
        return []
    start, end = bounds
    out = []
    for line in text.splitlines()[start:end]:
        # 只取顶层(无缩进)task。daily_dose>1 的 task 下挂的子 box 是进度刻度,不算独立 task。
        m = re.match(r"^-\s*\[([ x])\]\s*(.+)", line)
        if m:
            out.append({"name": m.group(2).strip(), "checked": m.group(1) == "x"})
    return out


def _ensure_md_progress_children(name: str, daily_dose: int, today_intake: int,
                                  target_date=None) -> bool:
    """daily_dose > 1 的 task,把 md 顶部该行下面挂 N 个进度子 box,前 today_intake 个 [x],其余 [ ]。
    幂等。
    target_date=None(默认):同时刷模板源 + 今天文件。
    target_date=datetime:只刷该日期对应的 md(用于历史回填,不动模板)。
    daily_dose <= 1 不做(单行就够,展开反而碍眼)。
    """
    if daily_dose < 2:
        return False
    changed = False
    targets = []
    if target_date is None:
        if SCHEDULE_TEMPLATE_PATH.exists():
            targets.append(SCHEDULE_TEMPLATE_PATH)
        today_f = find_today_journal()
        if today_f and today_f not in targets:
            targets.append(today_f)
    else:
        day_f = find_today_journal(target_date)
        if day_f:
            targets.append(day_f)
    for f in targets:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        bounds = _top_section_bounds(text)
        if not bounds:
            continue
        lines = text.splitlines()
        start, end = bounds
        # 找父行(顶层 only)
        parent_idx = None
        for i in range(start, end):
            m = re.match(r"^(-\s*\[)([ x])(\]\s*)(.+)$", lines[i])
            if m and m.group(4).strip() == name:
                parent_idx = i
                parent_m = m
                break
        if parent_idx is None:
            continue
        # 数已挂的子 box(紧随父行的缩进 - [ ] 行)
        child_end = parent_idx + 1
        while child_end < end and re.match(r"^\s+-\s*\[[ x]\]", lines[child_end]):
            child_end += 1
        # 目标:N 个子 box,前 K 个 [x],其余 [ ];父行根据"是否全勾"翻
        clamp_intake = max(0, min(today_intake, daily_dose))
        desired_children = [
            f"  - [{'x' if k <= clamp_intake else ' '}] {k}"
            for k in range(1, daily_dose + 1)
        ]
        parent_box = "x" if clamp_intake >= daily_dose else " "
        new_parent = f"{parent_m.group(1)}{parent_box}{parent_m.group(3)}{parent_m.group(4)}"
        existing_children = lines[parent_idx + 1:child_end]
        if lines[parent_idx] == new_parent and existing_children == desired_children:
            continue  # 已经 in sync
        new_lines = (
            lines[:parent_idx]
            + [new_parent]
            + desired_children
            + lines[child_end:]
        )
        _safe_write_text(
            f,
            "\n".join(new_lines) + ("\n" if text.endswith("\n") else ""),
            rotate=True,
        )
        changed = True
    return changed


def _set_md_checkbox(name: str, checked: bool, target_date=None) -> bool:
    """改 md 顶部 - [ ] / - [x]。找到返 True;没找到 False(不抛)。
    target_date=None → 今天;datetime → 该日(补卡用)。"""
    f = find_today_journal(target_date) if target_date is not None else find_today_journal()
    if not f:
        return False
    text = f.read_text(encoding="utf-8")
    bounds = _top_section_bounds(text)
    if not bounds:
        return False
    lines = text.splitlines()
    start, end = bounds
    box = "x" if checked else " "
    for i in range(start, end):
        m = re.match(r"(\s*-\s*\[)([ x])(\]\s*)(.+)", lines[i])
        if m and m.group(4).strip() == name:
            if m.group(2) == box:
                return True  # 已经是这个状态,no-op
            lines[i] = f"{m.group(1)}{box}{m.group(3)}{m.group(4)}"
            new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
            _safe_write_text(f, new_text, rotate=True)
            return True
    return False


# ── water cup image (8 杯水的个人化照片,跟 daily-task 共用 cutout 流) ──
WATER_CUP_KEY = "__water_cup__"  # 在 daily-task-images.json 里的保留 key

# ── vault audit + self-heal(防用户/AI 整理文件后映射失联)─────────────
def _audit_vault() -> dict:
    """扫所有"path-based 映射"是否还能落到真文件。
    返报告:{image_orphans, image_recoverable, meta_orphans, aggregate_broken_links}
    - image_orphans:image map 里 path 不存在 且 没找到同名 fallback → 真断
    - image_recoverable:path 不存在但 daily-task-images/ 内能找到同名文件 → 可自愈
    - meta_orphans:meta 有这个 task,但当前 daily-tasks.md + today.md 都没这一行
    - aggregate_broken_links:聚合页 row 的 link_target 找不到对应文件
    """
    report = {
        "image_orphans": [],
        "image_recoverable": [],
        "meta_orphans": [],
        "aggregate_broken_links": [],
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }

    # 1. images
    try:
        img_map = _load_task_image_map()
    except Exception:
        img_map = {}
    # 预扫描 daily-task-images 目录下所有 png(递归),建 basename → path 索引
    name_index = {}
    if DAILY_TASK_IMAGES_DIR.exists():
        for p in DAILY_TASK_IMAGES_DIR.rglob("*.png"):
            name_index.setdefault(p.name, []).append(p)
    for key, rel in img_map.items():
        target = PLATFORM_ROOT / rel
        if target.exists():
            continue
        # 尝试用 basename 找
        basename = Path(rel).name
        cands = name_index.get(basename, [])
        if cands:
            new_rel = _pretty_rel(cands[0])
            report["image_recoverable"].append({
                "task": key, "old_path": rel, "new_path": new_rel,
            })
        else:
            report["image_orphans"].append({"task": key, "path": rel})

    # 2. meta orphans:每个 meta key 必须能在当前活跃的 daily-task 列表里找到
    try:
        meta = _load_task_meta_map()
    except Exception:
        meta = {}
    active_names = set()
    for src in (SCHEDULE_TEMPLATE_PATH, find_today_journal()):
        if not src or not src.exists():
            continue
        try:
            text = src.read_text(encoding="utf-8")
            bounds = _top_section_bounds(text)
            if not bounds:
                continue
            for line in text.splitlines()[bounds[0]:bounds[1]]:
                m = re.match(r"^-\s*\[[ x]\]\s*(.+)", line)
                if m:
                    active_names.add(m.group(1).strip())
        except Exception:
            pass
    for key in meta:
        if key not in active_names:
            report["meta_orphans"].append({"task": key, "intake_log_days": len((meta[key] or {}).get("intake_log") or {})})

    # 3. 聚合页 row link 是否 404
    # 注意:markdown `[text](url)` 里 url 含未转义 `)` 会被截断 → link_target
    # 提前结束(如 `26.5.7(第五天` 没 .md)。fallback 重构:尝试 `path).md`。
    try:
        if TAG_AGGREGATE_PATH.exists():
            text = TAG_AGGREGATE_PATH.read_text(encoding="utf-8")
            for sec in _parse_tag_aggregate(text):
                for row in sec["rows"]:
                    link = row.get("link_target") or ""
                    if not link:
                        continue
                    path_part = link.split("#")[0]
                    if not path_part:
                        continue
                    target = VAULT_DIR / path_part
                    if target.exists():
                        continue
                    # fallback:截断 `).md` 重构
                    if not path_part.endswith(".md"):
                        alt = VAULT_DIR / (path_part + ").md")
                        if alt.exists():
                            continue
                    report["aggregate_broken_links"].append({
                        "tag": sec["tag"], "row_date": row.get("date_short"),
                        "row_time": row.get("time"), "link": link,
                    })
    except Exception:
        pass

    # total_drift 只算"真断"项:image_recoverable / image_orphans / meta_orphans。
    # aggregate_broken_links 报告但不计入(多半是 markdown 链接括号截断,iso_date
    # 解析仍正常,不影响 navigation)
    report["total_drift"] = (
        len(report["image_orphans"])
        + len(report["image_recoverable"])
        + len(report["meta_orphans"])
    )
    report["aggregate_broken_count"] = len(report["aggregate_broken_links"])
    return report


def _repair_vault() -> dict:
    """安全自动修:只动 image_recoverable(改 image map 指到新 path)。
    meta_orphans / aggregate_broken_links 留报告给用户决断,不自动碰。
    """
    report = _audit_vault()
    fixed_images = 0
    if report["image_recoverable"]:
        img_map = _load_task_image_map()
        for item in report["image_recoverable"]:
            img_map[item["task"]] = item["new_path"]
            fixed_images += 1
        _save_task_image_map(img_map)
    return {"fixed_images": fixed_images, "remaining": _audit_vault()}


@app.get("/api/vault/audit")
def vault_audit_get():
    return _audit_vault()


@app.post("/api/vault/repair")
def vault_repair():
    return _repair_vault()


# ── history API(给 history.html 前端用)──────────────────────────
# 数据源:vault git log + outcomes.json + thread-history.json,通过 history_exporter
# / outcome_tracker 计算。endpoint 永远现算(scale 小,不缓存)。
import history_exporter as _he
import outcome_tracker as _ot

def _active_repos():
    """返当前可用 repo 列表 [(source, path, outcomes_path), ...]。"""
    pulse_dir = APP_STATE_DIR / "pulse-mirror"
    out = []
    if (VAULT_DIR / ".git").exists():
        out.append(("vault", VAULT_DIR, DATA_DIR / "outcomes.json"))
    if pulse_dir.exists() and (pulse_dir / ".git").exists():
        out.append(("pulse", pulse_dir, DATA_DIR / "outcomes-pulse.json"))
    return out


@app.get("/api/history/stats")
def history_stats():
    """count + by_author + by_class + by_day(最近 30 天)+ by_source。"""
    from collections import Counter
    repos = _active_repos()
    if not repos:
        return {"error": "no git repos available"}
    by_author, by_class, by_day, by_source = Counter(), Counter(), Counter(), Counter()
    total = 0
    outcomes_computed_any = False
    for src, vpath, opath in repos:
        commits = _he.list_commits(vpath)
        outcomes_map = _ot.load_outcomes(opath).get("outcomes", {})
        if outcomes_map:
            outcomes_computed_any = True
        for c in commits:
            total += 1
            by_source[src] += 1
            by_author[_he.parse_author(c["subject"])] += 1
            by_day[c["ts"][:10]] += 1
            o = outcomes_map.get(c["hash"])
            if o:
                by_class[o.get("outcome_class") or "unknown"] += 1
    return {
        "total": total,
        "by_source": dict(by_source),
        "by_author": dict(by_author),
        "by_class": dict(by_class),
        "by_day": dict(sorted(by_day.items())[-30:]),
        "outcomes_computed": outcomes_computed_any,
    }


@app.get("/api/history/recent")
def history_recent(limit: int = 50):
    """最近 N commits brief。跨 repo 按 ts 排序,前端列表用。"""
    repos = _active_repos()
    if not repos:
        return {"error": "no git repos available"}
    all_brief = []
    for src, vpath, opath in repos:
        commits = _he.list_commits(vpath)
        outcomes_map = _ot.load_outcomes(opath).get("outcomes", {})
        for c in commits:
            o = outcomes_map.get(c["hash"], {})
            all_brief.append({
                "commit": c["hash"][:12],
                "full_hash": c["hash"],
                "source": src,
                "ts": c["ts"],
                "author": _he.parse_author(c["subject"]),
                "action": _he.strip_action_trailer(c["subject"]),
                "outcome_class": o.get("outcome_class"),
                "later_touch_count": o.get("later_touch_count", 0),
            })
    # ts 倒序(新在前)
    all_brief.sort(key=lambda r: r["ts"] or "", reverse=True)
    return {"commits": all_brief[: max(1, min(limit, 500))], "limit": limit}


@app.get("/api/history/commit/{commit_hash}")
def history_commit(commit_hash: str):
    """单 commit 完整(跨 repo 查找)。"""
    repos = _active_repos()
    if not repos:
        return {"error": "no git repos available"}
    for src, vpath, opath in repos:
        detail = _he.commit_detail(vpath, commit_hash)
        if detail["files"] or detail["diff"]:
            info = _he._run_git(["log", "-1", "--format=%aI%x09%s", commit_hash], vpath)
            parts = info.strip().split("\t", 1)
            ts = parts[0] if parts else ""
            subject = parts[1] if len(parts) > 1 else ""
            thread = _he.load_thread(_he.DEFAULT_THREAD_HISTORY)
            outcomes_map = _ot.load_outcomes(opath).get("outcomes", {})
            return _he.commit_to_row(vpath, {"hash": commit_hash, "ts": ts, "subject": subject},
                                     thread, outcomes=outcomes_map, source=src)
    return {"error": f"commit not found in any repo: {commit_hash}"}


@app.post("/api/history/rebuild")
def history_rebuild():
    """重新跑 outcome_tracker(每个 repo 各一份)+ history_exporter(multi-repo)。"""
    repos = []
    pulse_dir = APP_STATE_DIR / "pulse-mirror"
    if (VAULT_DIR / ".git").exists():
        repos.append(("vault", VAULT_DIR, DATA_DIR / "outcomes.json"))
    if pulse_dir.exists() and (pulse_dir / ".git").exists():
        repos.append(("pulse", pulse_dir, DATA_DIR / "outcomes-pulse.json"))
    if not repos:
        return {"error": "no git repos found (run /api/pulse/refresh-mirror first?)"}

    outcome_counts = {}
    for src, vpath, opath in repos:
        data = _ot.compute_all(vpath)
        _ot.save_outcomes(data, opath)
        outcome_counts[src] = data["count"]

    r = _he.export(repos=repos)
    return {"outcomes_counts": outcome_counts, "export": r}


# ── consent / licensing(数据卖给谁 + 挑哪几个 source/tag)──────────
# MVP:存 license config + 给 filter 算 preview count。不真生成 export bundle
# (那是 Phase 2 + 加密签名)。consent.html 前端用这 4 个 endpoint。
CONSENT_LICENSES_PATH = DATA_DIR / "consent-licenses.json"


def _load_licenses() -> list[dict]:
    if not CONSENT_LICENSES_PATH.exists():
        return []
    try:
        return json.loads(CONSENT_LICENSES_PATH.read_text(encoding="utf-8")).get("licenses", [])
    except Exception:
        return []


def _save_licenses(licenses: list[dict]) -> None:
    CONSENT_LICENSES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _safe_write_text(
        CONSENT_LICENSES_PATH,
        json.dumps({"licenses": licenses}, ensure_ascii=False, indent=2),
        rotate=True,
    )


def _matches_filters(row: dict, f: dict) -> bool:
    """row 是 history_exporter 出的 jsonl row,f 是 license filter 字典。
    任一字段为空(None / [])= 不过滤(全包)。"""
    if f.get("sources") and row.get("source") not in f["sources"]:
        return False
    if f.get("authors") and row.get("author") not in f["authors"]:
        return False
    tags = set(row.get("tags") or [])
    if f.get("tags_include"):
        if not tags & set(f["tags_include"]):
            return False
    if f.get("tags_exclude"):
        if tags & set(f["tags_exclude"]):
            return False
    ts = row.get("ts") or ""
    if f.get("since") and ts < f["since"]:
        return False
    if f.get("until") and ts > f["until"]:
        return False
    return True


def _iter_all_rows() -> list[dict]:
    """从 history-exports/all.jsonl 读所有 row(consent preview / export 用)。"""
    p = DATA_DIR / "history-exports" / "all.jsonl"
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


@app.get("/api/consent/licenses")
def consent_list():
    """列出已保存的 license 配置(含每个的 preview_count snapshot)。"""
    return {"licenses": _load_licenses()}


@app.post("/api/consent/preview")
async def consent_preview(req: Request):
    """给 filter dict,返本次 license 涵盖多少 row + 3 行 sample。
    body: {sources, authors, tags_include, tags_exclude, since, until}
    任一为空数组/null = 全包。
    """
    body = await req.json()
    rows = _iter_all_rows()
    matched = [r for r in rows if _matches_filters(r, body)]
    sample = []
    for r in matched[:3]:
        sample.append({
            "commit": r.get("commit", "")[:12],
            "ts": r.get("ts"),
            "source": r.get("source"),
            "author": r.get("author"),
            "action": r.get("action"),
            "tags": r.get("tags"),
        })
    return {
        "total_rows": len(rows),
        "matched_count": len(matched),
        "sample": sample,
        "filters_applied": body,
    }


@app.post("/api/consent/licenses")
async def consent_save(req: Request):
    """新增或更新 license。body 不带 id → 新增;带 id → update 同 id。
    schema:{label, buyer, filters, expires?}
    """
    body = await req.json()
    licenses = _load_licenses()
    lid = body.get("id") or f"lic_{secrets.token_hex(6)}"
    # 计算 preview snapshot
    rows = _iter_all_rows()
    matched_count = sum(1 for r in rows if _matches_filters(r, body.get("filters") or {}))
    entry = {
        "id": lid,
        "label": (body.get("label") or "untitled").strip(),
        "buyer": (body.get("buyer") or "—").strip(),
        "created": datetime.now().isoformat(timespec="seconds"),
        "expires": body.get("expires"),
        "filters": body.get("filters") or {},
        "preview_count": matched_count,
    }
    # upsert
    out = [l for l in licenses if l.get("id") != lid]
    out.append(entry)
    _save_licenses(out)
    return entry


@app.delete("/api/consent/licenses/{lid}")
def consent_delete(lid: str):
    licenses = _load_licenses()
    out = [l for l in licenses if l.get("id") != lid]
    if len(out) == len(licenses):
        return {"deleted": False, "id": lid}
    _save_licenses(out)
    return {"deleted": True, "id": lid, "remaining": len(out)}


# 启动时跑一次老路径 → APP_STATE_DIR 迁移
@app.on_event("startup")
def _startup_migrate_state():
    try:
        n = _migrate_old_state()
        if n > 0:
            log.warning(
                f"[migrate] copied {n} files from {DATA_HOME}/{{data,config}} → "
                f"{APP_STATE_DIR}/{{data,config}}. "
                f"老位置保留作 fallback,确认稳定后可手动 rm。"
            )
        log.info(f"[state] APP_STATE_DIR = {APP_STATE_DIR}")
    except Exception as e:
        log.warning(f"[migrate] failed: {e}")


# 启动时跑一次 audit,有 drift 就 log 警告(不阻塞启动)
def _vault_audit_step():
    # P0: 从同步 startup 钩子挪进后台 init 线程,不堵 server bind。
    try:
        r = _audit_vault()
        if r["total_drift"] > 0:
            log.warning(
                f"[vault audit] drift detected: "
                f"image_orphans={len(r['image_orphans'])} "
                f"image_recoverable={len(r['image_recoverable'])} "
                f"meta_orphans={len(r['meta_orphans'])} "
                f"aggregate_broken_links={len(r['aggregate_broken_links'])}. "
                f"前端会显示 banner;或 POST /api/vault/repair 自动修可修的。"
            )
    except Exception as e:
        log.warning(f"[vault audit] startup audit failed: {e}")


@app.on_event("startup")
def _startup_sf_sender():
    """启动 silent-failure 上送后台 thread。FEEDBACK_SINK_URL 没配就 no-op。"""
    global _SF_SENDER_THREAD
    if _SF_SENDER_THREAD is not None and _SF_SENDER_THREAD.is_alive():
        return
    _SF_SENDER_THREAD = threading.Thread(
        target=_sf_sender_loop, daemon=True, name="sf-sender"
    )
    _SF_SENDER_THREAD.start()


@app.on_event("startup")
def _startup_hb_sender():
    """启动日活心跳后台 thread。consent 关 / FEEDBACK_SINK_URL 没配都 no-op。"""
    global _HB_SENDER_THREAD
    if _HB_SENDER_THREAD is not None and _HB_SENDER_THREAD.is_alive():
        return
    _HB_SENDER_THREAD = threading.Thread(
        target=_hb_sender_loop, daemon=True, name="hb-sender"
    )
    _HB_SENDER_THREAD.start()


@app.on_event("shutdown")
def _shutdown_sf_sender():
    _SF_SENDER_STOP.set()
    _HB_SENDER_STOP.set()


@app.on_event("startup")
def _startup_config_sanity():
    """启动时扫一遍 config 内部一致性,有 silent risk 立即报。
    今天踩的 5.29 vision 401 — prod .env 缺 DASHSCOPE_API_KEY,
    base_url 不是 dashscope,fallback 用 deepseek key 调 dashscope endpoint —
    这种"配错了不报错,等真出问题再炸"的事必须启动就发现。
    """
    try:
        cfg = load_config() or {}
        dk = (cfg.get("dashscope_api_key") or "").strip()
        bu = (cfg.get("base_url") or "").strip()
        ak = (cfg.get("api_key") or "").strip()
        if not dk and ak and "dashscope" not in bu:
            # 顶层 key 是 deepseek-direct 类,vision 走 dashscope endpoint 会 401
            _report_silent_failure("config_sanity_vision_no_dashscope_key",
                f"dashscope_api_key 空 + base_url={bu[:60]} 不是 dashscope,vision 会 401",
                context={"has_top_api_key": bool(ak)})
            log.warning(
                "[config sanity] vision 可能会 401 — "
                "dashscope_api_key 没配且顶层 key 不是百炼 key (base_url 不指 dashscope)"
            )
    except Exception as e:
        log.warning(f"[config sanity] startup check failed: {e}")


def _vault_git_init_step():
    """vault 写入自动版本史 — 首次启动 init repo + .gitignore + baseline。
    pulse-mirror 也装独立 git(PULSE updates 进 training corpus 用)。
    P0: 从同步 startup 钩子挪进后台 init 线程 — 大文件夹 git add -A 不堵 server bind。"""
    try:
        status = vault_git.ensure_repo(VAULT_DIR)
        log.info(f"[vault_git] vault ensure_repo: {status} at {VAULT_DIR}")
    except Exception as e:
        log.warning(f"[vault_git] vault ensure_repo failed: {type(e).__name__}: {e}")
    try:
        _pulse = APP_STATE_DIR / "pulse-mirror"
        if _pulse.exists():
            status = vault_git.ensure_repo(_pulse)
            log.info(f"[vault_git] pulse-mirror ensure_repo: {status} at {_pulse}")
    except Exception as e:
        log.warning(f"[vault_git] pulse ensure_repo failed: {type(e).__name__}: {e}")


# ── P0: 后台 init —— server 立刻 bind 出页面,重活(git/audit)后台跑 + 进度可查 ──
_INIT_STATE = {
    "ready": False, "phase": "starting", "detail": "",
    "started_at": None, "finished_at": None, "error": None,
}
_INIT_LOCK = threading.Lock()


def _set_init_phase(phase: str, detail: str = ""):
    with _INIT_LOCK:
        _INIT_STATE["phase"] = phase
        _INIT_STATE["detail"] = detail
    log.info(f"[init] phase={phase} {detail}")


def _background_vault_init():
    """重活后台序列:git init(含大文件夹 baseline)→ vault audit。
    顺序保留(audit 依赖 repo 在);全程更新 _INIT_STATE 供前端进度屏轮询。
    自身永不让 ready 卡死 —— 任一步崩也置 ready,免前端永远转圈。"""
    try:
        _set_init_phase("git_init", "初始化版本历史")
        _vault_git_init_step()
        _set_init_phase("audit", "检查 vault 完整性")
        _vault_audit_step()
        # 抠图模型预热(Win/Linux/老 mac):从自家 COS 拉 u2net,绕开 rembg 内置
        # GitHub 下载(大陆不可达)。幂等 + 失败自上报,不进 init error(非关键路径)。
        _set_init_phase("cutout_model", "准备抠图模型")
        try:
            from cutout_local import prewarm_u2net
            prewarm_u2net()
        except Exception as e:
            log.warning(f"[init] u2net prewarm: {e}")
    except Exception as e:
        with _INIT_LOCK:
            _INIT_STATE["error"] = f"{type(e).__name__}: {str(e)[:160]}"
        log.warning(f"[init] background init crashed: {e}")
        # 后台 init 崩(git init / audit)→ 审计链可能断,远程看不见,上报
        _report_silent_failure("vault_init_failed",
            f"{type(e).__name__}: {str(e)[:120]}", context={"err_class": type(e).__name__})
    finally:
        with _INIT_LOCK:
            _INIT_STATE["phase"] = "ready"
            _INIT_STATE["ready"] = True
            _INIT_STATE["finished_at"] = datetime.now().isoformat()
        log.info("[init] background vault init done — ready")


@app.on_event("startup")
def _startup_background_init():
    """只 spawn 后台线程就返回 → server 立刻开始服务,WebView 秒出页面。"""
    with _INIT_LOCK:
        _INIT_STATE["started_at"] = datetime.now().isoformat()
    threading.Thread(
        target=_background_vault_init, daemon=True, name="vault-init"
    ).start()


# ── chat thread history(server-side 持久化,跨浏览器/跨设备同步源)──
THREAD_HISTORY_PATH = DATA_DIR / "thread-history.json"
_THREAD_LOCK = threading.Lock()


def _thread_history_mtime_ms() -> int:
    """毫秒级 mtime。用 ms(~1.78e12)而非 ns(~1.78e18)是因为 ns 超过
    JS Number.MAX_SAFE_INTEGER(9e15),前端存/传时丢精度会导致 CAS 把合法 save 误判成冲突。
    ms 精度对单用户冲突检测绰绰有余(同毫秒两次写几乎不可能)。"""
    try:
        return THREAD_HISTORY_PATH.stat().st_mtime_ns // 1_000_000
    except FileNotFoundError:
        return 0


def _thread_save_is_stale(base_mtime, current_mtime: int) -> bool:
    """CAS 判定:client 回传它 save 所基于的 base_mtime,若跟当前存档 mtime 不符,
    说明期间别的 client(或陈旧标签页)写过 → 这次 save 是陈旧覆盖 → 该拒。

    豁免:
    - base_mtime is None(旧 client 没回传)→ 不判定,放行(过渡兼容)
    - current_mtime == 0(文件还不存在,首次写)→ 放行
    防的就是 5.17 / 5.26 那种「开了几天的旧标签页用内存里的旧 history 盖掉新历史」。
    """
    if base_mtime is None:
        return False
    if current_mtime == 0:
        return False
    try:
        return int(base_mtime) != current_mtime
    except (TypeError, ValueError):
        return False


@app.get("/api/health")
def api_health():
    """轻量 ping — client 每 30s 检测,断了弹 banner。带版本号供设置"关于"页显示。"""
    return {"ok": True, "ts": datetime.now().isoformat(timespec="seconds"), "version": APP_VERSION}


@app.get("/api/init-status")
def api_init_status():
    """P0: 前端初始化屏轮询 — 后台 vault init(git/audit)进度。
    ready=True 前显示「正在初始化…」而非空白,回答用户「是慢还是卡住了」。"""
    with _INIT_LOCK:
        return dict(_INIT_STATE)


# PULSE_DIR 已搬到 pulse_io.py(P2,顶部 re-export)

# ─── daily eval (测试端点) ──────────────────────────────────────────────────
# 设计:保留 build_system_prompt() 的 co-writer 身份不动,evaluator role
# 后置注入。同一把嗓子,换硬话。每次新开 completion (无 chat history),
# 输出 NOT 持久化(测试模式)。生产版会写 eval-log + push 通知。
# EVAL_LOG_DIR + 8 _eval_* helpers + _classify_eval_err + 3 prompts 已搬到 pulse_eval.py(P3,顶部 re-export)

# ─── eval 持久化 + 通知 + 生产端点 ────────────────────────────────────────

# _eval_persist / _eval_notify / _eval_compress_past_logs 已搬到 pulse_eval.py(P3,顶部 re-export)


# _parse_pulse_md + _STATUS_EMOJI 已搬到 pulse_io.py(P2,顶部 re-export)


# pulse_detail 已搬到 pulse_routes.py(P1 thin wrapper)


# ── USER_PULSE 自演化 (0.1.4 起) ─────────────────────────────────────
# PULSE_BUDGET_CHARS / PULSE_STALE_DAYS / _TS_RE / _FROZEN_RE / _PLACEHOLDER_RE /
# _extract_frozen / _count_placeholders / _pulse_validate 已搬到 pulse_io.py(P2,顶部 re-export)


# _PULSE_UPDATE_PROMPT + _AGENT_CONTEXT_EVOLVE_PROMPT 已搬到 pulse_evolve.py(P4,顶部 re-export)


# ── vault reference 落地 + schema 升级 ──────────────────────────────
# 分发模板源在 `gateway/reference/`,PyInstaller bundle 进 .app
# startup 时:① 缺的 reference 拷进 vault(byte-equal 不动已有)
#            ② bundle schema-version 比 vault 高 → 后台 LLM 重组 vault 文件
# _SCHEMA_VERSION_RE + _get_schema_version 已搬到 pulse_io.py(P2,顶部 re-export)

_VAULT_REFERENCE_TARGETS = {
    "agent_context": {
        "bundled_name": "AGENT_CONTEXT.md",
        "vault_path": lambda: _AGENT_CONTEXT_PATH,
        "evolve_target": "agent_context",  # schema bump 走 _self_evolve_run
    },
    "daily_tasks": {
        "bundled_name": "daily-tasks.md",
        "vault_path": lambda: VAULT_DIR / "daily-tasks.md",
        "evolve_target": None,  # 用户编辑,不走 LLM
    },
    "tag_aggregation": {
        "bundled_name": "标签聚合.md",
        "vault_path": lambda: VAULT_DIR / "标签聚合.md",
        "evolve_target": None,
    },
}


# Pending notifications(给前端 banner 用)— 自动更新 + schema 迁移共用
_PENDING_NOTIFICATIONS: list[dict] = []
_NOTIF_LOCK = threading.Lock()  # async event loop ↔ threadpool 边界(#24)

def _push_notification(kind: str, message: str, payload: dict | None = None):
    """前端 30s poll /api/notifications,见 kind 后自决定 dismiss。"""
    n = {"kind": kind, "message": message, "payload": payload or {}, "ts": datetime.now().isoformat()}
    with _NOTIF_LOCK:
        _PENDING_NOTIFICATIONS.append(n)
        # 上限 20 条防泄漏
        if len(_PENDING_NOTIFICATIONS) > 20:
            del _PENDING_NOTIFICATIONS[0:len(_PENDING_NOTIFICATIONS)-20]
    # workflow #17 闭合:重要 kind 持久化到磁盘,防 sidecar 重启 / process 死掉 notification 永久丢
    # vault 被 LLM 自动改了 / reference bootstrap / schema 升级 — 用户必须知道
    _PERSIST_NOTIF_KINDS = {
        "vault-schema-migrated", "vault-schema-bumped",
        "vault-schema-migration-failed", "vault-schema-migration-skip-external-edit",
        "vault-reference-bootstrapped",
    }
    if kind in _PERSIST_NOTIF_KINDS:
        _persist_pending_notification(n)


def _pending_notif_path() -> Path:
    return APP_STATE_DIR / "data" / ".pending-notifications.jsonl"


# A-H5: persist + consume 同把 lock,防多线程 append 行截断 / consume 时漏未持久化条
_PENDING_NOTIF_FILE_LOCK = threading.Lock()


def _persist_pending_notification(n: dict):
    """append 到 ~/.../data/.pending-notifications.jsonl,sidecar 启动时读 + push + truncate。
    A-H5: lock + flush + fsync,保证 vault auto-modified / schema migration 这种用户必看的
    notification 不会因 append 半截行掉地。
    """
    try:
        p = _pending_notif_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(n, ensure_ascii=False) + "\n"
        with _PENDING_NOTIF_FILE_LOCK:
            with open(p, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
    except Exception as e:
        log.warning(f"persist pending notification 失败: {e}")


def _consume_pending_notifications():
    """sidecar 启动时把上次没消费的持久化通知补 push。
    A-H5: 锁内 read → push 内存队列 → 把"已成功 push 的行"清掉(write-back-good-lines)。
    比 read+unlink 安全 — read 期间新写的 append 不会被 unlink 整体吞掉。"""
    p = _pending_notif_path()
    if not p.exists():
        return
    with _PENDING_NOTIF_FILE_LOCK:
        try:
            raw = p.read_text(encoding="utf-8")
        except Exception as e:
            log.warning(f"读 pending notifications 失败: {e}")
            return  # 不动文件,等下次启动再试
        lines = raw.splitlines()
        if not lines:
            return
        count = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                n = json.loads(line)
            except Exception:
                continue
            with _NOTIF_LOCK:
                _PENDING_NOTIFICATIONS.append(n)
                if len(_PENDING_NOTIFICATIONS) > 20:
                    del _PENDING_NOTIFICATIONS[0:len(_PENDING_NOTIFICATIONS)-20]
            count += 1
        # 已消费 → 清空文件(atomic 写空)
        try:
            _safe_write_text(p, "", rotate=False)
        except Exception:
            pass
    if count:
        log.info(f"补 push {count} 条 pending notification")


# Schema migration attempts 记录(防 #19 LLM call 死循环烧 token)
# 文件落 APP_STATE_DIR/data/.schema-migration-attempts.json
# 失败 silent 时退到 module-level cache(R8 fix):防 disk full / 跨用户 sudo / 只读 fs
# 场景下 attempts gate 永不闭合,LLM 死循环烧 deepseek-v4-pro token


def _migration_llm_call(client, profile, prompt: str) -> str:
    """同步 LLM 一次性 call,给 to_thread 包。返清洗后的 markdown 文本。
    B-#1: 异常自然向外传,外层 except 走 `_classify_eval_err` 分桶 + silent-failure 上报。
    """
    resp = client.chat.completions.create(
        model=profile.get("model", "deepseek-v4-pro"),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=12000,
        temperature=0.2,
        timeout=180,
    )
    text = (resp.choices[0].message.content or "").strip()
    text = re.sub(r"^```(markdown|md)?\s*", "", text).strip()
    text = re.sub(r"\s*```\s*$", "", text).strip()
    return text


def _validate_migration_output(new_text: str, old_text: str, expected_version: int) -> str:
    """返 ""(空字符串)= OK,否则返错误描述。"""
    if not new_text:
        return "LLM 返空"
    if len(new_text) < int(len(old_text) * 0.7):
        return f"长度腰斩 {len(new_text)}/{len(old_text)}(<70%)"
    nv = _get_schema_version(new_text)
    if nv != expected_version:
        return f"schema-version 标记应为 {expected_version},LLM 返 {nv}"
    if not _TS_RE.search(new_text):
        return "缺 ts 标记"
    return ""


# 独立 schema 迁移 prompt(不复用 _PULSE_UPDATE_PROMPT — 那是 chat-compact 语义)
# 关键差别:不允许"压精简",只允许"按新结构重排同样数据"
_SCHEMA_MIGRATION_PROMPT = """vault 文件 {name} schema 升级:v{old_version} → v{new_version}。

任务:把 vault 现有内容按**新 reference 模板**的结构重组,**保留所有信息**,不要精简。

机械要求(server 会校验,违反就被拒):
- 必须保留 `<!-- schema-version: {new_version} -->` 标记
- 必须保留所有 `<!-- ts:YYYY-MM-DD -->` 标记;新加段用今天 {today}
- 输出长度必须 ≥ vault 当前内容的 70%(不能压精简,只能重组)

内容约束:
- **保留全部用户数据**:owner_handle / 角色 / 关心点 / 协作偏好 / 任何手写段
- **按新模板的段落顺序重排**:user 的内容塞到新模板对应段下
- **新模板里有但 vault 没的段**:保留空模板(给 user 后续填),用 today {today} 加 ts
- **vault 里有但新模板不再有的段**:依然保留(扔进 "其他自定义" 之类的容器),不要删
- **不要修改用户原话措辞**:只移动位置 + 加 ts + 加 schema-version 标记,不重新组织语言

返回纯 markdown,不要解释、不要 ``` 包裹。

=== 新 reference 模板(目标结构)===
{bundle_reference}

=== vault 当前内容(要迁移的)===
{vault_current}
"""


# _SELF_EVOLVE_TARGETS 已搬到 pulse_io.py(P2,顶部 re-export);
# lambda 闭包查 pulse_io 自己的 path 常量,跨模块 patch 走 monkeypatch.setitem 仍生效。


# _EVOLVE_LOCKS / _EVOLVE_LOCKS_GUARD / _get_evolve_lock 已搬到 pulse_evolve.py(P4,顶部 re-export)


# vault md (schedule + tag-aggregate) write 路径用,防 Obsidian 并发编辑被静默覆盖
# 跟 _EVOLVE_LOCKS 分开:一个保护 schema migration(LLM 重写真源),
# 一个保护 patch/insert/comment(块级编辑)。
_VAULT_MD_LOCKS: dict[str, threading.Lock] = {}
_VAULT_MD_LOCKS_GUARD = threading.Lock()


def _get_vault_md_lock(path_str: str) -> threading.Lock:
    with _VAULT_MD_LOCKS_GUARD:
        lk = _VAULT_MD_LOCKS.get(path_str)
        if lk is None:
            lk = threading.Lock()
            _VAULT_MD_LOCKS[path_str] = lk
        return lk


def _sha256_text(s: str) -> str:
    import hashlib as _hl
    return _hl.sha256(s.encode("utf-8")).hexdigest()


# _self_evolve_run 已搬到 pulse_evolve.py(P4,顶部 re-export)
# _ensure_schema_version_header 已搬到 pulse_io.py(P2,顶部 re-export)


@app.get("/api/notifications")
def get_notifications(dismiss: str = ""):
    """前端 poll banner 用。
    返 pending 通知列表;调用时带 `?dismiss=kind1,kind2` 一次性清掉这些类型。
    """
    with _NOTIF_LOCK:
        if dismiss:
            kinds = set(k.strip() for k in dismiss.split(",") if k.strip())
            # in-place 修改而不是 rebind(#24)
            _PENDING_NOTIFICATIONS[:] = [n for n in _PENDING_NOTIFICATIONS if n["kind"] not in kinds]
        return {"notifications": list(_PENDING_NOTIFICATIONS)}


@app.post("/api/updater/installed")
async def updater_installed(req: Request):
    """Tauri 自动更新完下载 + install 后(.app 二进制已替换,但当前 process 还跑旧版),
    Rust 端 POST 这里通知 sidecar,sidecar 推 banner 给前端 "重启生效"。"""
    body = {}
    try:
        body = await req.json()
    except Exception:
        pass
    version = (body.get("version") or "").strip() or "新版"
    _push_notification(
        "updater-installed",
        f"Gateway {version} 已下载,重启 app 生效",
        {"version": version},
    )
    return {"ok": True}


def _ver_tuple(s: str):
    """'0.1.34' → (0,1,34);解析失败返 None。"""
    import re as _re
    m = _re.search(r"(\d+)\.(\d+)\.(\d+)", s or "")
    return tuple(int(x) for x in m.groups()) if m else None


@app.post("/api/updater/report")
async def updater_report(req: Request):
    """Rust updater check 完把结果 POST 这里,sidecar 判异常后走 silent-failure 通道
    (本地缓冲 + 联网回传)。让远程用户的自更新故障也进表,不依赖摸到他们机器。
    body: {current_version, check_result, cos, yanpai}
      check_result: 'some:X' / 'none' / 'error:<msg>'
      cos / yanpai:  '<http_status>:<version>' / 'err:<msg>'
    只报真异常:check 报 error,或 COS 有新版但 check 却说 none(今天 bug 的指纹)。"""
    try:
        body = await req.json()
    except Exception:
        return {"ok": False}
    cur = (body.get("current_version") or "").strip()
    res = (body.get("check_result") or "").strip()
    cos = (body.get("cos") or "").strip()
    yanpai = (body.get("yanpai") or "").strip()
    # 异常 1:check 直接报错(网络/验签/parse)
    if res.startswith("error"):
        _report_silent_failure("updater_check_failed",
            f"cur={cur} {res[:120]}",
            context={"err": res[7:127], "phase": "check"})
        return {"ok": True, "reported": "updater_check_failed"}
    # 异常 2:COS 有更新版本,但 check() 却说无更新 → 自更新静默不弹的指纹
    if res == "none":
        cos_ver = _ver_tuple(cos.split(":")[-1] if ":" in cos else cos)
        cur_ver = _ver_tuple(cur)
        if cos_ver and cur_ver and cos_ver > cur_ver:
            _report_silent_failure("updater_silent_no_update",
                f"COS 有 {cos.split(':')[-1]} > 装机 {cur},但 check 返 none(yanpai={yanpai})",
                context={"phase": "check"})
            return {"ok": True, "reported": "updater_silent_no_update"}
    return {"ok": True, "reported": None}


# pulse_user_update 已搬到 pulse_routes.py(P1 thin wrapper)


# pulse_project_update 已搬到 pulse_routes.py(P1 thin wrapper)


# pulse_agent_context_update 已搬到 pulse_routes.py(P1 thin wrapper)


# Compact 摘要 — 抽到 compact_summary.py(行为零变化)。endpoint 留下面。
from compact_summary import compact_summary_run as _compact_summary_run


# pulse_compact_summary 已搬到 pulse_routes.py(P1 thin wrapper)


# pulse_refresh_mirror 已搬到 pulse_routes.py(P1 thin wrapper)


# pulse_dashboard 已搬到 pulse_routes.py(P1 thin wrapper)


# ── 标签聚合.md viewer ───────────────────────────────────────────────
_TAG_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_TAG_DATE_RE = re.compile(r"(\d{2})\.(\d{1,2})\.(\d{1,2})")


def _parse_tag_aggregate(text: str):
    """walk lines → [{tag, description, columns, rows}]
    rows: {date_short, iso_date, time, content, sub_tag, link_target}
    """
    sections = []
    cur = None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = re.match(r"^##\s+#(\S+)\s*$", line)
        if m:
            if cur:
                sections.append(cur)
            cur = {"tag": m.group(1), "description": "", "columns": [], "rows": []}
            continue
        if not cur:
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and cells[0] in ("日期", "Date"):
                cur["columns"] = cells
                continue
            if cells and all((not c) or set(c) <= set("-: ") for c in cells):
                continue
            if len(cells) >= 4:
                date_cell, time_cell, link_cell, content_cell = cells[0], cells[1], cells[2], cells[3]
                sub_tag = cells[4] if len(cells) >= 5 else None
                link_text, link_target = link_cell, ""
                m2 = _TAG_LINK_RE.search(link_cell)
                if m2:
                    link_text, link_target = m2.group(1), m2.group(2)
                iso_date = None
                m3 = _TAG_DATE_RE.search(link_target or date_cell)
                if m3:
                    yy, mo, dd = m3.groups()
                    iso_date = f"20{yy}-{int(mo):02d}-{int(dd):02d}"
                cur["rows"].append({
                    "date_short": date_cell,
                    "iso_date": iso_date,
                    "time": time_cell,
                    "link_text": link_text,
                    "link_target": link_target,
                    "content": content_cell,
                    "sub_tag": sub_tag if (sub_tag and sub_tag != "—") else None,
                })
            continue
        if line.strip() and not cur["description"] and not line.startswith(">"):
            cur["description"] = line.strip()
    if cur:
        sections.append(cur)
    return sections


# ── 初次配置 / setup 向导 ────────────────────────────────────────────
# Ritual 双角色:
#   · DeepSeek 直连 = 说话的(主对话,给 deepseek 直接充值的情绪价值)
#   · 阿里云百炼   = 给 deepseek 装上眼睛(vision/OCR)
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODELS = [
    {"id": "deepseek-v4-pro",   "label": "DeepSeek V4 Pro",   "tag": "强推理 · 默认", "default": True},
    {"id": "deepseek-v4-flash", "label": "DeepSeek V4 Flash", "tag": "快"},
    {"id": "deepseek-r1",       "label": "DeepSeek R1",       "tag": "深度思考"},
    {"id": "deepseek-chat",     "label": "DeepSeek Chat",     "tag": "兼容老命名"},
    {"id": "deepseek-reasoner", "label": "DeepSeek Reasoner", "tag": "推理"},
]

BAILIAN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# 百炼此处只作视觉助手 — 一个 vision model 够 99% 场景。要别的 model 自己加。
BAILIAN_VISION_MODELS = [
    {"id": "qwen3-vl-flash",    "label": "Qwen3 VL Flash",    "tag": "看图分类 · 默认(便宜+快)", "default": True},
    {"id": "qwen3-vl-plus",     "label": "Qwen3 VL Plus",     "tag": "更精细"},
    {"id": "qwen-vl-ocr-latest","label": "Qwen VL OCR",       "tag": "长截图文字"},
]
# 兼容老 setup.js 还在 fetch 这个名字
BAILIAN_MODELS = BAILIAN_VISION_MODELS


# ── 0.1.3 加: cloud telemetry consent ────────────────────────────────
@app.get("/api/telemetry/consent")
def telemetry_consent_get():
    """前端读 consent 状态 + 上报统计 + client_id (透明给用户看)。"""
    consent = _telemetry_consent()
    # 上报统计
    try:
        sf_count = len(SILENT_FAILURES_LOG.read_text(encoding="utf-8").splitlines()) \
                   if SILENT_FAILURES_LOG.exists() else 0
    except Exception:
        sf_count = 0
    return {
        **consent,
        "client_id": get_client_id(),
        "silent_failures_local": sf_count,
        "heartbeat_last_day": _hb_last_sent_day(),
        "needs_consent": consent.get("consented_at") is None,
    }


@app.post("/api/telemetry/consent")
async def telemetry_consent_set(req: Request):
    """前端 consent modal / 设置 tab 调,写两个开关。
    body: {failures: bool, heartbeat: bool}
    """
    body = await req.json()
    failures = bool(body.get("failures", False))
    heartbeat = bool(body.get("heartbeat", False))
    # 撤回检测:之前同意过 + 现在两项都关 = 撤回 → 触发云端 /forget(C-#10)
    prev = _telemetry_consent()
    is_withdrawal = (
        (prev.get("failures") or prev.get("heartbeat"))
        and not failures
        and not heartbeat
    )
    _telemetry_save(failures, heartbeat)
    if is_withdrawal:
        # fire-and-forget 异步发 /forget,不阻塞 consent 写盘成功响应
        try:
            import threading as _t
            _t.Thread(target=_send_forget_request, daemon=True).start()
        except Exception:
            pass
    return {"ok": True, **_telemetry_consent()}


def _send_forget_request():
    """C-#10: 撤回 consent 时通知 yanpai 删除已上传数据。
    满足 GDPR Art.17 / PIPL 第 47 条。失败不 retry(用户随时可手动再发)。"""
    try:
        url_base = (_env_overlay().get("FEEDBACK_SINK_URL", "")
                    or os.environ.get("FEEDBACK_SINK_URL", "")).strip().rstrip("/")
        if not url_base:
            return
        cid = get_client_id()
        r = requests.delete(
            f"{url_base}/forget",
            params={"client_id": cid},
            timeout=10,
        )
        if r.status_code != 200:
            log.warning(f"/forget 上报失败: HTTP {r.status_code}")
    except Exception as e:
        log.warning(f"/forget 上报失败: {e}")


@app.post("/api/telemetry/reset-client-id")
def telemetry_reset_client_id():
    """用户主动重置 client_id (在设置 → 数据 → 云上报里可点)。
    重置后 server 端看作新设备,DAU 会重复计一次,无副作用。
    """
    global _CLIENT_ID_CACHE
    try:
        import uuid as _uuid
        new_id = _uuid.uuid4().hex
        CLIENT_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
        CLIENT_ID_PATH.write_text(new_id, encoding="utf-8")
        _CLIENT_ID_CACHE = new_id
        # 重置 heartbeat 标记(让新 id 立刻发一次)
        try:
            _HB_LAST_SENT_PATH.unlink()
        except Exception:
            pass
        return {"ok": True, "client_id": new_id}
    except Exception as e:
        raise HTTPException(500, f"reset failed: {type(e).__name__}: {e}")


_SCHEDULE_FILE_RE = re.compile(r"^26\.(\d{1,2})\.(\d{1,2})")
_H1_TIME_RE = re.compile(r"^#\s+(\d{1,2}：\d{2})\s*$")
_H2_RE = re.compile(r"^##\s+(.+)$")
_HASH_TAG_RE = re.compile(r"#([A-Za-z0-9_\-/一-鿿]+)")


def _scan_schedule_for_project_tags(project_tags: set) -> dict:
    """Walk 半小时复盘/*.md, 抽 project-tagged H2 entries。
    返:{tag: [{iso_date, date_short, time, sub_tag, content, link_target}, ...]}

    规则:
    - H1 行 `# 13：30` 是当前时间块
    - H2 行 `## #tagA #tagB title` 是一条 entry
      - tag 包括可能的 #parent/child 形式 → roll-up 到 parent section,sub_tag = /child
      - title = H2 去掉所有 #tag token 后剩下的文本
    - 只收 project_tags 命中的;generic tag(#运动 #饮食)等忽略
    """
    out = {tag: [] for tag in project_tags}
    if not JOURNAL_DIR.exists():
        return out

    for f in sorted(JOURNAL_DIR.glob("26.*.md")):
        m = _SCHEDULE_FILE_RE.match(f.name)
        if not m:
            continue
        mo, dd = int(m.group(1)), int(m.group(2))
        iso_date = f"2026-{mo:02d}-{dd:02d}"
        date_short = f"{mo}.{dd}"

        cur_time = None
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue

        for line in lines:
            m1 = _H1_TIME_RE.match(line)
            if m1:
                cur_time = m1.group(1)
                continue
            m2 = _H2_RE.match(line)
            if not m2 or not cur_time:
                continue
            h2 = m2.group(1).strip()
            tag_tokens = _HASH_TAG_RE.findall(h2)
            if not tag_tokens:
                continue
            title = _HASH_TAG_RE.sub("", h2).strip()
            if not title:
                continue
            for tag_full in tag_tokens:
                if "/" in tag_full:
                    parent, child = tag_full.split("/", 1)
                    sub = f"/{child}"
                else:
                    parent, sub = tag_full, None
                if parent not in project_tags:
                    continue
                out[parent].append({
                    "iso_date":    iso_date,
                    "date_short":  date_short,
                    "time":        cur_time,
                    "sub_tag":     sub,
                    "content":     title,
                    "link_target": f"半小时复盘/{f.name}#{cur_time}",
                })
    return out


def _refresh_tag_aggregate() -> dict:
    """扫所有 schedule files,跟 标签聚合.md 比对,append 缺失行。

    安全方向:只 append,不 delete。删除/重命名留给手工(避免误杀 user 写的)。
    返:{added: N, total_scanned: N, per_tag: {tag: added_count}}
    """
    if not TAG_AGGREGATE_PATH.exists():
        return {"error": "标签聚合.md 不存在", "added": 0}

    text = TAG_AGGREGATE_PATH.read_text(encoding="utf-8")
    sections = _parse_tag_aggregate(text)
    project_tags = {s["tag"] for s in sections}
    if not project_tags:
        return {"error": "没找到任何 project tag section", "added": 0}

    scanned = _scan_schedule_for_project_tags(project_tags)

    # 现有 rows 的 key = (iso_date, time, sub_tag)
    existing_keys = {tag: set() for tag in project_tags}
    for s in sections:
        for r in s["rows"]:
            key = (r.get("iso_date"), r.get("time"), r.get("sub_tag"))
            existing_keys[s["tag"]].add(key)

    # 算出每个 tag 要 append 的 rows
    new_rows = {tag: [] for tag in project_tags}
    for tag, rows in scanned.items():
        seen_in_scan = set()
        for r in rows:
            key = (r["iso_date"], r["time"], r["sub_tag"])
            if key in existing_keys[tag]:
                continue
            if key in seen_in_scan:
                continue  # 同 scan 里重复(同一 entry 多 tag)
            seen_in_scan.add(key)
            new_rows[tag].append(r)

    total_added = sum(len(v) for v in new_rows.values())
    if total_added == 0:
        return {"added": 0, "per_tag": {}, "scanned": sum(len(v) for v in scanned.values())}

    # 把新行 append 进对应 section。策略:找 `## #tag` 下的最后一个 table 行,
    # 在它之后插入新行(无表则不动 — 这种情况不常见)。
    new_text = _append_rows_to_aggregate(text, new_rows)
    _safe_write_text(TAG_AGGREGATE_PATH, new_text, rotate=True)
    per_tag_summary = "+".join(f"#{t}" for t, rs in new_rows.items() if rs) or "none"
    vault_git.commit_after_write(VAULT_DIR, f"aggregate refresh +{total_added} rows {per_tag_summary}",
                                 author="system", paths=[TAG_AGGREGATE_PATH])

    return {
        "added": total_added,
        "per_tag": {tag: len(rows) for tag, rows in new_rows.items() if rows},
        "scanned": sum(len(v) for v in scanned.values()),
    }


def _format_row(row: dict, with_sub: bool) -> str:
    """单行 markdown table 行(链接锚点保留全角冒号)。"""
    link = f"[26.{row['date_short']}#{row['time']}]({row['link_target']})"
    base = f"| {row['date_short']} | {row['time']} | {link} | {row['content']} |"
    if with_sub:
        base += f" {row['sub_tag'] or '—'} |"
    return base


def _append_rows_to_aggregate(text: str, new_rows: dict) -> str:
    """对每个 tag,定位 `## #tag` 段落,在该段最后一个 table 行后插入新行。
    保留段内其他内容(description / 末尾 note 行)不动。
    """
    lines = text.splitlines()
    out_lines = []
    i = 0
    cur_tag = None
    pending_rows = []  # 当前段累积要 append 的行
    table_last_idx = -1  # 当前段最后一个 table 行在 out_lines 里的 index

    def flush_section():
        """段尾(下个 `## ` 或 `---` 或文件结束) → 在 table_last_idx 后插行。"""
        nonlocal pending_rows, table_last_idx
        if pending_rows and table_last_idx >= 0:
            # 判断是否带 sub 列(看 cur_tag 现有 row 有没有 sub)
            with_sub = any(r["sub_tag"] for r in pending_rows)
            # 也看 table header 决定(更准):看 last table 行的 cell 数量
            last_line = out_lines[table_last_idx]
            if last_line.count("|") >= 6:  # | a | b | c | d | e | → 5 cell = sub 列
                with_sub = True
            insertion = [_format_row(r, with_sub) for r in pending_rows]
            # 按 iso_date asc 排序新行(跟现有 row 排序一致)
            pending_rows_sorted = sorted(pending_rows, key=lambda r: (r["iso_date"], r["time"]))
            insertion = [_format_row(r, with_sub) for r in pending_rows_sorted]
            for offset, ln in enumerate(insertion, 1):
                out_lines.insert(table_last_idx + offset, ln)
        pending_rows = []
        table_last_idx = -1

    while i < len(lines):
        line = lines[i]
        # 新 section 开始
        m = re.match(r"^##\s+#(\S+)\s*$", line)
        if m:
            flush_section()
            cur_tag = m.group(1)
            pending_rows = list(new_rows.get(cur_tag, []))
            out_lines.append(line)
            i += 1
            continue
        # 段尾分隔(横线或下个 H2/H1)
        if line.strip() == "---":
            flush_section()
            cur_tag = None
            out_lines.append(line)
            i += 1
            continue
        # table 行(以 | 开头)— 含 separator;新行插在 table 末尾即可,
        # 这样空 section (只有 header + sep) 也能正确把 row 插在 sep 之后
        if line.startswith("|") and cur_tag:
            out_lines.append(line)
            table_last_idx = len(out_lines) - 1
            i += 1
            continue
        out_lines.append(line)
        i += 1
    flush_section()
    return "\n".join(out_lines) + ("\n" if text.endswith("\n") else "")


@app.get("/api/silent-failures/recent")
def silent_failures_recent(n: int = 100):
    """返最近 N 条 silent failure log(本地 ring buffer)。
    P1 调试 / P3 后给云端 audit dashboard。
    """
    n = max(1, min(int(n), _SILENT_FAILURES_RING_MAX))
    if not SILENT_FAILURES_LOG.exists():
        return {"items": [], "total": 0, "client_id": get_client_id()}
    try:
        lines = SILENT_FAILURES_LOG.read_text(encoding="utf-8").splitlines()
        items = []
        for line in lines[-n:]:
            try:
                items.append(json.loads(line))
            except Exception:
                continue
        return {"items": items, "total": len(lines), "client_id": get_client_id()}
    except Exception as e:
        raise HTTPException(500, f"read failed: {type(e).__name__}: {e}")


@app.post("/api/open-external")
async def open_external(req: Request):
    """打开外部 URL — 走系统默认浏览器。
    解决 Tauri WKWebView `target="_blank"` 哑火问题(同类已知 webview quirk)。
    安全:只白名单 http/https,挡 file:// + javascript: + 等本地 scheme。
    """
    import subprocess, sys as _sys
    body = await req.json()
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "need url")
    if not re.match(r"^https?://", url, flags=re.I):
        raise HTTPException(400, "only http(s) allowed")
    plat = _sys.platform
    try:
        if plat == "darwin":
            subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif plat == "win32":
            subprocess.Popen(["cmd", "/c", "start", "", url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False)
        else:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, f"open failed: {type(e).__name__}: {e}")


@app.get("/api/widgets/catalog")
def widgets_catalog():
    """扫 gateway/widgets/*/manifest.json,返回全部 widget 元数据 + 当前激活状态。
    前端 marketplace UI 渲染用。
    """
    active = []
    if USER_WIDGETS_PATH.exists():
        try:
            cfg = json.loads(USER_WIDGETS_PATH.read_text(encoding="utf-8"))
            active = cfg.get("active", []) or []
        except Exception:
            pass
    items = []
    if WIDGETS_DIR.exists():
        for d in sorted(WIDGETS_DIR.iterdir()):
            mf = d / "manifest.json"
            if not (d.is_dir() and mf.exists()):
                continue
            try:
                m = json.loads(mf.read_text(encoding="utf-8"))
            except Exception:
                continue
            items.append({
                "name": m.get("name", d.name),
                "title": m.get("title", d.name),
                "description": m.get("description", ""),
                "audience": m.get("audience", ""),
                "category": m.get("category", "uncategorized"),
                "default_loaded": bool(m.get("default_loaded", False)),
                "slot": m.get("slot", ""),
                # 'wip' = 开发中,marketplace 灰显 + 禁切;'stable' = 审核通过可用
                "status": m.get("status", "stable"),
                "active": m.get("name", d.name) in active,
            })
    return {"widgets": items, "active": active}


@app.post("/api/widgets/toggle")
async def widgets_toggle(req: Request):
    """开/关一个 widget,写 .user-widgets.json。
    body: {name, enable: bool}
    """
    body = await req.json()
    name = (body.get("name") or "").strip()
    enable = bool(body.get("enable"))
    if not name:
        raise HTTPException(400, "need name")
    # 校验 widget 真实存在
    mf = WIDGETS_DIR / name / "manifest.json"
    if not mf.exists():
        raise HTTPException(404, f"widget '{name}' not found")
    # 拦 wip — 前端已禁切,这里兜底防止绕过(curl 直调)
    try:
        if json.loads(mf.read_text(encoding="utf-8")).get("status") == "wip":
            raise HTTPException(403, f"widget '{name}' 仍在开发中,审核通过后才能启用")
    except HTTPException:
        raise
    except Exception:
        pass

    cfg = {"active": []}
    if USER_WIDGETS_PATH.exists():
        try:
            cfg = json.loads(USER_WIDGETS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    active = cfg.get("active", []) or []
    if enable and name not in active:
        active.append(name)
    elif not enable and name in active:
        active = [x for x in active if x != name]
    cfg["active"] = active
    # A-H9: atomic + rotate
    _safe_write_text(USER_WIDGETS_PATH,
        json.dumps(cfg, indent=2, ensure_ascii=False), rotate=True)
    return {"ok": True, "name": name, "enabled": enable, "active": active}


def _insert_block(f: Path, time_str: str, tag: str = "", title: str = "", author: str = "ai", body: str = "") -> dict:
    """加新条目。
    - 块不存在 → 新建 H1 + 一个 ## #tag title 的 H2
    - 块已存在 → append 新的 H2 到该块下(同时间多条目)
    tag/title 都可空,空时落 "## #新" 占位让 parser 不过滤(模板裸 ## 会被过滤)
    body = H2 下的散文正文(§ H5 result + significance)。标题-only 条目违反日记
    协议,tool schema 把 body 设 required;这里仍兼容空(老调用路径/前端)。
    Time can be HH:MM (half-width) or HH：MM (full-width). Stored as full-width.

    author='ai' (默认) 或 'user',新 H2 末尾 stamp @{author}。owner 决定后续 patch
    权限(详 _patch_block authorship boundary)。
    """
    m = re.fullmatch(r'\s*(\d{1,2})\s*[：:]\s*(\d{2})\s*', time_str)
    if not m:
        return {"error": "时间格式必须是 HH:MM,例如 9:15 或 16:42"}
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return {"error": f"时间超范围 (要 0:00 - 23:59)"}
    new_min = hh * 60 + mm

    text = f.read_text(encoding="utf-8")
    baseline_sha = _sha256_text(text)
    lines = text.splitlines()

    # 拼新 H2: tag 优先,兜底 #新;末尾 stamp @author 给 authorship boundary 用
    tag_clean = tag.strip().lstrip("#") or "新"
    h2_line = f"## #{tag_clean}" + (f" {title.strip()}" if title.strip() else "") + f" @{author}"
    # H2 + 正文一体落盘:body 空时 entry 只有标题行(老路径兼容,tool 层会提醒补写)
    body_lines = [ln.rstrip() for ln in (body or "").strip().splitlines()]
    entry_lines = [h2_line] + ([""] + body_lines if body_lines else [])

    # 找现有同时间块 + 找按时序插入位置
    existing_h1_idx = None
    insert_idx = None
    for i, ln in enumerate(lines):
        m1 = TIME_H1_RE.match(ln)
        if m1:
            em = int(m1.group(1)) * 60 + int(m1.group(2))
            if em == new_min:
                existing_h1_idx = i
                break
            if em > new_min and insert_idx is None:
                insert_idx = i

    if existing_h1_idx is not None:
        # 块已存在 → APPEND 新 H2 到块尾(每段 tag+title 是独立叙事,UI 层做时间去重显示)
        end_idx = len(lines)
        for j in range(existing_h1_idx + 1, len(lines)):
            if TIME_H1_RE.match(lines[j]):
                end_idx = j
                break
        # 倒查到非 --- 非空的真实块尾
        body_end = end_idx
        while body_end > existing_h1_idx + 1 and (not lines[body_end - 1].strip() or lines[body_end - 1].strip() == "---"):
            body_end -= 1
        # 若块只有占位 `##` 一行,直接替换它(否则 append)
        only_placeholder = False
        if body_end == existing_h1_idx + 2 and lines[existing_h1_idx + 1].strip() == "##":
            lines[existing_h1_idx + 1:existing_h1_idx + 2] = entry_lines
            only_placeholder = True
        elif body_end > existing_h1_idx + 1:
            # 检查 placeholder ## 在范围内
            for j in range(existing_h1_idx + 1, body_end):
                if lines[j].strip() == "##":
                    lines[j:j + 1] = entry_lines
                    only_placeholder = True
                    break
        if not only_placeholder:
            lines = lines[:body_end] + ["", *entry_lines, ""] + lines[body_end:]

        new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        with _get_vault_md_lock(str(f)):
            actual = f.read_text(encoding="utf-8")
            if _sha256_text(actual) != baseline_sha:
                return {"error": f"vault md `{f.name}` 在 insert 期间被外部修改,拒绝覆盖。",
                        "conflict": True, "file": _pretty_rel(f)}
            _safe_write_text(f, new_text, rotate=True)
        vault_git.commit_after_write(VAULT_DIR, f"insert {f.stem} {hh}:{mm:02d} #{tag_clean}", author=author, paths=[f])
        return {"ok": True, "appended_to_existing": True, "h2": h2_line,
                "file": _pretty_rel(f)}

    new_h1 = f"# {hh}：{mm:02d}"
    if insert_idx is not None:
        new_block = [new_h1, "", *entry_lines, "", "---", ""]
        new_lines = lines[:insert_idx] + new_block + lines[insert_idx:]
    else:
        new_lines = lines + ["", "---", "", new_h1, "", *entry_lines]

    new_text = "\n".join(new_lines) + ("\n" if text.endswith("\n") else "")
    with _get_vault_md_lock(str(f)):
        actual = f.read_text(encoding="utf-8")
        if _sha256_text(actual) != baseline_sha:
            return {"error": f"vault md `{f.name}` 在 insert 期间被外部修改,拒绝覆盖。",
                    "conflict": True, "file": _pretty_rel(f)}
        _safe_write_text(f, new_text, rotate=True)
    vault_git.commit_after_write(VAULT_DIR, f"insert {f.stem} {hh}:{mm:02d} #{tag_clean}", author=author, paths=[f])
    return {"ok": True, "inserted": new_h1, "file": _pretty_rel(f)}


# ── daily-task 维护(真相源 + 今天文件双写) ─────────────────────────
# 真相源 = vault/daily-tasks.md(用户拥有,跟着 vault 走)。
# 之前用 ~/.claude/skills/.../SCHEDULE_TEMPLATE.md 作模板顶部源,
# 但 new-day.sh 不读它而是 hardcode → 5.15 加的 肌酸 第二天就丢。
# 现在两边(new-day.sh + tool_manage_daily_task)都读写这个真相源。
DAILY_TASKS_SOURCE = VAULT_DIR / "daily-tasks.md"
SCHEDULE_TEMPLATE_PATH = DAILY_TASKS_SOURCE  # 兼容旧名(下方 _apply_task_op 还在用)

def _top_section_bounds(text: str):
    """找模板/日记顶部 section 的范围(从开头到第一个 `---`)。返回 (start_line, end_line_exclusive)。"""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() == "---":
            return (0, i)
    return None


@app.post("/api/template/task")
async def template_task(req: Request):
    """维护每日任务清单(顶部 section)。action ∈ {add, edit, del}。
    body: {action, text?, old_text?}
      add: text 是新项内容(不含 '- [ ] ' 前缀)
      edit: old_text 匹配现有行片段,text 是新内容
      del: old_text 匹配要删的行
    同时改模板(影响未来) + 当天文件(立刻生效)。
    """
    body = await req.json()
    action = body.get("action", "")
    text = (body.get("text") or "").strip()
    old_text = (body.get("old_text") or "").strip()
    if action not in ("add", "edit", "del"):
        raise HTTPException(400, "action must be add | edit | del")

    targets = []
    if SCHEDULE_TEMPLATE_PATH.exists():
        targets.append(SCHEDULE_TEMPLATE_PATH)
    today_f = find_today_journal()
    if today_f:
        targets.append(today_f)

    results = []
    for f in targets:
        results.append(_apply_task_op(f, action, text, old_text))
    return {"ok": True, "results": results}


def _apply_task_op(f: Path, action: str, text: str, old_text: str) -> dict:
    raw = f.read_text(encoding="utf-8")
    lines = raw.splitlines()
    bounds = _top_section_bounds(raw)
    if bounds is None:
        return {"file": _pretty_rel(f), "error": "找不到顶部 section (缺 --- 分割)"}
    start, end = bounds  # [start, end)

    # 顶层 task only — 不动 daily_dose>1 task 下挂的进度子 box
    def _is_top_task_line(s: str) -> bool:
        return s.startswith("- [")

    if action == "add":
        # 找最后一个顶层 '- [' 行,在它后面加;否则在 end 前加
        insert_after = end
        for j in range(end - 1, start - 1, -1):
            if _is_top_task_line(lines[j]):
                # 跳过该顶层项的子 box,新行插在子 box 之后
                k = j + 1
                while k < end and re.match(r"^\s+-\s*\[[ x]\]", lines[k]):
                    k += 1
                insert_after = k
                break
        new_line = f"- [ ] {text}"
        new_lines = lines[:insert_after] + [new_line] + lines[insert_after:]
    elif action == "edit":
        target_idx = None
        for j in range(start, end):
            if old_text and old_text in lines[j] and _is_top_task_line(lines[j]):
                target_idx = j
                break
        if target_idx is None:
            return {"file": str(f), "error": f"找不到含 '{old_text}' 的任务项"}
        # 保留 checkbox 状态前缀,替换文本部分
        checkbox_match = re.match(r'^(-\s*\[[ x]\]\s*)(.*)', lines[target_idx])
        if checkbox_match:
            lines[target_idx] = checkbox_match.group(1) + text
        else:
            lines[target_idx] = f"- [ ] {text}"
        new_lines = lines
    else:  # del
        target_idx = None
        for j in range(start, end):
            if old_text and old_text in lines[j] and _is_top_task_line(lines[j]):
                target_idx = j
                break
        if target_idx is None:
            return {"file": str(f), "error": f"找不到含 '{old_text}' 的任务项"}
        # 删父行 + 紧随的进度子 box(若有)
        end_idx = target_idx + 1
        while end_idx < end and re.match(r"^\s+-\s*\[[ x]\]", lines[end_idx]):
            end_idx += 1
        new_lines = lines[:target_idx] + lines[end_idx:]

    new_text = "\n".join(new_lines) + ("\n" if raw.endswith("\n") else "")
    _safe_write_text(f, new_text, rotate=True)
    try:
        rel = _pretty_rel(f)
    except Exception:
        rel = str(f)
    return {"file": rel, "ok": True}


def _patch_block(f: Path, time_label: str, new_md: str, author: str = "ai",
                 allow_h2_rename: bool = False) -> dict:
    """Replace the body between `# {time}` and the next `# H1` or `---` boundary.
    new_md should NOT include the H1 line itself — only what comes after it.

    author='ai' (默认,最严格) — 撞 @user 块拒绝。author='user' 可改任何块。
    @marker 解析:看时间块内第一个 H2 行的 @user/@ai。无 marker → @user(失败安全)。
    allow_h2_rename=True:跳过 H2 不匹配的拒,让 AI 显式 rename H2。仅在
    用户明示要改标题时由 tool caller 传。
    """
    text = f.read_text(encoding="utf-8")
    baseline_sha = _sha256_text(text)
    lines = text.splitlines()
    h, m = time_label.split(":")
    # match either "# 18：30" (full-width) or "# 18:30" (half-width)
    re_h1 = re.compile(rf'^# {int(h)}[：:]{m}\s*$')

    start = None
    for i, ln in enumerate(lines):
        if re_h1.match(ln):
            start = i
            break
    if start is None:
        return {"error": f"time block # {time_label} not found in {f.name}"}

    # find end: next # H1 (any time) OR `---` line, whichever comes first AFTER content
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if TIME_H1_RE.match(lines[j]) or lines[j].strip() == "---":
            end = j
            break

    # authorship boundary:扫块内首条 H2,看 owner。AI 调不能改 @user 块。
    if author != "user":
        for k in range(start + 1, end):
            if lines[k].startswith("## "):
                owner = _check_author(lines[k])
                if owner == "user":
                    return {"error": f"block @ {time_label} 是 @user 所有,AI 不能 patch。"
                                     f"想加评论用 append_journal_comment;想新加 entry 用 insert_journal_block。"}
                break  # 只看第一个 H2

    # AI 误用 patch 当 insert 的反向防御 — 对比现存第一条 H2 vs new_md 第一条 H2:
    # 完整行(除 @marker 之外)不一致 → AI 大概率是想"加新 entry"误用 patch,
    # 会把原 entry 整段吃掉。拒。
    # 5.29 16:00 联想 entry 被 patch 写舜宇光学吃掉的真事故 = 这条 guard 没有的恶果。
    # 注意:同 tag 同 title 但不同 body 是合法 patch(典型用例:补充 / 改散文措辞)。
    if author != "user":
        existing_first_h2 = None
        for k in range(start + 1, end):
            if lines[k].startswith("## "):
                existing_first_h2 = lines[k]
                break
        new_first_h2 = None
        for ln in new_md.splitlines():
            if ln.startswith("## "):
                new_first_h2 = ln
                break

        def _strip_author(h2):
            # 去掉末尾 @ai / @user / @<handle> 让对比看 tag + title
            return re.sub(r"\s*@\S+\s*$", "", h2 or "").strip()

        if (existing_first_h2 and new_first_h2
                and existing_first_h2.strip() != "##"
                and _strip_author(existing_first_h2) != _strip_author(new_first_h2)
                and not allow_h2_rename):
            return {"error":
                f"block @ {time_label} 已有 H2:`{existing_first_h2.strip()}`。"
                f"你的 new_md 第一个 H2 是:`{new_first_h2.strip()}` — 不一样。"
                f"patch_journal_block 会**整段替换**,原 H2 + body 会被吃掉。"
                f"如果想给块加新 H2 → 用 insert_journal_block(append,不覆盖)。"
                f"如果用户明示要改这个 entry 的标题 → 重传带 allow_h2_rename=true。"
                f"如果真要替换 = 放弃原 entry(数据丢失),先 read_today_schedule 确认要丢什么,"
                f"再在 new_md 里同时写原 H2 段 + 新 H2 段。"
            }

    new_lines = lines[:start + 1] + [""] + new_md.rstrip().splitlines() + [""] + lines[end:]
    new_content = "\n".join(new_lines) + ("\n" if text.endswith("\n") else "")
    # 锁内重读 + sha256 比对,防 Obsidian 并发编辑被静默覆盖(C5)
    with _get_vault_md_lock(str(f)):
        actual = f.read_text(encoding="utf-8")
        if _sha256_text(actual) != baseline_sha:
            return {"error": f"vault md `{f.name}` 在 patch 期间被外部修改(Obsidian?),"
                             f"拒绝覆盖。请前端 force-reload 后让用户重提交。",
                    "conflict": True, "file": _pretty_rel(f)}
        _safe_write_text(f, new_content, rotate=True)
    vault_git.commit_after_write(VAULT_DIR, f"patch {f.stem} {time_label}", author=author, paths=[f])
    return {"patched": time_label, "file": _pretty_rel(f)}


# PATTERN: util — append-only journal comment (authorship boundary 安全旁路)
# USE WHEN: AI 想给 @user 块留评论但不能动原文 — append 到 body 末尾
# COPY THIS: 改 prefix 标记(默认 *AI:* 给 user 看出来是 AI 加的)
def _append_comment_to_block(f: Path, time_label: str, comment_md: str) -> dict:
    """在指定时间块 body 末尾 append 一段 comment。**不修改原 H2 / 原 body**。
    给 @user 块写"穿线 / 回看 / AI 注"用 — _patch_block 拒绝 @user 时的合法替代路径。
    """
    text = f.read_text(encoding="utf-8")
    baseline_sha = _sha256_text(text)
    lines = text.splitlines()
    h, m = time_label.split(":")
    re_h1 = re.compile(rf'^# {int(h)}[：:]{m}\s*$')

    start = None
    for i, ln in enumerate(lines):
        if re_h1.match(ln):
            start = i
            break
    if start is None:
        return {"error": f"time block # {time_label} not found in {f.name}"}

    # 找块结束:next H1 / `---`
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if TIME_H1_RE.match(lines[j]) or lines[j].strip() == "---":
            end = j
            break

    # 在 end 之前插入 comment(保留原 body)。前留个空行让 markdown 段落分开。
    comment_lines = comment_md.rstrip().splitlines()
    new_lines = lines[:end] + [""] + comment_lines + [""] + lines[end:]
    new_content = "\n".join(new_lines) + ("\n" if text.endswith("\n") else "")
    # 锁内重读 + sha256 比对,防 Obsidian 并发编辑被静默覆盖(C5)
    with _get_vault_md_lock(str(f)):
        actual = f.read_text(encoding="utf-8")
        if _sha256_text(actual) != baseline_sha:
            return {"error": f"vault md `{f.name}` 在 append-comment 期间被外部修改,"
                             f"拒绝覆盖。请刷新后重试。",
                    "conflict": True, "file": _pretty_rel(f)}
        _safe_write_text(f, new_content, rotate=True)
    vault_git.commit_after_write(VAULT_DIR, f"append-comment {f.stem} {time_label}", author="ai", paths=[f])
    return {"appended": time_label, "file": _pretty_rel(f)}


# ── vault config (Obsidian-style 选址) ──────────────────────────────
@app.get("/api/vault")
def vault_status():
    """前端启动调:看要不要弹 setup modal。"""
    return {
        "active_vault": str(DATA_HOME),
        "known_vaults": vault_config.list_known(),
        "setup_required": vault_config.setup_required(),
        "config_path": str(vault_config.config_path()),
    }


@app.get("/api/vault/discover_obsidian")
def vault_discover_obsidian():
    """读 Obsidian 自己 config 拿用户已建的 vaults。"""
    return {"vaults": vault_config.discover_obsidian_vaults()}


@app.post("/api/vault/set")
async def vault_set(req: Request):
    """切到指定 vault。body: {path, name?}
    会:验证目录可读写 → 写 config → 返提示 (server 需重启 / 页面刷新)
    """
    body = await req.json()
    path = (body.get("path") or "").strip()
    name = (body.get("name") or "").strip()
    if not path:
        raise HTTPException(400, "need path")
    p = Path(path).expanduser().resolve()
    # 目录不存在尝试创建
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise HTTPException(400, f"cannot create vault dir: {e}")
    if not p.is_dir():
        raise HTTPException(400, f"path is not a directory: {p}")
    # 验证可写:试着 touch 一个文件再删
    try:
        test = p / ".human-ai-write-test"
        test.write_text("ok")
        test.unlink()
    except Exception as e:
        raise HTTPException(400, f"vault not writable: {e}")
    cfg = vault_config.set_active(str(p), name)
    needs_restart = (str(p) != str(DATA_HOME))
    return {
        "ok": True,
        "active_vault": cfg["active_vault"],
        "needs_restart": needs_restart,
        "hint": "新 vault 已写入 config。重启 gateway server 生效。" if needs_restart else "vault 已确认。",
    }


# ── static serving ───────────────────────────────────────────────────
@app.get("/")
def root():
    return FileResponse(GATEWAY_DIR / "index.html")

# Dev-mode 防黏缓存:JS/CSS/HTML 强制 revalidate,
# 避免用户改完代码不刷新就看不见 + 修了 bug 用户还是看到旧版
@app.middleware("http")
async def no_cache_for_static_assets(request, call_next):
    response = await call_next(request)
    path = request.url.path
    # /api/* 也禁缓存:Tauri 的 WKWebView 走系统网络栈,会缓存 API GET 响应 →
    # journal(15s)/thread(3s)轮询每次拿到旧数据,"AI/人输入后最新的不显示"。
    # 浏览器靠 Cmd+R 强制重新验证,Tauri 没 Cmd+R,所以这条对壳是刚需。
    if path.endswith((".html", ".js", ".css")) or path == "/" or path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# /data/* — daily-task images + map (顶层 data/,跟 gateway/ 平级)
if DATA_DIR.exists():
    app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")

# everything else: serve from gateway/
app.mount("/", StaticFiles(directory=str(GATEWAY_DIR), html=True), name="gateway")


if __name__ == "__main__":
    import uvicorn

    # PyInstaller --noconsole(Win 双击启动 standalone 路径)stdout/stderr 是 None;
    # uvicorn default log formatter 检 sys.stdout.isatty() 直接炸(0.1.5 Win 崩那条)。
    # 给 stdout/stderr 接 devnull,isatty() 返 False(走非彩色路径)。
    # Tauri sidecar 模式不命中(stdout 是 pipe 不是 None),那条由 Tauri rust 侧
    # drain rx channel 修(0.1.9 src-tauri/src/lib.rs)。
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    # 默认 4321;GATEWAY_PORT env 可覆盖(测试 / 多实例)
    port = int(os.environ.get("GATEWAY_PORT", "4321"))
    # 写真实端口到已知文件,给外部 launchd cron 发现用(eval 21:30 / pulse-refresh 21:00)。
    # Tauri 壳用动态端口 → cron 不能再写死 4321(否则连不上,5.27 留言板/PULSE 停更的真因)。
    # 配套:~/.human-ai/bin/gw-cron.sh 读这个文件再 curl。
    try:
        _port_file = Path(os.path.expanduser("~/.human-ai/.gateway-port"))
        _port_file.parent.mkdir(parents=True, exist_ok=True)
        _tmp = _port_file.with_suffix(".port.tmp")
        _tmp.write_text(str(port), encoding="utf-8")
        _tmp.replace(_port_file)  # 原子替换
    except Exception as _e:
        print(f"[gateway] 写 .gateway-port 失败(cron 发现端口会受影响): {_e}")
    print(f"[gateway] starting on http://localhost:{port}")
    print(f"[gateway] static root: {GATEWAY_DIR}")
    print(f"[gateway] config: {CONFIG_PATH} {'(set)' if CONFIG_PATH.exists() else '(missing — copy .gateway-config.example.json)'}")

    # PyInstaller .app 双击 Mac 场景:macOS 期待 GUI 窗口,我们 headless → Dock 一直
    # bounce。Info.plist LSUIElement=true 让 .app 当后台 app(无 Dock 图标),同时
    # 这里启动后自动开浏览器到 gateway,用户立刻看到界面而不是空 Dock。
    # GATEWAY_NO_OPEN=1 可禁(test / headless / 服务器场景)。
    if not os.environ.get("GATEWAY_NO_OPEN"):
        def _open_browser():
            import time as _t
            _t.sleep(1.5)  # 等 uvicorn 监听就绪
            url = f"http://127.0.0.1:{port}"
            try:
                if sys.platform == "darwin":
                    subprocess.Popen(["open", url])
                elif sys.platform.startswith("win"):
                    subprocess.Popen(["cmd", "/c", "start", "", url], shell=False)
                else:
                    subprocess.Popen(["xdg-open", url])
            except Exception as e:
                log.warning(f"auto-open browser failed: {e}")
        threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
