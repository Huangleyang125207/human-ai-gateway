"""thread_routes — APIRouter for /api/thread/* (聊天历史持久化).

Extract Module(ctrl-c-v § 9):thread-history 持久化三件套从 server.py 抽出。
chat 簇(D5)的降风险拆解第一刀 —— 这三个端点只管 thread-history 文件的读/存/恢复,
不碰 /api/chat 的 SSE 流式 + DSML 泄漏闸(那块单独后做)。

thin wrapper —— 3 个 handler 搬过来,业务逻辑零变化。
**留 server.py(lazy from server import 拉回):**
- _thread_history_mtime_ms / _thread_save_is_stale(CAS 判定 helper;test_thread_cas.py 直接
  调 server._thread_save_is_stale → 必须留 server)
- THREAD_HISTORY_PATH / _THREAD_LOCK(单写锁 + 路径常量;测试 patch server.THREAD_HISTORY_PATH)
- _safe_write_text(原子写三件套)/ _report_silent_failure / DATA_DIR / log

Cannot-break(characterization 守):
- GET 损坏 → status='corrupt' + baks(5.17:空 [] 不能当真覆盖)
- POST save CAS 409(5.26:陈旧标签页不能盖新历史)— test_thread_cas.py 锁
HTTP-only,零直接调用方 → 不 re-export。
characterization:tests/test_thread_routes.py(8)+ tests/test_thread_cas.py(8)。
"""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["thread"])


# ── GET /api/thread/history ──────────────────────────────────────────
@router.get("/api/thread/history")
def thread_history_get():
    """返聊天历史 + mtime_ns。client 轮询时 mtime 变化才重拉。"""
    from server import (THREAD_HISTORY_PATH, _THREAD_LOCK, _thread_history_mtime_ms,
                        _report_silent_failure, log)
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
        # 5.17 用户聊天历史被覆盖那条教训:即便 error 字段在,前端可能忽略 →
        # 看起来像 history 被 wipe。A-H14 收口:返显式 status='corrupt' + 可用 bak 列表
        # 前端读到这个状态必须拦下 saveHistory(避免空 list 当真覆盖)走 modal。
        _report_silent_failure("thread_history_read_failed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"file_size_kb": THREAD_HISTORY_PATH.stat().st_size // 1024 if THREAD_HISTORY_PATH.exists() else 0})
        # 收集可用 bak 列表给前端 modal restore 用
        baks = []
        for i in range(1, 6):
            bp = Path(f"{THREAD_HISTORY_PATH}.bak.{i}")
            if bp.exists():
                try:
                    baks.append({
                        "index": i,
                        "size_kb": bp.stat().st_size // 1024,
                        "mtime": int(bp.stat().st_mtime * 1000),
                    })
                except Exception:
                    pass
        return {
            "history": [],
            "mtime": 0,
            "status": "corrupt",
            "error": str(e)[:200],
            "baks": baks,
            "message": "thread-history 读取失败 — 选 bak 恢复或 start-fresh,别直接覆盖。",
        }


# ── POST /api/thread/restore-from-bak ────────────────────────────────
@router.post("/api/thread/restore-from-bak")
async def thread_history_restore(req: Request):
    """A-H14: 从指定 bak.N 恢复 thread-history。前端 modal 选哪个 bak 就调这个。
    body: {bak_index: 1..5}
    """
    from server import (THREAD_HISTORY_PATH, _THREAD_LOCK, _thread_history_mtime_ms,
                        _safe_write_text, datetime)
    body = await req.json()
    idx = int(body.get("bak_index") or 0)
    if idx < 1 or idx > 5:
        raise HTTPException(400, "bak_index 必须是 1..5")
    bp = Path(f"{THREAD_HISTORY_PATH}.bak.{idx}")
    if not bp.exists():
        raise HTTPException(404, f"bak.{idx} 不存在")
    try:
        data = json.loads(bp.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("bak 内容不是 list")
    except Exception as e:
        raise HTTPException(400, f"bak.{idx} 解析失败: {type(e).__name__}: {e}")
    with _THREAD_LOCK:
        # 把当前损坏的 thread-history 另存一份(免得用户后悔)
        if THREAD_HISTORY_PATH.exists():
            try:
                ts = int(datetime.now().timestamp())
                corrupted = THREAD_HISTORY_PATH.with_name(f"{THREAD_HISTORY_PATH.name}.corrupted.{ts}")
                THREAD_HISTORY_PATH.rename(corrupted)
            except Exception:
                pass
        _safe_write_text(
            THREAD_HISTORY_PATH,
            json.dumps(data, ensure_ascii=False, indent=2),
            rotate=False,  # bak 链已有,不用再 rotate 一次
        )
        mtime = _thread_history_mtime_ms()
    return {"ok": True, "restored_from": f"bak.{idx}", "count": len(data), "mtime": mtime}


# ── POST /api/thread/save ────────────────────────────────────────────
@router.post("/api/thread/save")
async def thread_history_save(req: Request):
    """全量覆盖。client 应送整段 history(最近 N 条)。
    返新 mtime,client 拿来作为下一次 poll 的基线(避免自己写完又被自己 poll 拉一遍)。
    """
    from server import (THREAD_HISTORY_PATH, _THREAD_LOCK, _thread_history_mtime_ms,
                        _thread_save_is_stale, _safe_write_text, DATA_DIR)
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
