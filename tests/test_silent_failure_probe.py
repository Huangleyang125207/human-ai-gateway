# TEST PATTERN: contract + effect — silent-failure 探针
# USE WHEN: 验上报前 home 路径脱敏(#1)+ 同指纹折叠(#2)
# COPY THIS: 改 monkeypatch 的 consent / log 路径
# TESTED IN: gateway (2026-06-10)
#
# 测的边界:
#   T1 _scrub_pii: /Users/<name> /home/<name> C:\Users\<name> → ~
#   T2 _scrub_pii: 非字符串/None 原样;幂等
#   T3 _sanitize_sf_context: 白名单内字符串值也脱敏
#   T4 _sf_fingerprint: 数字变化归同指纹;error_type 不同分开
#   T5 折叠: 同指纹 burst → 1 即时落盘(message 已脱敏)
#   T6 折叠: flush → 1 coalesced 汇总(occurrences=extra, coalesced=True)

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


# ─── T1 · home 路径脱敏 ───────────────────────────────────────

def test_scrub_pii_unix_home():
    s = "fatal: Unable to create '/Users/alice/.human-ai/vault/.git/index.lock'"
    assert "/Users/alice" not in server._scrub_pii(s)
    assert "~/.human-ai/vault/.git/index.lock" in server._scrub_pii(s)


def test_scrub_pii_linux_home():
    assert server._scrub_pii("/home/ubuntu/.ssh/authorized_keys") == "~/.ssh/authorized_keys"


def test_scrub_pii_windows_home():
    out = server._scrub_pii(r"C:\Users\Bob\AppData\Roaming\gateway")
    assert "Bob" not in out
    assert out == r"~\AppData\Roaming\gateway"


# ─── T2 · 非字符串/幂等 ───────────────────────────────────────

def test_scrub_pii_non_string_passthrough():
    assert server._scrub_pii(None) is None
    assert server._scrub_pii(123) == 123


def test_scrub_pii_idempotent():
    once = server._scrub_pii("/Users/alice/x")
    assert server._scrub_pii(once) == once == "~/x"


# ─── T3 · context 字符串值也脱敏 ──────────────────────────────

def test_sanitize_context_scrubs_string_values():
    out = server._sanitize_sf_context({"err": "boom at /Users/alice/.human-ai/x"})
    assert "/Users/alice" not in out["err"]
    assert "~/.human-ai/x" in out["err"]


# ─── T4 · 指纹归一 ────────────────────────────────────────────

def test_fingerprint_collapses_numbers():
    a = server._sf_fingerprint("vault_git_commit_failed", "index.lock age=42s pid=78757")
    b = server._sf_fingerprint("vault_git_commit_failed", "index.lock age=9s pid=18608")
    assert a == b


def test_fingerprint_distinct_error_types():
    a = server._sf_fingerprint("vault_git_add_failed", "x")
    b = server._sf_fingerprint("vault_git_commit_failed", "x")
    assert a != b


# ─── T5/T6 · 折叠 burst + flush 汇总 ──────────────────────────

@pytest.fixture
def isolated_sf(tmp_path, monkeypatch):
    """隔离 jsonl 路径 + 开 consent + 清 dedup 状态。"""
    log = tmp_path / "silent-failures.jsonl"
    monkeypatch.setattr(server, "SILENT_FAILURES_LOG", log)
    monkeypatch.setattr(server, "_telemetry_consent", lambda: {"failures": True})
    monkeypatch.setattr(server, "get_client_id", lambda: "test-client-0001")
    monkeypatch.setattr(server, "_trim_silent_failures", lambda: None)
    server._sf_dedup.clear()
    yield log
    server._sf_dedup.clear()


def _lines(log: Path):
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_burst_collapses_to_one_immediate_line(isolated_sf):
    msg = "fatal: index.lock at /Users/alice/.human-ai/vault/.git/index.lock pid=1"
    for _ in range(26):
        server._report_silent_failure("vault_git_commit_failed", msg)
    rows = _lines(isolated_sf)
    assert len(rows) == 1, f"burst 应只落 1 即时条; got {len(rows)}"
    # message 已脱敏
    assert "/Users/alice" not in rows[0]["message"]
    # 即时条不带 occurrences(单条形态)
    assert "occurrences" not in rows[0].get("context", {})


def test_flush_emits_coalesced_summary(isolated_sf):
    msg = "fatal: index.lock pid=1"
    for _ in range(26):
        server._report_silent_failure("vault_git_commit_failed", msg)
    server._sf_flush_dedup(force=True)
    rows = _lines(isolated_sf)
    assert len(rows) == 2, f"应 1 即时 + 1 汇总; got {len(rows)}"
    summary = rows[1]
    assert summary["context"]["coalesced"] is True
    assert summary["context"]["occurrences"] == 25  # count-1,首条已单独落
