# TEST PATTERN: effect — 心跳即刻发(不再等 30min)
# USE WHEN: 验 _hb_sender_loop 启动后立即 ping + consent 没开时重试不放弃
# TESTED IN: gateway (2026-06-11)
#
# 背景:原 HB_STARTUP_DELAY=30min,内测 tester 探几分钟就关 → 一次心跳都不发 → DAU 永远 0。
# 改 15s + 没发成 2min 重试。本测把延迟归零验"即刻发"。

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
import telemetry  # noqa: E402


class _Resp:
    status_code = 200
    text = ""


def test_heartbeat_fires_immediately(monkeypatch):
    monkeypatch.setattr(telemetry, "HB_STARTUP_DELAY", 0)
    monkeypatch.setenv("FEEDBACK_SINK_URL", "http://test-sink")
    monkeypatch.setattr(telemetry, "_telemetry_consent", lambda: {"heartbeat": True})
    monkeypatch.setattr(telemetry, "_hb_last_sent_day", lambda: "")
    monkeypatch.setattr(telemetry, "get_client_id", lambda: "hb-test-client")
    marked = []
    monkeypatch.setattr(telemetry, "_hb_mark_sent", lambda d: marked.append(d))
    posted = []

    def fake_post(url, json=None, timeout=None):
        posted.append((url, json))
        telemetry._HB_SENDER_STOP.set()  # 发完即停,免无限循环
        return _Resp()

    monkeypatch.setattr(telemetry.requests, "post", fake_post)
    telemetry._HB_SENDER_STOP.clear()
    try:
        t = threading.Thread(target=telemetry._hb_sender_loop, daemon=True)
        t.start()
        t.join(timeout=5)
        assert posted, "延迟归零后心跳应立即发出,而不是干等"
        assert posted[0][0].endswith("/heartbeat")
        assert posted[0][1]["client_id"] == "hb-test-client"
        assert posted[0][1]["version"] == server.APP_VERSION
        assert marked, "发成功应记当日戳子(每天去重)"
    finally:
        telemetry._HB_SENDER_STOP.clear()


def test_heartbeat_consent_off_does_not_post(monkeypatch):
    monkeypatch.setattr(telemetry, "HB_STARTUP_DELAY", 0)
    monkeypatch.setattr(telemetry, "HB_RETRY_INTERVAL", 0)  # 立即下一轮以便结束
    monkeypatch.setenv("FEEDBACK_SINK_URL", "http://test-sink")
    monkeypatch.setattr(telemetry, "_telemetry_consent", lambda: {"heartbeat": False})
    posted = []

    def fake_post(url, json=None, timeout=None):
        posted.append(url)
        return _Resp()

    monkeypatch.setattr(telemetry.requests, "post", fake_post)
    telemetry._HB_SENDER_STOP.clear()
    try:
        t = threading.Thread(target=telemetry._hb_sender_loop, daemon=True)
        t.start()
        # 跑一小会让它转两圈,确认 consent 关时不 post
        import time as _t
        _t.sleep(0.3)
        telemetry._HB_SENDER_STOP.set()
        t.join(timeout=3)
        assert posted == [], "consent 关闭时不该发心跳"
    finally:
        telemetry._HB_SENDER_STOP.clear()
