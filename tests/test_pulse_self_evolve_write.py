# TEST PATTERN: contract + effect — _self_evolve_run 写盘契约 + LLM kwargs 契约 + 503 分支
# USE WHEN: 锁住 _self_evolve_run 在 happy path / write failure / LLM mis-config 下的契约
# TESTED IN: gateway PULSE refactor P0+ TDD net (2026-06-18) — must-add #5 + must-add #6 基础设施验证
#
# 这是 LARGE refactor 的"行为固化"测试。重构(P1 → P4)无论怎么搬模块,
# 这些断言必须一字不变跑绿,否则就是真破坏行为了。
#
# 覆盖契约:
# - _safe_write_text 必传 rotate=True(rotate 默认 False,漏传 = 没 bak.1)
# - response.backup 指向真实的 .bak.1 文件
# - response 字段集稳定(前端 / 调试脚本依赖)
# - 写盘失败 → HTTPException(500),detail 含 name + "写盘失败"
# - LLM call kwargs(model / max_tokens / temperature / timeout / messages)契约
# - 503 分支:profile 缺失 / client 起不来
# - agent_context 走 _AGENT_CONTEXT_EVOLVE_PROMPT(frozen-start 段保护)
#
# fixture 走 tests/conftest.py — 跨 P2 refactor 鲁棒

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402

from conftest import VALID_PULSE, VALID_AGENT_CONTEXT, FakeChat, FakeClient  # noqa: E402


# ── 1. _safe_write_text rotate=True 契约 ────────────────────────────────

def test_safe_write_text_called_with_rotate_true(stubbed_llm, isolated_pulse_paths, monkeypatch):
    """_self_evolve_run 必须给 _safe_write_text 传 rotate=True,
    否则旧版不进 bak.1,重写后无法回退(workflow #11 #13)。
    """
    write_calls = []
    orig = server._safe_write_text

    def spy(path, content, **kw):
        write_calls.append({"path": Path(path), "text_len": len(content), **kw})
        return orig(path, content, **kw)

    monkeypatch.setattr(server, "_safe_write_text", spy)

    # user_pulse bootstrap 路径:文件不存在 + create_if_absent=True → 真走写盘
    result = server._self_evolve_run("user_pulse", "对话 A")
    assert result["ok"] is True

    assert len(write_calls) == 1, "_self_evolve_run 应该恰好调一次 _safe_write_text"
    assert write_calls[0]["rotate"] is True, \
        "必须传 rotate=True,否则旧版不旋转进 bak.1(refactor 时容易漏)"
    assert write_calls[0]["path"] == isolated_pulse_paths.user


# ── 2. response.backup 字段契约 ─────────────────────────────────────────

def test_response_backup_field_points_to_real_bak1(stubbed_llm, isolated_pulse_paths):
    """response['backup'] = str(path) + '.bak.1',且 rotate 会让 bak.1 真存在。
    user_pulse bootstrap 时 old 是空文件,所以 bak.1 不会存在;
    用 project_pulse 已存在路径测真实 rotate 后的 bak.1。
    """
    # 先写一份现存 project_pulse(有 ts)→ evolve 时旧版旋转进 bak.1
    initial = "<!-- ts:2026-06-10 -->\n# 旧版 PROJECT_PULSE\n旧内容\n"
    isolated_pulse_paths.project.write_text(initial, encoding="utf-8")

    result = server._self_evolve_run("project_pulse", "对话 B")
    assert result["ok"] is True

    expected_backup = str(isolated_pulse_paths.project) + ".bak.1"
    assert result["backup"] == expected_backup, \
        "backup 字段必须 = str(path) + '.bak.1'(前端 / 调试脚本依赖)"
    assert Path(result["backup"]).exists(), \
        "_safe_write_text(rotate=True) 应让 bak.1 真存在(回退路径靠这个)"
    # bak.1 内容 = 旧版原文
    assert Path(result["backup"]).read_text(encoding="utf-8") == initial


# ── 3. response 字段完整契约 ────────────────────────────────────────────

def test_response_keys_and_types_complete(stubbed_llm, isolated_pulse_paths):
    """response 字段集 + 类型稳定,refactor 不许漏字段不许改类型。"""
    result = server._self_evolve_run("user_pulse", "对话 C")
    expected_keys = {
        "ok", "target", "name",
        "old_chars", "new_chars",
        "old_records", "new_records",
        "backup", "bootstrap", "schema_version",
    }
    assert set(result.keys()) == expected_keys, \
        f"response keys 漂了: 多了 {set(result) - expected_keys}, 少了 {expected_keys - set(result)}"
    assert result["ok"] is True
    assert isinstance(result["target"], str) and result["target"] == "user_pulse"
    assert isinstance(result["name"], str) and result["name"] == "USER_PULSE"
    assert isinstance(result["old_chars"], int) and result["old_chars"] == 0  # bootstrap 起点空
    assert isinstance(result["new_chars"], int) and result["new_chars"] > 0
    assert isinstance(result["old_records"], int)
    assert isinstance(result["new_records"], int)
    assert isinstance(result["backup"], str)
    assert isinstance(result["bootstrap"], bool) and result["bootstrap"] is True
    assert isinstance(result["schema_version"], int)


# ── 4. 写盘失败 → HTTPException(500) ────────────────────────────────────

