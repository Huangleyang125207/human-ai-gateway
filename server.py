"""Gateway desktop sidecar server.

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
import json
import logging
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timedelta, date
from pathlib import Path

log = logging.getLogger("gateway")
log.setLevel(logging.INFO)  # 让 log.info 真的能出来,默认 WARNING 把 cache/quota 等观测吃掉
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s:gateway: %(message)s"))
    log.addHandler(_h)
    log.propagate = False  # 不再 bubble 到 root,避免 uvicorn 重复打
import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

import vault_git
from runtime_paths import (  # noqa: E402,F401
    APP_STATE_DIR,
    CODE_ROOT,
    CONFIG_DIR,
    DATA_DIR,
    DATA_HOME,
    GATEWAY_DIR,
    VAULT_DIR,
)

# PULSE 数据/IO/解析能力由组装根按需导入并注入消费者。
from pulse_io import (  # noqa: E402
    _AGENT_CONTEXT_PATH,
    PULSE_DIR,
    _get_schema_version, _ensure_schema_version_header,
    _parse_pulse_md,
)

# eval 子系统运行依赖由本组装根注入。
import pulse_eval  # noqa: E402
from pulse_eval import (  # noqa: E402,F401
    EVAL_LOG_DIR,
    _classify_eval_err,
    _eval_build_messages, _eval_build_feature_intro_messages,
    _eval_persist, _eval_notify,
)
pulse_eval.configure_effects(
    find_journal=lambda *args, **kwargs: find_today_journal(*args, **kwargs),
    pulse_dir=lambda: PULSE_DIR,
    load_config=lambda: load_config(),
    load_task_image_map=lambda: _load_task_image_map(),
    water_cup_key=lambda: WATER_CUP_KEY,
    data_home=lambda: DATA_HOME,
    widgets_dir=lambda: WIDGETS_DIR,
    vault_dir=lambda: VAULT_DIR,
    load_attachments_index=lambda: _load_attachments_index(),
    build_system_prompt=lambda *args, **kwargs: build_system_prompt(*args, **kwargs),
    compute_time_hint=lambda: _compute_time_block_hint(),
    safe_write_text=lambda *args, **kwargs: _safe_write_text(*args, **kwargs),
    logger=lambda: log,
    report_failure=lambda *args, **kwargs: _report_silent_failure(*args, **kwargs),
)

# PULSE LARGE refactor P4: _self_evolve_run + 2 prompt + EVOLVE_LOCKS 抽到
# pulse_evolve.py(silent corruption 红线集中地,40 P0+ 测试守)。
from pulse_evolve import (  # noqa: E402,F401
    _self_evolve_run as _self_evolve_run_impl, _get_evolve_lock,
)


def _self_evolve_run(target: str, conversation: str) -> dict:
    return _self_evolve_run_impl(
        target,
        conversation,
        get_profile=get_profile,
        get_client=get_client,
        vault_dir=VAULT_DIR,
        write_text=_safe_write_text,
        push_notification=_push_notification,
        report_failure=_report_silent_failure,
        logger=log,
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


# ── §2 原子写/备份存储层适配 ─────────────────────────────────────────
from safe_io import (  # noqa: E402
    _get_write_guard_lock,
    _pretty_rel as _pretty_rel_impl,
    _rotate_backup as _rotate_backup_impl,
    _safe_write_text as _safe_write_text_impl,
)


def _rotate_backup(path: Path, keep: int = 5):
    return _rotate_backup_impl(
        path,
        keep=keep,
        report_failure=_report_silent_failure,
    )


def _pretty_rel(path: Path) -> str:
    return _pretty_rel_impl(
        path,
        roots=(APP_STATE_DIR, DATA_HOME, CODE_ROOT),
    )


def _safe_write_text(
    path: Path,
    content: str,
    rotate: bool = False,
    encoding: str = "utf-8",
):
    return _safe_write_text_impl(
        path,
        content,
        rotate=rotate,
        encoding=encoding,
        lock_factory=_get_write_guard_lock,
        rotate_backup=_rotate_backup,
    )
ALLOWED_IMAGE_EXT = {"jpg", "jpeg", "png", "gif", "webp", "heic"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB

# ── §3 配置层适配 ─────────────────────────────────────────────────────
from config_store import (  # noqa: E402
    DEEPSEEK_DIRECT_URL,
    DEEPSEEK_OFFICIAL_URLS,
    DeepSeekTransport,
    direct_deepseek_profile,
    valid_deepseek_key,
    _env_overlay as _env_overlay_impl,
    _save_config as _save_config_impl,
    get_client as _get_client_impl,
    get_model as _get_model_impl,
    get_vision_model as _get_vision_model_impl,
    list_model_profiles as _list_model_profiles_impl,
    load_config as _load_config_impl,
    sync_env_secrets as _sync_env_secrets_impl,
)


def _env_overlay() -> dict:
    return _env_overlay_impl(
        gateway_dir=GATEWAY_DIR,
        config_dir=CONFIG_DIR,
        logger=log,
    )


def sync_env_secrets(updates: dict) -> None:
    return _sync_env_secrets_impl(
        updates,
        gateway_dir=GATEWAY_DIR,
        config_dir=CONFIG_DIR,
        writer=_safe_write_text,
        logger=log,
    )


def _save_config(cfg: dict) -> None:
    return _save_config_impl(
        cfg,
        config_path=CONFIG_PATH,
        writer=_safe_write_text,
    )


def load_config():
    return _load_config_impl(
        config_path=CONFIG_PATH,
        env_overlay=_env_overlay,
        logger=log,
        reporter=_report_silent_failure,
    )


def list_profiles_full():
    profile = get_profile()
    return [profile] if profile else []


def list_model_profiles():
    return _list_model_profiles_impl(list_profiles_fn=list_profiles_full)


def get_profile(model_id=None):
    return direct_deepseek_profile(load_config())


def get_client(profile=None):
    profile = profile or get_profile()
    if (OpenAI is None or not profile or not valid_deepseek_key(profile.get("api_key"))
            or str(profile.get("base_url") or "").rstrip("/") not in DEEPSEEK_OFFICIAL_URLS):
        return None
    # Only accept the credential itself; never invoke a legacy token exchange
    # or allow caller-supplied headers to override the direct authorization.
    profile = {"api_key": profile.get("api_key"), "base_url": DEEPSEEK_DIRECT_URL}
    return _get_client_impl(
        profile,
        get_profile_fn=get_profile,
        openai_factory=lambda **kwargs: OpenAI(
            **kwargs, http_client=httpx.Client(transport=DeepSeekTransport(), follow_redirects=False)
        ),
    )


def get_model(profile=None):
    return _get_model_impl(profile, get_profile_fn=get_profile)


def get_vision_model():
    return _get_vision_model_impl(get_profile_fn=get_profile)


# ── silent failure 反馈通道 (P1:本地落 jsonl,P3 加 cloud sender) ─────
# 用途:在任何"返 error 但 silently swallow 不告诉 user"的代码路径调用
# `_report_silent_failure(error_type, message, context)`。本地 jsonl ring
# buffer 保留最近 _SILENT_FAILURES_RING_MAX 条,/api/silent-failures/recent
# 返查。client_id 持久化(~/.human-ai/data/client-id.txt),匿名 UUID,跟用户
# 身份无关 — 没邮箱 / IP / 系统识别,只为同设备纵向去重(同 client 多天反复
# 触发 X 类 failure → 优先修)。
# 永远不在 hook 里上报 vault 内容 / API key / 用户文件名。
APP_VERSION = "1.0.0"  # 跟 tauri.conf.json sync;bump 时两处一起改

# ── §4 遥测(silent-failure / heartbeat / sink)已抽出 telemetry.py ──────────
# telemetry.py 是状态与算法的唯一所有者；本文件只注入边缘能力并保留 API facade。
import telemetry  # noqa: E402
from telemetry import (  # noqa: E402
    get_client_id,
    _telemetry_consent,
    _telemetry_save,
    _report_silent_failure,
    _sf_sender_loop,
    _hb_sender_loop,
)
telemetry.configure_effects(
    load_config=lambda: load_config(),
    save_config=lambda cfg: _save_config(cfg),
    env_overlay=lambda: _env_overlay(),
    safe_write_text=lambda *args, **kwargs: _safe_write_text(*args, **kwargs),
    logger=lambda: log,
    push_notification=lambda *args, **kwargs: _push_notification(*args, **kwargs),
    app_version=lambda: APP_VERSION,
)

# ── protocol 加载 + system prompt 构建 ─ 抽到 prompt_builder.py(清册01-§5,行为零变化)──
# 历史:此处原是 PROTOCOLS/load_protocol/_wants_widget_skill/_load_user_context/
# build_system_prompt/_compute_time_block_hint 本体(L483–709 现址)。
# prompt builder 的路径与日志由组装根提供。
from prompt_builder import (  # noqa: E402
    PROTOCOLS, load_protocol,
    build_system_prompt,
    _compute_time_block_hint as _compute_time_block_hint_impl,
)


def _compute_time_block_hint() -> str:
    return _compute_time_block_hint_impl(
        vault_dir=VAULT_DIR,
        logger=log,
    )


# ── tool definitions for DeepSeek ───────────────────────────────────
# ── tool implementations ─────────────────────────────────────────────
# ── widget/journal/daily-task/scrapbook 工具 ─ 抽到 journal_task_tools.py(清册01-§6,行为零变化)──
# 历史:此处原是 ~410 行 AI 写侧工具本体(含三条 LLM 行为疤的模糊匹配层,整段带走)。
# 工具实现归所有者模块，运行依赖由本组装根注入。
import journal_task_tools  # noqa: E402
from tag_vocabulary import build_tag_disclosure  # noqa: E402
journal_task_tools.configure_effects(
    user_widgets_path=lambda: USER_WIDGETS_PATH,
    widgets_dir=lambda: WIDGETS_DIR,
    pretty_rel=lambda path: _pretty_rel(path),
    report_failure=lambda *args, **kwargs: _report_silent_failure(*args, **kwargs),
    safe_write_text=lambda *args, **kwargs: _safe_write_text(*args, **kwargs),
    datetime_provider=lambda: datetime,
    find_today_journal=lambda *args, **kwargs: find_today_journal(*args, **kwargs),
    patch_block=lambda *args, **kwargs: _patch_block(*args, **kwargs),
    journal_for_date=lambda date=None: _journal_for_date(date),
    list_journal_files=lambda: _list_journal_files(),
    insert_block=lambda *args, **kwargs: _insert_block(*args, **kwargs),
    append_comment=lambda *args, **kwargs: _append_comment_to_block(*args, **kwargs),
    top_section_bounds=lambda text: _top_section_bounds(text),
    get_processed_attachment=lambda *args, **kwargs: _get_or_create_processed_attachment(
        *args, **kwargs
    ),
    daily_task_images_dir=lambda: DAILY_TASK_IMAGES_DIR,
    water_cup_key=lambda: WATER_CUP_KEY,
    load_task_image_map=lambda: _load_task_image_map(),
    save_task_image_map=lambda image_map: _save_task_image_map(image_map),
    sanitize_task_filename=lambda name: _sanitize_task_filename(name),
    schedule_template_path=lambda: SCHEDULE_TEMPLATE_PATH,
    apply_task_op=lambda *args, **kwargs: _apply_task_op(*args, **kwargs),
    load_task_meta_map=lambda: _load_task_meta_map(),
    save_task_meta_map=lambda meta: _save_task_meta_map(meta),
    platform_root=lambda: PLATFORM_ROOT,
    attachments_dir=lambda: ATTACHMENTS_DIR,
    scrapbook_images_dir=lambda: SCRAPBOOK_IMAGES_DIR,
    scrapbook_id=lambda: _scrapbook_id(),
    load_scrapbook=lambda date: _load_scrapbook(date),
    save_scrapbook=lambda date, items: _save_scrapbook(date, items),
    sync_tag_aggregate=lambda path: tag_aggregate._sync_tag_aggregate_for_file(path),
    disclose_unknown_tags=lambda tags: build_tag_disclosure(
        tags, _tag_aggregate_service().get().get("sections", [])
    ),
)

from domain_ai_tools import DomainAITools  # noqa: E402
domain_ai_tools = DomainAITools(
    tag_service=lambda: _tag_aggregate_service(),
    find_journal=lambda *args, **kwargs: find_today_journal(*args, **kwargs),
    top_section_bounds=lambda text: _top_section_bounds(text),
    load_task_meta=lambda: _load_task_meta_map(),
    load_task_images=lambda: _load_task_image_map(),
    load_scrapbook=lambda date: _load_scrapbook(date),
    save_scrapbook=lambda date, items: _save_scrapbook(date, items),
    write_text=lambda *args, **kwargs: _safe_write_text(*args, **kwargs),
    sync_tag_aggregate=lambda path: tag_aggregate._sync_tag_aggregate_for_file(path),
    app_state_dir=APP_STATE_DIR,
    pretty_rel=lambda path: _pretty_rel(path),
)


# ── DeepSeek vision / uploads 检索 / photo curator ─ 抽到 vision_tools.py ──
# vision 工具运行依赖由本组装根注入。
import vision_tools  # noqa: E402
vision_tools.configure_effects(
    load_config=lambda: load_config(),
    report_failure=lambda *args, **kwargs: _report_silent_failure(*args, **kwargs),
    logger=lambda: log,
    openai_factory=lambda *args, **kwargs: OpenAI(*args, **kwargs),
    pick_attachment_url=lambda args: journal_task_tools._pick_attachment_url(args),
    attachments_dir=lambda: ATTACHMENTS_DIR,
    load_attachments_index=lambda: _load_attachments_index(),
    curator_system_path=lambda: CURATOR_SYSTEM_PATH,
    rebuild_curator_prompt=lambda: _rebuild_curator_system_prompt(),
    get_profile=lambda *args, **kwargs: get_profile(*args, **kwargs),
    get_client=lambda profile: get_client(profile),
    log_cache_usage=lambda response, source: _log_cache_usage(response, source),
    index_upsert=lambda date, filename, **fields: _index_upsert(date, filename, **fields),
)


# ── search / 杂项工具 ─ 抽到 search_tools.py(清册01-§8,行为零变化)──
# search 工具运行依赖由本组装根注入。
import search_tools  # noqa: E402
search_tools.configure_effects(
    vault_dir=lambda: VAULT_DIR,
    attachments_dir=lambda: ATTACHMENTS_DIR,
    load_attachments_index=lambda: _load_attachments_index(),
    save_attachments_index=lambda items: _save_attachments_index(items),
    load_task_meta=lambda: _load_task_meta_map(),
    save_task_meta=lambda meta: _save_task_meta_map(meta),
    task_meta_state=lambda name, meta: _task_meta_state(name, meta),
    protocols=lambda: PROTOCOLS,
    load_protocol=lambda name: load_protocol(name),
)

# ── web_search / fetch_url 工具 ─ 抽到 web_tools.py(行为零变化,仅搬迁) ──
# 历史:此处原是 ~250 行 web_search 后端(360/ddgs/搜狗微信/B站)+ fetch_url + _html_to_text
# 现在:见 web_tools.py。这一对工具是 chat tool-dispatch 的纯 vertical,无模块级锁/线程/状态,
# 抽出后 TOOL_IMPL 直接引用同名函数,API 一字不变。
import web_tools  # noqa: E402
web_tools.configure_effects(
    load_config=lambda: load_config(),
    report_failure=lambda *args, **kwargs: _report_silent_failure(
        *args, **kwargs
    ),
    logger=log,
)

import widget_runtime  # noqa: E402
import memo_store  # noqa: E402


def _list_widgets_for_ai():
    return widget_runtime.tool_list_widgets(
        journal_task_tools.tool_list_widgets()
    )


# TOOL_IMPL 由各所有者模块的显式实现表组装。
import tool_registry  # noqa: E402
import skill_runtime  # noqa: E402
tool_registry.configure_effects(
    list_widgets=_list_widgets_for_ai,
    tool_impl=lambda: TOOL_IMPL,
    report_failure=lambda *args, **kwargs: _report_silent_failure(
        *args, **kwargs
    ),
    logger=lambda: log,
)
TOOL_IMPL = tool_registry.build_tool_impl({
    "list_widgets": _list_widgets_for_ai,
    "search_widget_capabilities": widget_runtime.tool_search_widget_capabilities,
    "validate_widget_spec": widget_runtime.tool_validate_widget_spec,
    "install_widget_spec": widget_runtime.tool_install_widget_spec,
    "set_widget_enabled": widget_runtime.tool_set_widget_enabled,
    "remove_widget": widget_runtime.tool_remove_widget,
    "list_memos": memo_store.tool_list_memos,
    "create_memo": memo_store.tool_create_memo,
    "update_memo": memo_store.tool_update_memo,
    "act_on_memo": memo_store.tool_act_on_memo,
    "manage_memo_series": memo_store.tool_manage_memo_series,
    "patch_journal_block": lambda args: journal_task_tools.tool_patch_journal_block(
        args, enforce_tag_vocabulary=True
    ),
    "read_today_schedule": journal_task_tools.tool_read_today_schedule,
    "list_recent_days": journal_task_tools.tool_list_recent_days,
    "insert_journal_block": lambda args: journal_task_tools.tool_insert_journal_block(
        args, enforce_tag_vocabulary=True
    ),
    "append_journal_comment": journal_task_tools.tool_append_journal_comment,
    "manage_daily_task": journal_task_tools.tool_manage_daily_task,
    "check_daily_task": journal_task_tools.tool_check_daily_task,
    "set_daily_task_image": journal_task_tools.tool_set_daily_task_image,
    "set_water_cup_image": journal_task_tools.tool_set_water_cup_image,
    "place_scrapbook_image": journal_task_tools.tool_place_scrapbook_image,
    "set_daily_task_meta": search_tools.tool_set_daily_task_meta,
    "search_text": search_tools.tool_search_text,
    "read_text": search_tools.tool_read_text,
    "delete_attachment": search_tools.tool_delete_attachment,
    "load_protocol": search_tools.tool_load_protocol,
    "search_skills": skill_runtime.tool_search_skills,
    "load_skill": skill_runtime.tool_load_skill,
    "read_skill_resource": skill_runtime.tool_read_skill_resource,
    "manage_tag_aggregate": domain_ai_tools.manage_tag_aggregate,
    "get_daily_care_state": domain_ai_tools.get_daily_care_state,
    "manage_scrapbook": domain_ai_tools.manage_scrapbook,
    "delete_journal_entry": domain_ai_tools.delete_journal_entry,
    "manage_mood": domain_ai_tools.manage_mood,
    "vision_classify": vision_tools.tool_vision_classify,
    "record_image_observation": vision_tools.tool_record_image_observation,
    "list_my_uploads": vision_tools.tool_list_my_uploads,
    "search_my_uploads": vision_tools.tool_search_my_uploads,
    "ask_photo_curator": vision_tools.tool_ask_photo_curator,
    "web_search": web_tools.tool_web_search,
    "fetch_url": web_tools.tool_fetch_url,
})


# ── tool 注册引擎(gating/quota/dispatch)─ 抽到 tool_registry.py(清册01-§9,行为零变化)──
# 历史:此处原是 ~120 行 lazy tool loading + TOOL_QUOTA + _dispatch_tool + cache 观测。
# chat 通过注入的 registry 函数调用。
from action_policy import build_action_context  # noqa: E402
from tool_registry import (  # noqa: E402
    _active_tools,
    _log_cache_usage, _dispatch_tool,
)

# ── app ──────────────────────────────────────────────────────────────
app = FastAPI(title=f"gateway v{APP_VERSION}")
from mood_routes import create_mood_router  # noqa: E402
app.include_router(create_mood_router(domain_ai_tools))

import system_routes  # noqa: E402
system_routes.configure_effects(
    gateway_dir=lambda: GATEWAY_DIR,
    server_file=lambda: Path(__file__),
)
app.include_router(system_routes.router)

import widget_routes  # noqa: E402
widget_routes.configure_effects(
    user_widgets_path=lambda: USER_WIDGETS_PATH,
    widgets_dir=lambda: WIDGETS_DIR,
    write_text=lambda *args, **kwargs: _safe_write_text(*args, **kwargs),
    experiment_variant=lambda: os.getenv(
        "GATEWAY_WIDGET_EXPERIMENT_VARIANT", "reference"
    ),
)
app.include_router(widget_routes.router)

import vault_config_routes  # noqa: E402
vault_config_routes.configure_effects(data_home=lambda: DATA_HOME)
app.include_router(vault_config_routes.router)

# PULSE LARGE refactor P1:7 /api/pulse/* endpoint 已搬到 pulse_routes.py(thin
# wrapper,运行依赖由本组装根注入)。本 include 后下方 PULSE endpoint
# 装饰器全删,业务逻辑(_self_evolve_run / _eval_* / _pulse_validate 等)P2-P4 续。
import pulse_routes  # noqa: E402
from pulse_routes import router as _pulse_router  # noqa: E402
pulse_routes.configure_effects(
    pulse_dir=lambda: PULSE_DIR,
    parse_pulse_md=lambda text, name: _parse_pulse_md(text, name),
    report_failure=lambda *args, **kwargs: _report_silent_failure(*args, **kwargs),
    logger=lambda: log,
    self_evolve_run=lambda *args, **kwargs: _self_evolve_run(*args, **kwargs),
    compact_summary_run=lambda conversation: _compact_summary_run(conversation),
    safe_write_text=lambda *args, **kwargs: _safe_write_text(*args, **kwargs),
    vault_git=lambda: vault_git,
)
app.include_router(_pulse_router)

# Extract Module(ctrl-c-v § 9):setup / config 簇(/api/setup-status
# /api/setup/* /api/models)搬到 setup_routes.py(thin wrapper,共享能力由本组装根
# 注入)。零直接调用方(HTTP-only)，组装根只注册 router。
# 配置 adapter 与 provider 在本组装根连接。
import setup_routes  # noqa: E402
from setup_routes import router as _setup_router  # noqa: E402
setup_routes.configure_effects(
    load_config=lambda: load_config(),
    save_config=lambda cfg: _save_config(cfg),
    sync_env_secrets=lambda updates: sync_env_secrets(updates),
    config_path=lambda: CONFIG_PATH,
    openai_available=lambda: OpenAI is not None,
)
app.include_router(_setup_router)

# Extract Module(ctrl-c-v § 9):daily-tasks 簇(8 endpoint:/api/daily-tasks/* +
# /api/water-cup GET+POST)搬到 daily_tasks_routes.py(thin wrapper,运行依赖由本
# 组装根注入 io-map、任务操作与图片能力。
import daily_tasks_routes  # noqa: E402
from daily_tasks_routes import router as _daily_tasks_router  # noqa: E402
daily_tasks_routes.configure_effects(
    datetime_provider=lambda: datetime,
    timedelta_provider=lambda: timedelta,
    today_date_str=lambda: _today_date_str(),
    read_tasks=lambda *args, **kwargs: _read_daily_tasks_from_md(*args, **kwargs),
    load_image_map=lambda: _load_task_image_map(),
    save_image_map=lambda image_map: _save_task_image_map(image_map),
    load_meta_map=lambda: _load_task_meta_map(),
    save_meta_map=lambda meta_map: _save_task_meta_map(meta_map),
    meta_state=lambda *args, **kwargs: _task_meta_state(*args, **kwargs),
    ensure_progress=lambda *args, **kwargs: _ensure_md_progress_children(
        *args, **kwargs
    ),
    writable_dates=lambda: _writable_dates_set(),
    logger=lambda: log,
    bump_intake=lambda *args, **kwargs: _bump_intake(*args, **kwargs),
    set_md_checkbox=lambda *args, **kwargs: _set_md_checkbox(*args, **kwargs),
    find_journal=lambda *args, **kwargs: find_today_journal(*args, **kwargs),
    schedule_template_path=lambda: SCHEDULE_TEMPLATE_PATH,
    apply_task_op=lambda *args, **kwargs: _apply_task_op(*args, **kwargs),
    platform_root=lambda: PLATFORM_ROOT,
    top_section_bounds=lambda text: _top_section_bounds(text),
    get_processed_attachment=lambda *args, **kwargs: _get_or_create_processed_attachment(
        *args, **kwargs
    ),
    task_images_dir=lambda: DAILY_TASK_IMAGES_DIR,
    pretty_rel=lambda path: _pretty_rel(path),
    water_cup_key=lambda: WATER_CUP_KEY,
)
app.include_router(_daily_tasks_router)

# WidgetSpec v1 is a narrow read-only boundary. The broker owns validation and
# capability selection; the composition root supplies only vault read effects.
import widget_runtime_routes  # noqa: E402
widget_runtime.configure_effects(
    now=lambda: datetime.now(),
    find_journal=lambda day: find_today_journal(day),
    top_section_bounds=lambda text: _top_section_bounds(text),
    specs_path=lambda: DATA_DIR / "widget-specs.json",
    write_text=lambda *args, **kwargs: _safe_write_text(*args, **kwargs),
    list_memos=lambda args: memo_store.tool_list_memos(args),
    set_system_widget_enabled=lambda args: widget_routes.set_widget_enabled(args),
)
def _record_memo_completion(text, occurrence_id):
    marker = f"<!-- memo:{occurrence_id} -->"
    journal = find_today_journal()
    if journal:
        try:
            if marker in journal.read_text(encoding="utf-8"):
                return {"ok": True, "already_recorded": True}
        except (OSError, UnicodeError):
            return {"error": "journal_read_failed"}
    return journal_task_tools.tool_insert_journal_block({
        "tag": "备忘",
        "title": "完成备忘",
        "body": f"{text}\n\n{marker}",
    }, enforce_tag_vocabulary=False)


memo_store.configure_effects(
    path=lambda: DATA_DIR / "memos.v1.json",
    write_text=lambda *args, **kwargs: _safe_write_text(*args, **kwargs),
    now=lambda: datetime.now().astimezone(),
    record_completion=_record_memo_completion,
)
widget_runtime_routes.configure_effects(
    capabilities=lambda: widget_runtime.CAPABILITIES,
    validate=lambda spec: widget_runtime.validate_widget_spec(spec),
    query=lambda spec: widget_runtime.query_widget(spec),
    installed=lambda: widget_runtime.list_installed_specs(),
)
app.include_router(widget_runtime_routes.router)

# Memo state remains owned by memo_store. This narrow adapter gives the PC GUI
# the same deterministic operations as AI tools without duplicating state rules.
from memo_routes import create_memo_router  # noqa: E402

app.include_router(create_memo_router(memo_store))

# thread-history 业务在 ThreadHistoryService，路由只做 HTTP 映射。provider 在请求时
# 读取 server 当前绑定，保留既有测试/兼容调用的 call-time patch 语义。
from thread_history import ThreadHistoryService  # noqa: E402
from thread_routes import create_thread_router  # noqa: E402


def _thread_history_service() -> ThreadHistoryService:
    return ThreadHistoryService(
        path=THREAD_HISTORY_PATH,
        data_dir=DATA_DIR,
        lock=_THREAD_LOCK,
        write_text=_safe_write_text,
        report_failure=_report_silent_failure,
        logger=log,
        now=datetime.now,
        mtime=lambda _path: _thread_history_mtime_ms(),
        is_stale=_thread_save_is_stale,
    )


_thread_router = create_thread_router(_thread_history_service)
app.include_router(_thread_router)

# Extract Module(ctrl-c-v § 9):eval/留言板(4 endpoint:/api/eval/list,today,test,run)
# 搬到 board_routes.py(纯 handler 搬迁,_eval_* helper + EVAL_LOG_DIR 早在 pulse_eval,
# 具名 effect 由本组装根注入。
import board_routes  # noqa: E402
from board_routes import router as _board_router  # noqa: E402
board_routes.configure_effects(
    eval_log_dir=lambda: EVAL_LOG_DIR,
    datetime_provider=lambda: datetime,
    timedelta_provider=lambda: timedelta,
    find_today_journal=lambda *args, **kwargs: find_today_journal(*args, **kwargs),
    get_profile=lambda *args, **kwargs: get_profile(*args, **kwargs),
    get_client=lambda profile: get_client(profile),
    get_model=lambda profile: get_model(profile),
    classify_eval_err=lambda error: _classify_eval_err(error),
    report_failure=lambda *args, **kwargs: _report_silent_failure(*args, **kwargs),
    build_messages=lambda *args, **kwargs: _eval_build_messages(*args, **kwargs),
    build_feature_intro_messages=lambda target: _eval_build_feature_intro_messages(target),
    eval_persist=lambda target, merged: _eval_persist(target, merged),
    eval_notify=lambda target, merged: _eval_notify(target, merged),
    log_cache_usage=lambda response, source: _log_cache_usage(response, source),
    logger=lambda: log,
)
app.include_router(_board_router)

# journal 查询、写入和 tag aggregate 通过三个窄服务组装。受保护的 authorship
# 原语仍只有 journal_core 一份，服务只负责编排。
from journal_read_routes import create_journal_read_router  # noqa: E402
from journal_read_service import JournalReadService  # noqa: E402
from journal_write_routes import create_journal_write_router  # noqa: E402
from journal_write_service import JournalWriteService  # noqa: E402
from tag_aggregate_routes import create_tag_aggregate_router  # noqa: E402
from tag_aggregate_service import TagAggregateService  # noqa: E402


def _journal_read_service() -> JournalReadService:
    return JournalReadService(
        journal_for_date=_journal_for_date,
        list_journal_files=_list_journal_files,
        journal_dir=JOURNAL_DIR,
    )


_journal_read_router = create_journal_read_router(_journal_read_service)
app.include_router(_journal_read_router)


def _journal_write_service() -> JournalWriteService:
    from journal_core import TIME_H1_RE
    return JournalWriteService(
        datetime_type=datetime,
        new_day_create=_new_day_create,
        find_journal=find_today_journal,
        insert_block=_insert_block,
        patch_block=_patch_block,
        write_text=_safe_write_text,
        pretty_rel=_pretty_rel,
        time_h1_re=TIME_H1_RE,
        sync_tag_aggregate=lambda path: tag_aggregate._sync_tag_aggregate_for_file(path),
    )


def _tag_aggregate_service() -> TagAggregateService:
    return TagAggregateService(
        path=TAG_AGGREGATE_PATH,
        vault_dir=VAULT_DIR,
        lock_factory=_get_vault_md_lock,
        write_text=_safe_write_text,
        commit_after_write=vault_git.commit_after_write,
        refresh_aggregate=_refresh_tag_aggregate,
        parse_aggregate=_parse_tag_aggregate,
        logger=log,
        on_tags_registered=lambda tags: _schedule_tag_metadata(tags),
    )


_journal_write_router = create_journal_write_router(
    _journal_write_service
)
_tag_aggregate_router = create_tag_aggregate_router(
    _tag_aggregate_service
)
app.include_router(_journal_write_router)
app.include_router(_tag_aggregate_router)

# Extract Module(ctrl-c-v § 9):chat 对话引擎(/api/chat + /api/chat/upload-image)搬到
# chat_routes.py(本 session 最高风险 — DSML 泄漏闸/SSE 契约/可变状态/claim 审计随之搬走,
# 15 条 characterization 守红线)。tool 引擎(TOOL_IMPL/_dispatch_tool/build_system_prompt/
# LLM、附件、工具与 prompt 能力由本组装根注入。
import chat_routes  # noqa: E402
from chat_routes import router as _chat_router  # noqa: E402
chat_routes.configure_effects(
    load_attachments_index=lambda: _load_attachments_index(),
    attachments_dir=lambda: ATTACHMENTS_DIR,
    ocr_text=lambda path: _ocr_text(path),
    index_upsert=lambda *args, **kwargs: _index_upsert(*args, **kwargs),
    vision_classify_image=lambda *args, **kwargs: vision_tools._deepseek_classify_image(
        *args, **kwargs
    ),
    report_failure=lambda *args, **kwargs: _report_silent_failure(*args, **kwargs),
    logger=lambda: log,
    dispatch_tool=lambda *args, **kwargs: _dispatch_tool(*args, **kwargs),
    active_tools=lambda action_context: _active_tools(action_context),
    log_cache_usage=lambda response, source: _log_cache_usage(response, source),
    allowed_image_ext=lambda: ALLOWED_IMAGE_EXT,
    max_image_bytes=lambda: MAX_IMAGE_BYTES,
    find_by_hash=lambda sha: _find_by_hash(sha),
    index_attachment=lambda *args, **kwargs: _index_attachment(*args, **kwargs),
    compute_time_hint=lambda: _compute_time_block_hint(),
    build_action_context=lambda user_msg, context, recent_user_texts=None: build_action_context(
        user_msg, context, recent_user_texts
    ),
    strip_ocr_history=lambda text: _strip_ocr_from_history(text),
    today_date_str=lambda: _today_date_str(),
    build_system_prompt=lambda *args, **kwargs: build_system_prompt(*args, **kwargs),
    get_client=lambda profile: get_client(profile),
    get_model=lambda profile: get_model(profile),
    get_profile=lambda *args, **kwargs: get_profile(*args, **kwargs),
    image_data_url=lambda path: vision_tools.attachment_to_data_url(path),
)
app.include_router(_chat_router)


async def _startup_retry_pending_vision():
    """Reconcile app-owned legacy photos, then drain one bounded index batch."""
    def migrate_and_retry():
        _reconcile_existing_attachments()
        return chat_routes.retry_pending_vision(3)

    asyncio.create_task(asyncio.to_thread(migrate_and_retry))


# 图像 HTTP 簇按附件、抠图、视觉分类三个 effect 服务组装；共享 helper 由
# composition root 注入，不在服务间反向查询。
from attachment_routes import create_attachment_router  # noqa: E402
from attachment_service import AttachmentService  # noqa: E402
from cutout_routes import create_cutout_router  # noqa: E402
from cutout_service import CutoutService  # noqa: E402
from vision_routes import create_vision_router  # noqa: E402
from vision_service import VisionService  # noqa: E402


def _attachment_service() -> AttachmentService:
    return AttachmentService(
        attachments_dir=ATTACHMENTS_DIR,
        load_index=_load_attachments_index,
        save_index=_save_attachments_index,
        index_attachment=_index_attachment,
    )


def _cutout_service() -> CutoutService:
    return CutoutService(
        attachments_dir=ATTACHMENTS_DIR,
        task_images_dir=DAILY_TASK_IMAGES_DIR,
        process_attachment=_get_or_create_processed_attachment,
        sanitize_task_filename=_sanitize_task_filename,
        pretty_rel=_pretty_rel,
        load_image_map=_load_task_image_map,
        save_image_map=_save_task_image_map,
        load_meta_map=_load_task_meta_map,
        save_meta_map=_save_task_meta_map,
        ocr_text=_ocr_text,
        parse_pill_count=_parse_pill_count_from_ocr,
        load_config=load_config,
        logger=log,
    )


def _vision_service() -> VisionService:
    return VisionService(
        attachments_dir=ATTACHMENTS_DIR,
        classify_image=vision_tools._deepseek_classify_image,
    )


app.include_router(create_attachment_router(_attachment_service))
app.include_router(create_cutout_router(_cutout_service))
app.include_router(create_vision_router(_vision_service))

# Extract Module(ctrl-c-v § 9):MD/schema 迁移编排 glue(横幅状态机 + SSE + 启动 hook +
# legacy rewriter,17 区 ~470 行)搬到 migration_routes.py。engine 早已外置 migration_plan.py。
# reference 目标与运行依赖由本组装根注入。
import migration_routes  # noqa: E402
from migration_routes import router as _migration_router  # noqa: E402
from migration_routes import (  # noqa: E402,F401
    _ensure_vault_reference_files, _run_schema_migration_if_needed, _startup_v0125_md_migration,
)
migration_routes.configure_effects(
    get_client=lambda *args, **kwargs: get_client(*args, **kwargs),
    get_model=lambda *args, **kwargs: get_model(*args, **kwargs),
    get_profile=lambda *args, **kwargs: get_profile(*args, **kwargs),
    app_version=lambda: APP_VERSION,
    gateway_dir=lambda: GATEWAY_DIR,
    vault_dir=lambda: VAULT_DIR,
    app_state_dir=lambda: APP_STATE_DIR,
    logger=lambda: log,
    reference_targets=lambda: _VAULT_REFERENCE_TARGETS,
    push_notification=lambda *args, **kwargs: _push_notification(*args, **kwargs),
    safe_write_text=lambda *args, **kwargs: _safe_write_text(*args, **kwargs),
    vault_git=lambda: vault_git,
    schema_migration_prompt=lambda: _SCHEMA_MIGRATION_PROMPT,
    classify_eval_err=lambda error: _classify_eval_err(error),
    ensure_schema_header=lambda *args, **kwargs: _ensure_schema_version_header(
        *args, **kwargs
    ),
    get_evolve_lock=lambda target: _get_evolve_lock(target),
    get_schema_version=lambda text: _get_schema_version(text),
    migration_llm_call=lambda *args, **kwargs: _migration_llm_call(*args, **kwargs),
    validate_migration_output=lambda *args, **kwargs: _validate_migration_output(
        *args, **kwargs
    ),
    date_provider=lambda: date,
    report_failure=lambda *args, **kwargs: _report_silent_failure(*args, **kwargs),
)
app.include_router(_migration_router)


# ── §17a no-cache 中间件 / 自动建日记 / updater pending 消费 ──
# startup_hooks.py 持有实现；这里按既有顺序显式注册 middleware 与 startup
# handlers（FastAPI 按注册顺序执行 startup handlers）。
from startup_hooks import (  # noqa: E402
    _no_cache_ui,
    _startup_auto_create, _startup_vault_reference_and_migration,
)
app.middleware("http")(_no_cache_ui)
app.on_event("startup")(_startup_auto_create)
app.on_event("startup")(_startup_vault_reference_and_migration)


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


# ── §11 attachments 索引 / curator prompt adapter ────────────────────
ATTACHMENTS_INDEX = ATTACHMENTS_DIR / "_index.json"
CURATOR_SYSTEM_PATH = ATTACHMENTS_DIR / "_curator_system.txt"
from attachments_index import (  # noqa: E402
    _load_attachments_index as _load_attachments_index_impl,
    _save_attachments_index as _save_attachments_index_impl,
    _format_curator_line,
    _rebuild_curator_system_prompt as _rebuild_curator_system_prompt_impl,
    _attachments_index_lock,
    _find_by_hash as _find_by_hash_impl,
    _index_upsert as _index_upsert_impl,
    _index_attachment as _index_attachment_impl,
    _reconcile_existing_attachments as _reconcile_existing_attachments_impl,
)


def _load_attachments_index() -> list:
    return _load_attachments_index_impl(
        index_path=ATTACHMENTS_INDEX,
        report_failure=_report_silent_failure,
    )


def _save_attachments_index(items: list):
    return _save_attachments_index_impl(
        items,
        index_path=ATTACHMENTS_INDEX,
        write_text=_safe_write_text,
    )


def _rebuild_curator_system_prompt():
    return _rebuild_curator_system_prompt_impl(
        load_index=_load_attachments_index,
        format_line=_format_curator_line,
        prompt_path=CURATOR_SYSTEM_PATH,
        write_text=_safe_write_text,
        report_failure=_report_silent_failure,
    )


def _find_by_hash(sha256_hex: str):
    return _find_by_hash_impl(
        sha256_hex,
        load_index=_load_attachments_index,
    )


def _index_upsert(date: str, filename: str, **fields):
    return _index_upsert_impl(
        date,
        filename,
        lock=_attachments_index_lock,
        load_index=_load_attachments_index,
        save_index=_save_attachments_index,
        rebuild_prompt=_rebuild_curator_system_prompt,
        **fields,
    )


def _reconcile_existing_attachments():
    return _reconcile_existing_attachments_impl(
        attachments_dir=ATTACHMENTS_DIR,
        allowed_extensions=ALLOWED_IMAGE_EXT,
        lock=_attachments_index_lock,
        load_index=_load_attachments_index,
        save_index=_save_attachments_index,
        rebuild_prompt=_rebuild_curator_system_prompt,
    )


def _index_attachment(
    date: str,
    filename: str,
    original: str,
    size: int,
    sha256_hex: str = "",
):
    return _index_attachment_impl(
        date,
        filename,
        original,
        size,
        sha256_hex,
        attachments_dir=ATTACHMENTS_DIR,
        ocr_text=_ocr_text,
        logger=log,
        upsert=_index_upsert,
    )

# ── OCR dispatcher + 文本工具 ─ 抽到 ocr.py(行为零变化,仅搬迁) ──
# _ocr_text / _strip_ocr_from_history / _parse_pill_count_from_ocr 三个 helper +
# 配套 _OCR_BLOCK_RE / _OCR_FILENAME_RE / _PILL_COUNT_RE 三个正则 一起搬到 ocr.py。
# silent-failure 走 ocr 模块自己的 _emit_failure(server.py 启动时已注入 sink)。
from ocr import (
    _ocr_text as _ocr_text_impl,
    _strip_ocr_from_history, _parse_pill_count_from_ocr,
)


def _ocr_text(file_path: Path) -> str:
    return _ocr_text_impl(
        file_path,
        load_config=load_config,
    )


# ── sliding-window summarization (B 包) ─ 抽到 history_summary.py(清册01-§12,行为零变化)──
# RECENT_KEEP/SUMMARY_MIN_OLD/_SUMMARY_CACHE(_MAX)/_summarize_history 全量搬迁(无测试
# 直接 monkeypatch,与 THREAD_HISTORY_PATH 那类需留权威在 server 的常量不同)。
# history summary 已由消费者直接依赖所有者模块。


# _OCR_BLOCK_RE / _OCR_FILENAME_RE 已搬到 ocr.py(顶部 from ocr import 进来)


# _strip_ocr_from_history 已搬到 ocr.py(顶部 from ocr import 进来)


# ── journal parser + authorship 写原语 ─ 抽到 journal_core.py(清册01-§13,行为零变化)──
# journal authorship 与写原语由 journal_core 持有。
import journal_core  # noqa: E402
from journal_core import (  # noqa: E402
    find_today_journal, parse_journal,
    _get_vault_md_lock,
    _insert_block, _top_section_bounds, _apply_task_op, _patch_block,
    _append_comment_to_block,
)
journal_core.configure_effects(
    journal_dir=lambda: JOURNAL_DIR,
    pretty_rel=lambda: _pretty_rel,
    write_text=lambda: _safe_write_text,
    vault_dir=lambda: VAULT_DIR,
)

# ── daily-task io-map / MD 进度同步 ─ 抽到 daily_task_store.py(清册01-§14,行为零变化)──
# daily-task 状态由 store 持有，路径与写入 effect 在此组装。
import daily_task_store  # noqa: E402
from daily_task_store import (  # noqa: E402
    _sanitize_task_filename, _load_task_meta_map, _task_meta_state, _bump_intake,
    _read_daily_tasks_from_md, _ensure_md_progress_children, _set_md_checkbox,
    WATER_CUP_KEY,
)
daily_task_store.configure_effects(
    meta_path=lambda: DAILY_TASK_META_MAP,
    report_failure=lambda *args, **kwargs: _report_silent_failure(
        *args, **kwargs
    ),
    save_meta=lambda meta: _save_task_meta_map(meta),
    today_date=lambda: _today_date_str(),
    find_journal=lambda *args: find_today_journal(*args),
    template_path=lambda: SCHEDULE_TEMPLATE_PATH,
    top_section_bounds=lambda text: _top_section_bounds(text),
    write_text=lambda *args, **kwargs: _safe_write_text(*args, **kwargs),
)


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

# ── 新日创建 / "第N天" baseline ─ 抽到 day_create.py(清册01-§18,行为零变化)──
# _DAY_CN/_get_day_one/_new_day_create 函数体逐字节照搬,load_config/_list_journal_files/
# JOURNAL_DIR/VAULT_DIR/_pretty_rel 由本组装根显式注入——
# tests/test_day_one_and_water_cup.py 的 isolated_vault fixture monkeypatch.setattr(server,
# "JOURNAL_DIR"/"load_config", ...) 仍由适配器 call-time resolve。
from day_create import (  # noqa: E402
    _get_day_one as _get_day_one_impl,
    _new_day_create as _new_day_create_impl,
)


def _get_day_one(today_iso: str) -> datetime:
    return _get_day_one_impl(
        today_iso,
        load_config=load_config,
        list_journal_files=_list_journal_files,
    )


def _new_day_create(date_iso: str) -> dict:
    return _new_day_create_impl(
        date_iso,
        get_day_one=_get_day_one,
        journal_dir=JOURNAL_DIR,
        vault_dir=VAULT_DIR,
        pretty_rel=_pretty_rel,
    )


# ── scrapbook (手账浮层照片) ─────────────────────────────────────────
# 每天一个 json: data/scrapbook/{YYYY-MM-DD}.json
# 数组: [{id, src, x, y, w, h, rotation, anchor_time, z}]
# - src 是相对 / 开头的 url(/data/scrapbook-images/xxx.png 或 /attachments/yyy)
# - x,y 是相对 stream 容器左上的 px(整数)
# - rotation 是度数(可负)
# - anchor_time 是 "HH:MM" 字串,用于"贴在哪个时间块附近"的语义锚点
SCRAPBOOK_DIR = DATA_DIR / "scrapbook"
SCRAPBOOK_IMAGES_DIR = DATA_DIR / "scrapbook-images"


# scrapbook 叶子函数通过目录、写入和告警 effect 组装，endpoint 留下面。
from scrapbook import (  # noqa: E402,F401
    _load_scrapbook as _load_scrapbook_impl,
    _save_scrapbook as _save_scrapbook_impl,
    _scrapbook_id,
    _scrapbook_path as _scrapbook_path_impl,
)


def _scrapbook_path(date_str: str) -> Path:
    return _scrapbook_path_impl(
        date_str,
        scrapbook_dir=SCRAPBOOK_DIR,
    )


def _load_scrapbook(date_str: str) -> list:
    return _load_scrapbook_impl(
        date_str,
        path_for_date=_scrapbook_path,
        report_failure=_report_silent_failure,
    )


def _save_scrapbook(date_str: str, items: list):
    return _save_scrapbook_impl(
        date_str,
        items,
        scrapbook_dir=SCRAPBOOK_DIR,
        path_for_date=_scrapbook_path,
        write_text=_safe_write_text,
    )


import scrapbook_routes  # noqa: E402
scrapbook_routes.configure_effects(
    load=lambda date: _load_scrapbook(date),
    save=lambda date, items: _save_scrapbook(date, items),
    new_id=lambda: _scrapbook_id(),
)
app.include_router(scrapbook_routes.router)


# ── daily-task images (个人化打卡图) ──────────────────────────────────
DAILY_TASK_IMAGES_DIR = DATA_DIR / "daily-task-images"
DAILY_TASK_IMAGES_MAP = DATA_DIR / "daily-task-images.json"
DAILY_TASK_META_MAP = DATA_DIR / "daily-task-meta.json"

# _PILL_COUNT_RE / _parse_pill_count_from_ocr 已搬到 ocr.py(顶部 from ocr import 进来)


# _sanitize_task_filename 由 daily_task_store 持有。

# ── 图像处理 dispatcher ─ 抽到 cutout.py(行为零变化,仅搬迁) ──
# 历史:此处原是 ~73 行 attachment → 端侧/百度/原图 三层 dispatcher。
# 现在:见 cutout.py。silent-failure 走 cutout 模块自己的 _emit_failure(server 启动时
# 已注入 sink,L2984-2985)。附件目录与配置读取由本组装根注入。
from cutout import (
    _get_or_create_processed_attachment as _get_or_create_processed_attachment_impl,
)


def _get_or_create_processed_attachment(
    attachment_url: str,
    cutout: bool = True,
):
    return _get_or_create_processed_attachment_impl(
        attachment_url,
        cutout,
        attachments_dir=ATTACHMENTS_DIR,
        load_config=load_config,
    )


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


# _load_task_meta_map 由 daily_task_store 持有。


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


# _task_meta_state / _bump_intake / _read_daily_tasks_from_md / _ensure_md_progress_children /
# MD checkbox 与 WATER_CUP_KEY 由 daily_task_store 持有。

# ── §15 vault audit/repair + git history 已抽出 vault_audit_routes.py ──────
# vault audit/history router 由具名 effect 组装。
import vault_audit_routes  # noqa: E402
from vault_audit_routes import (  # noqa: E402
    _audit_vault,
    router as _vault_audit_router,
)
vault_audit_routes.configure_effects(
    load_image_map=lambda: _load_task_image_map(),
    save_image_map=lambda image_map: _save_task_image_map(image_map),
    load_meta_map=lambda: _load_task_meta_map(),
    task_images_dir=lambda: DAILY_TASK_IMAGES_DIR,
    platform_root=lambda: PLATFORM_ROOT,
    pretty_rel=lambda: _pretty_rel,
    template_path=lambda: SCHEDULE_TEMPLATE_PATH,
    find_journal=lambda: find_today_journal(),
    top_section_bounds=lambda text: _top_section_bounds(text),
    aggregate_path=lambda: TAG_AGGREGATE_PATH,
    parse_aggregate=lambda text: _parse_tag_aggregate(text),
    vault_dir=lambda: VAULT_DIR,
    app_state_dir=lambda: APP_STATE_DIR,
    data_dir=lambda: DATA_DIR,
)
app.include_router(_vault_audit_router)


# ── §16 consent licenses 已抽出 consent_routes.py ──────────────────────────
# consent router 的路径与原子写能力由本组装根注入。
CONSENT_LICENSES_PATH = DATA_DIR / "consent-licenses.json"
import consent_routes  # noqa: E402
from consent_routes import router as _consent_router  # noqa: E402
consent_routes.configure_effects(
    licenses_path=lambda: CONSENT_LICENSES_PATH,
    data_dir=lambda: DATA_DIR,
    safe_write_text=lambda *args, **kwargs: _safe_write_text(*args, **kwargs),
)
app.include_router(_consent_router)


# ── §17b 启动期迁移 / config sanity / vault git init / P0 后台 init 已抽出 startup_hooks.py ──
# 注册顺序保持；共享 init state 与运行能力由具名 effect 连接。
import startup_hooks  # noqa: E402
from startup_hooks import (  # noqa: E402
    _startup_migrate_state, _vault_audit_step, _startup_sf_sender, _startup_hb_sender,
    _shutdown_sf_sender, _startup_config_sanity, _vault_git_init_step,
    _INIT_STATE, _INIT_LOCK, _startup_background_init,
)


startup_hooks.configure_effects(
    code_root=lambda: CODE_ROOT,
    find_today_journal=lambda *args, **kwargs: find_today_journal(*args, **kwargs),
    logger=lambda: log,
    ensure_vault_reference_files=lambda: _ensure_vault_reference_files(),
    run_schema_migration=lambda: _run_schema_migration_if_needed(),
    startup_md_migration=lambda: _startup_v0125_md_migration(),
    consume_pending_notifications=lambda: _consume_pending_notifications(),
    report_failure=lambda *args, **kwargs: _report_silent_failure(*args, **kwargs),
    push_notification=lambda *args, **kwargs: _push_notification(*args, **kwargs),
    migrate_old_state=lambda: _migrate_old_state(),
    data_home=lambda: DATA_HOME,
    app_state_dir=lambda: APP_STATE_DIR,
    audit_vault=lambda: _audit_vault(),
    sf_thread_get=telemetry.get_sf_sender_thread,
    sf_thread_set=telemetry.set_sf_sender_thread,
    sf_sender_loop=lambda: _sf_sender_loop(),
    hb_thread_get=telemetry.get_hb_sender_thread,
    hb_thread_set=telemetry.set_hb_sender_thread,
    hb_sender_loop=lambda: _hb_sender_loop(),
    stop_senders=telemetry.stop_sender_threads,
    load_config=lambda: load_config(),
    vault_git=lambda: vault_git,
    vault_dir=lambda: VAULT_DIR,
    run_vault_git_step=lambda: _vault_git_init_step(),
    run_vault_audit_step=lambda: _vault_audit_step(),
)
app.on_event("startup")(_startup_migrate_state)
app.on_event("startup")(_startup_sf_sender)
app.on_event("startup")(_startup_hb_sender)
app.on_event("shutdown")(_shutdown_sf_sender)
app.on_event("startup")(_startup_config_sanity)
app.on_event("startup")(_startup_background_init)
# 必须晚于 _startup_migrate_state 注册：首次从 legacy state 升级时，先把旧附件
# 搬进 app-state，再做存量索引发现，避免要到第二次启动才补到。
app.on_event("startup")(_startup_retry_pending_vision)


# ── chat thread history(server-side 持久化,跨浏览器/跨设备同步源)──
# 路径常量 + 单写锁暂留 composition root；thread service 由上方 provider 组装。
# 无参 mtime wrapper 与 stale helper 暂留给现有直接调用测试，后续 contract 阶段移除。
THREAD_HISTORY_PATH = DATA_DIR / "thread-history.json"
_THREAD_LOCK = threading.Lock()

from thread_cas import (  # noqa: E402
    _thread_history_mtime_ms as _thread_history_mtime_ms_for_path,
    _thread_save_is_stale,
)


def _thread_history_mtime_ms() -> int:
    return _thread_history_mtime_ms_for_path(THREAD_HISTORY_PATH)


# ── §20a health/init-status 已抽出 notification_routes.py ──────────────────
# health/init-status 由 notification router 提供。
import notification_routes  # noqa: E402
from notification_routes import router as _notification_router  # noqa: E402
app.include_router(_notification_router)


# PULSE_DIR 由 pulse_io 持有。

# ─── daily eval (测试端点) ──────────────────────────────────────────────────
# 设计:保留 build_system_prompt() 的 co-writer 身份不动,evaluator role
# 后置注入。同一把嗓子,换硬话。每次新开 completion (无 chat history),
# 输出 NOT 持久化(测试模式)。生产版会写 eval-log + push 通知。
# eval 能力由 pulse_eval 持有。

# ─── eval 持久化 + 通知 + 生产端点 ────────────────────────────────────────

# eval persistence/notification 由 pulse_eval 持有。


# pulse parsing 由 pulse_io 持有。


# pulse_detail 已搬到 pulse_routes.py(P1 thin wrapper)


# ── USER_PULSE 自演化 (0.1.4 起) ─────────────────────────────────────
# PULSE_BUDGET_CHARS / PULSE_STALE_DAYS / _TS_RE / _FROZEN_RE / _PLACEHOLDER_RE /
# pulse validation 由 pulse_io 持有。


# evolve prompts 由 pulse_evolve 持有。


# ── vault reference 落地 + schema 升级 ──────────────────────────────
# 分发模板源在 `gateway/reference/`,PyInstaller bundle 进 .app
# startup 时:① 缺的 reference 拷进 vault(byte-equal 不动已有)
#            ② bundle schema-version 比 vault 高 → 后台 LLM 重组 vault 文件
# schema version parsing 由 pulse_io 持有。

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

# A-H5: persist + consume 同把 lock,防多线程 append 行截断 / consume 时漏未持久化条
_PENDING_NOTIF_FILE_LOCK = threading.Lock()

# notification 共享队列在组装根创建并注入所有者模块。
from notification_routes import (  # noqa: E402
    _push_notification,
    _persist_pending_notification, _consume_pending_notifications,
)
notification_routes.configure_effects(
    app_version=lambda: APP_VERSION,
    init_lock=lambda: _INIT_LOCK,
    init_state=lambda: _INIT_STATE,
    notification_lock=lambda: _NOTIF_LOCK,
    pending_notifications=lambda: _PENDING_NOTIFICATIONS,
    persist_notification=lambda item: _persist_pending_notification(item),
    app_state_dir=lambda: APP_STATE_DIR,
    pending_file_lock=lambda: _PENDING_NOTIF_FILE_LOCK,
    logger=lambda: log,
    write_text=lambda *args, **kwargs: _safe_write_text(*args, **kwargs),
    push_notification=lambda *args, **kwargs: _push_notification(
        *args, **kwargs
    ),
    report_failure=lambda *args, **kwargs: _report_silent_failure(
        *args, **kwargs
    ),
)

# vault_git 是可独立复用的仓储叶子；组装根只注入反馈与通知 effect。
# lambda 保留 call-time patch 语义，测试替换 server 同名函数仍会命中。
vault_git.configure_effects(
    report_failure=lambda *args, **kwargs: _report_silent_failure(
        *args, **kwargs
    ),
    push_notification=lambda *args, **kwargs: _push_notification(
        *args, **kwargs
    ),
)


# Schema migration attempts 记录(防 #19 LLM call 死循环烧 token)
# 文件落 APP_STATE_DIR/data/.schema-migration-attempts.json
# 失败 silent 时退到 module-level cache(R8 fix):防 disk full / 跨用户 sudo / 只读 fs
# 场景下 attempts gate 永不闭合,LLM 死循环烧 deepseek-v4-pro token


# migration/telemetry effects 由本组装根连接。
import migration_telemetry_routes  # noqa: E402
from migration_telemetry_routes import (  # noqa: E402
    _migration_llm_call, _validate_migration_output,
)
migration_telemetry_routes.configure_effects(
    telemetry_consent=lambda: _telemetry_consent(),
    telemetry_save=lambda failures, heartbeat: _telemetry_save(
        failures, heartbeat
    ),
    env_overlay=lambda: _env_overlay(),
    get_client_id=lambda: get_client_id(),
    logger=lambda: log,
    client_id_path=lambda: telemetry.CLIENT_ID_PATH,
    set_client_id_cache=telemetry.set_client_id_cache,
    heartbeat_path=lambda: telemetry._HB_LAST_SENT_PATH,
    silent_failures_log=lambda: telemetry.SILENT_FAILURES_LOG,
    silent_failures_ring_max=lambda: telemetry._SILENT_FAILURES_RING_MAX,
    heartbeat_last_sent_day=telemetry._hb_last_sent_day,
)


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


# _SELF_EVOLVE_TARGETS 由 pulse_io 持有；
# lambda 闭包查 pulse_io 自己的 path 常量,跨模块 patch 走 monkeypatch.setitem 仍生效。


# evolve locks 由 pulse_evolve 持有。


# vault Markdown locks 由 journal_core 持有。

# evolve 与 schema helpers 由各自所有者模块持有。


# updater endpoints 由 notification router 提供。
# pulse_user_update 已搬到 pulse_routes.py(P1 thin wrapper)


# pulse_project_update 已搬到 pulse_routes.py(P1 thin wrapper)


# pulse_agent_context_update 已搬到 pulse_routes.py(P1 thin wrapper)


# Compact 摘要 — 抽到 compact_summary.py(行为零变化)。endpoint 留下面。
from compact_summary import compact_summary_run as _compact_summary_run_impl


def _compact_summary_run(conversation: str) -> str:
    return _compact_summary_run_impl(
        conversation,
        get_profile=get_profile,
        get_client=get_client,
        report_failure=_report_silent_failure,
        logger=log,
    )


# pulse_compact_summary 已搬到 pulse_routes.py(P1 thin wrapper)


# pulse_refresh_mirror 已搬到 pulse_routes.py(P1 thin wrapper)


# pulse_dashboard 已搬到 pulse_routes.py(P1 thin wrapper)


# tag aggregate parsing/refresh 由所有者模块提供。
import tag_aggregate  # noqa: E402
from tag_annotation import (  # noqa: E402
    enrich_tag_metadata,
    schedule_tag_metadata_enrichment,
)
from tag_aggregate import (  # noqa: E402
    _parse_tag_aggregate,
    _refresh_tag_aggregate,
)
tag_aggregate.configure_effects(
    journal_dir=lambda: JOURNAL_DIR,
    aggregate_path=lambda: TAG_AGGREGATE_PATH,
    lock_factory=lambda: _get_vault_md_lock,
    write_text=lambda: _safe_write_text,
    vault_dir=lambda: VAULT_DIR,
    on_tags_registered=lambda tags: _schedule_tag_metadata(tags),
)


def _tag_annotation_model_call(prompt: str) -> str:
    profile = (
        get_profile("deepseek-v4-flash")
        or get_profile("deepseek-v4-pro")
        or get_profile()
    )
    if not profile:
        raise RuntimeError("DeepSeek 未配置")
    client = get_client(profile)
    if client is None:
        raise RuntimeError("DeepSeek client 初始化失败")
    response = client.chat.completions.create(
        model=profile.get("model", "deepseek-v4-flash"),
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=500,
        timeout=60,
    )
    return response.choices[0].message.content or ""


def _run_tag_metadata(tags) -> dict:
    return enrich_tag_metadata(
        path=TAG_AGGREGATE_PATH,
        parse_aggregate=_parse_tag_aggregate,
        lock_factory=_get_vault_md_lock,
        write_text=_safe_write_text,
        call_model=_tag_annotation_model_call,
        tags=tags,
        commit_after_write=lambda path, tag: vault_git.commit_after_write(
            VAULT_DIR,
            f"tag metadata #{tag}",
            author="ai",
            paths=[path],
        ),
    )


def _schedule_tag_metadata(tags) -> bool:
    return schedule_tag_metadata_enrichment(
        tags=tags,
        runner=_run_tag_metadata,
        logger=log,
    )


# ── §21b telemetry consent / diagnostics router ─────────────────────
from migration_telemetry_routes import (  # noqa: E402
    router as _migration_telemetry_router,
)
app.include_router(_migration_telemetry_router)


# journal insert 由 journal_core 持有。


# ── daily-task 维护(真相源 + 今天文件双写) ─────────────────────────
# 真相源 = vault/daily-tasks.md(用户拥有,跟着 vault 走)。
# 之前用 ~/.claude/skills/.../SCHEDULE_TEMPLATE.md 作模板顶部源,
# 但 new-day.sh 不读它而是 hardcode → 5.15 加的 肌酸 第二天就丢。
# 现在两边(new-day.sh + tool_manage_daily_task)都读写这个真相源。
DAILY_TASKS_SOURCE = VAULT_DIR / "daily-tasks.md"
SCHEDULE_TEMPLATE_PATH = DAILY_TASKS_SOURCE  # 兼容旧名(下方 _apply_task_op 还在用)

# journal section parsing 由 journal_core 持有。


# journal task/patch/comment 原语由 journal_core 持有。



app.middleware("http")(system_routes.no_cache_for_static_assets)

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
