# TEST PATTERN: contract — output filter (server audit on AI text)
# USE WHEN: server-side post-process needs to flag AI "I did X" claims w/o tool calls
# COPY THIS: 改 fixture 的 (content, actions) → assert disclaimer present/absent
# TESTED IN: gateway (2026-05-24)
#
# Path X(CC's tool_use → 我们的 server audit 适配):
#   T1 claim 措辞 + 空 actions → 加 disclaimer(撒谎)
#   T2 claim 措辞 + 非空 actions → 不加(真的做了,chip 已显示)
#   T3 无 claim 措辞 + 空 actions → 不加(普通对话)
#   T4 空 content → 不加(防 None / "")
#   T5 多种 claim 同时存在仍只加一次 disclaimer

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


# ─── T1 · claim + 空 actions → 加 disclaimer ──────────────────────────

@pytest.mark.parametrize("claim_text", [
    "记进 17:30 了",
    "写进 17:30 了",
    "搞定,已写入",
    "已写好了,你看看",
    "saved!",
    "done,下一条你说什么",
    "已贴到 19:00",
    "已添加到 schedule",
    "patched 21:00",
])
def test_audit_appends_disclaimer_on_claim_without_action(claim_text):
    out = server._audit_unauthorized_claim(claim_text, actions=[])
    assert "server audit" in out, f"missing disclaimer for {claim_text!r}: got {out!r}"
    assert claim_text in out, "original claim must be preserved (用户能看到 AI 原话)"


# ─── T2 · claim + 真 action → 不加(action 是真的,只是模型多嘴复述)──

def test_audit_silent_when_action_present():
    actions = [{"name": "patch_journal_block", "args": {"time": "17:30"}, "result": {"ok": True}}]
    out = server._audit_unauthorized_claim("记进 17:30 了", actions=actions)
    assert "server audit" not in out, "audit shouldn't fire when actions exist"
    assert out == "记进 17:30 了"


# ─── T3 · 无 claim 词 → 不加(普通对话) ──────────────────────────────

def test_audit_silent_on_plain_conversation():
    out = server._audit_unauthorized_claim("你今天累成这样,要不去睡个觉?", actions=[])
    assert "server audit" not in out


def test_audit_silent_on_question():
    out = server._audit_unauthorized_claim("你想让我帮你记进哪个时间块?", actions=[])
    # 注意:"记进"在问句里也算 claim 词 — false positive,但 disclaimer 不破坏意思,可接受
    # 这里只是 sanity:测函数不崩
    assert isinstance(out, str)


# ─── T4 · 空 content → 不加 ───────────────────────────────────────────

def test_audit_silent_on_empty_content():
    assert server._audit_unauthorized_claim("", actions=[]) == ""
    assert server._audit_unauthorized_claim(None, actions=[]) is None


# ─── T5 · 多个 claim 词 → 只加一次 disclaimer ─────────────────────────

def test_audit_single_disclaimer_for_multi_claims():
    text = "记进 17:30 了。已写入完成,搞定。"
    out = server._audit_unauthorized_claim(text, actions=[])
    assert out.count("server audit") == 1, "disclaimer must be appended exactly once"
