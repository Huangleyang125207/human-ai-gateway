# PATTERN: routes — health/init-status + in-app notification push/persist + updater report endpoints
# USE WHEN: /api/health|init-status|notifications|updater/* 端点或 pending-notification 持久化改动
# COPY THIS: 无 — 本模块是 server.py §20(清册01)的搬迁体,契约在 server re-export
#
# 抽出记录(2026-07-22, 清册01-§20,Parallel Change expand):
# - 原址 server.py 三个不相邻块:① api_health/api_init_status,② _push_notification/
#   _pending_notif_path/_persist_pending_notification/_consume_pending_notifications,
#   ③ updater_installed/_ver_tuple/updater_report,函数体逐字节照搬。
# - 权威可变状态(_PENDING_NOTIFICATIONS 列表 + _NOTIF_LOCK + _PENDING_NOTIF_FILE_LOCK)
#   **原样留 server.py**(get_notifications 端点仍在 server 直接读写这三个名字,未纳入
#   本段搬迁范围——卡片真源锚点未列 get_notifications);本模块函数体经
#   S = _srv() 现取,包括模块内部互调(_push_notification 调
#   _persist_pending_notification 时也走 S.,不是本文件内直调)——这样
#   tests/conftest.py::stubbed_llm 的 monkeypatch.setattr(server, "_push_notification", spy)
#   即便本模块另一函数内部触发推送,仍打中 spy(patch-where-used,ctrl-c-v-python G3)。
# - 共享队列/锁保持 server 权威对象，路径、写入、push/report 以命名 provider 注入。
# - 3 端点组(health/init-status、updater/installed、updater/report)上 APIRouter
#   (HTTP 路径不变,同 consent_routes.py 先例);tests/test_updater_report.py 直调
#   server._ver_tuple / server.api_init_status(见 test_background_init.py)不受影响
#   （module-attribute 查找命中 re-export）。
import json

from fastapi import APIRouter, Request

router = APIRouter(tags=["notifications", "updater"])

_APP_VERSION = None
_INIT_LOCK = None
_INIT_STATE = None
_NOTIF_LOCK = None
_PENDING_NOTIFICATIONS = None
_PERSIST_NOTIFICATION = None
_APP_STATE_DIR = None
_PENDING_FILE_LOCK = None
_LOGGER = None
_WRITE_TEXT = None
_PUSH_NOTIFICATION = None
_REPORT_FAILURE = None


def configure_effects(
    *,
    app_version,
    init_lock,
    init_state,
    notification_lock,
    pending_notifications,
    persist_notification,
    app_state_dir,
    pending_file_lock,
    logger,
    write_text,
    push_notification,
    report_failure,
) -> None:
    global _APP_VERSION, _INIT_LOCK, _INIT_STATE, _NOTIF_LOCK
    global _PENDING_NOTIFICATIONS, _PERSIST_NOTIFICATION, _APP_STATE_DIR
    global _PENDING_FILE_LOCK, _LOGGER, _WRITE_TEXT
    global _PUSH_NOTIFICATION, _REPORT_FAILURE
    _APP_VERSION = app_version
    _INIT_LOCK = init_lock
    _INIT_STATE = init_state
    _NOTIF_LOCK = notification_lock
    _PENDING_NOTIFICATIONS = pending_notifications
    _PERSIST_NOTIFICATION = persist_notification
    _APP_STATE_DIR = app_state_dir
    _PENDING_FILE_LOCK = pending_file_lock
    _LOGGER = logger
    _WRITE_TEXT = write_text
    _PUSH_NOTIFICATION = push_notification
    _REPORT_FAILURE = report_failure


@router.get("/api/health")
def api_health():
    """轻量 ping — client 每 30s 检测,断了弹 banner。带版本号供设置"关于"页显示。"""
    from datetime import datetime
    return {"ok": True, "ts": datetime.now().isoformat(timespec="seconds"), "version": _APP_VERSION()}


@router.get("/api/init-status")
def api_init_status():
    """P0: 前端初始化屏轮询 — 后台 vault init(git/audit)进度。
    ready=True 前显示「正在初始化…」而非空白,回答用户「是慢还是卡住了」。"""
    with _INIT_LOCK():
        return dict(_INIT_STATE())


