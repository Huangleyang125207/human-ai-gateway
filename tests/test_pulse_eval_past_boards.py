# TEST PATTERN: effect — _eval_build_messages 注入 past_boards
# USE WHEN: 验跨夜 eval 连贯性 — AI 必须看到过去 N 晚的留言板原文
# TESTED IN: gateway PULSE refactor P0 TDD net (2026-06-18)
#
# 这是 PULSE.md Cannot break 红线之一:past_boards 注入丢了 → AI 跨夜失忆 → 每天
# 都重复同一句鼓励。重构 _eval_build_messages 时这条不能被破。
#
# fix_existing #2/#6 修订:
#   - EVAL_LOG_DIR 走 conftest 的 isolated_pulse_paths(env-override 友好)
#   - 用 UUID sentinel 防字符串污染假阳性
#   - 加 strict < target boundary case(明天 vs 今天)

import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


@pytest.fixture
def eval_log_with_history(isolated_pulse_paths, monkeypatch):
    """构造 5 天历史 eval-log,每条带 UUID sentinel 防字符串污染假阳"""
    log_dir = isolated_pulse_paths.eval_log
    sentinels = []
    for i in range(13, 18):
        sentinel = f"BOARD-{uuid.uuid4().hex[:8]}-day{i}"
        f = log_dir / f"2026-06-{i:02d}.md"
        f.write_text(f"过去板 2026-06-{i:02d}: {sentinel}\n", encoding="utf-8")
        sentinels.append((f"2026-06-{i:02d}", sentinel))
    # mock 上游 helper,让本测专注 past_boards 注入
    # P3 后:_eval_load_X 住在 pulse_eval,_eval_build_messages 走 pulse_eval namespace
    # 查这些 helper。两边都 patch(raising=False 兼容 P3 之前)
    import pulse_eval
    for mod in (server, pulse_eval):
        monkeypatch.setattr(mod, "find_today_journal", lambda *a, **k: None, raising=False)
        monkeypatch.setattr(mod, "_eval_load_recent_md", lambda *a, **k: "<<<RECENT_MD_MARKER>>>", raising=False)
        monkeypatch.setattr(mod, "_eval_load_pulse_all", lambda *a, **k: "<<<PULSE_ALL_MARKER>>>", raising=False)
        monkeypatch.setattr(mod, "_eval_load_project_claude_md", lambda *a, **k: "<<<CLAUDE_MD_MARKER>>>", raising=False)
    return log_dir, sentinels


def test_past_boards_injected_into_user_payload(eval_log_with_history):
    """_eval_build_messages 的 user payload 必须含过去 5 天每条 sentinel"""
    log_dir, sentinels = eval_log_with_history
    target = datetime(2026, 6, 18)  # 今天
    messages = server._eval_build_messages(target, model_id="test-model")

    # 必须是 [system, user] 两条
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"

    user_payload = messages[1]["content"]
    # 锁红线:5 条历史 board 每条 sentinel 都在
    for date, sentinel in sentinels:
        assert sentinel in user_payload, \
            f"past_boards 注入丢了:sentinel '{sentinel}' (date={date}) 不在 user payload"


def test_past_boards_excludes_target_day(eval_log_with_history):
    """严格小于 target,target 当天的 eval 不该被注入(否则 AI 读自己今晚要写的)"""
    log_dir, _ = eval_log_with_history
    today_sentinel = f"TODAY-{uuid.uuid4().hex[:8]}"
    (log_dir / "2026-06-18.md").write_text(
        f"今天的 board: {today_sentinel}\n", encoding="utf-8")

    target = datetime(2026, 6, 18)
    messages = server._eval_build_messages(target, model_id="test-model")
    user_payload = messages[1]["content"]
    assert today_sentinel not in user_payload, \
        "past_boards 严格小于 target 那条契约被破 — target 当天不该出现"


def test_past_boards_strict_less_than_boundary(isolated_pulse_paths, monkeypatch):
    """严格小于(<)而非 ≤:target=2026-06-18 → 含 17, 不含 18;
    target=2026-06-19 → 含 17/18, 不含 19。(fix_existing #6 加的边界 case)"""
    log_dir = isolated_pulse_paths.eval_log
    sentinels = {}
    for d in ("2026-06-17", "2026-06-18", "2026-06-19"):
        s = f"SENTINEL-{d}-{uuid.uuid4().hex[:6]}"
        (log_dir / f"{d}.md").write_text(s, encoding="utf-8")
        sentinels[d] = s
    import pulse_eval
    for mod in (server, pulse_eval):
        monkeypatch.setattr(mod, "find_today_journal", lambda *a, **k: None, raising=False)
        monkeypatch.setattr(mod, "_eval_load_recent_md", lambda *a, **k: "(no recent)", raising=False)
        monkeypatch.setattr(mod, "_eval_load_pulse_all", lambda *a, **k: "(no pulse)", raising=False)
        monkeypatch.setattr(mod, "_eval_load_project_claude_md", lambda *a, **k: "(no claude md)", raising=False)

    # target=06-18 → 含 17,不含 18/19
    msgs = server._eval_build_messages(datetime(2026, 6, 18))
    p = msgs[1]["content"]
    assert sentinels["2026-06-17"] in p
    assert sentinels["2026-06-18"] not in p, "target 当天必排除(<)"
    assert sentinels["2026-06-19"] not in p, "未来日期当然排除"

    # target=06-19 → 含 17 + 18,不含 19
    msgs = server._eval_build_messages(datetime(2026, 6, 19))
    p = msgs[1]["content"]
    assert sentinels["2026-06-17"] in p
    assert sentinels["2026-06-18"] in p, "昨天必含"
    assert sentinels["2026-06-19"] not in p, "target 当天必排除"


def test_no_past_boards_returns_placeholder(isolated_pulse_paths, monkeypatch):
    """全空 eval-log 时返占位,不抛(让 LLM 知道这是首晚)"""
    # eval_log dir 是空(isolated_pulse_paths 创建但没填)
    import pulse_eval
    for mod in (server, pulse_eval):
        monkeypatch.setattr(mod, "find_today_journal", lambda *a, **k: None, raising=False)
        monkeypatch.setattr(mod, "_eval_load_recent_md", lambda *a, **k: "(no recent)", raising=False)
        monkeypatch.setattr(mod, "_eval_load_pulse_all", lambda *a, **k: "(no pulse)", raising=False)
        monkeypatch.setattr(mod, "_eval_load_project_claude_md", lambda *a, **k: "(no claude md)", raising=False)

    target = datetime(2026, 6, 18)
    messages = server._eval_build_messages(target)
    user_payload = messages[1]["content"]
    # 占位字符串(在 _eval_load_past_boards 内定义)
    assert ("(target 之前没有历史 eval)" in user_payload or
            "(没有历史 eval — 这是第一次)" in user_payload)


def test_past_boards_section_header_present(eval_log_with_history):
    """user payload 里必须有 '过去 7 晚...留言板原文' 这个 section 标签 — LLM 靠它定位"""
    target = datetime(2026, 6, 18)
    messages = server._eval_build_messages(target)
    user_payload = messages[1]["content"]
    assert "过去 7 晚" in user_payload
    assert "留言板原文" in user_payload
