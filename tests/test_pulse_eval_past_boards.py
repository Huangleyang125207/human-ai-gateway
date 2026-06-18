# TEST PATTERN: effect — _eval_build_messages 注入 past_boards
# USE WHEN: 验跨夜 eval 连贯性 — AI 必须看到过去 N 晚的留言板原文,才能"不重复鼓励 / 跟进 tomorrow_question"
# TESTED IN: gateway PULSE refactor P0 TDD net (2026-06-18)
#
# 这是 PULSE.md Cannot break 红线之一:past_boards 注入丢了 → AI 跨夜失忆 → 每天
# 都重复同一句鼓励。重构 _eval_build_messages 时这条不能被破。

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


@pytest.fixture
def eval_log_with_history(monkeypatch, tmp_path):
    """构造 N 天历史 eval-log,monkeypatch EVAL_LOG_DIR 到 tmp"""
    log_dir = tmp_path / "eval-log"
    log_dir.mkdir()
    # 造 5 天 past boards(target=今天,所以这些都该被读)
    sentences = [
        "板 2026-06-13: 用户当晚问要不要喝水",
        "板 2026-06-14: AI 鼓励完成了散步",
        "板 2026-06-15: tomorrow_question 关于阅读",
        "板 2026-06-16: 用户没回应 reading question",
        "板 2026-06-17: AI 换了维度问身体感受",
    ]
    for i, line in enumerate(sentences, start=13):
        f = log_dir / f"2026-06-{i:02d}.md"
        f.write_text(line + "\n", encoding="utf-8")
    monkeypatch.setattr(server, "EVAL_LOG_DIR", log_dir)
    return log_dir, sentences


def test_past_boards_injected_into_user_payload(eval_log_with_history, monkeypatch):
    """_eval_build_messages 的 user payload 必须含过去 7 天的 past_boards 原文"""
    log_dir, sentences = eval_log_with_history
    # mock 掉外部依赖:vault md / pulse / claude.md 不存在时返占位,不该影响 past_boards 注入
    monkeypatch.setattr(server, "find_today_journal", lambda *a, **k: None)
    monkeypatch.setattr(server, "_eval_load_recent_md", lambda *a, **k: "(no recent)")
    monkeypatch.setattr(server, "_eval_load_pulse_all", lambda *a, **k: "(no pulse)")
    monkeypatch.setattr(server, "_eval_load_project_claude_md", lambda *a, **k: "(no claude md)")

    target = datetime(2026, 6, 18)  # 今天
    messages = server._eval_build_messages(target, model_id="test-model")

    # 必须是 [system, user] 两条
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"

    user_payload = messages[1]["content"]
    # 锁红线:5 条历史 board 全在
    for s in sentences:
        assert s in user_payload, f"past_boards 注入丢了:'{s}' 不在 user payload"


def test_past_boards_excludes_target_day(eval_log_with_history, monkeypatch):
    """严格小于 target,target 当天的 eval 不该被注入(否则 AI 读自己今晚要写的)"""
    log_dir, _ = eval_log_with_history
    # 加一条今天的(模拟 target 当天已经写过 — 不该被读)
    (log_dir / "2026-06-18.md").write_text("今天的 board 不该被注入", encoding="utf-8")
    monkeypatch.setattr(server, "find_today_journal", lambda *a, **k: None)
    monkeypatch.setattr(server, "_eval_load_recent_md", lambda *a, **k: "(no recent)")
    monkeypatch.setattr(server, "_eval_load_pulse_all", lambda *a, **k: "(no pulse)")
    monkeypatch.setattr(server, "_eval_load_project_claude_md", lambda *a, **k: "(no claude md)")

    target = datetime(2026, 6, 18)
    messages = server._eval_build_messages(target, model_id="test-model")
    user_payload = messages[1]["content"]
    assert "今天的 board 不该被注入" not in user_payload, \
        "past_boards 严格小于 target 那条契约被破 — target 当天不该出现"


def test_no_past_boards_returns_placeholder(monkeypatch, tmp_path):
    """全空 eval-log 时返占位,不抛(让 LLM 知道这是首晚)"""
    log_dir = tmp_path / "empty-eval-log"
    log_dir.mkdir()
    monkeypatch.setattr(server, "EVAL_LOG_DIR", log_dir)
    monkeypatch.setattr(server, "find_today_journal", lambda *a, **k: None)
    monkeypatch.setattr(server, "_eval_load_recent_md", lambda *a, **k: "(no recent)")
    monkeypatch.setattr(server, "_eval_load_pulse_all", lambda *a, **k: "(no pulse)")
    monkeypatch.setattr(server, "_eval_load_project_claude_md", lambda *a, **k: "(no claude md)")

    target = datetime(2026, 6, 18)
    messages = server._eval_build_messages(target)
    user_payload = messages[1]["content"]
    # 占位字符串(在 _eval_load_past_boards 内定义)
    assert "(target 之前没有历史 eval)" in user_payload or \
           "(没有历史 eval — 这是第一次)" in user_payload


def test_past_boards_section_header_present(eval_log_with_history, monkeypatch):
    """user payload 里必须有 '过去 7 晚你(AI)给 user 的留言板原文' 这个 section 标签 —
    LLM 靠它定位"""
    monkeypatch.setattr(server, "find_today_journal", lambda *a, **k: None)
    monkeypatch.setattr(server, "_eval_load_recent_md", lambda *a, **k: "(no recent)")
    monkeypatch.setattr(server, "_eval_load_pulse_all", lambda *a, **k: "(no pulse)")
    monkeypatch.setattr(server, "_eval_load_project_claude_md", lambda *a, **k: "(no claude md)")

    target = datetime(2026, 6, 18)
    messages = server._eval_build_messages(target)
    user_payload = messages[1]["content"]
    # section 头(_eval_build_messages 写死的格式)
    assert "过去 7 晚" in user_payload
    assert "留言板原文" in user_payload