def _push_notification(kind: str, message: str, payload: dict | None = None):
    """前端 30s poll /api/notifications,见 kind 后自决定 dismiss。"""
    from datetime import datetime
    n = {"kind": kind, "message": message, "payload": payload or {}, "ts": datetime.now().isoformat()}
    pending = _PENDING_NOTIFICATIONS()
    with _NOTIF_LOCK():
        pending.append(n)
        # 上限 20 条防泄漏
        if len(pending) > 20:
            del pending[0:len(pending)-20]
    # workflow #17 闭合:重要 kind 持久化到磁盘,防 sidecar 重启 / process 死掉 notification 永久丢
    # vault 被 LLM 自动改了 / reference bootstrap / schema 升级 — 用户必须知道
    _PERSIST_NOTIF_KINDS = {
        "vault-schema-migrated", "vault-schema-bumped",
        "vault-schema-migration-failed", "vault-schema-migration-skip-external-edit",
        "vault-reference-bootstrapped",
    }
    if kind in _PERSIST_NOTIF_KINDS:
        _PERSIST_NOTIFICATION(n)


def _pending_notif_path():
    return _APP_STATE_DIR() / "data" / ".pending-notifications.jsonl"


def _persist_pending_notification(n: dict):
    """append 到 ~/.../data/.pending-notifications.jsonl,sidecar 启动时读 + push + truncate。
    A-H5: lock + flush + fsync,保证 vault auto-modified / schema migration 这种用户必看的
    notification 不会因 append 半截行掉地。
    """
    import os
    try:
        p = _pending_notif_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(n, ensure_ascii=False) + "\n"
        with _PENDING_FILE_LOCK():
            with open(p, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
    except Exception as e:
        _LOGGER().warning(f"persist pending notification 失败: {e}")


def _consume_pending_notifications():
    """sidecar 启动时把上次没消费的持久化通知补 push。
    A-H5: 锁内 read → push 内存队列 → 把"已成功 push 的行"清掉(write-back-good-lines)。
    比 read+unlink 安全 — read 期间新写的 append 不会被 unlink 整体吞掉。"""
    p = _pending_notif_path()
    if not p.exists():
        return
    with _PENDING_FILE_LOCK():
        try:
            raw = p.read_text(encoding="utf-8")
        except Exception as e:
            _LOGGER().warning(f"读 pending notifications 失败: {e}")
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
            pending = _PENDING_NOTIFICATIONS()
            with _NOTIF_LOCK():
                pending.append(n)
                if len(pending) > 20:
                    del pending[0:len(pending)-20]
            count += 1
        # 已消费 → 清空文件(atomic 写空)
        try:
            _WRITE_TEXT(p, "", rotate=False)
        except Exception:
            pass
    if count:
        _LOGGER().info(f"补 push {count} 条 pending notification")


@router.get("/api/notifications")
def get_notifications(dismiss: str = ""):
    """返 pending 通知列表；dismiss 按 kind 原地清除。"""
    pending = _PENDING_NOTIFICATIONS()
    with _NOTIF_LOCK():
        if dismiss:
            kinds = {kind.strip() for kind in dismiss.split(",") if kind.strip()}
            pending[:] = [
                item for item in pending if item["kind"] not in kinds
            ]
        return {"notifications": list(pending)}


@router.post("/api/updater/installed")
async def updater_installed(req: Request):
    """Tauri 自动更新完下载 + install 后(.app 二进制已替换,但当前 process 还跑旧版),
    Rust 端 POST 这里通知 sidecar,sidecar 推 banner 给前端 "重启生效"。"""
    body = {}
    try:
        body = await req.json()
    except Exception:
        pass
    version = (body.get("version") or "").strip() or "新版"
    _PUSH_NOTIFICATION(
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


@router.post("/api/updater/report")
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
        _REPORT_FAILURE("updater_check_failed",
            f"cur={cur} {res[:120]}",
            context={"err": res[7:127], "phase": "check"})
        return {"ok": True, "reported": "updater_check_failed"}
    # 异常 2:COS 有更新版本,但 check() 却说无更新 → 自更新静默不弹的指纹
    if res == "none":
        cos_ver = _ver_tuple(cos.split(":")[-1] if ":" in cos else cos)
        cur_ver = _ver_tuple(cur)
        if cos_ver and cur_ver and cos_ver > cur_ver:
            _REPORT_FAILURE("updater_silent_no_update",
                f"COS 有 {cos.split(':')[-1]} > 装机 {cur},但 check 返 none(yanpai={yanpai})",
                context={"phase": "check"})
            return {"ok": True, "reported": "updater_silent_no_update"}
    return {"ok": True, "reported": None}
