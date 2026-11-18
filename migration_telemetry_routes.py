# PATTERN: routes — migration schema-upgrade LLM helper + telemetry consent CRUD extracted from god module
# USE WHEN: schema 迁移 LLM 调用/校验逻辑,或 /api/telemetry/consent|reset-client-id 端点改动
# COPY THIS: 无 — 本模块是 server.py §21(清册01)的搬迁体,契约在 server re-export
#
# 抽出记录(2026-07-22, 清册01-§21,Parallel Change expand):
# - 原址 server.py 两个不相邻块:① _migration_llm_call/_validate_migration_output
#   (纯函数,无 @app 端点;编排已在更早的刀抽到 migration_routes.py,该文件函数体内
#   lazy `from server import ..., _migration_llm_call, _validate_migration_output, ...`
#   ——本段搬走后 server 仍经 re-export 满足这条 lazy import,零改动),
#   ② telemetry_consent_set/_send_forget_request/telemetry_reset_client_id,函数体
#   逐字节照搬。
# - 边界比卡片标题窄:_SCHEMA_MIGRATION_PROMPT(纯字符串常量)+ telemetry_consent_get
#   (GET 端点)不在卡片真源锚点列表内,原样留 server(migration_routes.py:350 仍
#   lazy 拉 server._SCHEMA_MIGRATION_PROMPT,未受影响)。
# - migration validator 直接依赖 pulse_io 叶子；telemetry state/effects 由组装根
#   以命名 provider 注入。
# - telemetry_reset_client_id 通过具名 setter 更新 telemetry.py 的权威缓存，
#   文件、内存缓存与 heartbeat 去重戳保持一致。
# - 2 telemetry 端点上 APIRouter(HTTP 路径不变,同 consent_routes.py 先例);
#   tests/test_migration_glue.py 只 patch mig._create_migration_llm(migration_routes
#   模块内),与本段搬迁的 _migration_llm_call/_validate_migration_output 互不相干。
import json
import re

from fastapi import APIRouter, HTTPException, Request
from pulse_io import _TS_RE, _get_schema_version

router = APIRouter(tags=["migration", "telemetry"])

_TELEMETRY_CONSENT = None
_TELEMETRY_SAVE = None
_ENV_OVERLAY = None
_GET_CLIENT_ID = None
_LOGGER = None
_CLIENT_ID_PATH = None
_SET_CLIENT_ID_CACHE = None
_HB_LAST_SENT_PATH = None
_SILENT_FAILURES_LOG = None
_SILENT_FAILURES_RING_MAX = None
_HB_LAST_SENT_DAY = None


def configure_effects(
    *,
    telemetry_consent,
    telemetry_save,
    env_overlay,
    get_client_id,
    logger,
    client_id_path,
    set_client_id_cache,
    heartbeat_path,
    silent_failures_log,
    silent_failures_ring_max,
    heartbeat_last_sent_day,
) -> None:
    global _TELEMETRY_CONSENT, _TELEMETRY_SAVE, _ENV_OVERLAY
    global _GET_CLIENT_ID, _LOGGER, _CLIENT_ID_PATH
    global _SET_CLIENT_ID_CACHE, _HB_LAST_SENT_PATH
    global _SILENT_FAILURES_LOG, _SILENT_FAILURES_RING_MAX, _HB_LAST_SENT_DAY
    _TELEMETRY_CONSENT = telemetry_consent
    _TELEMETRY_SAVE = telemetry_save
    _ENV_OVERLAY = env_overlay
    _GET_CLIENT_ID = get_client_id
    _LOGGER = logger
    _CLIENT_ID_PATH = client_id_path
    _SET_CLIENT_ID_CACHE = set_client_id_cache
    _HB_LAST_SENT_PATH = heartbeat_path
    _SILENT_FAILURES_LOG = silent_failures_log
    _SILENT_FAILURES_RING_MAX = silent_failures_ring_max
    _HB_LAST_SENT_DAY = heartbeat_last_sent_day


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


