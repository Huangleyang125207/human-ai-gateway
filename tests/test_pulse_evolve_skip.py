# TEST PATTERN: contract — _self_evolve_run skip-if-absent / create_if_absent
# USE WHEN: 验三 target(user_pulse / project_pulse / agent_context)在文件不存在时的差异化行为
# TESTED IN: gateway PULSE refactor P0 TDD net (2026-06-18)
#
# 6.17 那个 USER_PULSE skip-if-absent bug 的根因:user_pulse 文件不存在时被 graceful skip,
# 但 user_pulse 实际允许 create_if_absent=True 应走 bootstrap 创建首版。本测把这三类
# 行为锁死,防 refactor 把 _SELF_EVOLVE_TARGETS 的 create_if_absent 配置弄漂。
#
# fixture 走 tests/conftest.py — 跨 P2 refactor 鲁棒(patch dict item 而非 module 常量)

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


# ── skip-if-absent 行为契约 ───────────────────────────────────────────

def test_user_pulse_missing_creates_via_bootstrap(stubbed_llm, isolated_pulse_paths):
    """user_pulse create_if_absent=True → 文件不存在也走 bootstrap 写入,不 skip"""
    assert not isolated_pulse_paths.user.exists()  # 起点是空
    result = server._self_evolve_run("user_pulse", "对话原文 ABC")
    assert result["ok"] is True
    assert result.get("skipped") is not True, \
        "user_pulse 不存在时应走 bootstrap 创建首版,不该 skip(6.17 那个 bug)"
    assert result["bootstrap"] is True
    assert isolated_pulse_paths.user.exists(), "首版应该真写到盘上"


def test_project_pulse_missing_graceful_skips(stubbed_llm, isolated_pulse_paths):
    """project_pulse 无 create_if_absent → 文件不存在时 graceful skip,不抛"""
    assert not isolated_pulse_paths.project.exists()
    result = server._self_evolve_run("project_pulse", "对话原文")
    assert result == {
        "ok": True,
        "skipped": True,
        "reason": result["reason"],
        "target": "project_pulse",
        "name": "项目 PULSE",
    }
    assert "不存在" in result["reason"]
    assert not isolated_pulse_paths.project.exists(), "skip 路径下不该创建文件"


def test_agent_context_missing_graceful_skips(stubbed_llm, isolated_pulse_paths):
    """agent_context 无 create_if_absent → 同 project_pulse"""
    assert not isolated_pulse_paths.agent_context.exists()
    result = server._self_evolve_run("agent_context", "对话原文")
    assert result["ok"] is True
    assert result["skipped"] is True
    assert result["target"] == "agent_context"
    assert not isolated_pulse_paths.agent_context.exists()


def test_user_pulse_existing_skips_bootstrap(stubbed_llm, isolated_pulse_paths):
    """user_pulse 已存在 → 不走 bootstrap,走正常 evolve(non-bootstrap 路径)"""
    # 写一份初始 USER_PULSE(带 ts 让 bootstrap detection 跳过)
    isolated_pulse_paths.user.write_text(
        "<!-- ts:2026-06-10 -->\n# 旧版\n旧内容\n", encoding="utf-8")
    result = server._self_evolve_run("user_pulse", "对话")
    assert result["ok"] is True
    assert result["bootstrap"] is False, \
        "已有 ts 标记的 PULSE 不该是 bootstrap"


def test_unknown_target_raises_400():
    """未知 target → HTTPException(400)"""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        server._self_evolve_run("totally_unknown_target", "x")
    assert exc.value.status_code == 400


# ── _SELF_EVOLVE_TARGETS 配置契约 ─────────────────────────────────────

def test_self_evolve_targets_config_unchanged():
    """三 target 配置项:create_if_absent / budget / prompt_template 都不能漂"""
    cfg = server._SELF_EVOLVE_TARGETS
    assert set(cfg.keys()) == {"user_pulse", "project_pulse", "agent_context"}
    # 只有 user_pulse 允许 create_if_absent(6.17 教训)
    assert cfg["user_pulse"].get("create_if_absent") is True
    assert cfg["project_pulse"].get("create_if_absent", False) is False
    assert cfg["agent_context"].get("create_if_absent", False) is False
    # 各 target 的 budget
    assert cfg["user_pulse"]["budget"] == 12000
    assert cfg["project_pulse"]["budget"] == 24000
    assert cfg["agent_context"]["budget"] == 8000
    # AGENT_CONTEXT 走独立 prompt template(frozen 段保护)
    assert cfg["agent_context"]["prompt_template"] == "agent_context"
    assert cfg["user_pulse"]["prompt_template"] == "default"
    assert cfg["project_pulse"]["prompt_template"] == "default"
