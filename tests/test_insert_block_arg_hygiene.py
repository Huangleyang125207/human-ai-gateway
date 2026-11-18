# TEST PATTERN: effect — insert_journal_block 参数卫生(对齐 RN adaptToolArgs)
# USE WHEN: 验 tag/title 里的 "#" 前缀 / "@user"/"@ai" 伪造署名被剥离
# TESTED IN: gateway (2026-07-24)
#
# 背景:RN services/toolGating.ts adaptToolArgs 已做 tag 去 "#" 前缀 + tag/title
# 剥 @user/@ai(7.21 真机实锤:模型伪造署名)。PC 是 oracle,两端行为必须一致,
# 这里把同等卫生下沉到 tool_insert_journal_block 入口(journal_task_tools.py)。

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
import journal_task_tools  # noqa: E402


TEMPLATE = """# 9：00

##

---
"""


@pytest.fixture
def journal(tmp_path, monkeypatch):
    f = tmp_path / "26.7.24.md"
    f.write_text(TEMPLATE, encoding="utf-8")
    monkeypatch.setattr(server.vault_git, "commit_after_write", lambda *a, **k: None)
    monkeypatch.setattr(server, "find_today_journal", lambda *a, **k: f)
    return f


def test_tag_hash_prefix_stripped(journal):
    out = journal_task_tools.tool_insert_journal_block(
        {"tag": "#算法", "title": "标题", "time": "9:00", "body": "正文。"})
    assert out["ok"] is True
    text = journal.read_text(encoding="utf-8")
    assert "## #算法 标题 @ai" in text
    assert "###算法" not in text  # 没有残留双 #(去掉的是原始 tag 里的 "#",不是 H2 markdown 前缀)


def test_tag_and_title_strip_fake_authorship(journal):
    out = journal_task_tools.tool_insert_journal_block(
        {"tag": "#工作@user", "title": "内容@ai 伪装", "time": "9:00", "body": "正文。"})
    assert out["ok"] is True
    text = journal.read_text(encoding="utf-8")
    assert "## #工作 内容 伪装 @ai" in text
    assert "@user" not in text.split("\n")[2]  # H2 行本身只有真实作者署名 @ai


def test_title_strips_at_ai_without_tag_issue(journal):
    out = journal_task_tools.tool_insert_journal_block(
        {"tag": "探索", "title": "写了 @ai 的话", "time": "9:00", "body": "正文。"})
    assert out["ok"] is True
    text = journal.read_text(encoding="utf-8")
    assert "@ai 的话" not in text
    assert "写了" in text and "的话" in text


def test_hygiene_strips_sig_adjacent_to_chinese(journal):
    """7.23 跨语言对拍分叉回归:Python \\b 把汉字算词字符 → "中间@user嵌套的"不剥;
    改 (?![A-Za-z0-9_]) 显式 ASCII 边界后与 RN(JS \\b)一致:剥。@aider 等长词不误伤。"""
    out = journal_task_tools.tool_insert_journal_block(
        {"tag": "#算法@user续", "title": "中间@user嵌套的 @aider 保留", "time": "9:00", "body": "正文。"})
    assert out["ok"] is True
    text = journal.read_text(encoding="utf-8")
    assert "## #算法续 中间嵌套的 @aider 保留 @ai" in text
