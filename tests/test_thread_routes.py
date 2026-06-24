# TEST PATTERN: characterization — /api/thread/* history persistence golden behavior
# USE WHEN: 锁 thread-history get(损坏→modal)+ restore-from-bak 现行行为,守 thread_routes 抽出(§ 9)
# TESTED IN: gateway thread_routes extraction (2026-06-24), § T7 characterization
#
# § T7 GREEN-LOCK:monolith 上先 GREEN,thread_routes.py 抽出后 STAY GREEN。
# 分工:/api/thread/save 的 CAS(409/写入)已由 test_thread_cas.py 锁(那 8 条抽出后照样 GREEN,
#       因为它用 server._thread_save_is_stale + HTTP)。本文件补它没覆盖的两块:
#   - GET /api/thread/history:空 / 正常 / 损坏→modal(★5.17 Cannot-break:空 [] 不能当真覆盖)
#   - POST /api/thread/restore-from-bak:roundtrip / bad index / missing bak
# helper(_thread_history_mtime_ms / _thread_save_is_stale)+ THREAD_HISTORY_PATH + _THREAD_LOCK
# 抽出时 *留 server.py*,handler 走 lazy from server import → patch server.X 仍命中。

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


@pytest.fixture
def th(monkeypatch, tmp_path):
    f = tmp_path / "thread-history.json"
    monkeypatch.setattr(server, "THREAD_HISTORY_PATH", f)
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    return SimpleNamespace(path=f, dir=tmp_path)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(server.app)


# ── GET /api/thread/history ──────────────────────────────────────────

def test_history_empty_when_no_file(client, th):
    r = client.get("/api/thread/history")
    assert r.status_code == 200
    assert r.json() == {"history": [], "mtime": 0}


def test_history_happy_returns_list_and_mtime(client, th):
    hist = [{"role": "user", "content": "嗨"}, {"role": "assistant", "content": "在"}]
    th.path.write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
    d = client.get("/api/thread/history").json()
    assert d["history"] == hist
    assert d["mtime"] > 0
    assert "status" not in d  # 正常不带 corrupt 标记


def test_history_corrupt_returns_modal_payload_and_rings(client, th, monkeypatch):
    """★5.17 Cannot-break:损坏读必返 status='corrupt' + baks(空 history 不能当真覆盖),
    且响铃。抽出后 _report_silent_failure / bak 扫描必须仍 resolve;botched cut → 此条 RED。"""
    rung = []
    monkeypatch.setattr(server, "_report_silent_failure",
                        lambda et, msg="", context=None: rung.append((et, msg, context)))
    th.path.write_text('[{"role": BROKEN', encoding="utf-8")     # 损坏 json
    Path(f"{th.path}.bak.1").write_text(json.dumps([{"role": "user", "content": "旧好的"}]),
                                        encoding="utf-8")          # 一个可恢复 bak

    d = client.get("/api/thread/history").json()
    assert d["status"] == "corrupt"
    assert d["history"] == []                                     # 空,但带 corrupt 标记让前端拦住
    assert d["mtime"] == 0
    assert any(b["index"] == 1 for b in d["baks"])                # bak 列表给 modal restore 用
    assert "message" in d
    assert any(et == "thread_history_read_failed" for et, _, _ in rung)  # 铃响了


# ── POST /api/thread/restore-from-bak ────────────────────────────────

def test_restore_from_bak_roundtrip(client, th):
    th.path.write_text("CORRUPT-CURRENT", encoding="utf-8")       # 当前损坏
    good = [{"role": "assistant", "content": "bak.2 的内容"}]
    Path(f"{th.path}.bak.2").write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")

    r = client.post("/api/thread/restore-from-bak", json={"bak_index": 2})
    assert r.status_code == 200
    d = r.json()
    assert d["restored_from"] == "bak.2" and d["count"] == 1
    assert json.loads(th.path.read_text(encoding="utf-8")) == good   # 文件 = bak.2 内容
    # 原损坏文件另存为 .corrupted.<ts>(不直接丢)
    assert any(p.name.startswith(th.path.name + ".corrupted.") for p in th.dir.iterdir())


def test_restore_bad_index_400(client, th):
    assert client.post("/api/thread/restore-from-bak", json={"bak_index": 0}).status_code == 400
    assert client.post("/api/thread/restore-from-bak", json={"bak_index": 6}).status_code == 400


def test_restore_missing_bak_404(client, th):
    assert client.post("/api/thread/restore-from-bak", json={"bak_index": 3}).status_code == 404


# ── inline adversarial 补 gap(小簇,inline 替 workflow)───────────────

def test_corrupt_with_no_baks_returns_empty_baks_not_crash(client, th, monkeypatch):
    """损坏但一个 bak 都没有 → 仍 status='corrupt' + baks=[](别因为扫 bak 崩)。"""
    monkeypatch.setattr(server, "_report_silent_failure", lambda *a, **k: None)
    th.path.write_text("{not json", encoding="utf-8")
    d = client.get("/api/thread/history").json()
    assert d["status"] == "corrupt"
    assert d["baks"] == []


def test_save_rejects_non_list_history_400(client, th):
    """history 不是 list → 400(契约边界;抽出'好心'try/except 不能悄改成 200 静默不写)。"""
    assert client.post("/api/thread/save", json={"history": "oops"}).status_code == 400
    assert client.post("/api/thread/save", json={}).status_code == 400
