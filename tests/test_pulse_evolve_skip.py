# TEST PATTERN: contract — _self_evolve_run skip-if-absent / create_if_absent
# USE WHEN: 验三 target(user_pulse / project_pulse / agent_context)在文件不存在时的差异化行为
# TESTED IN: gateway PULSE refactor P0 TDD net (2026-06-18)
#
# 6.17 那个 USER_PULSE skip-if-absent bug 的根因:user_pulse 文件不存在时被 graceful skip,
# 但 user_pulse 实际允许 create_if_absent=True 应走 bootstrap 创建首版。本测把这三类
# 行为锁死,防 refactor 把 _SELF_EVOLVE_TARGETS 的 create_if_absent 配置弄漂。

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


# ── 假 LLM client:返一段合规 PULSE,绕 _pulse_validate ─────────────────

class _FakeLLMResp:
    def __init__(self, text):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=text))]


class _FakeChat:
    def __init__(self, text):
        self._text = text
        self.completions = self
    def create(self, **_kw):
        return _FakeLLMResp(self._text)


class _FakeClient:
    def __init__(self, text):
        self.chat = _FakeChat(text)


@pytest.fixture
def stubbed_llm(monkeypatch):
    """get_profile / get_client 都假;LLM 真调时返一段合规带 ts 的 PULSE"""
    valid_pulse = (
        "<!-- ts:2026-06-18 -->\n"
        "# 一句话\n半小时块协作日记\n\n"
        "## 现在\n🟡 in progress · 第一版\n\n"
        "## Cannot break\n- 这条 ts 在\n"
    )
    monkeypatch.setattr(server, "get_profile",
                        lambda *a, **k: {"model": "fake-model"})
    monkeypatch.setattr(server, "get_client",
                        lambda profile: _FakeClient(valid_pulse))
    # 避免真写 vault_git
    monkeypatch.setattr(server.vault_git, "commit_after_write",
                        lambda *a, **k: None)
    # 避免真打通知
    monkeypatch.setattr(server, "_push_notification",
                        lambda *a, **k: None)
    return valid_pulse


@pytest.fixture
def isolated_pulse_paths(monkeypatch, tmp_path):
    """三 target 的路径全 monkeypatch 到 tmp。_SELF_EVOLVE_TARGETS 里的 lambda
    每次调用都从 server module 重读,所以 patch module 属性即生效。"""
    user_p = tmp_path / "USER_PULSE.md"
    proj_p = tmp_path / "PROJECT_PULSE.md"
    agent_p = tmp_path / "AGENT_CONTEXT.md"
    monkeypatch.setattr(server, "_USER_PULSE_PATH", user_p)
    monkeypatch.setattr(server, "_PROJECT_PULSE_PATH", proj_p)
    monkeypatch.setattr(server, "_AGENT_CONTEXT_PATH", agent_p)
    return user_p, proj_p, agent_p


# ── skip-if-absent 行为契约 ───────────────────────────────────────────

def test_user_pulse_missing_creates_via_bootstrap(stubbed_llm, isolated_pulse_paths):
    """user_pulse create_if_absent=True → 文件不存在也走 bootstrap 写入,不 skip"""
    user_p, _, _ = isolated_pulse_paths
    assert not user_p.exists()  # 起点是空
    result = server._self_evolve_run("user_pulse", "对话原文 ABC")
    assert result["ok"] is True
    assert result.get("skipped") is not True, \
        "user_pulse 不存在时应走 bootstrap 创建首版,不该 skip(6.17 那个 bug)"
    assert result["bootstrap"] is True
    assert user_p.exists(), "首版应该真写到盘上"


def test_project_pulse_missing_graceful_skips(stubbed_llm, isolated_pulse_paths):
    """project_pulse 无 create_if_absent → 文件不存在时 graceful skip,不抛"""
    _, proj_p, _ = isolated_pulse_paths
    assert not proj_p.exists()
    result = server._self_evolve_run("project_pulse", "对话原文")
    assert result == {
        "ok": True,
        "skipped": True,
        "reason": result["reason"],
        "target": "project_pulse",
        "name": "项目 PULSE",
    }
    assert "不存在" in result["reason"]
    assert not proj_p.exists(), "skip 路径下不该创建文件"


def test_agent_context_missing_graceful_skips(stubbed_llm, isolated_pulse_paths):
    """agent_context 无 create_if_absent → 同 project_pulse"""
    _, _, agent_p = isolated_pulse_paths
    assert not agent_p.exists()
    result = server._self_evolve_run("agent_context", "对话原文")
    assert result["ok"] is True
    assert result["skipped"] is True
    assert result["target"] == "agent_context"
    assert not agent_p.exists()


def test_user_pulse_existing_skips_bootstrap(stubbed_llm, isolated_pulse_paths):
    """user_pulse 已存在 → 不走 bootstrap,走正常 evolve(non-bootstrap 路径)"""
    user_p, _, _ = isolated_pulse_paths
    # 写一份初始 USER_PULSE(带 ts 让 bootstrap detection 跳过)
    user_p.write_text(
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
