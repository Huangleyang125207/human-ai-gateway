# TEST PATTERN: effect — self-evolve 首次创建 USER_PULSE
# USE WHEN: 验 user_pulse 文件不存在时 LLM 生成首版并写盘;project_pulse 维持 skip
# TESTED IN: gateway (2026-06-11)
#
# 背景:原逻辑"文件不存在 → skip",但全代码 0 处创建 USER_PULSE → 自演化永远启动不了。
# 修:user_pulse 配 create_if_absent,不存在时当空 pulse 走 bootstrap 让 LLM 生成首版。

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


GOOD_PULSE = """# USER_PULSE

<!-- ts:2026-06-11 -->
## 当下气压
内测铺开前夜,焦虑但方向清晰。

<!-- ts:2026-06-11 -->
## 想做
先把可观测性发出去再扩内测。
"""


class _FakeChoice:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})()


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeClient:
    def __init__(self, content):
        self._content = content
        self.calls = []

    @property
    def chat(self):
        outer = self

        class _Comp:
            @staticmethod
            def create(**kw):
                outer.calls.append(kw)
                return _FakeResp(outer._content)

        class _Chat:
            completions = _Comp()

        return _Chat()


def _wire_llm(monkeypatch, client):
    monkeypatch.setattr(server, "get_profile", lambda *a, **k: {"model": "deepseek-v4-pro"})
    monkeypatch.setattr(server, "get_client", lambda p: client)


def test_user_pulse_created_when_absent(monkeypatch, tmp_path):
    target_md = tmp_path / "USER_PULSE.md"
    assert not target_md.exists()
    monkeypatch.setitem(
        server._SELF_EVOLVE_TARGETS["user_pulse"], "path", lambda: target_md
    )
    client = _FakeClient(GOOD_PULSE)
    _wire_llm(monkeypatch, client)

    out = server._self_evolve_run("user_pulse", "用户:今天聊了内测的事。\nAI:嗯。")

    assert out["ok"] is True
    assert not out.get("skipped"), f"不该 skip: {out}"
    assert out["bootstrap"] is True, "首次创建应走 bootstrap"
    assert target_md.exists(), "USER_PULSE.md 应被创建"
    assert "当下气压" in target_md.read_text(encoding="utf-8")
    assert client.calls, "应真调了 LLM"
    # prompt 里旧 pulse 为空(从虚空生成首版)
    assert "当前 USER_PULSE 全文" in client.calls[0]["messages"][0]["content"]


def test_project_pulse_still_skips_when_absent(monkeypatch, tmp_path):
    target_md = tmp_path / "PROJECT_PULSE.md"
    monkeypatch.setitem(
        server._SELF_EVOLVE_TARGETS["project_pulse"], "path", lambda: target_md
    )
    client = _FakeClient(GOOD_PULSE)
    _wire_llm(monkeypatch, client)

    out = server._self_evolve_run("project_pulse", "随便聊点啥")

    assert out["ok"] is True
    assert out.get("skipped") is True, "project_pulse 不存在仍应 skip(陌生用户没项目)"
    assert not target_md.exists()
    assert not client.calls, "skip 路径不该调 LLM"


def test_user_pulse_existing_file_unaffected(monkeypatch, tmp_path):
    """回归:已有 USER_PULSE 的老路径(重写而非创建)不受影响。"""
    target_md = tmp_path / "USER_PULSE.md"
    target_md.write_text(GOOD_PULSE, encoding="utf-8")
    monkeypatch.setitem(
        server._SELF_EVOLVE_TARGETS["user_pulse"], "path", lambda: target_md
    )
    updated = GOOD_PULSE.replace("2026-06-11", "2026-06-12")
    client = _FakeClient(updated)
    _wire_llm(monkeypatch, client)

    out = server._self_evolve_run("user_pulse", "用户:又一天。")

    assert out["ok"] is True and not out.get("skipped")
    assert "2026-06-12" in target_md.read_text(encoding="utf-8")
    # 重写路径有 rotate backup
    assert (tmp_path / "USER_PULSE.md.bak.1").exists()