def test_safe_write_text_failure_wraps_to_http_500(stubbed_llm, isolated_pulse_paths, monkeypatch):
    """_safe_write_text 抛 → HTTPException(500),detail 含 name 和 '写盘失败'。
    refactor 时容易漏掉这层 try/except 把 OSError 直接吐给前端,失去定位信息。
    """
    def boom(path, content, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(server, "_safe_write_text", boom)

    with pytest.raises(HTTPException) as exc_info:
        server._self_evolve_run("user_pulse", "对话 D")

    assert exc_info.value.status_code == 500
    detail = str(exc_info.value.detail)
    assert "USER_PULSE" in detail, f"detail 应含 target name USER_PULSE: {detail}"
    assert "写盘失败" in detail, f"detail 应含 '写盘失败' 提示: {detail}"


# ── 5. LLM call kwargs 契约 ────────────────────────────────────────────

def test_llm_call_kwargs_locked(stubbed_llm, isolated_pulse_paths):
    """LLM call 参数集稳定 — model / max_tokens / temperature / timeout / messages
    refactor 时容易把超时 120s 改成 60s 把 max_tokens 改小 → 直接砸 LLM 输出截断。
    """
    result = server._self_evolve_run("user_pulse", "对话原文 E 是测 LLM call kwargs 用的")
    assert result["ok"] is True

    assert len(stubbed_llm.chat.calls) >= 1, "LLM 至少被调一次"
    call = stubbed_llm.chat.calls[0]

    assert call["model"] == "fake-model", \
        "model 必须取自 profile (stubbed_llm 的 get_profile 返 model=fake-model)"
    assert call["max_tokens"] == 8000, \
        "max_tokens 锁 8000(PULSE 体量上限,改小直接砸 LLM 截断输出)"
    assert call["temperature"] == 0.3, \
        "temperature 锁 0.3(PULSE 重写要稳定,不能高随机)"
    assert call["timeout"] == 120, \
        "timeout 锁 120s(deepseek 重写 24K 字 PULSE 真要这么久)"

    messages = call["messages"]
    assert isinstance(messages, list) and len(messages) == 1
    assert messages[0]["role"] == "user"
    content = messages[0]["content"]
    assert "对话原文 E 是测 LLM call kwargs 用的" in content, \
        "对话原文必须注进 prompt"


def test_llm_call_message_contains_bootstrap_note_when_creating(stubbed_llm, isolated_pulse_paths):
    """user_pulse bootstrap 路径(文件不存在 + create_if_absent)
    → prompt 必须含 bootstrap_note(让 LLM 知道要给每段加 ts)。
    """
    assert not isolated_pulse_paths.user.exists()
    server._self_evolve_run("user_pulse", "对话 F")

    content = stubbed_llm.chat.calls[0]["messages"][0]["content"]
    assert "bootstrap" in content.lower(), \
        "首次创建时 prompt 必须含 bootstrap 提示(LLM 要给每段加 ts,否则下一 cycle 拒)"


# ── 6. 503 分支 ────────────────────────────────────────────────────────

def test_503_when_profile_missing(stubbed_llm, isolated_pulse_paths, monkeypatch):
    """get_profile 返 None → HTTPException(503, 'deepseek 主模型未配置')
    用户没填阿里云 key 的状态,必须明确告知不是默默卡死。
    """
    monkeypatch.setattr(server, "get_profile", lambda *a, **k: None)

    with pytest.raises(HTTPException) as exc_info:
        server._self_evolve_run("user_pulse", "对话 G")
    assert exc_info.value.status_code == 503
    assert "deepseek" in str(exc_info.value.detail).lower()
    assert "未配置" in str(exc_info.value.detail)


def test_503_when_client_unavailable(stubbed_llm, isolated_pulse_paths, monkeypatch):
    """get_client 返 None → HTTPException(503, 'deepseek client 起不来')
    profile 有但 client 起不来(网络 / SDK 初始化失败)。
    """
    monkeypatch.setattr(server, "get_client", lambda profile: None)

    with pytest.raises(HTTPException) as exc_info:
        server._self_evolve_run("user_pulse", "对话 H")
    assert exc_info.value.status_code == 503
    assert "client" in str(exc_info.value.detail).lower()
    assert "起不来" in str(exc_info.value.detail)


# ── 7. agent_context 走专用 prompt ──────────────────────────────────────

def test_agent_context_uses_dedicated_prompt(stubbed_llm, isolated_pulse_paths):
    """agent_context target → 走 _AGENT_CONTEXT_EVOLVE_PROMPT 而非 default。
    专用 prompt 含 'frozen-start' / '协议手册' 词,default(_PULSE_UPDATE_PROMPT)没有。
    workflow #5 root cause B 闭合 — frozen 段保护必须靠对的 prompt。

    先放一份合法 agent_context.md 让走非 skip 路径(agent_context 没有 create_if_absent)。
    再让 stubbed_llm 返合规 agent_context 内容防 _pulse_validate 拒。
    """
    isolated_pulse_paths.agent_context.write_text(
        VALID_AGENT_CONTEXT, encoding="utf-8")
    stubbed_llm.chat.responses = [VALID_AGENT_CONTEXT]

    result = server._self_evolve_run("agent_context", "对话 I")
    assert result["ok"] is True
    assert result.get("skipped") is not True, \
        "agent_context 文件已存在,应该真走 LLM 不 skip"

    content = stubbed_llm.chat.calls[0]["messages"][0]["content"]
    # _AGENT_CONTEXT_EVOLVE_PROMPT 独有词(default 没有)
    assert ("frozen-start" in content or "协议手册" in content), (
        "agent_context 必须走 _AGENT_CONTEXT_EVOLVE_PROMPT(含 frozen-start / 协议手册),"
        "走错 prompt 会让 frozen 段失去保护"
    )
