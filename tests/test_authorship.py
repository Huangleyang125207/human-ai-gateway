# TEST PATTERN: contract + effect — authorship boundary on journal blocks
# USE WHEN: AI 写型 tool 要约束不能动 @user 块
# COPY THIS: 改 fixture / journal 内容,跑 pytest tests/test_authorship.py -v
# TESTED IN: gateway (2026-05-22)
#
# 测的边界:
#   T1 _check_author 解析 @user/@ai/无标记(默认 user)
#   T2 _patch_block author=ai 撞 @user 块 → 拒绝 + 原文不变
#   T3 _patch_block author=ai 改 @ai 块 → 允许
#   T4 _patch_block author=user 可改任何块
#   T5 _patch_block 没传 author → 默认 ai(最严格)
#   T6 _insert_block 必 stamp 调用方 @marker 到新 H2
#   T7 _append_comment_to_block 原内容一字不动,只 append

import sys
from pathlib import Path

import pytest

# 让 import server 找到模块(tests 在 gateway/tests/ 下)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


# ─── T1 · _check_author 是 pure function ────────────────────────────

def test_check_author_user_marker():
    assert server._check_author("## #思考 早醒 @user") == "user"

def test_check_author_ai_marker():
    assert server._check_author("## #投资 #协作 KV cache 闭环 @ai") == "ai"

def test_check_author_no_marker_defaults_user():
    """无标记 → @user(失败安全:旧 entry 默认保护,不能被 AI 改)"""
    assert server._check_author("## #思考 早醒") == "user"

def test_check_author_marker_anywhere_in_line():
    """marker 在 tag 之前也认(虽然 convention 是行末)"""
    assert server._check_author("## @ai #投资 something") == "ai"


# ─── 共用 fixture ────────────────────────────────────────────────────

JOURNAL_WITH_BOTH = """# 9：00

## #思考 早醒 @user
昨晚 11:30 睡到 7:00,闹钟 7:40。躺着也没睡着。

# 10：00

## #投资 #协作 KV cache @ai
推 RDMA 思路。

- #commit (user): tracked
- #commit (claude-opus-4-7): RDMA assumption
"""

JOURNAL_EMPTY = """# 9：00


# 10：00

"""


@pytest.fixture
def journal_both(tmp_path):
    f = tmp_path / "26.5.21(test).md"
    f.write_text(JOURNAL_WITH_BOTH, encoding="utf-8")
    return f


@pytest.fixture
def journal_empty(tmp_path):
    f = tmp_path / "26.5.22(test).md"
    f.write_text(JOURNAL_EMPTY, encoding="utf-8")
    return f


# ─── T2 · _patch_block author=ai REFUSES @user 块 ────────────────────

def test_patch_block_ai_refuses_user_block(journal_both):
    """核心防御:AI 不能 patch @user 块。"""
    result = server._patch_block(
        journal_both, "9:00",
        "## #思考 改了 @ai\n[AI hallucinated content]",
        author="ai",
    )
    assert "error" in result, f"expected error dict, got {result}"
    # 原文件内容 intact —— 这是最关键的 assert
    text = journal_both.read_text(encoding="utf-8")
    assert "昨晚 11:30 睡到 7:00" in text
    assert "[AI hallucinated content]" not in text


# ─── T3 · _patch_block author=ai ALLOWS @ai 块 ───────────────────────

def test_patch_block_ai_allows_ai_block(journal_both):
    """AI 可以改自己的 @ai 块。"""
    result = server._patch_block(
        journal_both, "10:00",
        "## #投资 #协作 重写过 @ai\n新内容。",
        author="ai",
    )
    assert "error" not in result, f"expected success, got: {result}"
    text = journal_both.read_text(encoding="utf-8")
    assert "新内容" in text
    assert "推 RDMA 思路" not in text  # 旧 body 被替换


# ─── T4 · _patch_block author=user 可改任何块 ────────────────────────

def test_patch_block_user_can_patch_user_block(journal_both):
    """用户改自己的块,允许。"""
    result = server._patch_block(
        journal_both, "9:00",
        "## #思考 改过 @user\n改了。",
        author="user",
    )
    assert "error" not in result
    assert "改了" in journal_both.read_text(encoding="utf-8")


def test_patch_block_user_can_patch_ai_block(journal_both):
    """用户也能改 AI 写的(user 是最高权威)。"""
    result = server._patch_block(
        journal_both, "10:00",
        "## #投资 user 接管 @user\n人接手了。",
        author="user",
    )
    assert "error" not in result


# ─── T5 · 默认 author='ai'(最严格,fail-safe) ─────────────────────

def test_patch_block_default_caller_is_ai(journal_both):
    """未传 author → 默认 'ai',撞 @user 块仍拒绝。"""
    result = server._patch_block(
        journal_both, "9:00",
        "## #思考 sneak @ai\n偷改!",
    )
    assert "error" in result, "unspecified caller must default to most restricted"


# ─── T6 · _insert_block 必 stamp 调用方 @marker ──────────────────────

def test_insert_block_stamps_ai_marker(journal_empty):
    """AI 走的路径,新 H2 带 @ai。"""
    result = server._insert_block(
        journal_empty, "9:00",
        tag="思考", title="新条目",
        author="ai",
    )
    assert "error" not in result, f"insert failed: {result}"
    text = journal_empty.read_text(encoding="utf-8")
    assert "@ai" in text, f"expected @ai stamp; got:\n{text}"
    assert "## #思考 新条目" in text


def test_insert_block_stamps_user_marker(journal_empty):
    """HTTP user-facing 路径,新 H2 带 @user。"""
    result = server._insert_block(
        journal_empty, "10:00",
        tag="思考", title="人手输入",
        author="user",
    )
    assert "error" not in result
    text = journal_empty.read_text(encoding="utf-8")
    assert "@user" in text
    assert "## #思考 人手输入" in text


# ─── T7 · _append_comment_to_block 原内容一字不动 ────────────────────

def test_append_comment_preserves_original_body(journal_both):
    """append_comment 在 @user 块 body 末尾 append,原文必须 intact。"""
    original = journal_both.read_text(encoding="utf-8")
    result = server._append_comment_to_block(
        journal_both, "9:00",
        comment_md="*AI 回看 5.22: 这条线还在跑*",
    )
    assert "error" not in result, f"append failed: {result}"
    text = journal_both.read_text(encoding="utf-8")
    # 原文每一行都还在
    for line in "昨晚 11:30 睡到 7:00,闹钟 7:40。躺着也没睡着。".split("\n"):
        assert line in text, f"original line missing: {line!r}"
    # 新 comment 在
    assert "AI 回看 5.22" in text
    # 顺序对(原 body 在前,comment 在后)
    body_idx = text.index("昨晚 11:30")
    comment_idx = text.index("AI 回看")
    assert body_idx < comment_idx


def test_append_comment_unknown_block_returns_error(journal_empty):
    """指向不存在的时间块 → error,文件不变。"""
    before = journal_empty.read_text(encoding="utf-8")
    result = server._append_comment_to_block(journal_empty, "23:30", comment_md="test")
    assert "error" in result
    assert journal_empty.read_text(encoding="utf-8") == before
