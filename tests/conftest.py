"""共享 pytest fixture — 主要给 PULSE refactor P0+ TDD 网用。
其余测试可按需 import。

设计要点:
- 跨模块鲁棒(P2 把 _SELF_EVOLVE_TARGETS / _USER_PULSE_PATH 等搬到 pulse_io.py 后仍工作):
  * `isolated_pulse_paths` patch _SELF_EVOLVE_TARGETS 字典 item(dict 是引用,跨模块共享),
    同时兜底 patch module 常量(给直接读它们的代码用)
  * server.py 必须保 re-export(见 Active spec § Plan 的 re-export checklist),否则
    `monkeypatch.setattr(server, X)` 失效 — fixture sanity 加 assert 守
- LLM 真实度(must-add #6):_FakeChat 升级 capture-spy + 可注入序列回应 + 可抛异常,
  全部调用 kwargs 入 .calls 列表
- silent-failure / push 通知 spy:从 lambda *a, **k: None 升级到列表 capture,
  分桶名漂走能抓到
- vault_git audit chain spy(must-add #3):用 MagicMock 替原 stub,
  assert_called_once + call.kwargs 验证
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


# ── LLM 假货:capture-spy 版 ─────────────────────────────────────────

class FakeLLMResp:
    """模拟 openai SDK ChatCompletion 响应。.choices[0].message.content"""
    def __init__(self, text):
        self.choices = [SimpleNamespace(
            message=SimpleNamespace(content=text))]


class FakeChat:
    """capture-spy LLM client。
    - responses: str | list[str|Exception] — 按调用顺序消费;到末尾继续返最后一个
    - .calls: list[dict] 累积所有调用的 kwargs(messages/model/max_tokens/temperature/timeout 全在)
    用法:
      chat = FakeChat("合规返")
      chat = FakeChat([bad_response, valid_response])  # retry 场景
      chat = FakeChat(Exception("401 unauth"))         # error 场景
    """
    def __init__(self, responses):
        self.responses = responses if isinstance(responses, list) else [responses]
        self.calls = []
        self.completions = self  # 让 client.chat.completions.create 工作

    def create(self, **kwargs):
        self.calls.append(kwargs)
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        resp = self.responses[idx]
        if isinstance(resp, BaseException):
            raise resp
        return FakeLLMResp(resp)


class FakeClient:
    """模拟 openai.OpenAI() client。chat.completions.create → FakeChat"""
    def __init__(self, chat):
        self.chat = SimpleNamespace(completions=chat)


# ── 合规 PULSE 文本 ─────────────────────────────────────────────────

VALID_PULSE = (
    "<!-- ts:2026-06-18 -->\n"
    "# 一句话\n协作日记\n\n"
    "## 现在\n🟡 in progress · 第一版\n\n"
    "## Cannot break\n- ts 在\n"
)


VALID_AGENT_CONTEXT = (
    "<!-- ts:2026-06-18 -->\n"
    "# AGENT_CONTEXT\n\n"
    "## 用户偏好\n半小时块协作\n"
)


# ── 三 fixture:LLM + 路径 + 完整 stack ────────────────────────────────

@pytest.fixture
def fake_chat():
    """单独的 FakeChat,默认返合规 PULSE。
    用法:fake_chat.responses = [bad, good]; fake_chat.calls 拿 spy 数据。
    """
    return FakeChat(VALID_PULSE)


@pytest.fixture
def isolated_pulse_paths(monkeypatch, tmp_path):
    """所有 PULSE 真源路径 + mirror 路径 + EVAL_LOG_DIR 都隔离到 tmp。

    跨 P2 重构鲁棒:
      ① patch _SELF_EVOLVE_TARGETS dict 里 lambda(dict 是引用,跨模块共享)
      ② 兜底 patch server module 常量(给直接读它们的代码,不通过 lambda 的)
      ③ P2 后 server.py 须 re-export(见 Active spec § Plan),否则 setattr(server, X) raise
    """
    user_p = tmp_path / "USER_PULSE.md"
    proj_p = tmp_path / "PROJECT_PULSE.md"
    agent_p = tmp_path / "AGENT_CONTEXT.md"
    mirror_dir = tmp_path / "pulse-mirror"
    mirror_dir.mkdir()
    eval_dir = tmp_path / "eval-log"
    eval_dir.mkdir()

    # ① 关键:patch dict item — dict 是引用,跨模块共享,P2 后仍生效
    monkeypatch.setitem(
        server._SELF_EVOLVE_TARGETS["user_pulse"], "path", lambda: user_p)
    monkeypatch.setitem(
        server._SELF_EVOLVE_TARGETS["project_pulse"], "path", lambda: proj_p)
    monkeypatch.setitem(
        server._SELF_EVOLVE_TARGETS["agent_context"], "path", lambda: agent_p)
    # ② 兜底:module-level 常量(直接读这些的代码用,不经 lambda)
    # raising=False 防 P2 后 server.py 真把这些常量删了(本来期望 re-export 但万一漏)
    monkeypatch.setattr(server, "_USER_PULSE_PATH", user_p, raising=False)
    monkeypatch.setattr(server, "_PROJECT_PULSE_PATH", proj_p, raising=False)
    monkeypatch.setattr(server, "_AGENT_CONTEXT_PATH", agent_p, raising=False)
    monkeypatch.setattr(server, "PULSE_DIR", mirror_dir, raising=False)
    monkeypatch.setattr(server, "EVAL_LOG_DIR", eval_dir, raising=False)
    # VAULT_DIR 默认隔离到 tmp,让 path.resolve().is_relative_to(VAULT_DIR) 命中
    # ⇒ vault_git.commit_after_write 这条分支真执行(P0+ must-add #3 要)
    monkeypatch.setattr(server, "VAULT_DIR", tmp_path, raising=False)

    return SimpleNamespace(
        user=user_p, project=proj_p, agent_context=agent_p,
        mirror=mirror_dir, eval_log=eval_dir, vault=tmp_path,
    )


@pytest.fixture
def stubbed_llm(monkeypatch, fake_chat):
    """完整 LLM + audit + notification stack stub,带 spy 列表。

    返 SimpleNamespace:
      .chat            — FakeChat 实例(.calls = LLM call kwargs 列表)
      .vault_git       — MagicMock(vault_git.commit_after_write spy)
      .silent_calls    — list[(error_type, message, context)] _report_silent_failure spy
      .push_calls      — list[(kind, kwargs)] _push_notification spy
      .responses       — 改 fake_chat.responses 的快捷
    """
    silent_calls = []
    push_calls = []
    vgit_mock = MagicMock(name="vault_git.commit_after_write")

    monkeypatch.setattr(server, "get_profile",
                        lambda *a, **k: {"model": "fake-model"})
    monkeypatch.setattr(server, "get_client",
                        lambda profile: FakeClient(fake_chat))
    monkeypatch.setattr(server.vault_git, "commit_after_write", vgit_mock)
    monkeypatch.setattr(server, "_push_notification",
                        lambda kind, message="", context=None:
                        push_calls.append((kind, {"message": message, "context": context})))
    monkeypatch.setattr(server, "_report_silent_failure",
                        lambda et, msg="", context=None:
                        silent_calls.append((et, msg, context)))

    return SimpleNamespace(
        chat=fake_chat,
        vault_git=vgit_mock,
        silent_calls=silent_calls,
        push_calls=push_calls,
    )


@pytest.fixture
def client():
    """FastAPI TestClient — endpoint 测试用"""
    from fastapi.testclient import TestClient
    return TestClient(server.app)
