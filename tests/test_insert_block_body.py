# TEST PATTERN: effect — insert_journal_block 一步写全(标题 + 正文)
# USE WHEN: 验 AI 加新 entry 时正文跟标题一次落盘;漏正文时 tool result 带钉子
# TESTED IN: gateway (2026-06-11)
#
# 背景:原 schema 没 body 参数 → AI 物理上只能写标题-only 条目(违反 § H5)。
# 修:schema 加 required body;_insert_block 拼正文;空 body 时 result 带 warning 压补写。

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


TEMPLATE = """# 9：00

##

---

# 9：30

##

---
"""


@pytest.fixture
def journal(tmp_path, monkeypatch):
    f = tmp_path / "26.6.11.md"
    f.write_text(TEMPLATE, encoding="utf-8")
    monkeypatch.setattr(server.vault_git, "commit_after_write", lambda *a, **k: None)
    return f


def test_insert_with_body_writes_prose(journal):
    out = server._insert_block(journal, "9:00", tag="探索", title="测试条目",
                               author="ai", body="发生了什么。\n\n为什么重要。")
    assert out["ok"] is True
    text = journal.read_text(encoding="utf-8")
    assert "## #探索 测试条目 @ai" in text
    assert "发生了什么。" in text
    assert "为什么重要。" in text
    # 正文紧跟 H2,在下一个 H1 之前
    assert text.index("## #探索") < text.index("发生了什么") < text.index("# 9：30")


def test_insert_new_block_with_body(journal):
    out = server._insert_block(journal, "10:00", tag="工作", title="新块",
                               author="ai", body="新时间块也带正文。")
    assert out["ok"] is True
    text = journal.read_text(encoding="utf-8")
    assert "# 10：00" in text
    assert "新时间块也带正文。" in text


def test_insert_without_body_still_works(journal):
    """回归:老调用(无 body)不 break — 前端 UI 用户加空条目走这条。"""
    out = server._insert_block(journal, "9:30", tag="饮食", title="只有标题", author="user")
    assert out["ok"] is True
    assert "## #饮食 只有标题 @user" in journal.read_text(encoding="utf-8")


def test_tool_handler_nags_on_missing_body(journal, monkeypatch):
    monkeypatch.setattr(server, "find_today_journal", lambda *a, **k: journal)
    out = server.tool_insert_journal_block({"tag": "饮食", "title": "没正文", "time": "9:30"})
    assert out["ok"] is True
    assert "warning" in out and "正文" in out["warning"], "漏 body 应在 tool result 落钉子"


def test_tool_handler_no_nag_with_body(journal, monkeypatch):
    monkeypatch.setattr(server, "find_today_journal", lambda *a, **k: journal)
    out = server.tool_insert_journal_block(
        {"tag": "探索", "title": "带正文", "time": "9:00", "body": "完整的散文。"})
    assert out["ok"] is True
    assert "warning" not in out


def test_schema_requires_body():
    import json
    schemas = json.dumps(server.TOOLS, ensure_ascii=False) if hasattr(server, "TOOLS") else ""
    # TOOLS schema 6.25 抽到 tool_specs.py;直接在那源里验 schema
    src = (Path(server.__file__).parent / "tool_specs.py").read_text(encoding="utf-8")
    i = src.find('"name": "insert_journal_block"')
    seg = src[i:i + 1200]
    assert '"body"' in seg, "schema 必须有 body 参数"
    assert '"required": ["tag", "body"]' in seg, "body 必须 required"
