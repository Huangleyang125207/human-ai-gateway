# PATTERN: hook — FastAPI startup/shutdown 事件 + 自动建日记 + 后台 init 序列
# USE WHEN: 改启动顺序 / 加新 startup 步骤 / 改 P0 后台 init 编排
# COPY THIS: 无 — 本模块是 server.py §17(清册01)的搬迁体,契约在 server 注册处
#
# 抽出记录(2026-07-22, 清册01-§17,Parallel Change expand):
# - 原址 server.py §17 段(no-cache 中间件 / 自动建日记 / updater pending 消费 /
#   启动期迁移+config sanity+vault git init / _INIT_STATE 后台 init),函数体逐字节照搬。
# - 本模块内函数**不带** @app.middleware / @app.on_event 装饰器(避免循环 import —
#   `app` 对象定义在 server.py,server.py 反过来要 import 本模块)。server.py 顶层用
#   `app.middleware("http")(_no_cache_ui)` / `app.on_event(...)( _startup_xxx)` 显式
#   注册,**注册顺序与原文件完全一致**(FastAPI 按注册顺序跑 startup/shutdown handler,
#   这段本身就是"启动顺序全靠通读全文重建"的高危段,搬迁时顺序是唯一不能错的契约)。
# - 跨模块路径、迁移、通知、遥测线程与 vault 初始化能力由组装根以具名
#   provider 注入；模块自身 helper 直接调用，不反向导入 server。
# - test_background_init.py 直调 `server._background_vault_init()` +
#   `monkeypatch.setattr(server, "_vault_git_init_step"/"_vault_audit_step", ...)` —
#   `_background_vault_init` 内部对这两个 helper 的调用走组装根注入的专用 callback，
#   因此测试对 server re-export 的 patch 仍命中。`_INIT_STATE`/`_INIT_LOCK` 是 dict/Lock,搬到本模块后经
#   re-export 与 server._INIT_STATE 共享同一对象引用(G2)——test 的
#   `server._INIT_STATE.update(...)` 与 notification_routes.py:49 `S._INIT_STATE` 零改动。
# - 遥测 thread 标量由 telemetry.py 持有，借助专用 getter/setter 注入。
import asyncio
import json
import subprocess
import threading
from datetime import datetime
from pathlib import Path


_CODE_ROOT = None
_FIND_TODAY_JOURNAL = None
_LOGGER = None
_ENSURE_VAULT_REFERENCE_FILES = None
_RUN_SCHEMA_MIGRATION = None
_STARTUP_MD_MIGRATION = None
_CONSUME_PENDING_NOTIFICATIONS = None
_REPORT_FAILURE = None
_PUSH_NOTIFICATION = None
_MIGRATE_OLD_STATE = None
_DATA_HOME = None
_APP_STATE_DIR = None
_AUDIT_VAULT = None
_SF_THREAD_GET = None
_SF_THREAD_SET = None
_SF_SENDER_LOOP = None
_HB_THREAD_GET = None
_HB_THREAD_SET = None
_HB_SENDER_LOOP = None
_STOP_SENDERS = None
_LOAD_CONFIG = None
_VAULT_GIT = None
_VAULT_DIR = None
_RUN_VAULT_GIT_STEP = None
_RUN_VAULT_AUDIT_STEP = None


