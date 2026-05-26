# TEST PATTERN: boundary + contract — thread-history save 的 CAS 防陈旧覆盖
# USE WHEN: 验 _thread_save_is_stale 各分支 + 409 endpoint 不写文件
# COPY THIS: 改 base/current 组合加 case
# TESTED IN: gateway (2026-05-26) — 防 5.17/5.26 陈旧标签页覆盖历史事故

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


# ─── T1 boundary · base_mtime None(旧 client 没回传)→ 放行 ───────────

def test_none_base_not_stale():
    assert server._thread_save_is_stale(None, 12345) is False


# ─── T2 boundary · 文件还不存在(current 0)→ 首次写放行 ──────────────

def test_no_file_not_stale():
    assert server._thread_save_is_stale(999, 0) is False


# ─── T3 contract · base == current → 新鲜,放行 ───────────────────────

def test_matching_mtime_not_stale():
    assert server._thread_save_is_stale(12345, 12345) is False


# ─── T4 contract · base != current → 陈旧,拒绝(核心防线)────────────

def test_mismatch_is_stale():
    assert server._thread_save_is_stale(111, 222) is True


def test_incident_shape_is_stale():
    """复刻 5.26:陈旧 tab base_mtime 停在旧值,文件已被推到新 mtime → 必拒。"""
    stale_tab_base = 1779700000000000000   # 5.21 era
    server_current = 1779761700000000000   # 5.25 era(更大)
    assert server._thread_save_is_stale(stale_tab_base, server_current) is True


# ─── T5 boundary · base 是垃圾值 → 不崩,放行(不误拒)────────────────

def test_garbage_base_not_stale():
    assert server._thread_save_is_stale("not-a-number", 12345) is False
    assert server._thread_save_is_stale([], 12345) is False


# ─── T6 effect · 字符串数字 base 能正确比较(JSON 可能传 str)─────────

def test_string_int_base_compares():
    assert server._thread_save_is_stale("222", 222) is False   # 相等
    assert server._thread_save_is_stale("111", 222) is True    # 不等 → 拒


# ─── T7 effect · stale save 走 endpoint 不动文件 ─────────────────────

def test_stale_save_leaves_file_untouched(tmp_path, monkeypatch):
    """模拟:文件已是 mtimeX,client 拿旧 base_mtime 来 save → 应 409 + 文件原样。
    用 TestClient 跑真 endpoint。"""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi testclient unavailable")

    f = tmp_path / "thread-history.json"
    original = [{"role": "assistant", "content": "真实最新历史"}]
    f.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(server, "THREAD_HISTORY_PATH", f)
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)

    client = TestClient(server.app)
    current = server._thread_history_mtime_ms()
    stale_base = current - 999999  # 故意旧

    r = client.post("/api/thread/save", json={
        "history": [{"role": "user", "content": "陈旧标签页的旧内容"}],
        "base_mtime": stale_base,
    })
    assert r.status_code == 409
    # 文件没被覆盖 — 还是真实最新历史
    after = json.loads(f.read_text(encoding="utf-8"))
    assert after == original


# ─── T8 effect · 匹配 base 的 save 正常写入 ───────────────────────────

def test_fresh_save_writes(tmp_path, monkeypatch):
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi testclient unavailable")

    f = tmp_path / "thread-history.json"
    f.write_text(json.dumps([{"role": "user", "content": "旧"}], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(server, "THREAD_HISTORY_PATH", f)
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)

    client = TestClient(server.app)
    current = server._thread_history_mtime_ms()

    new_hist = [{"role": "user", "content": "旧"}, {"role": "assistant", "content": "新增一条"}]
    r = client.post("/api/thread/save", json={"history": new_hist, "base_mtime": current})
    assert r.status_code == 200
    assert r.json()["count"] == 2
    after = json.loads(f.read_text(encoding="utf-8"))
    assert after == new_hist
