# TEST PATTERN: contract — updater check 结果异常判定
# USE WHEN: 验 /api/updater/report 只报真异常(check Err / COS有新版但check说none)
# TESTED IN: gateway (2026-06-11)

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


def test_ver_tuple():
    assert server._ver_tuple("0.1.34") == (0, 1, 34)
    assert server._ver_tuple("200:0.1.33") == (200, 1, 33) or server._ver_tuple("0.1.33") == (0, 1, 33)
    assert server._ver_tuple("garbage") is None
    assert server._ver_tuple("") is None


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