def configure_effects(
    *,
    code_root,
    find_today_journal,
    logger,
    ensure_vault_reference_files,
    run_schema_migration,
    startup_md_migration,
    consume_pending_notifications,
    report_failure,
    push_notification,
    migrate_old_state,
    data_home,
    app_state_dir,
    audit_vault,
    sf_thread_get,
    sf_thread_set,
    sf_sender_loop,
    hb_thread_get,
    hb_thread_set,
    hb_sender_loop,
    stop_senders,
    load_config,
    vault_git,
    vault_dir,
    run_vault_git_step,
    run_vault_audit_step,
) -> None:
    global _CODE_ROOT, _FIND_TODAY_JOURNAL, _LOGGER
    global _ENSURE_VAULT_REFERENCE_FILES, _RUN_SCHEMA_MIGRATION
    global _STARTUP_MD_MIGRATION, _CONSUME_PENDING_NOTIFICATIONS
    global _REPORT_FAILURE, _PUSH_NOTIFICATION, _MIGRATE_OLD_STATE
    global _DATA_HOME, _APP_STATE_DIR, _AUDIT_VAULT
    global _SF_THREAD_GET, _SF_THREAD_SET, _SF_SENDER_LOOP
    global _HB_THREAD_GET, _HB_THREAD_SET, _HB_SENDER_LOOP, _STOP_SENDERS
    global _LOAD_CONFIG, _VAULT_GIT, _VAULT_DIR
    global _RUN_VAULT_GIT_STEP, _RUN_VAULT_AUDIT_STEP
    _CODE_ROOT = code_root
    _FIND_TODAY_JOURNAL = find_today_journal
    _LOGGER = logger
    _ENSURE_VAULT_REFERENCE_FILES = ensure_vault_reference_files
    _RUN_SCHEMA_MIGRATION = run_schema_migration
    _STARTUP_MD_MIGRATION = startup_md_migration
    _CONSUME_PENDING_NOTIFICATIONS = consume_pending_notifications
    _REPORT_FAILURE = report_failure
    _PUSH_NOTIFICATION = push_notification
    _MIGRATE_OLD_STATE = migrate_old_state
    _DATA_HOME = data_home
    _APP_STATE_DIR = app_state_dir
    _AUDIT_VAULT = audit_vault
    _SF_THREAD_GET = sf_thread_get
    _SF_THREAD_SET = sf_thread_set
    _SF_SENDER_LOOP = sf_sender_loop
    _HB_THREAD_GET = hb_thread_get
    _HB_THREAD_SET = hb_thread_set
    _HB_SENDER_LOOP = hb_sender_loop
    _STOP_SENDERS = stop_senders
    _LOAD_CONFIG = load_config
    _VAULT_GIT = vault_git
    _VAULT_DIR = vault_dir
    _RUN_VAULT_GIT_STEP = run_vault_git_step
    _RUN_VAULT_AUDIT_STEP = run_vault_audit_step


# ── UI 文件禁缓存:WKWebView 会按 URL 缓存 html/js/css,改了代码不 bump ?v= 就吃旧版
# (2026-06-15 踩过:补建逻辑改了、重构建了,WebView 还服务 Build-1 缓存的旧 JS)。
# local-first app 文件本就在盘上,no-store 零成本换"永远拉新"。字体 woff2 不在此列,照常缓存。
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
    script = _CODE_ROOT() / "scripts" / "new-day.sh"
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
    return _FIND_TODAY_JOURNAL() is None


async def _startup_auto_create():
    """server 启动时:若当前时间 ≥ 02:00 且今天文件缺,补建一次。
    再起一个后台 task,每 60 秒检查一次,过点自动建。
    """
    now = datetime.now()
    if now.hour >= AUTO_CREATE_AFTER_HOUR and _today_journal_missing():
        _silent_run_new_day()
    asyncio.create_task(_auto_create_loop())


