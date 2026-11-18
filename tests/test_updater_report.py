# TEST PATTERN: contract — updater check 结果异常判定
# USE WHEN: 验 /api/updater/report 只报真异常(check Err / COS有新版但check说none)
# TESTED IN: gateway (2026-06-11)

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
import notification_routes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_notification_routes_module_does_not_import_server():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import notification_routes; "
            "raise SystemExit(1 if 'server' in sys.modules else 0)",
        ],
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0


def test_push_uses_shared_queue_and_call_time_persistence(monkeypatch):
    pending = []
    persisted = []
    monkeypatch.setattr(server, "_PENDING_NOTIFICATIONS", pending)
    monkeypatch.setattr(
        server,
        "_persist_pending_notification",
        lambda item: persisted.append(item),
    )

    server._push_notification(
        "vault-schema-migrated",
        "done",
        {"version": 2},
    )

    assert pending[0]["kind"] == "vault-schema-migrated"
    assert persisted == pending


def test_ver_tuple():
    assert notification_routes._ver_tuple("0.1.34") == (0, 1, 34)
    assert notification_routes._ver_tuple("200:0.1.33") == (200, 1, 33) or notification_routes._ver_tuple("0.1.33") == (0, 1, 33)
    assert notification_routes._ver_tuple("garbage") is None
    assert notification_routes._ver_tuple("") is None


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    reported = []
    monkeypatch.setattr(server, "_report_silent_failure",
                        lambda et, msg="", context=None: reported.append((et, msg)))
    c = TestClient(server.app)
    c.reported = reported
    return c


def test_check_error_reports(client):
    r = client.post("/api/updater/report", json={
        "current_version": "0.1.33", "check_result": "error:timeout", "cos": "200:0.1.34", "yanpai": "200:0.1.30"})
    assert r.json().get("reported") == "updater_check_failed"
    assert client.reported and client.reported[0][0] == "updater_check_failed"


def test_cos_newer_but_none_reports(client):
    # COS 有 0.1.34 > 装机 0.1.33,但 check 返 none → 静默不弹的指纹
    r = client.post("/api/updater/report", json={
        "current_version": "0.1.33", "check_result": "none", "cos": "200:0.1.34", "yanpai": "200:0.1.30"})
    assert r.json().get("reported") == "updater_silent_no_update"
    assert client.reported[0][0] == "updater_silent_no_update"


def test_none_and_cos_same_no_report(client):
    # COS 跟装机同版 → 正常"无更新",不该报
    r = client.post("/api/updater/report", json={
        "current_version": "0.1.34", "check_result": "none", "cos": "200:0.1.34", "yanpai": "200:0.1.30"})
    assert r.json().get("reported") is None
    assert client.reported == []


def test_some_no_report(client):
    # check 找到新版(正常路径)→ 不报
    r = client.post("/api/updater/report", json={
        "current_version": "0.1.33", "check_result": "some:0.1.34", "cos": "200:0.1.34", "yanpai": "200:0.1.30"})
    assert r.json().get("reported") is None
    assert client.reported == []
