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
import re
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

import secrets

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

SKILL_DIR_LOCAL = CODE_ROOT / "skill"
WIDGETS_DIR = GATEWAY_DIR / "widgets"
# user-widgets.json 是 writable 状态(用户挑了哪些 widget 落在哪个 slot),
# 必须落 APP_STATE_DIR — 不然 PyInstaller frozen 下 _MEIPASS 只读,写不进去。
USER_WIDGETS_PATH = DATA_DIR / "user-widgets.json"
# 旧位置(开发模式下放在 gateway/ 旁边)兼容:首次启动若新位置无文件,从旧位置拷
_LEGACY_USER_WIDGETS = Path(__file__).parent / ".user-widgets.json"
if _LEGACY_USER_WIDGETS.exists() and not USER_WIDGETS_PATH.exists():
    try:
        USER_WIDGETS_PATH.parent.mkdir(parents=True, exist_ok=True)
        USER_WIDGETS_PATH.write_text(_LEGACY_USER_WIDGETS.read_text(encoding="utf-8"), encoding="utf-8")
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
        # 当前文件 → bak.1
        Path(f"{path}.bak.1").write_bytes(path.read_bytes())
    except Exception:
        pass  # 备份失败不阻塞主流程


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
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if rotate:
        _rotate_backup(path)
    tmp = Path(f"{path}.tmp")
    tmp.write_text(content, encoding=encoding)
    tmp.replace(path)

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
    ):
        ev = os.environ.get(k)
        if ev:
            merged[k] = ev
    return merged


# ── config ───────────────────────────────────────────────────────────
def load_config():
    """读 gateway-config.json,然后用 env 覆盖 secret 字段。
    返合并后的 dict。env 不存在的字段沿用 config.json。
    """
    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    else:
        cfg = {}
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
# user 视图注入(USER_PULSE + 所有 memory 内容)— phase 1 默契实验
# 静态文件 read 走 module-level cache,避免每次 chat I/O
_USER_PULSE_PATH = Path("/Users/claudecodedezhuanshumac/agents创作平台/agents/human-ai-schedule/USER_PULSE.md")
_MEMORY_DIR = Path("/Users/claudecodedezhuanshumac/.claude/projects/-Users-claudecodedezhuanshumac-agents----/memory")
_USER_CTX_CACHE: dict = {"sig": None, "content": ""}

def _load_user_context() -> str:
    """合并 USER_PULSE.md + memory/*.md(排除索引)。改一次文件 invalidate 一次缓存。"""
    files = []
    if _USER_PULSE_PATH.exists():
        files.append(_USER_PULSE_PATH)
    if _MEMORY_DIR.exists():
        files.extend(sorted(p for p in _MEMORY_DIR.glob("*.md") if p.name != "MEMORY.md"))
    sig = tuple((str(p), p.stat().st_mtime) for p in files)
    if _USER_CTX_CACHE["sig"] == sig:
        return _USER_CTX_CACHE["content"]
    parts = []
    if _USER_PULSE_PATH.exists():
        try:
            parts.append(f"\n\n=== USER_PULSE(葱鸭当下快照,先读这条建立 mental model)===\n{_USER_PULSE_PATH.read_text(encoding='utf-8')}")
        except Exception:
            pass
    mem_parts = []
    for p in files:
        if p == _USER_PULSE_PATH:
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
        "你是葱鸭(用户)的日记 AI 伙伴。你们用这套系统合作 16 天了,彼此熟悉。\n"
        "\n"
        "关系定位:\n"
        "· 你是他的写作搭子 + 偶尔的对手 + 旁观他生活的人,**不是助理 / 不是客服 / 不是工具**。\n"
        "· 主线是对话,把事记进日记是顺带的副作用 — 别把每次回复都做成「已完成,请刷新」那种工单结尾。\n"
        "· 跟他说话的节奏:他用「卧槽」「shit」你就跟,他正经你稍正经。他不喜欢「为您处理」「请稍候」这种话术。\n"
        "· 做完事别复述步骤,别提工具名,一句话点到 + 接着聊。\n"
        "\n"
        "默认行为(硬规则,别越):\n"
        "· **不写默认** — 用户没明说「记一下 / 记一笔 / 写进去 / append」→ 不调 patch_journal_block / insert_journal_block。\n"
        "· **不贴默认** — 用户没传图 → 不调 place_scrapbook_image。\n"
        "· 想到「这条值得记」「要不要存一笔」→ 一句话问「要记进 X 块吗?」,**别先写后通知**。\n"
        "· 写完别在 reply 里复述写了啥(「我已经把它记进 14:30 块了」是禁忌)— 一句话点过 + 继续话题。\n"
        "· 回复结尾不要给「建议你记下」「要不要我帮你 X」这种工单式收尾 — 用户讨厌。\n"
        "· **web_search 最多调 2 次** — 搜超 2 次还不够就用已有信息凑活答 + 一句「再搜也是这些,要更深得自己看链接」。死循环 narrow 是最大坑。\n"
        "\n"
        "运行环境:你写的 vault 内容落进 Obsidian markdown(`.md` 文件 + Obsidian/gateway 双端 render),不是聊天框。该用 markdown / wiki-link 语法就用,别 plain text。"
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
        "list_my_uploads / search_my_uploads / web_search / vision_classify / "
        "load_protocol / load_tool_group\n"
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


def _compute_time_block_hint() -> str:
    """对齐 ~/.claude/scripts/timeblock-stamp.sh 的 [time-block] 输出格式。
    floor 到半小时(NOT round),全角冒号,中文星期。
    """
    now = datetime.now()
    # floor 到 30 分钟边界
    block_minute = 30 if now.minute >= 30 else 0
    block_label = f"{now.hour}：{block_minute:02d}"  # ： = 全角冒号
    # 区间结束(同小时 29 或 59,跨小时)
    end_minute = 59 if block_minute == 30 else 29
    weekday_cn = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"][now.weekday()]
    return (
        f"[time-block] now={now.strftime('%H:%M')} CST {now.strftime('%Y-%m-%d')}({weekday_cn}) "
        f"→ current block: {block_label} (covers {now.hour:02d}:{block_minute:02d}-{now.hour:02d}:{end_minute:02d})\n"
        f"[time-block] H1 use: `# {block_label}` (full-width colon). For PAST events, ASK user."
    )