async def _startup_vault_reference_and_migration():
    """启动时:
    ① 确保 vault 里 reference 文件存在,缺则从 bundle 拷(byte-equal 不动已有)
    ② bundle schema-version 比 vault 高 → 后台 async LLM 重组 vault 文件
    ③ Rust updater 上次留下的 pending 通知(sidecar 没起来时落的)→ 自补
    """
    try:
        _ENSURE_VAULT_REFERENCE_FILES()
    except Exception as e:
        _LOGGER().warning(f"_ensure_vault_reference_files: {e}")
    # 迁移走 async background,LLM call 不阻塞 startup
    asyncio.create_task(_RUN_SCHEMA_MIGRATION())
    # v0.1.25 起:LLM 弹性 MD 迁移(scope 不预设);走 /api/migration/stream SSE 通报进度
    asyncio.create_task(_STARTUP_MD_MIGRATION())
    # 接 Rust updater 落的 pending(review #18)
    try:
        _consume_updater_pending()
    except Exception as e:
        _LOGGER().warning(f"_consume_updater_pending: {e}")
    # 接上轮没消费的持久化 notification(workflow #17)
    try:
        _CONSUME_PENDING_NOTIFICATIONS()
    except Exception as e:
        _LOGGER().warning(f"_consume_pending_notifications: {e}")
    # B-#6: 把 silent-failure 通道挂进 library 模块(ocr.py / cutout.py),
    # 避免它们 silent swallow 网络/quota 失败 — 5.29 加的 37 hooks 全在 server.py,
    # 没覆盖 library 层。注入 callable 走 import-time 避免循环依赖。
    try:
        from ocr import set_failure_sink as _ocr_set_sink
        _ocr_set_sink(_REPORT_FAILURE)
    except Exception as e:
        _LOGGER().warning(f"ocr set_failure_sink: {e}")
    try:
        from cutout import set_failure_sink as _cutout_set_sink
        _cutout_set_sink(_REPORT_FAILURE)
    except Exception:
        pass  # cutout 可能还没装上报针脚,先 best-effort
    try:
        from cutout_local import set_failure_sink as _cutout_local_set_sink
        _cutout_local_set_sink(_REPORT_FAILURE)
    except Exception as e:
        _LOGGER().warning(f"cutout_local set_failure_sink: {e}")


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
        _PUSH_NOTIFICATION(
            "updater-installed",
            f"Gateway {version} 已下载,重启 app 生效",
            {"version": version, "source": "pending-file"},
        )
        _LOGGER().info(f"消费 updater pending 文件 -> notification: v{version}")
        pushed = True
    except Exception as e:
        # 损坏文件 — 不再 push,但仍 unlink 解卡
        _LOGGER().warning(f"读 updater pending 失败(损坏文件): {e}")
        _REPORT_FAILURE(
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


async def _auto_create_loop():
    while True:
        try:
            now = datetime.now()
            if now.hour >= AUTO_CREATE_AFTER_HOUR and _today_journal_missing():
                _silent_run_new_day()
        except Exception:
            pass
        await asyncio.sleep(60)


# 启动时跑一次老路径 → APP_STATE_DIR 迁移
def _startup_migrate_state():
    try:
        n = _MIGRATE_OLD_STATE()
        if n > 0:
            _LOGGER().warning(
                f"[migrate] copied {n} files from {_DATA_HOME()}/{{data,config}} → "
                f"{_APP_STATE_DIR()}/{{data,config}}. "
                f"老位置保留作 fallback,确认稳定后可手动 rm。"
            )
        _LOGGER().info(f"[state] APP_STATE_DIR = {_APP_STATE_DIR()}")
    except Exception as e:
        _LOGGER().warning(f"[migrate] failed: {e}")


# 启动时跑一次 audit,有 drift 就 log 警告(不阻塞启动)
def _vault_audit_step():
    # P0: 从同步 startup 钩子挪进后台 init 线程,不堵 server bind。
    try:
        r = _AUDIT_VAULT()
        if r["total_drift"] > 0:
            _LOGGER().warning(
                f"[vault audit] drift detected: "
                f"image_orphans={len(r['image_orphans'])} "
                f"image_recoverable={len(r['image_recoverable'])} "
                f"meta_orphans={len(r['meta_orphans'])} "
                f"aggregate_broken_links={len(r['aggregate_broken_links'])}. "
                f"前端会显示 banner;或 POST /api/vault/repair 自动修可修的。"
            )
    except Exception as e:
        _LOGGER().warning(f"[vault audit] startup audit failed: {e}")


def _startup_sf_sender():
    """启动 silent-failure 上送后台 thread。FEEDBACK_SINK_URL 没配就 no-op。"""
    current = _SF_THREAD_GET()
    if current is not None and current.is_alive():
        return
    sender = threading.Thread(
        target=_SF_SENDER_LOOP, daemon=True, name="sf-sender"
    )
    _SF_THREAD_SET(sender)
    sender.start()


def _startup_hb_sender():
    """启动日活心跳后台 thread。consent 关 / FEEDBACK_SINK_URL 没配都 no-op。"""
    current = _HB_THREAD_GET()
    if current is not None and current.is_alive():
        return
    sender = threading.Thread(
        target=_HB_SENDER_LOOP, daemon=True, name="hb-sender"
    )
    _HB_THREAD_SET(sender)
    sender.start()


def _shutdown_sf_sender():
    _STOP_SENDERS()


def _startup_config_sanity():
    """启动时确认单一 DeepSeek key 可以同时服务对话与视觉。"""
    try:
        from config_store import DEEPSEEK_OFFICIAL_URLS

        cfg = _LOAD_CONFIG() or {}
        base_url = str(cfg.get("base_url") or "").strip().rstrip("/")
        if base_url and base_url not in DEEPSEEK_OFFICIAL_URLS:
            _LOGGER().warning(
                "[config sanity] 已忽略自定义模型地址，AI 仅连接 DeepSeek 官方端点"
            )
    except Exception as e:
        _LOGGER().warning(f"[config sanity] startup check failed: {e}")


def _vault_git_init_step():
    """vault 写入自动版本史 — 首次启动 init repo + .gitignore + baseline。
    pulse-mirror 也装独立 git(PULSE updates 进 training corpus 用)。
    P0: 从同步 startup 钩子挪进后台 init 线程 — 大文件夹 git add -A 不堵 server bind。"""
    try:
        vault_dir = _VAULT_DIR()
        status = _VAULT_GIT().ensure_repo(vault_dir)
        _LOGGER().info(f"[vault_git] vault ensure_repo: {status} at {vault_dir}")
    except Exception as e:
        _LOGGER().warning(f"[vault_git] vault ensure_repo failed: {type(e).__name__}: {e}")
    try:
        _pulse = _APP_STATE_DIR() / "pulse-mirror"
        if _pulse.exists():
            status = _VAULT_GIT().ensure_repo(_pulse)
            _LOGGER().info(f"[vault_git] pulse-mirror ensure_repo: {status} at {_pulse}")
    except Exception as e:
        _LOGGER().warning(f"[vault_git] pulse ensure_repo failed: {type(e).__name__}: {e}")


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
    _LOGGER().info(f"[init] phase={phase} {detail}")


def _background_vault_init():
    """重活后台序列:git init(含大文件夹 baseline)→ vault audit。
    顺序保留(audit 依赖 repo 在);全程更新 _INIT_STATE 供前端进度屏轮询。
    自身永不让 ready 卡死 —— 任一步崩也置 ready,免前端永远转圈。"""
    try:
        _set_init_phase("git_init", "初始化版本历史")
        _RUN_VAULT_GIT_STEP()
        _set_init_phase("audit", "检查 vault 完整性")
        _RUN_VAULT_AUDIT_STEP()
        # 抠图模型预热(Win/Linux/老 mac):从自家 COS 拉 u2net,绕开 rembg 内置
        # GitHub 下载(大陆不可达)。幂等 + 失败自上报,不进 init error(非关键路径)。
        _set_init_phase("cutout_model", "准备抠图模型")
        try:
            from cutout_local import prewarm_u2net
            prewarm_u2net()
        except Exception as e:
            _LOGGER().warning(f"[init] u2net prewarm: {e}")
    except Exception as e:
        with _INIT_LOCK:
            _INIT_STATE["error"] = f"{type(e).__name__}: {str(e)[:160]}"
        _LOGGER().warning(f"[init] background init crashed: {e}")
        # 后台 init 崩(git init / audit)→ 审计链可能断,远程看不见,上报
        _REPORT_FAILURE("vault_init_failed",
            f"{type(e).__name__}: {str(e)[:120]}", context={"err_class": type(e).__name__})
    finally:
        with _INIT_LOCK:
            _INIT_STATE["phase"] = "ready"
            _INIT_STATE["ready"] = True
            _INIT_STATE["finished_at"] = datetime.now().isoformat()
        _LOGGER().info("[init] background vault init done — ready")


def _startup_background_init():
    """只 spawn 后台线程就返回 → server 立刻开始服务,WebView 秒出页面。"""
    with _INIT_LOCK:
        _INIT_STATE["started_at"] = datetime.now().isoformat()
    threading.Thread(
        target=_background_vault_init, daemon=True, name="vault-init"
    ).start()