@router.get("/api/telemetry/consent")
def telemetry_consent_get():
    """前端读 consent 状态 + 上报统计 + client_id (透明给用户看)。"""
    consent = _TELEMETRY_CONSENT()
    silent_failures_log = _SILENT_FAILURES_LOG()
    try:
        sf_count = (
            len(silent_failures_log.read_text(encoding="utf-8").splitlines())
            if silent_failures_log.exists()
            else 0
        )
    except Exception:
        sf_count = 0
    return {
        **consent,
        "client_id": _GET_CLIENT_ID(),
        "silent_failures_local": sf_count,
        "heartbeat_last_day": _HB_LAST_SENT_DAY(),
        "needs_consent": consent.get("consented_at") is None,
    }


@router.post("/api/telemetry/consent")
async def telemetry_consent_set(req: Request):
    """前端 consent modal / 设置 tab 调,写两个开关。
    body: {failures: bool, heartbeat: bool}
    """
    body = await req.json()
    failures = bool(body.get("failures", False))
    heartbeat = bool(body.get("heartbeat", False))
    # 撤回检测:之前同意过 + 现在两项都关 = 撤回 → 触发云端 /forget(C-#10)
    prev = _TELEMETRY_CONSENT()
    is_withdrawal = (
        (prev.get("failures") or prev.get("heartbeat"))
        and not failures
        and not heartbeat
    )
    _TELEMETRY_SAVE(failures, heartbeat)
    if is_withdrawal:
        # fire-and-forget 异步发 /forget,不阻塞 consent 写盘成功响应
        try:
            import threading as _t
            _t.Thread(target=_send_forget_request, daemon=True).start()
        except Exception:
            pass
    return {"ok": True, **_TELEMETRY_CONSENT()}


def _send_forget_request():
    """C-#10: 撤回 consent 时通知 yanpai 删除已上传数据。
    满足 GDPR Art.17 / PIPL 第 47 条。失败不 retry(用户随时可手动再发)。"""
    import os
    import requests
    try:
        url_base = (_ENV_OVERLAY().get("FEEDBACK_SINK_URL", "")
                    or os.environ.get("FEEDBACK_SINK_URL", "")).strip().rstrip("/")
        if not url_base:
            return
        cid = _GET_CLIENT_ID()
        r = requests.delete(
            f"{url_base}/forget",
            params={"client_id": cid},
            timeout=10,
        )
        if r.status_code != 200:
            _LOGGER().warning(f"/forget 上报失败: HTTP {r.status_code}")
    except Exception as e:
        _LOGGER().warning(f"/forget 上报失败: {e}")


@router.post("/api/telemetry/reset-client-id")
def telemetry_reset_client_id():
    """用户主动重置 client_id (在设置 → 数据 → 云上报里可点)。
    重置后 server 端看作新设备,DAU 会重复计一次,无副作用。
    """
    import uuid as _uuid
    try:
        new_id = _uuid.uuid4().hex
        client_id_path = _CLIENT_ID_PATH()
        client_id_path.parent.mkdir(parents=True, exist_ok=True)
        client_id_path.write_text(new_id, encoding="utf-8")
        _SET_CLIENT_ID_CACHE(new_id)
        # 重置 heartbeat 标记(让新 id 立刻发一次)
        try:
            _HB_LAST_SENT_PATH().unlink()
        except Exception:
            pass
        return {"ok": True, "client_id": new_id}
    except Exception as e:
        raise HTTPException(500, f"reset failed: {type(e).__name__}: {e}")


@router.get("/api/silent-failures/recent")
def silent_failures_recent(n: int = 100):
    """返最近 N 条 silent failure log(本地 ring buffer)。"""
    n = max(1, min(int(n), _SILENT_FAILURES_RING_MAX()))
    silent_failures_log = _SILENT_FAILURES_LOG()
    if not silent_failures_log.exists():
        return {"items": [], "total": 0, "client_id": _GET_CLIENT_ID()}
    try:
        lines = silent_failures_log.read_text(encoding="utf-8").splitlines()
        items = []
        for line in lines[-n:]:
            try:
                items.append(json.loads(line))
            except Exception:
                continue
        return {
            "items": items,
            "total": len(lines),
            "client_id": _GET_CLIENT_ID(),
        }
    except Exception as e:
        raise HTTPException(500, f"read failed: {type(e).__name__}: {e}")