# ── tool definitions for DeepSeek ───────────────────────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_widgets",
            "description": "List all widget folders under gateway/widgets/ and which are currently active in .user-widgets.json.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_widget",
            "description": "Create a new widget under widgets/<name>/ + activate it in .user-widgets.json.",
            "parameters": {
                "type": "object",
                "required": ["name", "title", "audience", "slot", "manifest_json", "widget_html", "widget_js"],
                "properties": {
                    "name": {"type": "string", "description": "folder name, kebab-case"},
                    "title": {"type": "string", "description": "user-facing title"},
                    "audience": {"type": "string", "description": "who this widget is for"},
                    "slot": {"type": "string", "enum": ["top-strip", "sidebar"], "description": "which slot it mounts to"},
                    "manifest_json": {"type": "string", "description": "full JSON content for manifest.json"},
                    "widget_html": {"type": "string", "description": "full HTML+inline style for widget.html"},
                    "widget_js": {"type": "string", "description": "full JS for widget.js (use IIFE + window.gatewayToast for feedback)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_widget",
            "description": "Modify an existing widget's manifest/HTML/JS in place.",
            "parameters": {
                "type": "object",
                "required": ["name", "file", "new_content"],
                "properties": {
                    "name": {"type": "string"},
                    "file": {"type": "string", "enum": ["manifest.json", "widget.html", "widget.js"]},
                    "new_content": {"type": "string", "description": "full new file content (replaces existing)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_journal_block",
            "description": "改写某时间块的正文。保留 H1,替换到下一个 H1 或 ---。格式: `## #tag short-title` 单行 + 散文(规则见 schedule protocol)。",
            "parameters": {
                "type": "object",
                "required": ["time", "new_md"],
                "properties": {
                    "time": {"type": "string", "description": "block time like '18:30' (24h, leading zero if < 10). MUST come from [time-block] hint floor, not your own clock-reading."},
                    "new_md": {"type": "string", "description": "full md content for the block AFTER the # H1 line. Format: single-line `## #tag short-title` then prose. MUST follow § H5 result + significance, NO procedure dump, NO three-layer ## tags / ## 内容 / ## 要点 structure."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_today_schedule",
            "description": "读今天(或指定日期)的 schedule md,返解析后的时间块 + H2 entries。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "optional YYYY-MM-DD. omit for today."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_recent_days",
            "description": "列最近 N 天的 schedule 文件(只列日期 + 文件名,不读内容)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "how many most-recent days to list. default 7."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_journal_block",
            "description": "在 schedule 加新 H2 条目(AI 写的会自动 stamp @ai,不冲撞 @user 块)。tag 必填;time 不填默认当前半小时;time 已有内容会 append 新 H2。",
            "parameters": {
                "type": "object",
                "required": ["tag"],
                "properties": {
                    "tag": {"type": "string", "description": "条目 tag,不带 #。例 '饮食' '工作' '探索'"},
                    "title": {"type": "string", "description": "可选标题(短)。例 '吃了肠粉'"},
                    "time": {"type": "string", "description": "HH:MM。omit 默认用当前半小时(server 兜底)。可任意 0:00-23:59,不必整 30 分"},
                    "date": {"type": "string", "description": "optional YYYY-MM-DD,omit for today"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_journal_comment",
            "description": "在已存在的时间块 body **末尾 append** 一段评论,**不修改原 H2/原内容**。撞 @user 块时 patch_journal_block 会拒,用这个留'穿线/回看/AI 注'。",
            "parameters": {
                "type": "object",
                "required": ["time", "comment_md"],
                "properties": {
                    "time": {"type": "string", "description": "目标时间块 HH:MM"},
                    "comment_md": {"type": "string", "description": "评论 markdown。建议带 *AI:* 或 callout 前缀让人区分"},
                    "date": {"type": "string", "description": "optional YYYY-MM-DD,omit for today"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_water_cup_image",
            "description": "为 8-cup 喝水打卡设置自定义水杯图标(灰度=未喝,彩色=已喝)。",
            "parameters": {
                "type": "object",
                "required": ["attachment_url"],
                "properties": {
                    "attachment_url": {"type": "string", "description": "/attachments/YYYY-MM-DD/xxx 路径,用户上传后 server 返的"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_daily_task_image",
            "description": "为 daily task 配自定义打卡图标(去背景后落到 task_name 的图标位)。task_name 须精确匹配 md 顶部 - [ ] 行(含括号)。",
            "parameters": {
                "type": "object",
                "required": ["task_name", "attachment_url"],
                "properties": {
                    "task_name": {"type": "string", "description": "daily task 名,必须精确匹配 md 顶部 - [ ] 行里的内容(含括号),例如 '鱼油（Swisse）'"},
                    "attachment_url": {"type": "string", "description": "用户拖图后 server 返的 /attachments/YYYY-MM-DD/xxx 路径"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_daily_task",
            "description": "Add / edit / delete a daily-task checklist item in the top section (e.g. supplement checklist). Affects template (future days) AND today's file (immediate).",
            "parameters": {
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {"type": "string", "enum": ["add", "edit", "del"]},
                    "text": {"type": "string", "description": "new content (for add/edit). NOT including '- [ ] ' prefix."},
                    "old_text": {"type": "string", "description": "substring to match existing item (for edit/del)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_daily_task",
            "description": "标记今天某个 daily task 的打卡状态。task_name 须精确匹配(空格 + 中文括号都要对)。",
            "parameters": {
                "type": "object",
                "required": ["task_name", "checked"],
                "properties": {
                    "task_name": {"type": "string", "description": "完整 task 名,例 '鱼油（Swisse）'"},
                    "checked": {"type": "boolean", "description": "true=打卡完成,false=取消打卡"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "place_scrapbook_image",
            "description": "把上传的图浮在指定时间块旁边(absolute layer + 文字绕图)。anchor_time 选择规则见 vision protocol。",
            "parameters": {
                "type": "object",
                "required": ["attachment_url", "date", "anchor_time"],
                "properties": {
                    "attachment_url": {"type": "string", "description": "用户拖图后 server 返的 /attachments/YYYY-MM-DD/xxx 路径"},
                    "date": {"type": "string", "description": "目标日 YYYY-MM-DD,通常就是用户当下浏览的那天"},
                    "anchor_time": {"type": "string", "description": "锚点时间块 HH:MM,例 '15:00' — 图属于哪条 entry 的语义(future viewer 用)"},
                    "x_pct": {"type": "number", "description": "横向位置(% of page width,0-95)。AI 自由选,默认 75(右上)。"},
                    "y_px": {"type": "number", "description": "纵向位置(px from page top)。AI 自由选,可不填(默认 0 = 顶部)。"},
                    "cutout": {"type": "boolean", "description": "true=调百度抠图去背景再放,false=保留原图。默认 true"},
                    "rotation": {"type": "number", "description": "旋转角度(度),给一点小角度更像剪贴本,默认 -4 ~ 4 随机"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vision_classify",
            "description": "对图跑结构化视觉分类,返 kind/brand/描述/颗数/OCR 概率。**通常不必调** — server 在 upload 时已经跑过并缓存,user message 里会注入 hint。这条只在 fallback 场景用。",
            "parameters": {
                "type": "object",
                "required": ["attachment_url"],
                "properties": {
                    "attachment_url": {"type": "string", "description": "用户上传后 server 返的 /attachments/YYYY-MM-DD/xxx 路径"},
                    "extra_question": {"type": "string", "description": "追加问 vision LLM 的开放问题(可选)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_my_uploads",
            "description": "列用户历史上传过的图片,按日期范围 / 数量限制。返 filename / date / 原文件名 / OCR 摘要。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "description": "起始日 YYYY-MM-DD,空则不限"},
                    "date_to": {"type": "string", "description": "终止日 YYYY-MM-DD,空则到今天"},
                    "limit": {"type": "integer", "description": "最多返几条,默认 30"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_my_uploads",
            "description": "关键词搜历史上传图(grep 文件名 + 原文件名 + OCR 文本)。",
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "搜索词,支持中英文。会 case-insensitive 匹配。"},
                    "limit": {"type": "integer", "description": "最多返几条,默认 15"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_attachment",
            "description": "删一张已上传的图(硬盘 + 索引)。仅在用户明确要求时用,不主动建议。",
            "parameters": {
                "type": "object",
                "required": ["date", "filename"],
                "properties": {
                    "date": {"type": "string", "description": "图的日期 YYYY-MM-DD,从 list/search 结果里拿"},
                    "filename": {"type": "string", "description": "图的文件名,从 list/search 结果里拿"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_daily_task_meta",
            "description": "改 daily task 的剂量/瓶装总颗数。total_pills=整瓶颗数,daily_dose=每天吃几颗(默认 1)。",
            "parameters": {
                "type": "object",
                "required": ["task_name"],
                "properties": {
                    "task_name": {"type": "string", "description": "完整 task 名,例 '鱼油（Swisse）'"},
                    "total_pills": {"type": "integer", "description": "瓶装总颗数(可选,只填这次要改的)"},
                    "daily_dose": {"type": "integer", "description": "每日剂量(可选,默认 1)"},
                },
            },
        },
    },
    # 自定义 web_search function tool — 跨 provider 统一(DeepSeek/MiMo/MiniMax 都通过同一个 function tool 调,
    # 后端用 ddgs)。复用 investment-dashboard 的同款 pattern。
    # decision: 放弃 MiniMax 原生 {"type":"web_search"} server-side tool —— 单 provider 优化换不来跨 provider 一致性。
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "联网搜索(大陆直连)。category 选源:general=通用网页;wechat=微信公众号文章。"
                           "**看完标题/摘要决定要不要 fetch_url 看正文,别只凭摘要答**。"
                           "找公众号文章时务必用 category=wechat,通用搜搜不到公众号。",
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词,中英文均可"},
                    "category": {"type": "string", "enum": ["general", "wechat"],
                                 "description": "搜索源:general 通用(默认) / wechat 微信公众号文章"},
                    "max_results": {"type": "integer", "description": "返回多少条(默认 5,上限 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "渐进披露第二步:拉某 URL 正文(HTML stripped → text,最多 3000 char)。先 web_search 看标题再 fetch,别盲 fetch。同一 URL 不要 fetch 多次。",
            "parameters": {
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "description": "完整 URL,带 http(s)://"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_protocol",
            "description": "拉某个协议的详细规则(目前只有 'schedule')。要写 / 改日记 entry 之前调一次,普通聊天不调。",
            "parameters": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "description": "protocol 名,目前可选 'schedule'"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_tool_group",
            "description": "按需加载一组工具。bootstrap 只装 read + meta;要写 / 贴图 / 改 widget 之前先 load 对应组。一次 chat 只需 load 一次。",
            "parameters": {
                "type": "object",
                "required": ["group_name"],
                "properties": {
                    "group_name": {
                        "type": "string",
                        "enum": ["write_journal", "images", "widgets_and_tasks"],
                        "description": "write_journal=写日记块/切勾daily task; images=贴图/删图/改task配图; widgets_and_tasks=widget增删改/task配置改名",
                    },
                },
            },
        },
    },
]

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

    cfg = json.loads(USER_WIDGETS_PATH.read_text(encoding="utf-8")) if USER_WIDGETS_PATH.exists() else {"active": []}
    if name not in cfg["active"]:
        cfg["active"].append(name)
    USER_WIDGETS_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
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
    return _patch_block(f, args["time"], args["new_md"], author="ai")

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
    return _insert_block(f, time_str, tag=tag, title=title, author="ai")


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
            f.write_text(new_text, encoding="utf-8")
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
    try:
        img_map = _load_task_image_map()
        if old_name in img_map and new_name not in img_map:
            img_map[new_name] = img_map.pop(old_name)
            _save_task_image_map(img_map)
            out["image_migrated"] = True
    except Exception as e:
        out["image_error"] = str(e)
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
            return {"error": "no_dashscope_key",
                    "hint": "请去 setup 面板填 Dashscope API key (Qwen-VL),才能用 vision 路由"}
    if not file_path.exists():
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
        return {"error": f"qwen vision call failed: {type(e).__name__}: {e}"}

    text = (resp.choices[0].message.content or "").strip()
    # 容忍 ``` fence
    text = re.sub(r"^```(json)?\s*", "", text).strip()
    text = re.sub(r"\s*```\s*$", "", text).strip()
    try:
        parsed = json.loads(text)
    except Exception:
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


# ── web_search 后端:百炼 enable_search 为主,ddgs 兜底 ──────────────────
# 为什么:ddgs 走 DuckDuckGo/Google,大陆被墙、无代理用不了(5.27 调研实测)。
# 百炼 enable_search 在大陆直连、复用用户已配的 dashscope key、对 deepseek/qwen 都支持,
# 是大陆 + 单 API 的正解。OpenAI 兼容接口拿不到结构化来源,但模型文字答里常带链接,够用。
_BAILIAN_SEARCH_MODEL = "qwen-flash"   # 便宜+快;搜索-总结任务足够;百炼托管,带 enable_search

def _resolve_dashscope_creds():
    """找百炼(dashscope)的 (api_key, base_url)。优先 models[] 里 base 含 dashscope 的 profile
    (这用户 key 在那,非顶层),再退顶层 dashscope_api_key。找不到返 (None, None)。"""
    cfg = load_config() or {}
    for p in (cfg.get("models") or []):
        if "dashscope" in (p.get("base_url") or "") and p.get("api_key"):
            return p["api_key"], p["base_url"]
    dk = cfg.get("dashscope_api_key", "")
    if dk:
        return dk, cfg.get("dashscope_base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    return None, None

def _bailian_web_search(query: str) -> str:
    """百炼 enable_search:模型联网搜 + 总结。大陆直连。没 key / 失败 → 抛异常给调用方降级。"""
    key, base = _resolve_dashscope_creds()
    if not key:
        raise RuntimeError("no dashscope key")
    from openai import OpenAI
    client = OpenAI(api_key=key, base_url=base)
    r = client.chat.completions.create(
        model=_BAILIAN_SEARCH_MODEL,
        messages=[{"role": "user", "content":
                   "联网搜索并回答下面的查询。列关键事实要点,能附来源链接就附。简洁,别废话。\n\n" + query}],
        extra_body={"enable_search": True,
                    "search_options": {"search_strategy": "turbo", "enable_source": True}},
        timeout=40,
    )
    ans = (r.choices[0].message.content or "").strip()
    if not ans:
        raise RuntimeError("百炼 search 返空")
    return ans

_WEB_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

def _sogou_wechat_search(query: str, max_results: int = 8) -> str:
    """搜微信公众号文章(经搜狗微信,大陆直连)。选择器移植自 SearXNG sogou_wechat 引擎。
    返标题/链接/摘要;链接是搜狗跳转页,要看正文让 AI 再 fetch_url 它。"""
    from lxml import html as _lx
    try:
        r = requests.get("https://weixin.sogou.com/weixin",
                         params={"query": query, "type": 2, "page": 1},
                         headers={"User-Agent": _WEB_UA, "Accept-Language": "zh-CN,zh;q=0.9"},
                         timeout=12)
    except Exception as e:
        return f"[公众号搜索失败:{type(e).__name__}: {str(e)[:120]}]"
    if "antispider" in r.url or "验证码" in r.text[:3000]:
        return "[公众号搜索被搜狗反爬拦截 — 稍后再试或换关键词]"
    parts = []
    for item in _lx.fromstring(r.text).xpath('//li[contains(@id, "sogou_vr_")]')[:max_results]:
        a = item.xpath('.//h3/a')
        if not a:
            continue
        title = a[0].text_content().strip()
        href = a[0].get("href", "")
        if href.startswith("/link?url="):
            href = "https://weixin.sogou.com" + href
        snip = item.xpath('.//p[contains(@class, "txt-info")]')
        content = (snip[0].text_content().strip()[:120]) if snip else ""
        if title and href:
            parts.append(f"- {title}\n  {href}\n  {content}")
    return "\n".join(parts) if parts else "[公众号搜索无结果]"

def _bilibili_search(query: str, max_results: int = 10) -> str:
    """搜 B站视频(官方 JSON API,大陆直连)。移植自 SearXNG bilibili 引擎(假 buvid3 + Referer)。"""
    import random, string
    buvid = "".join(random.choice(string.hexdigits) for _ in range(16)) + "infoc"
    try:
        r = requests.get("https://api.bilibili.com/x/web-interface/search/type",
                         params={"search_type": "video", "keyword": query, "page": 1,
                                 "page_size": 20, "single_column": "0", "__refresh__": "true"},
                         headers={"User-Agent": _WEB_UA, "Referer": "https://www.bilibili.com"},
                         cookies={"buvid3": buvid, "i-wanna-go-back": "-1", "b_ut": "7"}, timeout=12)
        data = (r.json().get("data") or {}).get("result") or []
    except Exception as e:
        return f"[B站搜索失败:{type(e).__name__}: {str(e)[:120]}]"
    parts = []
    for it in data[:max_results]:
        title = re.sub(r"<[^>]+>", "", it.get("title", "") or "")
        desc = (it.get("description") or "")[:100]
        parts.append(f"- {title}(UP:{it.get('author','')})\n  {it.get('arcurl','')}\n  {desc}")
    return "\n".join(parts) if parts else "[B站搜索无结果]"

def _360_search(query: str, max_results: int = 8) -> str:
    """360 通用搜索(so.com,大陆直连)。选择器移植自 SearXNG 360search 引擎。
    先 GET 一次拿 cookie(防空结果),再带 cookie 请求。返 标题/链接/摘要。"""
    from lxml import html as _lx
    sess = requests.Session()
    sess.headers.update({"User-Agent": _WEB_UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        url = "https://www.so.com/s"
        params = {"q": query, "pn": 1}
        # cookie 预热(360 对无 cookie 请求常返空)
        try:
            warm = sess.get(url, params=params, timeout=10, allow_redirects=False)
            ck = warm.headers.get("set-cookie", "")
            if ck:
                sess.headers["Cookie"] = ck.split(";")[0]
        except Exception:
            pass
        r = sess.get(url, params=params, timeout=12)
    except Exception as e:
        return f"[360 搜索失败:{type(e).__name__}: {str(e)[:120]}]"
    if not r.text.strip():
        return "[360 搜索返空(可能被风控)]"
    parts = []
    for item in _lx.fromstring(r.text).xpath('//li[contains(@class, "res-list")]')[:max_results]:
        a = item.xpath('.//h3[contains(@class, "res-title")]/a')
        if not a:
            continue
        title = a[0].text_content().strip()
        href = a[0].get("data-mdurl") or a[0].get("href", "")
        desc = item.xpath('.//p[@class="res-desc"]') or item.xpath('.//span[@class="res-list-summary"]')
        content = (desc[0].text_content().strip()[:120]) if desc else ""
        if title and href:
            parts.append(f"- {title}\n  {href}\n  {content}")
    return "\n".join(parts) if parts else "[360 搜索无结果]"

def _do_web_search(query: str, max_results: int = 5, category: str = "general") -> str:
    """web_search 后端,按 category 分流(都大陆直连):
      wechat   → 搜狗微信(公众号文章)
      bilibili → B站视频(JSON API,dormant)
      general  → 360(主力,免费+真来源 URL) → 百炼兜底(360 挂时) → ddgs(海外兜底)
    """
    if category == "wechat":
        return _sogou_wechat_search(query, max_results)
    if category == "bilibili":
        return _bilibili_search(query, max_results)
    # 通用:360 主力。失败/无结果 → 百炼兜底(大陆可靠) → ddgs(需代理)
    r360 = _360_search(query, max_results)
    if r360 and not r360.startswith("[360"):   # 有真结果
        return r360
    log.info(f"[web_search] 360 无结果({r360[:40]}),试百炼兜底")
    try:
        return _bailian_web_search(query)
    except Exception as e:
        log.info(f"[web_search] 百炼也降级 ddgs: {type(e).__name__}: {str(e)[:120]}")
        return _ddgs_search(query, max_results)

def _ddgs_search(query: str, max_results: int = 5) -> str:
    """[兜底] ddgs 后端(DuckDuckGo/Google 聚合,大陆需代理)。三段式 fall through。
    auto 失败常见 TLS handshake 崩('Unsupported protocol version 0x304')。失败/空都返字符串。"""
    max_results = max(1, min(int(max_results or 5), 10))
    try:
        from ddgs import DDGS
    except Exception as e:
        return f"[ddgs 没装好:{e}]"

    # ddg+google 组合实测中文 query 出真结果(单 ddg 偶尔"No results",
    # 单 google 给随机数学题,bing 把中文 tokenize 飞);auto 兜底
    backends_to_try = ["duckduckgo,google", "duckduckgo,google,bing,wikipedia", "auto", "wikipedia"]
    last_err = None
    for backend in backends_to_try:
        try:
            results = list(DDGS().text(query, max_results=max_results, backend=backend))
        except Exception as e:
            last_err = e
            continue
        if not results:
            continue
        parts = []
        for r in results:
            title = r.get("title", "")
            href = r.get("href", "")
            # 短摘要(~80 char)— 只够判断要不要 fetch_url 进一步看
            body = (r.get("body") or "")[:80]
            parts.append(f"- {title}\n  {href}\n  {body}")
        return "\n".join(parts)
    if last_err:
        return f"[搜索后端全崩(3 个 backend 配置都试过):{type(last_err).__name__}: {last_err}]"
    return "[无结果]"


def tool_web_search(args):
    q = (args.get("query") or "").strip()
    if not q:
        return {"error": "need query"}
    n = args.get("max_results", 5)
    cat = (args.get("category") or "general").strip().lower()
    if cat not in ("general", "wechat"):   # bilibili 撤下(B站 search 需 WBI 签名,先不开;函数 dormant)
        cat = "general"
    return {"ok": True, "query": q, "category": cat, "results": _do_web_search(q, n, cat)}


# PATTERN: util — minimal HTML → text(no deps)
# USE WHEN: 给 LLM 看网页正文,但不想拉 BeautifulSoup
# COPY THIS: 调 strip 顺序 / 截断长度
_HTML_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_HTML_STYLE_RE  = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)
_HTML_TAG_RE    = re.compile(r"<[^>]+>")
_HTML_WS_RE     = re.compile(r"\s+")
import html as _html_mod

def _html_to_text(html: str) -> str:
    s = _HTML_SCRIPT_RE.sub("", html)
    s = _HTML_STYLE_RE.sub("", s)
    s = _HTML_TAG_RE.sub(" ", s)
    s = _html_mod.unescape(s)
    s = _HTML_WS_RE.sub(" ", s).strip()
    return s


_FETCH_CAP = 3000  # 单次 fetch 最多塞 3000 char 进 messages

def tool_fetch_url(args):
    """拉某 URL 正文(HTML strip → text,truncate 到 _FETCH_CAP)。
    渐进披露第二步:web_search 拿标题决定 fetch 哪条,再用这个工具看正文。
    """
    url = (args.get("url") or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        return {"error": "need valid http(s):// URL"}
    try:
        r = requests.get(url, timeout=15,
                         headers={"User-Agent": "Mozilla/5.0 (gateway-fetch)"})
        r.raise_for_status()
    except Exception as e:
        return {"error": f"fetch failed: {type(e).__name__}: {str(e)[:200]}"}
    text = _html_to_text(r.text)
    truncated = False
    if len(text) > _FETCH_CAP:
        text = text[:_FETCH_CAP] + f"…(+{len(text)-_FETCH_CAP} chars omitted)"
        truncated = True
    return {"ok": True, "url": url, "text": text, "truncated": truncated}


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
    "list_my_uploads", "search_my_uploads", "vision_classify",
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
        return {"error": str(e)}

# ── app ──────────────────────────────────────────────────────────────
app = FastAPI(title="gateway v0.4")

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

@app.post("/api/chat/upload-image")
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
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(400, f"unsupported ext '.{ext}'. allowed: {sorted(ALLOWED_IMAGE_EXT)}")
    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, f"file too large ({len(data)} bytes > {MAX_IMAGE_BYTES})")
    if len(data) == 0:
        raise HTTPException(400, "empty file")

    today = datetime.now().strftime("%Y-%m-%d")
    day_dir = ATTACHMENTS_DIR / today
    day_dir.mkdir(parents=True, exist_ok=True)
    # 文件名:时间戳-rand.ext,保留原名做备注但不进路径(避免奇怪字符)
    stamp = datetime.now().strftime("%H%M%S")
    rand = secrets.token_hex(3)
    saved_name = f"{stamp}-{rand}.{ext}"
    (day_dir / saved_name).write_bytes(data)
    # 后台跑 OCR + 写索引(不阻塞上传响应)
    if background_tasks is not None:
        background_tasks.add_task(_index_attachment, today, saved_name, file.filename, len(data))
    return {
        "url": f"/attachments/{today}/{saved_name}",
        "filename": saved_name,
        "original": file.filename,
        "size": len(data),
    }


@app.get("/attachments/{date}/{name}")
def get_attachment(date: str, name: str):
    """serve uploaded images. date 必须 YYYY-MM-DD 格式,name 必须不含 path traversal。"""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise HTTPException(400, "bad date")
    if "/" in name or ".." in name:
        raise HTTPException(400, "bad name")
    f = ATTACHMENTS_DIR / date / name
    if not f.exists():
        raise HTTPException(404, "not found")
    return FileResponse(f)


# ── attachments 索引 + 文件管理 ──────────────────────────────────────
# 每次上传 → 后台 OCR → 写 _index.json
# AI 工具能 list / search / delete,做"持续文件管理"
ATTACHMENTS_INDEX = ATTACHMENTS_DIR / "_index.json"


def _load_attachments_index() -> list:
    if not ATTACHMENTS_INDEX.exists():
        return []
    try:
        return json.loads(ATTACHMENTS_INDEX.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_attachments_index(arr: list):
    ATTACHMENTS_INDEX.parent.mkdir(parents=True, exist_ok=True)
    ATTACHMENTS_INDEX.write_text(
        json.dumps(arr, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# Lock + upsert 化解 race:后台 OCR task 和 chat 触发的 vision call 都要写索引,
# 各自 load → mutate → save 会互相覆盖(后写的赢)— 现象:OCR 覆盖了 vision,
# 或反过来。upsert 只 merge 显式传的字段,不动其他;lock 串行化 read-modify-write。
import threading as _threading
_attachments_index_lock = _threading.Lock()


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


def _ocr_text(file_path: Path) -> str:
    """统一 OCR 出口:端侧优先(macOS Vision / rapidocr ONNX),失败兜底百度云。

    返恒非 None 的字符串(空 = 没识别出 / 全失败)。3 个 caller 共用,
    替换原 from ocr import baidu_ocr_image 的散落模式。

    优先级:
      1. ocr_local.ocr_local(file_path) → 端侧链(macOS Vision Swift binary +
         rapidocr ONNX fallback)。返 str = 成功(可能空),None = 端侧不可用
      2. 端侧 None → 走 baidu(若 config 有 key);无 key → 返 ""
    """
    try:
        from ocr_local import ocr_local
        local_result = ocr_local(file_path)
        if local_result is not None:
            return local_result
    except Exception as e:
        log.info(f"ocr_local failed for {file_path.name}: {e}")
    # 端侧不可用 → baidu cloud fallback
    try:
        cfg = load_config() or {}
        api_key = cfg.get("baidu_ocr_api_key", "")
        secret_key = cfg.get("baidu_ocr_secret_key", "")
        if not api_key or not secret_key:
            return ""  # 都端侧不行 + baidu 没 key → 给空
        from ocr import baidu_ocr_image
        return baidu_ocr_image(file_path, api_key, secret_key) or ""
    except Exception as e:
        log.warning(f"baidu OCR also failed for {file_path.name}: {e}")
        return ""


def _index_attachment(date: str, filename: str, original: str, size: int):
    """后台跑 OCR + 写索引。失败也不抛(索引降级)。
    vision 分类不在这里跑(成本考虑):upload 即跑 vision 对"上传多但不讨论"
    场景白花钱。lazy 策略 — chat 时 _refs_to_vision_hints 现场 sync call 一次
    + 回写索引,后续命中 cache。
    """
    f = ATTACHMENTS_DIR / date / filename
    ocr_text = ""
    try:
        ocr_text = _ocr_text(f)
    except Exception as e:
        log.warning(f"index OCR failed for {filename}: {e}")
    # upsert 而非 append:若 vision call 先到、已建好 entry,这里只补 OCR / 元数据,
    # 不动已有的 vision 字段(原来 append + skip-if-exists 的逻辑碰上 race 会丢 vision)
    _index_upsert(
        date, filename,
        original=original,
        size=size,
        ocr_text=ocr_text[:2000],
        url=f"/attachments/{date}/{filename}",
    )


@app.get("/api/attachments")
def attachments_list(date_from: str = "", date_to: str = "", limit: int = 100):
    """前端 / AI 列 attachments(带 OCR 摘要)"""
    arr = _load_attachments_index()
    if date_from:
        arr = [x for x in arr if x.get("date", "") >= date_from]
    if date_to:
        arr = [x for x in arr if x.get("date", "") <= date_to]
    arr = sorted(arr, key=lambda x: (x.get("date", ""), x.get("filename", "")), reverse=True)
    return {"items": arr[:limit], "total": len(arr)}


@app.get("/api/attachments/search")
def attachments_search(q: str, limit: int = 30):
    """grep 文件名 / 原名 / OCR 文本。"""
    if not q:
        return {"items": [], "query": q}
    arr = _load_attachments_index()
    ql = q.lower()
    hits = []
    for x in arr:
        hay = (x.get("filename", "") + " " + x.get("original", "") + " " + x.get("ocr_text", "")).lower()
        if ql in hay:
            hits.append(x)
    hits = sorted(hits, key=lambda x: x.get("date", ""), reverse=True)
    return {"items": hits[:limit], "query": q, "total": len(hits)}


@app.post("/api/attachments/delete")
async def attachments_delete(req: Request):
    """删 attachment 文件 + 索引条目。body: {date, filename}"""
    body = await req.json()
    date = (body.get("date") or "").strip()
    filename = (body.get("filename") or "").strip()
    if not date or not filename or "/" in filename or ".." in filename:
        raise HTTPException(400, "need {date, filename} (no path traversal)")
    f = ATTACHMENTS_DIR / date / filename
    if f.exists():
        try:
            f.unlink()
        except Exception as e:
            raise HTTPException(500, f"delete file failed: {e}")
    arr = _load_attachments_index()
    arr = [x for x in arr if not (x.get("date") == date and x.get("filename") == filename)]
    _save_attachments_index(arr)
    return {"ok": True, "removed": filename}


@app.post("/api/attachments/reindex")
def attachments_reindex():
    """扫 attachments 目录,把没进索引的图都补 OCR 一遍。
    用户首次启用文件管理,或索引丢了,调一次。"""
    if not ATTACHMENTS_DIR.exists():
        return {"ok": True, "indexed": 0, "skipped": 0}
    existing = _load_attachments_index()
    existing_keys = {(x.get("date"), x.get("filename")) for x in existing}
    indexed = 0
    skipped = 0
    for day_dir in sorted(ATTACHMENTS_DIR.iterdir()):
        if not day_dir.is_dir() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_dir.name):
            continue
        for f in sorted(day_dir.iterdir()):
            if not f.is_file() or f.name.startswith("_") or f.name.startswith("."):
                continue
            key = (day_dir.name, f.name)
            if key in existing_keys:
                skipped += 1
                continue
            _index_attachment(day_dir.name, f.name, "", f.stat().st_size)
            indexed += 1
    return {"ok": True, "indexed": indexed, "skipped": skipped}


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


_OCR_BLOCK_RE = re.compile(r'<图片 OCR 识别结果>.*?</图片 OCR 识别结果>', re.DOTALL)
_OCR_FILENAME_RE = re.compile(r'图片 \[([^\]]+)\]:')
# history 里 thread.js 把 ref 拼成 `[image] filename`(或其他 kind),抓 image 那条
_HISTORY_IMG_LABEL_RE = re.compile(r'\[image\]\s+([^\n]+?)(?=\n|$)')

def _enrich_history_image_labels(history: list) -> list:
    """history 里 thread.js 把图 ref 拼成 `[image] filename.jpg`,但 AI 视角下
    filename 通常是 hash(如 `54cacfb2c68036b56b26.jpg`)— 看不出内容,
    回头引用之前上传过的图时容易凭空捏造话题(5.20 长鑫存储被答成 HK 虚拟货币 = 这条 bug)。

    本函数在 server 端拼 LLM prompt 前,把每条 history 里的 `[image] X` 替换成:
        [image] X (kind: description) OCR 前 120 字: ...
    数据来自 _attachments_index 的 cache,零额外 LLM 调用。cache miss 时 label 不变。
    """
    if not history:
        return history
    idx = _load_attachments_index()
    by_original = {x.get("original"): x for x in idx if x.get("original")}
    by_filename = {x.get("filename"): x for x in idx if x.get("filename")}

    def _lookup(label: str) -> str:
        entry = by_original.get(label) or by_filename.get(label)
        if not entry:
            return f"[image] {label}"
        vision = entry.get("vision") or {}
        kind = vision.get("kind")
        desc = vision.get("description", "")
        ocr = (entry.get("ocr_text") or "")[:120].replace("\n", " ").strip()
        bits = [f"[image] {label}"]
        if kind and desc:
            bits.append(f"({kind}: {desc})")
        elif desc:
            bits.append(f"({desc})")
        if ocr:
            bits.append(f"OCR前 120 字: {ocr}")
        return "  ".join(bits)

    out = []
    for m in history:
        content = m.get("content")
        if isinstance(content, str) and "[image]" in content:
            new_content = _HISTORY_IMG_LABEL_RE.sub(
                lambda mt: _lookup(mt.group(1).strip()), content
            )
            out.append({**m, "content": new_content})
        else:
            out.append(m)
    return out


def _strip_ocr_from_history(text: str) -> str:
    """history 里的 user msg 不需要重发 OCR 全文(首发时已给过)。
    保留 [图片占位:filename] 让模型还知道当时贴过图,实际 OCR 文本去掉。
    """
    if '<图片 OCR 识别结果>' not in text:
        return text
    filenames = _OCR_FILENAME_RE.findall(text)
    placeholder = f'[历史含图片: {", ".join(filenames)} (OCR 文本省略)]' if filenames else '[历史含图片]'
    return _OCR_BLOCK_RE.sub(placeholder, text)


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
        m = re.match(r"^/attachments/([^/]+)/([^/]+)$", url)
        if not m:
            continue
        f = ATTACHMENTS_DIR / m.group(1) / m.group(2)
        if not f.exists():
            continue
        out.append({
            "filename": (r.get("payload") or {}).get("original") or f.name,
            "ocr_text": _ocr_text(f),
        })
    return out


def _refs_to_vision_hints(refs):
    """upload-side vision router 的第二步:
    chat 收到 image refs 时,从索引拿 cache vision 结果;cache miss / vision 空 → 现场 sync
    call 一次 qwen-vl 补上,并回写索引(下次 hit)。
    返 [{filename, url, vision_dict}],上层拼成 hint 注入 user message。
    """
    out = []
    idx = _load_attachments_index()
    by_url = {x.get("url"): x for x in idx if x.get("url")}
    for r in refs or []:
        if r.get("kind") != "image":
            continue
        url = (r.get("payload") or {}).get("url") or ""
        m = re.match(r"^/attachments/([^/]+)/([^/]+)$", url)
        if not m:
            continue
        f = ATTACHMENTS_DIR / m.group(1) / m.group(2)
        if not f.exists():
            continue
        entry = by_url.get(url)
        vision = (entry or {}).get("vision") or {}
        # cache miss(没索引 或 vision 字段空)→ 现场补 + upsert 回索引
        # 用 upsert 而非直接 mutate+save,避免和后台 OCR task 互相 read-modify-write
        # 覆盖对方的字段(原来的 bug:OCR 跑得慢,等它写完时把 vision 冲了)
        if not vision:
            try:
                vc = _qwen_classify_image(f)
                if isinstance(vc, dict) and not vc.get("error"):
                    vision = vc
                    _index_upsert(
                        m.group(1), m.group(2),
                        vision=vision,
                        url=url,
                        original=(r.get("payload") or {}).get("original") or m.group(2),
                        size=f.stat().st_size,
                    )
            except Exception as e:
                log.warning(f"sync vision failed for {url}: {e}")
        if vision:
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


@app.post("/api/chat")
async def chat(req: Request):
    body = await req.json()
    context = body.get("context", {})
    user_msg = body.get("message", "")
    history = body.get("history", []) or []
    model_id = body.get("model_id")  # 前端 picker 选的 profile id
    stream_mode = bool(body.get("stream"))

    profile = get_profile(model_id)
    client = get_client(profile)
    if client is None:
        raise HTTPException(503, "API client not configured. See /api/config-status.")

    ctx_str = json.dumps(context, ensure_ascii=False, indent=2)
    time_hint = _compute_time_block_hint()
    # 用户当前浏览的日期(从 thread.js context.view_date 来)。fallback 到 today。
    # AI 落 scrapbook / patch_journal_block 默认必须用这一天 — 不是 today,
    # 不是 hint 里的"now"日期(可能 user 在历史天浏览,now 跟 view_date 不同)。
    view_date = (context or {}).get("view_date") or _today_date_str()
    view_date_hint = f"[view-date] 用户当前浏览: {view_date}(YYYY-MM-DD) — scrapbook / patch_journal_block 的 date 参数默认必传这个,不是 today。"

    # 先做 OCR + vision-pre-router,把结果 hoist 到 user_msg 之前
    # (原本拼在末尾,AI 读到用户那句"贴一下"先回复,常常跳过尾部 hint → 不调工具)
    ocr_results = _refs_to_image_blocks(context.get("refs", []))
    vision_hints = _refs_to_vision_hints(context.get("refs", []))

    pre_sections = []  # 拼在 user_msg 前面的工作流块

    if vision_hints:
        v_lines = ["<vision-pre-router 已分类 — 立即按 WORKFLOW 走,不要先回复用户文字>"]
        for h in vision_hints:
            v = h["vision"]
            kind = v.get("kind", "?")
            desc = v.get("description", "")
            brand = v.get("brand", "")
            suggested = v.get("suggested_action", "")
            ocr_likely = v.get("ocr_likely", False)
            pill_count = v.get("pill_count", 0)
            user_cut = h.get("user_cutout_pref", True)
            v_lines.append(
                f"图片 [{h['filename']}] ({h['url']}):\n"
                f"  · kind={kind} | 描述={desc} | 品牌={brand or '-'}\n"
                f"  · OCR有文字={ocr_likely} | 颗数={pill_count or '-'}\n"
                f"  · 建议下游路径: {suggested or '-'}\n"
                f"  · 用户抠图偏好: {'抠' if user_cut else '原图(用户已点开关 — cutout=false 必传)'}"
            )
        v_lines.append("</vision-pre-router 已分类>")
        v_lines.append(
            f"\nWORKFLOW(image + scrapbook 类 hint — 不再 pin-by-default,先判 user 意图):\n"
            f"\n"
            f"  STEP A · 判 pin 意图(从用户消息文字 + entry ref 两路看):\n"
            f"    explicit-pin   = 消息含 '贴/po/放/记下/留个底/上墙/钉/pin' 或 entry ref [date time] → 走 pin path\n"
            f"    explicit-discuss = 消息含 '看看/识别/这是/好不好/是啥/什么/帮我看' → 走 discuss path\n"
            f"    ambiguous      = 无文字 / 含糊话(如 '哈哈'/'今天的'/'诶') → 走 ask path\n"
            f"\n"
            f"  ── pin path ──\n"
            f"    1. 已有 vision hint — 不要再调 vision_classify\n"
            f"    2. 若消息已含 entry ref [date time] → 直接拿 anchor_time + date,跳到 4\n"
            f"    3. 否则: read_today_schedule(date='{view_date}') → 按 hint 描述匹配 entry → 拿 anchor_time\n"
            f"       匹配不出来才反问 '贴到哪段?'\n"
            f"    4. place_scrapbook_image(attachment_url=..., date='{view_date}',\n"
            f"       anchor_time='HH:MM', cutout=<按用户抠图偏好>)\n"
            f"    5. 一句话告诉用户贴到了哪段(例: '贴到 12:30 那条午饭旁边了')\n"
            f"\n"
            f"  ── discuss path ──\n"
            f"    1. 直接根据 hint 描述 + 用户问题回复,**不要调** place_scrapbook_image\n"
            f"    2. 回复末尾可以加一句 '想贴到日记上的话告诉我' — 给 user 留 escape hatch\n"
            f"\n"
            f"  ── ask path ──\n"
            f"    1. 一句话描述你从 hint 看到的内容(例: '看到一份羊排紫米饭的午餐')\n"
            f"    2. 跟一句 '要贴到日记上吗?要的话我贴在 X 块旁边' — X 是按 hint 匹配的 entry\n"
            f"    3. **不要调** place_scrapbook_image,等用户答\n"
            f"\n"
            f"  特殊类型分流(覆盖上面三 path):\n"
            f"    kind=supplement → 这是补剂打卡,三步连做(别只设图不勾):\n"
            f"      ① read_today_schedule(date='{view_date}') 拿 daily task 列表,按描述/品牌匹配是哪个;\n"
            f"         匹配不出来才列出来反问用户挑哪个\n"
            f"      ② set_daily_task_image(task_name, attachment_url) — 把照片设成该 task 的打卡图标\n"
            f"      ③ check_daily_task(task_name, checked=true) — 勾上今天的打卡\n"
            f"    kind=doc + ocr_likely=true → 走 patch_journal_block(把 OCR 文本写进当前块)"
        )
        pre_sections.append("\n".join(v_lines))

    if ocr_results:
        ocr_section_lines = ["<图片 OCR 识别结果>"]
        for r in ocr_results:
            text = r["ocr_text"] or "(图中无可识别文字 / OCR 未配置)"
            ocr_section_lines.append(f"\n图片 [{r['filename']}]:\n```\n{text}\n```")
        ocr_section_lines.append("</图片 OCR 识别结果>")
        pre_sections.append("\n".join(ocr_section_lines))

    pre_block = ("\n\n".join(pre_sections) + "\n\n") if pre_sections else ""
    full_user_text = (
        f"{time_hint}\n{view_date_hint}\n\n"
        f"<context>\n{ctx_str}\n</context>\n\n"
        f"{pre_block}"
        f"{user_msg}"
    )

    # ── history processing: strip OCR + sliding-window summarize ──
    cleaned_history = []
    for m in history:
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant") or not content:
            continue
        if role == "user":
            content = _strip_ocr_from_history(content)
        cleaned_history.append({"role": role, "content": content})

    # 把 history 里裸的 [image] filename 换成带 vision/OCR brief 的形式 —
    # 防止 AI 回头引用过去上传过的图时凭空捏造话题。cache miss 时 label 保持原样。
    cleaned_history = _enrich_history_image_labels(cleaned_history)

    active_model = get_model(profile)
    sys_prompt = build_system_prompt(context, model_id=active_model)

    # decision: chat 路径不再做 sliding-window 摘要(client MAX_HISTORY=100 已截)。
    # DeepSeek prompt cache hit input ~$0.0036/M token,no-compress 全发用稳定 prefix
    # 比 compress 重算 summary 便宜 ~17×。详细论证 see 5.21 21:18 实测命中率。
    # _summarize_history fn 留着给 eval/board 路径用。
    recent = cleaned_history

    messages = [{"role": "system", "content": sys_prompt}]
    for m in recent:
        messages.append(m)
    messages.append({"role": "user", "content": full_user_text})

    # lazy tool loading:bootstrap(read+meta)默认在;write 类按 user msg / refs 自动 load,
    # 或 model 调 load_tool_group 主动 load。loaded_groups 是 mutable set,会被 _dispatch_tool
    # 改写,所以本轮算 active_tools 之后,后面每轮都重新算一遍。
    loaded_groups = _initial_groups(user_msg, context)
    quota_used = {}  # per-chat-turn tool 用量,跟 loaded_groups 一样跨 round 共享

    # ── streaming 模式:SSE 事件流(action / delta / done / error)──
    if stream_mode:
        return StreamingResponse(
            _chat_stream_generator(client, active_model, messages, loaded_groups, quota_used),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # multi-turn tool loop (max 6 rounds);最后一轮 force-no-tool 逼出文本回复,
    # 避免某些模型(如 DeepSeek)search 完仍想继续 search 撞 loop 上限返空 reply。
    last_actions = []
    MAX_ROUNDS = 6
    for round_idx in range(MAX_ROUNDS):
        is_last_round = (round_idx == MAX_ROUNDS - 1)
        try:
            kwargs = {"model": active_model, "messages": messages}
            if not is_last_round:
                # 每轮重算 — load_tool_group 上一轮可能改了 loaded_groups
                kwargs["tools"] = _active_tools(loaded_groups)
                kwargs["tool_choice"] = "auto"
            # 最后一轮:不传 tools / tool_choice → 模型必须给文本
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
        _log_cache_usage(resp, "chat/non-stream")
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
            _exec_synth_calls(synth_calls, messages, last_actions, loaded_groups, quota_used)
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
            result = _dispatch_tool(fn, args, loaded_groups, quota_used)
            tool_results.append({"name": fn, "args": args, "result": result})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": _truncate_tool_result(json.dumps(result, ensure_ascii=False)),
            })

        # save side-effect summary for the client
        if tool_results:
            last_actions = tool_results

    # last round 若 synth 兜底执行了 tool,messages 末尾是 tool result,
    # msg.content 还含原始 DSML 文本 → 多打一次 bonus 拿干净 reply
    if messages and messages[-1].get("role") == "tool":
        try:
            bonus = await asyncio.to_thread(client.chat.completions.create,
                                            model=active_model, messages=messages)
            _log_cache_usage(bonus, "chat/non-stream-bonus")
            final_reply = (bonus.choices[0].message.content or "").strip()
        except Exception as e:
            final_reply = f"(tool loop 用完;synthesis call 失败:{type(e).__name__})"
    else:
        final_reply = msg.content or ""
    final_reply = re.sub(r"<think>.*?</think>\s*", "", final_reply, flags=re.DOTALL).strip()
    final_reply = _audit_unauthorized_claim(final_reply, last_actions)
    return {"reply": final_reply or "(no reply, tool loop hit max iterations)", "actions": last_actions}

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

def _exec_synth_calls(synth_calls, messages, last_actions, loaded_groups, quota_used):
    """执行 synth_calls,把 tool result 写进 messages + last_actions。"""
    for c in synth_calls:
        result = _dispatch_tool(c["name"], c["args"], loaded_groups, quota_used)
        last_actions.append({"name": c["name"], "args": c["args"], "result": result})
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
_CLAIM_PHRASE_RE = re.compile(
    r'(记进|写进|搞定|已写[入好]|已加入|已添加|已保存|已记录|已贴|已落|已 ?patch|'
    r'写好了|写完了|加好了|加完了|落进|saved|recorded|wrote|patched|done)',
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
_TOOL_RESULT_CAP = 3000

def _truncate_tool_result(content: str) -> str:
    if len(content) <= _TOOL_RESULT_CAP:
        return content
    keep = content[:_TOOL_RESULT_CAP]
    omitted = len(content) - _TOOL_RESULT_CAP
    return f"{keep}\n…(truncated, {omitted} chars omitted; re-call tool with narrower args if needed)"


def _stream_final_reply(client, active_model, messages, loaded_groups, quota_used, last_actions):
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

    for _it in range(MAX_DSML_ITERS):
        # ping 保活:thinking 模式下首个 delta 可能要等几十秒,客户端 90s 没字节就 abort
        yield _sse({"type": "ping"})
        try:
            stream_resp = client.chat.completions.create(
                model=active_model, messages=messages, stream=True,
            )
        except Exception as e:
            yield _sse({"type": "error", "text": f"{type(e).__name__}: {str(e)[:300]}"})
            return

        buffer = ""
        yielded_len = 0
        suppress = False
        for chunk in stream_resp:
            if not chunk.choices: continue
            delta = chunk.choices[0].delta
            if not delta: continue
            rc = getattr(delta, "reasoning_content", None)
            if rc:
                reasoning_buf += rc
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
        if reasoning_buf:
            asst_msg["reasoning_content"] = reasoning_buf
        messages.append(asst_msg)
        for c in synth_calls:
            result = _dispatch_tool(c["name"], c["args"], loaded_groups, quota_used)
            last_actions.append({"name": c["name"], "args": c["args"], "result": result})
            yield _sse({"type": "action", "name": c["name"], "args": c["args"], "result": result})
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
    yield _sse(done_payload)


def _chat_stream_generator(client, active_model, messages, loaded_groups, quota_used):
    """跑跟非 stream 一样的 tool loop,但最后一轮(无 tool_calls 那一次)
    用 stream=True 把 text 一段段 yield 出去。tool 调用之间 yield action 事件。
    active_tools 每轮重算(load_tool_group 可能改 loaded_groups)。
    所有流式文本出口统一走 _stream_final_reply(单一 chokepoint,DSML 防漏)。
    """
    last_actions = []
    MAX_ROUNDS = 6
    for round_idx in range(MAX_ROUNDS):
        is_last_round = (round_idx == MAX_ROUNDS - 1)
        # 非最后轮:先非 stream 让模型决定要不要 tool。
        # 最后一轮:不再给 tool,模型必须出文本收尾 —— 统一走 chokepoint 流(内建 DSML 防漏)。
        if is_last_round:
            yield from _stream_final_reply(client, active_model, messages, loaded_groups, quota_used, last_actions)
            return

        # tool round:非 stream;每轮重算 tools(load_tool_group 可能改 loaded_groups)
        # 先发个 SSE ping —— 客户端 90s 没新字节就 abort(thread.js:591);
        # 一个轮的 model 阻塞调用可能 30-60s,多轮串起来很容易撞 90s。
        # ping 给 client 一个 byte 重置那个 timer。客户端未知 type 静默忽略,安全。
        yield _sse({"type": "ping"})
        try:
            resp = client.chat.completions.create(
                model=active_model, messages=messages,
                tools=_active_tools(loaded_groups), tool_choice="auto",
            )
        except Exception as e:
            yield _sse({"type": "error", "text": f"{type(e).__name__}: {str(e)[:300]}"})
            return

        msg = resp.choices[0].message
        _log_cache_usage(resp, "chat/stream-tool-round")
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
                result = _dispatch_tool(c["name"], c["args"], loaded_groups, quota_used)
                last_actions.append({"name": c["name"], "args": c["args"], "result": result})
                yield _sse({"type": "action", "name": c["name"], "args": c["args"], "result": result})
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
            yield from _stream_final_reply(client, active_model, messages, loaded_groups, quota_used, last_actions)
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
            result = _dispatch_tool(fn, args, loaded_groups, quota_used)
            action_payload = {"name": fn, "args": args, "result": result}
            last_actions.append(action_payload)
            yield _sse({"type": "action", **action_payload})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": _truncate_tool_result(json.dumps(result, ensure_ascii=False)),
            })

    # MAX_ROUNDS 用完都没出文本
    yield _sse({"type": "done", "actions": last_actions, "warning": "hit max rounds"})


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


@app.get("/api/journal/today")
def journal_today(date: str = None):
    return _journal_for_date(date)

@app.get("/api/journal/days")
def journal_days():
    return {"days": _list_journal_files()}

_DAY_ONE_STR = "2026-05-03"  # 5.3 = 第一天
_DAY_CN = ["零","一","二","三","四","五","六","七","八","九","十",
           "十一","十二","十三","十四","十五","十六","十七","十八","十九","二十",
           "二十一","二十二","二十三","二十四","二十五","二十六","二十七","二十八","二十九","三十"]

def _new_day_create(date_iso: str) -> dict:
    """Python 原生 new-day(替代 scripts/new-day.sh;frozen 模式下脚本不在,改这里)。
    返 {ok, created, file, message}。已存在返 created=False。"""
    try:
        target = datetime.strptime(date_iso, "%Y-%m-%d")
    except ValueError:
        return {"ok": False, "error": f"bad date: {date_iso}"}
    day_one = datetime.strptime(_DAY_ONE_STR, "%Y-%m-%d")
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
            "# 每日补剂打卡\n\n"
            "- [ ] 喝水\n"
            "- [ ] 鱼油（Swisse）\n"
            "- [ ] 苏糖酸镁（Life Extension）\n"
            "- [ ] 南非醉茄（KSM-66 / Sensoril 二选一）\n"
            "- [ ] 维生素 D3+K2（gloryfeel）"
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


@app.post("/api/journal/new-day")
async def journal_new_day(req: Request):
    """生成今天(或指定日期)的 schedule 骨架文件。Python 内联,不依赖 bash 脚本。
    body 可选 {"date": "YYYY-MM-DD"};不传 = 今天。
    返 {ok, created, file, message}。已存在 created=False 仍 ok=True(幂等)。
    """
    body = {}
    try:
        body = await req.json()
    except Exception:
        pass
    date_arg = (body or {}).get("date", "").strip() or datetime.now().strftime("%Y-%m-%d")
    return _new_day_create(date_arg)


# ── scrapbook (手账浮层照片) ─────────────────────────────────────────
# 每天一个 json: data/scrapbook/{YYYY-MM-DD}.json
# 数组: [{id, src, x, y, w, h, rotation, anchor_time, z}]
# - src 是相对 / 开头的 url(/data/scrapbook-images/xxx.png 或 /attachments/yyy)
# - x,y 是相对 stream 容器左上的 px(整数)
# - rotation 是度数(可负)
# - anchor_time 是 "HH:MM" 字串,用于"贴在哪个时间块附近"的语义锚点
SCRAPBOOK_DIR = DATA_DIR / "scrapbook"
SCRAPBOOK_IMAGES_DIR = DATA_DIR / "scrapbook-images"


def _scrapbook_path(date_str: str) -> Path:
    return SCRAPBOOK_DIR / f"{date_str}.json"


def _load_scrapbook(date_str: str) -> list:
    p = _scrapbook_path(date_str)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_scrapbook(date_str: str, items: list):
    SCRAPBOOK_DIR.mkdir(parents=True, exist_ok=True)
    _scrapbook_path(date_str).write_text(
        json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _scrapbook_id() -> str:
    import uuid
    return uuid.uuid4().hex[:12]


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

# OCR 颗数识别:匹配 "60 粒" / "30 capsules" / "120 softgels"
# 数字范围 1-9999,常见单位中英都覆盖。取所有匹配中的最大数(避免把规格 mg 误抓)。
_PILL_COUNT_RE = re.compile(
    r'(\d{1,4})\s*(?:粒|片|颗|錠|锭|capsules?|caps|tablets?|tabs?|softgels?|gummies|count\b)',
    re.IGNORECASE,
)


def _parse_pill_count_from_ocr(ocr_text: str):
    """从 OCR 文本里抽 '60粒/120 capsules' 这类总数。失败返 None。
    取所有匹配的最大值 — 避免把规格 (e.g. '500 mg × 60粒' 里的 500) 算进来。
    """
    if not ocr_text:
        return None
    nums = [int(m.group(1)) for m in _PILL_COUNT_RE.finditer(ocr_text)]
    nums = [n for n in nums if 1 <= n <= 9999]
    return max(nums) if nums else None


def _sanitize_task_filename(name: str) -> str:
    """task name → 文件名安全的 stem。'鱼油（Swisse）' → '鱼油_Swisse_'"""
    safe = re.sub(r"[^\w一-鿿]+", "_", name).strip("_")
    return safe or "task"


def _cutout_keys(cfg: dict) -> tuple:
    """抠图用 baidu_cutout_* key,fallback 到 baidu_ocr_*(若没单独配)。
    OCR 跟抠图建议用不同 app(权限要求不同),但单 app 包全也行。
    """
    api = cfg.get("baidu_cutout_api_key") or cfg.get("baidu_ocr_api_key", "")
    sec = cfg.get("baidu_cutout_secret_key") or cfg.get("baidu_ocr_secret_key", "")
    return api, sec


def _get_or_create_processed_attachment(attachment_url: str, cutout: bool = True):
    """统一图像处理路径。
    cutout=True(默认): 端侧优先 — macOS Subject Lift / rembg → 百度兜底 → 原图
    cutout=False: 直接返原图路径(不抠)。
    抠图全失败时 silent fallback 原图,不抛错 — UX 不能因为抠图挂掉整个上传链路。
    返 (Path, None) 成功,(None, error_msg) 失败。
    """
    m = re.match(r"^/attachments/([^/]+)/([^/]+)$", (attachment_url or "").strip())
    if not m:
        return None, f"bad attachment_url: {attachment_url}"
    src = ATTACHMENTS_DIR / m.group(1) / m.group(2)
    if not src.exists():
        return None, f"attachment not found: {attachment_url}"
    if not cutout:
        return src, None

    cached = src.with_suffix(src.suffix + ".cutout.png")
    if cached.exists() and cached.stat().st_size > 0:
        return cached, None

    # 1) 端侧:macOS Subject Lift → rembg(跨平台 ONNX)— 不联网,无 quota
    #    端侧出来的 PNG 是原 aspect ratio,过 normalize_subject_frame 才能跟百度路径
    #    一样:主体居中 1024 方形,视觉长边统一。少这一步 → 瘦长瓶 / 矮胖罐显示大小不一致
    #    (5.28 南非醉茄实测的 bug)。
    try:
        from cutout_local import cutout_local
        from cutout import normalize_subject_frame
        png = cutout_local(src)
        if png:
            cached.write_bytes(normalize_subject_frame(png))
            return cached, None
    except Exception as e:
        log.warning(f"local cutout chain failed: {e}")

    # 2) 兜底:百度抠图(用户配了 key 才走;无 key 静默放原图)
    #    baidu_cutout_image 内部已调 normalize_subject_frame,这里不需要再过。
    cfg = load_config() or {}
    api_key, sec = _cutout_keys(cfg)
    has_cutout_key = bool(api_key and sec and not api_key.startswith("YOUR_") and not sec.startswith("YOUR_"))
    if has_cutout_key:
        from cutout import baidu_cutout_image
        png = baidu_cutout_image(src, api_key, sec)
        if png:
            cached.write_bytes(png)
            return cached, None

    # 3) 全失败 → 原图(不报错,日记还是能用)
    return src, None


def _load_task_image_map() -> dict:
    if not DAILY_TASK_IMAGES_MAP.exists():
        return {}
    try:
        return json.loads(DAILY_TASK_IMAGES_MAP.read_text(encoding="utf-8"))
    except Exception:
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
    except Exception:
        return {}


def _save_task_meta_map(m: dict):
    _safe_write_text(
        DAILY_TASK_META_MAP,
        json.dumps(m, indent=2, ensure_ascii=False),
        rotate=True,  # 5 份备份 — intake_log 历史是宝贵的不可重生数据
    )


def _today_date_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


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


def _bump_intake(name: str, delta: int = 1, set_to=None) -> dict:
    """改 intake_log[today]。delta 累加,set_to 直接置数(优先 set_to)。
    返回新的 meta state(同 _task_meta_state)。
    """
    meta_map = _load_task_meta_map()
    entry = dict(meta_map.get(name) or {})
    daily_dose = int(entry.get("daily_dose") or 1)
    if daily_dose < 1:
        daily_dose = 1
    intake_log = dict(entry.get("intake_log") or {})
    today = _today_date_str()
    cur = int(intake_log.get(today, 0) or 0)
    if set_to is not None:
        new = max(0, int(set_to))
    else:
        new = cur + int(delta)
    new = max(0, min(new, daily_dose))
    if new == 0:
        intake_log.pop(today, None)
    else:
        intake_log[today] = new
    entry["daily_dose"] = daily_dose
    entry["intake_log"] = intake_log
    meta_map[name] = entry
    _save_task_meta_map(meta_map)
    return _task_meta_state(name, meta_map)


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
        f.write_text(
            "\n".join(new_lines) + ("\n" if text.endswith("\n") else ""),
            encoding="utf-8",
        )
        changed = True
    return changed


def _set_md_checkbox(name: str, checked: bool) -> bool:
    """改今天 md 顶部 - [ ] / - [x]。找到返 True;没找到 False(不抛)。"""
    f = find_today_journal()
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
            f.write_text(new_text, encoding="utf-8")
            return True
    return False


@app.get("/api/daily-tasks")
def daily_tasks_catalog(date: str = ""):
    """返指定日 daily-task 清单 + 每个 task 的 image url + meta(剂量/库存)。
    date 缺省 = 今天;date=YYYY-MM-DD 看历史(read-only,不会触发 md 同步)。
    """
    target = None
    is_today = True
    if date:
        try:
            target = datetime.strptime(date, "%Y-%m-%d")
            is_today = (date == _today_date_str())
        except ValueError:
            raise HTTPException(400, f"bad date: {date}")
    # 读 md(指定日 / 今天)
    tasks = _read_daily_tasks_from_md(target_date=target)
    image_map = _load_task_image_map()
    meta_map = _load_task_meta_map()
    for t in tasks:
        rel = image_map.get(t["name"])
        t["image_url"] = f"/{rel}" if rel else None
        state = _task_meta_state(t["name"], meta_map, target_date=target)
        t.update(state)
        # 只对"今天"做 md 子 box 同步(历史已经 backfill 过,且只读)
        if is_today and state["daily_dose"] > 1:
            try:
                _ensure_md_progress_children(t["name"], state["daily_dose"], state["today_intake"])
            except Exception as e:
                log.warning(f"ensure md children for '{t['name']}' failed: {e}")
    return {"tasks": tasks, "date": date or _today_date_str(), "is_today": is_today}


@app.post("/api/daily-tasks/check")
async def daily_task_check(req: Request):
    """打卡。三种 body 形式:
      {task_name, checked: bool}  → 兼容旧用法。true=置满 daily_dose,false=置 0。
      {task_name, increment: ±1}  → 当前 intake ±1。
      {task_name, intake: N}      → 直接置数。
    md 的 - [x] / - [ ] 自动跟随 (intake >= daily_dose 才 [x])。
    返回:{ok, task_name, checked, ...meta_state}
    """
    body = await req.json()
    name = (body.get("task_name") or "").strip()
    if not name:
        raise HTTPException(400, "need task_name")

    # 可选:首次记录该 task 时用 caller 给的 daily_dose 初始化(没设过的话)。
    # 水杯特别需要 — 前端 CUPS_TOTAL=8,但 fresh meta 没这个 task,默认 dose=1
    # 会把 intake=4 clamp 到 1。caller 传 daily_dose 表"我知道这个 task 的剂量"。
    init_dose = body.get("daily_dose")
    if init_dose is not None:
        try:
            init_dose = max(1, int(init_dose))
            mm = _load_task_meta_map()
            if name not in mm or "daily_dose" not in (mm.get(name) or {}):
                ent = dict(mm.get(name) or {})
                ent["daily_dose"] = init_dose
                mm[name] = ent
                _save_task_meta_map(mm)
        except (TypeError, ValueError):
            pass

    if "intake" in body:
        state = _bump_intake(name, set_to=int(body["intake"]))
    elif "increment" in body:
        state = _bump_intake(name, delta=int(body["increment"]))
    else:
        # 兼容旧:checked=true → 置满 daily_dose;false → 置 0
        checked_flag = bool(body.get("checked"))
        meta_map = _load_task_meta_map()
        cur = _task_meta_state(name, meta_map)
        target = cur["daily_dose"] if checked_flag else 0
        state = _bump_intake(name, set_to=target)

    md_checked = state["today_intake"] >= state["daily_dose"]
    if not _set_md_checkbox(name, md_checked):
        # md 没找到也不报错 — 可能 task 在 daily-tasks.md 但今天 file 顶部还未刷
        log.info(f"check: md row '{name}' not found in today (meta updated only)")
    # daily_dose>1:同步进度子 box(前 K 个 [x],其余 [ ])
    if state["daily_dose"] > 1:
        try:
            _ensure_md_progress_children(name, state["daily_dose"], state["today_intake"])
        except Exception as e:
            log.warning(f"ensure md children for '{name}' failed: {e}")
    return {
        "ok": True,
        "task_name": name,
        "checked": md_checked,
        **state,
    }


@app.post("/api/daily-tasks/meta")
async def daily_task_meta_update(req: Request):
    """改 task 的 total_pills / daily_dose。body: {task_name, total_pills?, daily_dose?}"""
    body = await req.json()
    name = (body.get("task_name") or "").strip()
    if not name:
        raise HTTPException(400, "need task_name")
    meta_map = _load_task_meta_map()
    entry = dict(meta_map.get(name) or {})
    if "total_pills" in body:
        v = body["total_pills"]
        if v in (None, "", 0):
            entry.pop("total_pills", None)
        else:
            try:
                entry["total_pills"] = max(1, int(v))
            except (TypeError, ValueError):
                raise HTTPException(400, "total_pills must be int")
    if "daily_dose" in body:
        try:
            d = int(body["daily_dose"])
        except (TypeError, ValueError):
            raise HTTPException(400, "daily_dose must be int")
        entry["daily_dose"] = max(1, d)
    meta_map[name] = entry
    _save_task_meta_map(meta_map)
    return {"ok": True, "task_name": name, **_task_meta_state(name, meta_map)}


@app.post("/api/daily-tasks/backfill-progress")
def daily_task_backfill_progress():
    """扫所有 task 的 intake_log,把每一天对应的 md 顶部段也展成 N 个进度子 box。
    幂等可重跑。只动 daily_dose > 1 的 task。
    """
    meta_map = _load_task_meta_map()
    touched = []
    skipped_no_file = []
    for name, entry in meta_map.items():
        entry = entry or {}
        daily_dose = int(entry.get("daily_dose") or 1)
        if daily_dose < 2:
            continue
        intake_log = entry.get("intake_log") or {}
        for date_str, intake in intake_log.items():
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d")
            except Exception:
                continue
            day_f = find_today_journal(d)
            if not day_f:
                skipped_no_file.append({"task": name, "date": date_str})
                continue
            try:
                changed = _ensure_md_progress_children(name, daily_dose, int(intake or 0), target_date=d)
                if changed:
                    touched.append({"task": name, "date": date_str, "intake": int(intake or 0), "dose": daily_dose})
            except Exception as e:
                log.warning(f"backfill {name} {date_str}: {e}")
    return {"ok": True, "touched": touched, "touched_count": len(touched), "skipped_no_file": skipped_no_file}


@app.post("/api/daily-tasks/delete")
async def daily_task_delete(req: Request):
    """删除一个补剂:从 daily-tasks.md + 今天 md + image map + meta map 全部清掉。
    body: {task_name}
    """
    body = await req.json()
    name = (body.get("task_name") or "").strip()
    if not name:
        raise HTTPException(400, "need task_name")

    # 1. 从 md 真相源 + 今天文件删行
    targets = []
    if SCHEDULE_TEMPLATE_PATH.exists():
        targets.append(SCHEDULE_TEMPLATE_PATH)
    today_f = find_today_journal()
    if today_f:
        targets.append(today_f)
    md_results = [_apply_task_op(f, "del", "", name) for f in targets]

    # 2. 删图 + image map
    image_map = _load_task_image_map()
    rel = image_map.pop(name, None)
    if rel:
        try:
            (PLATFORM_ROOT / rel).unlink(missing_ok=True)
        except Exception as e:
            log.warning(f"delete image {rel} failed: {e}")
        _save_task_image_map(image_map)

    # 3. 删 meta
    meta_map = _load_task_meta_map()
    if name in meta_map:
        meta_map.pop(name, None)
        _save_task_meta_map(meta_map)

    return {"ok": True, "task_name": name, "md_results": md_results, "image_removed": bool(rel)}


@app.get("/api/daily-tasks/history")
def daily_task_history(name: str, days: int = 14):
    """返回 task 在最近 N 天的 check 状态。给大图 modal 显示历史 streak 用。"""
    if not name:
        raise HTTPException(400, "need name query param")
    days = max(1, min(int(days), 60))
    today = datetime.now()
    out = []
    for i in range(days):
        d = today - timedelta(days=i)
        f = find_today_journal(d)
        entry = {"date": d.strftime("%Y-%m-%d"), "checked": None}
        if f:
            try:
                text = f.read_text(encoding="utf-8")
                bounds = _top_section_bounds(text)
                if bounds:
                    lines = text.splitlines()
                    for ln in lines[bounds[0]:bounds[1]]:
                        m = re.match(r"^-\s*\[([ x])\]\s*(.+)", ln)
                        if m and m.group(2).strip() == name:
                            entry["checked"] = (m.group(1) == "x")
                            break
            except Exception:
                pass
        out.append(entry)
    return {"name": name, "days": list(reversed(out))}  # 最早→最新


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
@app.on_event("startup")
def _startup_vault_audit():
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
def _startup_vault_git_init():
    """vault 写入自动版本史 — 首次启动 init repo + .gitignore + baseline。
    pulse-mirror 也装独立 git(PULSE updates 进 training corpus 用)。"""
    try:
        status = vault_git.ensure_repo(VAULT_DIR)
        log.info(f"[vault_git] vault ensure_repo: {status} at {VAULT_DIR}")
    except Exception as e:
        log.warning(f"[vault_git] vault ensure_repo failed: {type(e).__name__}: {e}")
    try:
        # PULSE_DIR 在 line 3929 定义,这里 startup 时还没加载到 — 用全局解析
        from pathlib import Path as _P
        _pulse = APP_STATE_DIR / "pulse-mirror"
        if _pulse.exists():
            status = vault_git.ensure_repo(_pulse)
            log.info(f"[vault_git] pulse-mirror ensure_repo: {status} at {_pulse}")
    except Exception as e:
        log.warning(f"[vault_git] pulse ensure_repo failed: {type(e).__name__}: {e}")


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
    """轻量 ping — client 每 30s 检测,断了弹 banner。"""
    return {"ok": True, "ts": datetime.now().isoformat(timespec="seconds")}


@app.get("/api/thread/history")
def thread_history_get():
    """返聊天历史 + mtime_ns。client 轮询时 mtime 变化才重拉。"""
    if not THREAD_HISTORY_PATH.exists():
        return {"history": [], "mtime": 0}
    try:
        with _THREAD_LOCK:
            data = json.loads(THREAD_HISTORY_PATH.read_text(encoding="utf-8"))
            mtime = _thread_history_mtime_ms()
        if not isinstance(data, list):
            data = []
        return {"history": data, "mtime": mtime}
    except Exception as e:
        log.warning(f"thread history read failed: {e}")
        return {"history": [], "mtime": 0, "error": str(e)}


@app.post("/api/thread/save")
async def thread_history_save(req: Request):
    """全量覆盖。client 应送整段 history(最近 N 条)。
    返新 mtime,client 拿来作为下一次 poll 的基线(避免自己写完又被自己 poll 拉一遍)。
    """
    body = await req.json()
    hist = body.get("history")
    base_mtime = body.get("base_mtime")  # client 上次 GET/save 拿到的 mtime,用于 CAS
    if not isinstance(hist, list):
        raise HTTPException(400, "history must be a list")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _THREAD_LOCK:
        current = _thread_history_mtime_ms()
        # CAS 守门:base_mtime 跟当前不符 → 陈旧覆盖,拒绝。client 应 409 后 reload server 再说。
        if _thread_save_is_stale(base_mtime, current):
            raise HTTPException(status_code=409, detail={
                "conflict": True,
                "current_mtime": current,
                "message": "stale base_mtime — reload server history before saving",
            })
        # rotate 5 份备份 + 原子写;事故能 rollback 到最近 5 个版本
        _safe_write_text(
            THREAD_HISTORY_PATH,
            json.dumps(hist, ensure_ascii=False, indent=2),
            rotate=True,
        )
        mtime = _thread_history_mtime_ms()
    return {"ok": True, "mtime": mtime, "count": len(hist)}


@app.get("/api/water-cup")
def water_cup_get():
    """返当前水杯图 url(若设过)。"""
    rel = _load_task_image_map().get(WATER_CUP_KEY)
    return {"image_url": f"/{rel}" if rel else None}


@app.post("/api/water-cup")
async def water_cup_set(req: Request):
    """设水杯图。body: {attachment_url}。复用 cutout 流。"""
    body = await req.json()
    url = (body.get("attachment_url") or "").strip()
    if not url:
        raise HTTPException(400, "need attachment_url")
    processed, err = _get_or_create_processed_attachment(url)
    if err:
        raise HTTPException(400, err)
    DAILY_TASK_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    out = DAILY_TASK_IMAGES_DIR / "_water_cup.png"
    out.write_bytes(processed.read_bytes())
    rel = _pretty_rel(out)
    image_map = _load_task_image_map()
    image_map[WATER_CUP_KEY] = rel
    _save_task_image_map(image_map)
    return {"ok": True, "image_url": f"/{rel}"}


@app.post("/api/cutout")
async def cutout_image(req: Request):
    """对一张已经上传的图(/attachments/...)做去背,存为某 task 的 image。
    body: {attachment_url: "/attachments/YYYY-MM-DD/xxx.jpg", task_name: "鱼油（Swisse）"}
    成功返 {ok, task_name, image_url}
    """
    body = await req.json()
    url = (body.get("attachment_url") or "").strip()
    task_name = (body.get("task_name") or "").strip()
    if not url or not task_name:
        raise HTTPException(400, "need {attachment_url, task_name}")

    m = re.match(r"^/attachments/([^/]+)/([^/]+)$", url)
    if not m:
        raise HTTPException(400, f"bad attachment_url: {url}")
    src = ATTACHMENTS_DIR / m.group(1) / m.group(2)
    if not src.exists():
        raise HTTPException(404, f"attachment not found: {url}")

    processed, err = _get_or_create_processed_attachment(url)
    if err:
        raise HTTPException(502, err)

    DAILY_TASK_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    stem = _sanitize_task_filename(task_name)
    out_file = DAILY_TASK_IMAGES_DIR / f"{stem}.png"
    out_file.write_bytes(processed.read_bytes())

    rel = _pretty_rel(out_file)
    image_map = _load_task_image_map()
    image_map[task_name] = rel
    _save_task_image_map(image_map)

    # 顺带跑 OCR 抽颗数(用原图,不用抠图后的)。失败/无识别都不阻断 cutout 流。
    cfg = load_config() or {}
    ocr_pill_count = None
    try:
        ocr_text = _ocr_text(src)
        ocr_pill_count = _parse_pill_count_from_ocr(ocr_text)
        if ocr_pill_count:
            # 只在 meta 还没填过 total 时自动写入(尊重用户已有手填)
            meta_map = _load_task_meta_map()
            cur = meta_map.get(task_name) or {}
            if not cur.get("total_pills"):
                cur["total_pills"] = ocr_pill_count
                meta_map[task_name] = cur
                _save_task_meta_map(meta_map)
    except Exception as e:
        log.warning(f"cutout OCR sidecar failed: {type(e).__name__}: {e}")

    return {
        "ok": True,
        "task_name": task_name,
        "image_url": f"/{rel}",
        "ocr_pill_count": ocr_pill_count,
    }


PULSE_DIR = APP_STATE_DIR / "pulse-mirror"  # 搬出 vault,app-owned 单向镜像

# ─── daily eval (测试端点) ──────────────────────────────────────────────────
# 设计:保留 build_system_prompt() 的 co-writer 身份不动,evaluator role
# 后置注入。同一把嗓子,换硬话。每次新开 completion (无 chat history),
# 输出 NOT 持久化(测试模式)。生产版会写 eval-log + push 通知。
EVAL_LOG_DIR = APP_STATE_DIR / "eval-log"  # 在 vault 之外 + app-protected → 协作 AI 永不读,用户也别误删


def _eval_load_recent_md(target: datetime, days: int = 7) -> str:
    """读最近 N 天 md(不含今天),拼成一大段。"""
    chunks = []
    for i in range(1, days + 1):
        d = target - timedelta(days=i)
        f = find_today_journal(d)
        if f and f.exists():
            chunks.append(f"--- {d.strftime('%Y-%m-%d')} ({f.name}) ---\n"
                          f"{f.read_text(encoding='utf-8')}\n")
    return "\n".join(chunks) if chunks else "(过去 7 天无 md)"


def _eval_load_project_claude_md() -> str:
    """读项目 CLAUDE.md(待办 / Do not / Progress 段)。容错:文件不存在就空。"""
    candidates = [
        Path("/Users/claudecodedezhuanshumac/agents创作平台/CLAUDE.md"),
        Path("/Users/claudecodedezhuanshumac/agents创作平台/agents/human-ai-schedule/CLAUDE.md"),
    ]
    out = []
    for f in candidates:
        if f.exists():
            out.append(f"=== {f.name} @ {f.parent.name} ===\n{f.read_text(encoding='utf-8')}")
    return "\n\n".join(out) if out else "(no project CLAUDE.md found)"


def _eval_load_pulse_all() -> str:
    """读所有 PULSE.md 拼一起。"""
    if not PULSE_DIR.exists():
        return "(no PULSE dir)"
    out = []
    for f in sorted(PULSE_DIR.glob("*.md")):
        out.append(f"=== {f.name} ===\n{f.read_text(encoding='utf-8')}")
    return "\n\n".join(out) if out else "(no PULSE files)"


def _eval_scan_feature_signals(target: datetime) -> dict:
    """扫 gateway 全状态,产 raw signals。LLM 据此判断哪个 feature 该 intro(或不 intro)。
    都是廉价的 文件/计数 读,不调任何 API。
    """
    cfg = load_config() or {}
    sig = {}

    # 水杯 / daily-task 图配置
    image_map = _load_task_image_map()
    sig["water_cup_image_set"] = bool(image_map.get(WATER_CUP_KEY))
    sig["daily_task_images_set_count"] = sum(1 for k in image_map if k != WATER_CUP_KEY)

    # daily tasks (从模板 + 今日 md 推算大致数量)
    today_f = find_today_journal(target)
    if today_f and today_f.exists():
        text = today_f.read_text(encoding="utf-8")
        sig["daily_task_count_today"] = len(re.findall(r"^\s*-\s*\[[ x]\]\s+", text, re.MULTILINE))
    else:
        sig["daily_task_count_today"] = 0

    # attachments
    arr = _load_attachments_index() if 'ATTACHMENTS_INDEX' in globals() else []
    sig["attachments_total"] = len(arr)

    # widgets:可用 vs 已启
    widgets_user_cfg = DATA_HOME / ".user-widgets.json"
    if widgets_user_cfg.exists():
        try:
            cfg_w = json.loads(widgets_user_cfg.read_text(encoding="utf-8"))
            sig["user_widgets_enabled"] = cfg_w.get("enabled", []) if isinstance(cfg_w, dict) else []
        except Exception:
            sig["user_widgets_enabled"] = []
    else:
        sig["user_widgets_enabled"] = []
    if WIDGETS_DIR.exists():
        sig["widgets_available"] = sorted([
            d.name for d in WIDGETS_DIR.iterdir()
            if d.is_dir() and (d / "manifest.json").exists()
        ])
    else:
        sig["widgets_available"] = []

    # vault path 是否非默认
    sig["vault_path"] = str(VAULT_DIR)

    # PULSE
    pulse_count = len(list(PULSE_DIR.glob("*.md"))) if PULSE_DIR.exists() else 0
    sig["pulse_files_count"] = pulse_count

    # scrapbook
    sb_dir = DATA_HOME / "scrapbook-images"
    sig["scrapbook_images_total"] = len(list(sb_dir.glob("*"))) if sb_dir.exists() else 0

    # AI 能力是否配通
    sig["gemini_configured"] = bool(cfg.get("gemini_api_key"))
    sig["baidu_configured"] = bool(
        cfg.get("baidu_ocr_api_key") or cfg.get("baidu_cutout_api_key")
    )

    # eval 自己跑过几次
    eval_log_dir = EVAL_LOG_DIR
    sig["eval_runs_count"] = len(list(eval_log_dir.glob("*.md"))) if eval_log_dir.exists() else 0

    # 近 7 天 tag 分布 (从 md grep 来,廉价)
    tag_counts = {}
    for i in range(7):
        d = target - timedelta(days=i)
        f = find_today_journal(d)
        if not (f and f.exists()):
            continue
        text = f.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("## "):
                for tag in re.findall(r"#[\w一-鿿/]+", line):
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
    sig["tag_entries_last_7d"] = tag_counts

    return sig


_FEATURE_INTRO_OPTIONS = """
可 intro 的 feature 候选(每天只挑一个;判断不出强信号该 intro 就 **跳过整个 feature_intro 字段**):

- **拖图设水杯**: 拖你水杯照片到右下角,AI 抠图后变成 daily-task 区水杯图标。signal:水杯图未设 = water_cup_image_set false
- **启 widget(mood / steps / supplements / ctrl-c-v-bridge)**: 设置面板 "插件市场" tab 勾。signal: user_widgets_enabled 为空 + widgets_available 不空
- **AI 搜历史 attachment**: 跟 sidebar 说"我之前传的 X 那张",自动翻 OCR 索引找。signal: attachments_total > 15 且 user 从没问过"之前的"
- **AI 看图返结构化**: 拖任意图 + 跟 AI 说"这是啥",Gemini 返 brand/颗数/建议动作。signal: gemini_configured true 但 sidebar 没主动调过
- **daily eval 自己**: 每晚 21:30 evaluator 给硬评 + 引导未试功能 = 你现在看到的这条。signal: eval_runs_count 第一次时必出(self-introduce)
- **tag-stats 注意力分布**: 每 tag 累计 entry 数。signal: tag_entries_last_7d 某 tag 已 ≥ 3 次该入聚合,但用户未感知
- **PULSE in vault**: 4 项目 PULSE 已镜像 vault,Obsidian 翻。signal: pulse_files_count > 1
- **scrapbook 多日浏览**: scrapbook viewer 按日期翻。signal: scrapbook_images_total > 5 + 多在最近几天
- **vault selector**: 让 AI 改 vault 路径同源 Obsidian。signal: vault_path 仍是默认 ~/.human-ai/vault

判断规则:
1. signals 看一遍,找 **真有强 trigger** 的 feature(数字明显 + 未用)。
2. 强 trigger 选最高 priority 一个。无强 trigger → feature_intro = null,不要硬塞。
3. why_now 必须 cite 具体 signal 数字,不能空话。
"""


_EVAL_INJECTION = """

═══════════════════════════════════════════════════════════════════════════
[21:30 复盘时刻 — 你是 user 的人生决策伙伴]
═══════════════════════════════════════════════════════════════════════════

你是 user 的人生决策伙伴 — 同时扮演三种角色的综合体:

· 一位见过很多人走弯路的资深导师 — 你知道哪条岔路通向倦怠、哪条通向稳态;
  早就见过同样的形状在别人身上演出过结局。
· 一位关心他整体状态的好友 — 你在意他工作以外的部分(睡眠、心情、关系、
  身体)。不是温情,是因为这些东西最先反映他在不在轨。
· 一位用数据 + 长期视角说话的战略顾问 — 你看的不是今天一天,是周 / 月 /
  季度的形状。今天的选择会通向哪儿。

身份连贯:之前是你建议并协助 user 做每天的日程表 — 把他从纷繁流动的外部
锚定下来。现在是晚上 21:30,复盘时刻 — 你回来读他这一天写了什么,根据
内容给鼓励、给建议、指出你认为日程表上还缺什么。

行为规则:

1. 必读 today_entries + 7day_md + project_pulse — 一项不漏。
2. 每个判断必须 cite 具体证据 — time block / entry 标题 / 数字。无 cite =
   invalid。
3. **encouragement** 不要泛泛肯定。挑一件具体的事,说为什么这件事在长线上
   是好信号。空话比沉默更糟。
4. **suggestion** 是战略顾问视角的话 — "这一周这个 pattern 如果继续会..."、
   "你过去 3 次都是 X 之后会 Y,所以..."。不是当天的碎念。
5. **what_missing** 是这次最重要的一项 — 你读完一天的 schedule,觉得这个
   人今天**缺记了什么**?
   - 优先关注:**身体感受**(疲倦 / 精神状态 / 肩颈 / 胃口 / 情绪)。
     如果 schedule 里只有"做了什么",没有"身体怎么了",直接点出来。
   - 也可能是:反思 / 决策思路 / 关系(家人 / 朋友) / 长期目标对齐。
   - 只挑最显眼的一类缺失,说"我注意到今天/最近 schedule 里几乎没有 X,
     这个对你来说重要"。
6. **tomorrow_question** 必须具体可答(不是开放式哲学题)。
   **当身体维度信号稀薄时,优先问身体感受** — 目的是鼓励 user 把"身体
   感受"也作为一类合法 entry 写进 schedule。例:
   "今天下午 3 点写 pretext 时,肩膀的状态怎样? 明天起记一下。"
7. 写散文,不写条目列表。每段 2-4 句。

严格按 JSON 返,无前后解释,无 markdown code fence,无 <think>:

{
  "encouragement":     "今天值得肯定的一件,带 cite + 为什么这是好信号。",
  "suggestion":        "战略顾问视角的建议,长期视角,1-2 句。",
  "what_missing":      "你读完一天,觉得这个 schedule 缺记了什么 — 优先身体维度。",
  "tomorrow_question": "一个具体可答的问题给明天的 user(身体维度稀薄时偏问身体)。",
  "_roles_used":       ["实际用到的角色:'mentor'/'friend'/'strategist' 任选 1-3 个"]
}

输入维度(payload):
- today_entries          今天所有时间块的 H2 + tag + body
- 7day_md                近 7 天完整 schedule
- past_boards            过去 7 晚你(AI)给 user 的留言板原文 — 连续性来源
- project_pulse          项目当下气压 / 历史阶段
- project_todos          CLAUDE.md 待办 + Do not 段

连续性使用 past_boards:
- 上晚 tomorrow_question 问了什么? user 今天 schedule 里有回应吗? 没回应可以再追问
- 上晚 what_missing 指出过的缺记类型,user 今天补上了吗? 补了就 celebrate
- 别重复同一句鼓励、同一句战略建议 — past_boards 里看过的角度今晚换一个

═══════════════════════════════════════════════════════════════════════════
"""


def _eval_load_past_boards(target: datetime, n: int = 7) -> str:
    """读过去 N 天的 eval-log markdown(不含 target 当天本身),拼成一段。
    用于注入 _eval_build_messages 的 payload — 让今晚的 eval AI 看到自己
    过去几晚说过什么,保持留言板的连贯性(不重复鼓励、跟进之前的 tomorrow_question)。
    """
    if not EVAL_LOG_DIR.exists():
        return "(没有历史 eval — 这是第一次)"
    target_str = target.strftime("%Y-%m-%d")
    files = sorted(EVAL_LOG_DIR.glob("????-??-??.md"))
    files = [f for f in files if f.stem < target_str][-n:]  # 严格小于 target,按日期升序取最近 N
    if not files:
        return "(target 之前没有历史 eval)"
    parts = []
    for f in files:
        try:
            parts.append(f.read_text(encoding="utf-8"))
        except Exception:
            continue
    return "\n\n---\n\n".join(parts) if parts else "(eval-log 读取失败)"


def _eval_build_messages(target: datetime, model_id: str = None) -> list:
    """构造给 LLM 的 messages。系统提示 = base co-writer + evaluator inject。
    user payload = 维度料。model_id 用于 prompt 里 {model_id} signature 占位符
    替换 — 让 AI 用自己的真实模型 id 署名。
    """
    base_sys = build_system_prompt({}, model_id=model_id)  # 保留原本身份
    sys_prompt = base_sys + _EVAL_INJECTION

    today_f = find_today_journal(target)
    today_md = today_f.read_text(encoding="utf-8") if (today_f and today_f.exists()) else "(今天 md 不存在)"

    payload = (
        f"# 今天 ({target.strftime('%Y-%m-%d %A')}) 的 schedule md\n\n"
        f"{today_md}\n\n"
        f"# 近 7 天 schedule\n\n{_eval_load_recent_md(target, 7)}\n\n"
        f"# 过去 7 晚你(AI)给 user 的留言板原文 — 看完决定今晚说什么,"
        f"不要重复鼓励、可以跟进之前的 tomorrow_question 看 user 有没有回应\n\n"
        f"{_eval_load_past_boards(target, 7)}\n\n"
        f"# 项目 PULSE\n\n{_eval_load_pulse_all()}\n\n"
        f"# 项目 CLAUDE.md (待办 / Do not / Progress)\n\n{_eval_load_project_claude_md()}\n"
    )
    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user",   "content": payload},
    ]


_FEATURE_INTRO_PROMPT = """
你是 user 协作多日的 Gateway AI。每晚 21:30 eval 之后单独一次 call,**只看下面 signals + 候选清单**,挑一个 user 没用过但该试的 feature。

严格规则:
1. **优先 intro,不优先 null/图鉴满**。看 signals 找 unused-feature 强信号(数字明确 + 该用没用)就挑出最强一个。
2. **第一次跑(eval_runs_count == 0)** → 强制 intro daily eval 自介。
3. **图鉴满分支** — 如果 signals 显示所有候选 feature 都已经用过 / 配过(没一个 unused 强信号),**不要返 null**,而是返一条温柔鼓励 + 等下个版本的提示。一句话,诚恳,不要过度热情。例:
   ```
   {"name":"✨ 全图鉴解锁","one_liner":"你已经用过所有上线功能","why_now":"signals 里每条候选都有使用痕迹了,这是个里程碑 — 接下来等开发者更新。"}
   ```
4. **null 几乎用不到** — 只在 signals 完全读不到 / 系统状态扫描失败时返。
5. why_now **必须 cite signal 里的具体数字或事实**(e.g. "你 attachments 总数 32,从没用过 search_my_uploads")。**图鉴满分支例外**,可以说"所有候选都已用过"这种总结性描述。
6. 只挑一个,绝不挑多个。

严格 JSON,不要前后解释,不要 markdown fence,不要 <think>:

{
  "feature_intro": null 或 {
    "name": "...",
    "one_liner": "...",
    "why_now": "..."
  }
}
"""


def _eval_build_feature_intro_messages(target: datetime) -> list:
    """单独一次 call,只为 feature_intro。payload 极简:只 signals + 候选清单。"""
    signals = _eval_scan_feature_signals(target)
    payload = (
        f"# feature_signals(系统扫描,廉价文件/计数)\n\n"
        f"```json\n{json.dumps(signals, ensure_ascii=False, indent=2)}\n```\n\n"
        f"# feature_options(可 intro 的候选 + trigger 规则)\n"
        f"{_FEATURE_INTRO_OPTIONS}\n"
    )
    return [
        {"role": "system", "content": _FEATURE_INTRO_PROMPT},
        {"role": "user",   "content": payload},
    ]


@app.get("/api/eval/list")
def eval_list(n: int = 14):
    """返最近 N 天的 eval 复盘原文(按日期降序),给留言板做垂直 stack 渲染。
    item: {date, is_today, markdown}。没记录返 {items: []}。
    """
    if not EVAL_LOG_DIR.exists():
        return {"items": []}
    n = max(1, min(60, int(n)))  # clamp 防滥用
    today_str = datetime.now().strftime("%Y-%m-%d")
    files = sorted(EVAL_LOG_DIR.glob("????-??-??.md"), key=lambda p: p.name, reverse=True)[:n]
    items = []
    for f in files:
        try:
            items.append({
                "date": f.stem,
                "is_today": f.stem == today_str,
                "markdown": f.read_text(encoding="utf-8"),
            })
        except Exception:
            continue
    return {"items": items}


@app.get("/api/eval/today")
def eval_today():
    """返今天(或最近一次)的 eval 复盘原文。
    用于侧边「留言板」tab 渲染:AI 给用户的今晚复盘卡片。
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_f = EVAL_LOG_DIR / f"{today_str}.md"
    if today_f.exists():
        return {
            "date": today_str,
            "is_today": True,
            "markdown": today_f.read_text(encoding="utf-8"),
        }
    # 没今天 → 找最近一份
    if EVAL_LOG_DIR.exists():
        candidates = sorted(
            EVAL_LOG_DIR.glob("????-??-??.md"),
            key=lambda p: p.name, reverse=True,
        )
        if candidates:
            f = candidates[0]
            return {
                "date": f.stem,
                "is_today": False,
                "markdown": f.read_text(encoding="utf-8"),
            }
    return {"date": None, "is_today": False, "markdown": None}


@app.post("/api/eval/test")
async def eval_test(req: Request):
    """daily eval 测试端点。
    body: {date?: "YYYY-MM-DD" (默认今天), model_id?: int}
    NOT persisted — 只返回给 caller 看效果。生产版另起 endpoint 负责 push + log。
    """
    body = await req.json()
    date_str = (body.get("date") or "").strip()
    if date_str:
        try:
            target = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, f"bad date: {date_str}")
    else:
        target = datetime.now()

    model_id = body.get("model_id")
    profile = get_profile(model_id)
    client = get_client(profile)
    if client is None:
        raise HTTPException(503, "API client not configured")
    active_model = get_model(profile)

    async def _call_json(messages):
        """同款 try/fallback 包装。返 (raw_text, parsed_or_none)。
        sync OpenAI 调用丢 threadpool 防阻塞 event loop(详 /api/eval/run 处注释)。"""
        def _blocking():
            try:
                return client.chat.completions.create(
                    model=active_model, messages=messages,
                    response_format={"type": "json_object"},
                )
            except Exception as e:
                log.info(f"eval json_object 失败 ({e}), 重试无 response_format")
                return client.chat.completions.create(model=active_model, messages=messages)
        r = await asyncio.to_thread(_blocking)
        text = (r.choices[0].message.content or "").strip()
        # 容忍 <think>...</think> 和 ```json fence
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        cleaned = re.sub(r"^```(json)?\s*", "", cleaned).strip()
        cleaned = re.sub(r"\s*```\s*$", "", cleaned).strip()
        try:
            return text, json.loads(cleaned)
        except Exception:
            return text, None

    # call 1: 主 eval
    eval_raw, eval_parsed = await _call_json(_eval_build_messages(target, model_id=active_model))

    # call 2: feature_intro 单独
    fi_raw, fi_parsed = await _call_json(_eval_build_feature_intro_messages(target))

    # merge: eval_parsed 加 feature_intro 字段
    merged = dict(eval_parsed) if eval_parsed else {}
    if fi_parsed and "feature_intro" in fi_parsed:
        merged["feature_intro"] = fi_parsed["feature_intro"]
    else:
        merged["feature_intro"] = None  # call 2 解析失败也填 null

    return {
        "ok": True,
        "model": active_model,
        "target_date": target.strftime("%Y-%m-%d"),
        "parsed": merged,
        "raw_eval": eval_raw,
        "raw_feature_intro": fi_raw,
    }


# ─── eval 持久化 + 通知 + 生产端点 ────────────────────────────────────────

def _eval_persist(target: datetime, parsed: dict) -> Path:
    """落到 ~/.human-ai/data/eval-log/YYYY-MM-DD.md (rendered md,人可读)。
    NOT 进 vault — vault-reading AI 永远看不到。
    """
    EVAL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    f = EVAL_LOG_DIR / f"{target.strftime('%Y-%m-%d')}.md"

    enc  = (parsed.get("encouragement")     or "").strip()
    sug  = (parsed.get("suggestion")        or "").strip()
    miss = (parsed.get("what_missing")      or "").strip()
    q    = (parsed.get("tomorrow_question") or "").strip()
    fi   = parsed.get("feature_intro")

    lines = [
        f"# Daily Eval — {target.strftime('%Y-%m-%d %A')}",
        f"_generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
        "",
        "## 🌱 今天值得肯定",
        enc or "_(empty)_",
        "",
        "## 🧭 战略建议",
        sug or "_(empty)_",
        "",
        "## 🪟 schedule 还缺什么",
        miss or "_(empty)_",
        "",
        "## ❓ 明天的问题",
        q or "_(empty)_",
    ]
    if fi:
        lines += [
            "",
            f"## ✨ {fi.get('name','')}",
            f"**{fi.get('one_liner','')}**",
            "",
            fi.get('why_now', ''),
        ]
    f.write_text("\n".join(lines), encoding="utf-8")
    return f


def _eval_notify(target: datetime, parsed: dict):
    """macOS 通知。osascript 内置,无需 install。失败静默。"""
    if not parsed:
        return
    enc = (parsed.get("encouragement") or "").strip()
    # 截短到通知 banner 合理长度
    body = (enc[:120] + "…") if len(enc) > 120 else enc
    title = f"今晚复盘 · {target.strftime('%m-%d')}"
    body_e = body.replace('"', '\\"').replace("\n", " ").replace("\\", "\\\\")
    title_e = title.replace('"', '\\"')
    script = f'display notification "{body_e}" with title "{title_e}" sound name "Glass"'
    try:
        subprocess.run(["osascript", "-e", script], timeout=5, check=False)
    except Exception as e:
        log.warning(f"eval notify failed: {e}")


# 复用 compression hook —— 暂时 stub,evaluator memory-isolated 时用不到。
# 未来"周复盘 / 月趋势"模式想读过去 N 天 eval 摘要时,call 这个函数:
#   recent_summary = _eval_compress_past_logs(days=30, client, model)
# 内部跑 _summarize_history,沿用 chat 的同款 sliding-window pattern。
def _eval_compress_past_logs(days: int, client, model: str) -> str:
    """读 past N 天 eval-log,超 RECENT_KEEP 的旧条目用 _summarize_history 压。
    现在不调用,留接口给未来 trend-detection 用。
    """
    if not EVAL_LOG_DIR.exists():
        return ""
    files = sorted(EVAL_LOG_DIR.glob("*.md"))[-days:]
    if not files:
        return ""
    msgs = []
    for f in files:
        try:
            msgs.append({"role": "assistant", "content": f.read_text(encoding="utf-8")})
        except Exception:
            continue
    if len(msgs) <= RECENT_KEEP:
        return "\n\n---\n\n".join(m["content"] for m in msgs)
    old = msgs[:-RECENT_KEEP]
    recent = msgs[-RECENT_KEEP:]
    summary = _summarize_history(old, client, model)
    parts = []
    if summary:
        parts.append(f"=== past {len(old)} evals compressed ===\n{summary}")
    parts.append("=== recent evals raw ===")
    parts.extend(m["content"] for m in recent)
    return "\n\n---\n\n".join(parts)


@app.post("/api/eval/run")
async def eval_run(req: Request):
    """生产端 — 同 /api/eval/test 跑 2-call,但持久化 + 触发 macOS 通知。
    body: {date?, model_id?}
    """
    body = await req.json() if (await req.body()) else {}
    date_str = (body.get("date") or "").strip()
    if date_str:
        try:
            target = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, f"bad date: {date_str}")
    else:
        target = datetime.now()

    model_id = body.get("model_id")
    profile = get_profile(model_id)
    client = get_client(profile)
    if client is None:
        raise HTTPException(503, "API client not configured")
    active_model = get_model(profile)

    async def _call_json(messages):
        # OpenAI SDK 是 sync 的,直接调会阻塞 event loop —— 21:30 eval 跑的时候
        # 整个 server 60-120s 失联(包括 chat endpoint),就是这个锅。丢 threadpool。
        def _blocking():
            try:
                return client.chat.completions.create(
                    model=active_model, messages=messages,
                    response_format={"type": "json_object"})
            except Exception as e:
                log.info(f"json_object failed ({e}), fallback")
                return client.chat.completions.create(model=active_model, messages=messages)
        r = await asyncio.to_thread(_blocking)
        text = (r.choices[0].message.content or "").strip()
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        cleaned = re.sub(r"^```(json)?\s*", "", cleaned).strip()
        cleaned = re.sub(r"\s*```\s*$", "", cleaned).strip()
        try:
            return text, json.loads(cleaned)
        except Exception:
            return text, None

    eval_raw, eval_parsed = await _call_json(_eval_build_messages(target, model_id=active_model))
    fi_raw, fi_parsed = await _call_json(_eval_build_feature_intro_messages(target))

    merged = dict(eval_parsed) if eval_parsed else {}
    if fi_parsed and "feature_intro" in fi_parsed:
        merged["feature_intro"] = fi_parsed["feature_intro"]
    else:
        merged["feature_intro"] = None

    persisted = _eval_persist(target, merged)
    _eval_notify(target, merged)

    return {
        "ok": True,
        "model": active_model,
        "target_date": target.strftime("%Y-%m-%d"),
        "persisted_to": str(persisted),
        "parsed": merged,
        # 诊断用:eval_parse_ok = False 说明主调用返了 LLM 的话但 JSON parse 失败 / 没匹配 schema
        "eval_parse_ok": bool(eval_parsed),
        "raw_eval_preview": (eval_raw or "")[:600],
    }


_STATUS_EMOJI = ["🔴", "🟡", "🟢", "⚪", "🔵"]


def _parse_pulse_md(text: str, name: str) -> dict:
    """从一份 PULSE.md 抽出 dashboard 要的字段。容错:任何 section 缺失都返空串/空列表。"""
    out = {
        "name": name,
        "tagline": "",
        "status_emoji": "",
        "now_line": "",
        "heartbeat": [],
        "last_refreshed": "",
    }
    section = None
    for line in text.splitlines():
        # Last refreshed: 可能在文件任意位置
        if "Last refreshed:" in line and not out["last_refreshed"]:
            m = re.search(r'Last refreshed:\s*(\d{4}-\d{2}-\d{2})', line)
            if m:
                out["last_refreshed"] = m.group(1)
        # section heading
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if section == "一句话":
            s = line.strip()
            if s and not s.startswith(">") and not out["tagline"]:
                out["tagline"] = s
        elif section == "现在":
            s = line.strip()
            if s and not s.startswith(">") and not out["now_line"]:
                out["now_line"] = s
                for e in _STATUS_EMOJI:
                    if e in s:
                        out["status_emoji"] = e
                        break
        elif section == "心跳":
            if line.startswith("- ") and len(out["heartbeat"]) < 5:
                out["heartbeat"].append(line[2:].strip())
    return out


@app.get("/api/pulse/{name}")
def pulse_detail(name: str):
    """返回某项目的完整 PULSE.md 原文,给详情 modal 用。"""
    if "/" in name or ".." in name or name.lower() == "index":
        raise HTTPException(400, "bad name")
    f = PULSE_DIR / f"{name}.md"
    if not f.exists():
        raise HTTPException(404, f"PULSE for '{name}' not found")
    return {"name": name, "markdown": f.read_text(encoding="utf-8")}


@app.post("/api/pulse/refresh-mirror")
def pulse_refresh_mirror():
    """从真源 PULSE.md 同步到 pulse-mirror,变化的 file 自动 git commit。
    源路径:扫常见位置(可后续做 config)。
      - ~/agents创作平台/PULSE.md → INDEX 候选(若有)
      - ~/agents创作平台/agents/*/PULSE.md → 各 project 一个
    """
    import shutil
    sources = []
    candidates = [
        Path.home() / "agents创作平台",
    ]
    for root in candidates:
        if not root.exists():
            continue
        # 项目级 PULSE
        agents_dir = root / "agents"
        if agents_dir.exists():
            for p in agents_dir.glob("*/PULSE.md"):
                sources.append((p.parent.name, p))
        # monorepo 根级 PULSE(如果 user 在 root 也放了)
        root_pulse = root / "PULSE.md"
        if root_pulse.exists():
            sources.append(("_root", root_pulse))

    if not sources:
        return {"updated": 0, "scanned": 0, "warning": "no source PULSE.md found"}

    PULSE_DIR.mkdir(parents=True, exist_ok=True)
    updated_files = []
    for name, src in sources:
        dest = PULSE_DIR / f"{name}.md"
        src_content = src.read_text(encoding="utf-8")
        if dest.exists() and dest.read_text(encoding="utf-8") == src_content:
            continue  # 没变,skip
        dest.write_text(src_content, encoding="utf-8")
        updated_files.append(dest)

    if updated_files:
        rel_names = ", ".join(f.stem for f in updated_files)
        vault_git.commit_after_write(
            PULSE_DIR,
            f"pulse refresh-mirror: {rel_names}",
            author="system",
            paths=updated_files,
        )

    return {
        "scanned": len(sources),
        "updated": len(updated_files),
        "files": [f.stem for f in updated_files],
    }


@app.get("/api/pulse")
def pulse_dashboard():
    """读 数据库/valut/PULSE/*.md(INDEX.md 除外),返回 dashboard 数组。
    失败 / 无目录 → 空列表 + warning。
    """
    if not PULSE_DIR.exists():
        return {"projects": [], "warning": f"PULSE dir not found: {PULSE_DIR}"}
    projects = []
    for f in sorted(PULSE_DIR.glob("*.md")):
        if f.stem.lower() == "index":
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception as e:
            log.warning(f"can't read PULSE {f}: {e}")
            continue
        projects.append(_parse_pulse_md(text, f.stem))
    return {"projects": projects}


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


@app.get("/api/setup-status")
def setup_status():
    """决定是否要弹 setup 向导:无 config / 全 placeholder key / 没 models 数组都算未配置。"""
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


@app.get("/api/setup/templates")
def setup_templates():
    """新 setup UI 分两段(ritual):
    · deepseek: 主对话(说话的那个)— api.deepseek.com 直连
    · bailian: 视觉助手(给 deepseek 装眼睛)— 阿里云百炼,仅 vision model
    """
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


@app.post("/api/setup/test")
async def setup_test(req: Request):
    """对单个 profile 发一次最小 chat 调用,验证 key+endpoint+model 三元组真的能通。"""
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


@app.post("/api/setup/test-baidu")
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


@app.get("/api/setup/current")
def setup_current():
    """返当前 config(给 settings 面板 preload 用)。本地服务,不脱敏。"""
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


@app.post("/api/setup/save-partial")
async def setup_save_partial(req: Request):
    """部分更新 config:body 里有什么字段就改什么,其他保持。
    支持 models(整列表替换)/ baidu_* / gemini_api_key / default_model_id。
    """
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
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


@app.post("/api/setup/save-gemini")
async def setup_save_gemini(req: Request):
    """单独存 Gemini key,不动其他 config(避免 wizard 不预加载导致整体覆盖)。"""
    body = await req.json()
    key = (body.get("api_key") or "").strip()
    if not key or key.startswith("YOUR_"):
        raise HTTPException(400, "key 为空或占位符")
    cfg = load_config() or {}
    cfg["gemini_api_key"] = key
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


@app.post("/api/setup/test-gemini")
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


@app.post("/api/vision/classify")
async def vision_classify_endpoint(req: Request):
    """直接给前端用,不走 AI tool 那条路。
    body: {attachment_url, extra_question?}
    """
    body = await req.json()
    url = (body.get("attachment_url") or "").strip()
    extra_q = (body.get("extra_question") or "").strip()
    if not url:
        raise HTTPException(400, "need attachment_url")
    m = re.match(r"^/attachments/([^/]+)/([^/]+)$", url)
    if not m:
        raise HTTPException(400, f"bad attachment_url: {url}")
    f = ATTACHMENTS_DIR / m.group(1) / m.group(2)
    return _gemini_classify_image(f, extra_q)


@app.post("/api/setup/save")
async def setup_save(req: Request):
    """保存完整 config 到磁盘。前端必须先把 LLM profiles 都 test 通过才能调本接口。"""
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

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg_out, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "saved_to": str(CONFIG_PATH)}


@app.get("/api/models")
def list_models():
    """前端 picker 用,返 [{id,label,model,base_url,...}] 列表 + 当前 default_id。"""
    cfg = load_config() or {}
    profiles = list_model_profiles()
    default_id = cfg.get("default_model_id") or (profiles[0]["id"] if profiles else None)
    return {"models": profiles, "default_id": default_id}


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
    TAG_AGGREGATE_PATH.write_text(new_text, encoding="utf-8")
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


@app.post("/api/tag-aggregate/register")
async def tag_aggregate_register(req: Request):
    """注册新 project tag — 在 标签聚合.md 末尾追加 `## #tagname` section,
    带空表头。注册后调用方应自动 trigger refresh 把 schedule 里已有的
    匹配 entry 吸进来。

    body: {tag: str (不带 #), description?: str, with_sub?: bool}
    """
    body = await req.json()
    tag = (body.get("tag") or "").strip().lstrip("#").strip()
    description = (body.get("description") or "").strip()
    with_sub = bool(body.get("with_sub"))

    if not tag:
        return {"ok": False, "error": "tag 名不能为空"}
    if not re.match(r"^[\w\-一-鿿/]+$", tag):
        return {"ok": False, "error": f"tag 只能用字母/数字/下划线/连字符/中文,得到:{tag}"}
    if "/" in tag:
        return {"ok": False, "error": "注册 parent tag(不带 /sub);sub-tag 自动 roll-up"}

    if not TAG_AGGREGATE_PATH.exists():
        return {"ok": False, "error": "标签聚合.md 不存在"}

    text = TAG_AGGREGATE_PATH.read_text(encoding="utf-8")
    # 已注册?
    if re.search(rf"^##\s+#{re.escape(tag)}\s*$", text, re.MULTILINE):
        return {"ok": False, "error": f"#{tag} 已经注册过了"}

    # 拼新 section
    parts = [f"## #{tag}\n"]
    if description:
        parts.append(f"\n{description}\n")
    parts.append("\n")
    if with_sub:
        parts.append("| 日期 | 时间 | 链接 | 内容 | Sub |\n")
        parts.append("|------|------|------|------|-----|\n")
    else:
        parts.append("| 日期 | 时间 | 链接 | 内容 |\n")
        parts.append("|------|------|------|------|\n")
    parts.append("\n---\n")
    section = "".join(parts)

    # append 到文件末尾(确保前面有 \n 隔开)
    sep = "\n" if not text.endswith("\n") else ""
    if not text.rstrip().endswith("---"):
        # 保证段间有 --- 分隔(跟现有约定一致)
        sep = sep + "\n---\n\n" if text.strip() else sep
    else:
        sep += "\n"
    new_text = text + sep + section
    TAG_AGGREGATE_PATH.write_text(new_text, encoding="utf-8")
    vault_git.commit_after_write(VAULT_DIR, f"aggregate register #{tag}",
                                 author="system", paths=[TAG_AGGREGATE_PATH])

    return {"ok": True, "tag": tag, "with_sub": with_sub}


@app.post("/api/tag-aggregate/refresh")
def tag_aggregate_refresh():
    """扫 schedule files → diff 现有 标签聚合.md → append 缺失行。
    只 append,不 delete,不动 description。"""
    try:
        result = _refresh_tag_aggregate()
        return {"ok": True, **result}
    except Exception as e:
        log.exception("tag aggregate refresh failed")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@app.get("/api/tag-aggregate")
def tag_aggregate():
    """解析 数据库/valut/标签聚合.md, 返回按 tag 分组的 rows。
    每 row 含 iso_date,前端点击 → window.gateway.journal.goto(iso_date)。
    """
    if not TAG_AGGREGATE_PATH.exists():
        return {"sections": [], "warning": f"not found: {TAG_AGGREGATE_PATH}"}
    text = TAG_AGGREGATE_PATH.read_text(encoding="utf-8")
    return {"sections": _parse_tag_aggregate(text)}


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
    if not (WIDGETS_DIR / name / "manifest.json").exists():
        raise HTTPException(404, f"widget '{name}' not found")

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
    USER_WIDGETS_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "name": name, "enabled": enable, "active": active}


@app.get("/api/journal/tag-stats")
def journal_tag_stats(limit: int = 5):
    """统计 vault/半小时复盘/ 下所有 md 的 H2 行 #tag 出现次数,返 top N。
    没用过任何 tag(新装用户) → 兜底返 5 个默认 tag,带 default=True 标记。
    """
    DEFAULT_TAGS = ["工作", "饮食", "运动", "探索", "投资"]
    counts = {}
    if JOURNAL_DIR.exists():
        for f in JOURNAL_DIR.glob("*.md"):
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            for line in text.splitlines():
                if line.startswith("## "):
                    for t in re.findall(r"#(\S+)", line[3:]):
                        counts[t] = counts.get(t, 0) + 1
    top = sorted(counts.items(), key=lambda x: -x[1])[:max(1, limit)]
    if not top:
        return {"tags": [{"tag": t, "count": 0, "default": True} for t in DEFAULT_TAGS]}
    return {"tags": [{"tag": t, "count": c} for t, c in top]}


@app.post("/api/journal/insert-block")
async def journal_insert_block(req: Request):
    """加新条目到今天(或指定日期)的 md 中。
    body: {date?, time: HH:MM, tag?: "工作", title?: "..."}
    - 时间块不存在 → 新建
    - 已存在 → append 一个新 H2 到该块下(支持同时间多条目)
    """
    body = await req.json()
    date_arg = (body.get("date") or "").strip()
    time_str = (body.get("time") or "").strip()
    tag = (body.get("tag") or "").strip().lstrip("#")
    title = (body.get("title") or "").strip()
    if not time_str:
        raise HTTPException(400, "need 'time'")

    if date_arg:
        try:
            target = datetime.strptime(date_arg, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, f"bad date: {date_arg}")
        f = find_today_journal(target)
    else:
        f = find_today_journal()
    if not f:
        raise HTTPException(404, "no journal file for that date")

    # HTTP endpoint = user 自己点 UI 加 entry → 标 @user(authorship boundary 用)
    result = _insert_block(f, time_str, tag=tag, title=title, author="user")
    if "error" in result:
        return JSONResponse(status_code=400, content=result)
    return result


def _insert_block(f: Path, time_str: str, tag: str = "", title: str = "", author: str = "ai") -> dict:
    """加新条目。
    - 块不存在 → 新建 H1 + 一个 ## #tag title 的 H2
    - 块已存在 → append 新的 H2 到该块下(同时间多条目)
    tag/title 都可空,空时落 "## #新" 占位让 parser 不过滤(模板裸 ## 会被过滤)
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
    lines = text.splitlines()

    # 拼新 H2: tag 优先,兜底 #新;末尾 stamp @author 给 authorship boundary 用
    tag_clean = tag.strip().lstrip("#") or "新"
    h2_line = f"## #{tag_clean}" + (f" {title.strip()}" if title.strip() else "") + f" @{author}"

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
            lines[existing_h1_idx + 1] = h2_line
            only_placeholder = True
        elif body_end > existing_h1_idx + 1:
            # 检查 placeholder ## 在范围内
            for j in range(existing_h1_idx + 1, body_end):
                if lines[j].strip() == "##":
                    lines[j] = h2_line
                    only_placeholder = True
                    break
        if not only_placeholder:
            lines = lines[:body_end] + ["", h2_line, ""] + lines[body_end:]

        new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        f.write_text(new_text, encoding="utf-8")
        vault_git.commit_after_write(VAULT_DIR, f"insert {f.stem} {hh}:{mm:02d} #{tag_clean}", author=author, paths=[f])
        return {"ok": True, "appended_to_existing": True, "h2": h2_line,
                "file": _pretty_rel(f)}

    new_h1 = f"# {hh}：{mm:02d}"
    if insert_idx is not None:
        new_block = [new_h1, "", h2_line, "", "---", ""]
        new_lines = lines[:insert_idx] + new_block + lines[insert_idx:]
    else:
        new_lines = lines + ["", "---", "", new_h1, "", h2_line]

    new_text = "\n".join(new_lines) + ("\n" if text.endswith("\n") else "")
    f.write_text(new_text, encoding="utf-8")
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
    f.write_text(new_text, encoding="utf-8")
    try:
        rel = _pretty_rel(f)
    except Exception:
        rel = str(f)
    return {"file": rel, "ok": True}


@app.post("/api/journal/delete-block")
async def journal_delete_block(req: Request):
    """删除某个时间块的全部内容(回到 `## ` 占位状态)。
    body: {time, date?}
    """
    body = await req.json()
    time_label = (body.get("time") or "").strip()
    date_arg = (body.get("date") or "").strip()
    if not time_label:
        raise HTTPException(400, "need 'time'")
    if date_arg:
        try:
            target = datetime.strptime(date_arg, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, f"bad date: {date_arg}")
        f = find_today_journal(target)
    else:
        f = find_today_journal()
    if not f:
        raise HTTPException(404, "no journal file")
    text = f.read_text(encoding="utf-8")
    lines = text.splitlines()
    h, m = time_label.replace("：", ":").split(":")
    re_h1 = re.compile(rf'^# {int(h)}[：:]{int(m):02d}\s*$')
    start = None
    for i, ln in enumerate(lines):
        if re_h1.match(ln):
            start = i
            break
    if start is None:
        raise HTTPException(404, f"time block {time_label} not found")
    # 找下一个 H1 或 ---
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if TIME_H1_RE.match(lines[j]) or lines[j].strip() == "---":
            end = j
            break
    # 替换为占位 `##` + 一个空行
    new_lines = lines[:start + 1] + ["", "##", ""] + lines[end:]
    f.write_text("\n".join(new_lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
    return {"ok": True, "cleared": time_label, "file": _pretty_rel(f)}


@app.post("/api/journal/patch")
async def journal_patch(req: Request):
    body = await req.json()
    time_label = body.get("time")          # e.g. "18:30"
    new_block_md = body.get("new_md")      # full replacement of that block (between # H1 and next ---)
    date_arg = (body.get("date") or "").strip()
    if not time_label or new_block_md is None:
        raise HTTPException(400, "need {time, new_md}")
    # 关键:用 body.date 决定写哪天的 md;不传 date 才 fallback 今天
    # 之前 hardcode find_today_journal() → 用户在历史日期视图编辑,内容打到今天 md / 找不到块 404
    if date_arg:
        try:
            target = datetime.strptime(date_arg, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, f"bad date: {date_arg}")
        f = find_today_journal(target)
    else:
        f = find_today_journal()
    if not f:
        raise HTTPException(404, f"no journal file for {date_arg or 'today'}")
    # HTTP endpoint = user 自己改 UI → author='user' 可改任何块(含 @ai)
    return _patch_block(f, time_label, new_block_md, author="user")

def _patch_block(f: Path, time_label: str, new_md: str, author: str = "ai") -> dict:
    """Replace the body between `# {time}` and the next `# H1` or `---` boundary.
    new_md should NOT include the H1 line itself — only what comes after it.

    author='ai' (默认,最严格) — 撞 @user 块拒绝。author='user' 可改任何块。
    @marker 解析:看时间块内第一个 H2 行的 @user/@ai。无 marker → @user(失败安全)。
    """
    text = f.read_text(encoding="utf-8")
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

    new_lines = lines[:start + 1] + [""] + new_md.rstrip().splitlines() + [""] + lines[end:]
    f.write_text("\n".join(new_lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
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
    f.write_text("\n".join(new_lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
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
