# TEST PATTERN: contract — _self_evolve_run retry loop + error 分桶 + HTTPException(500) 抛出
# USE WHEN: 验 self-evolve 在 LLM 返不合规/抛异常时的 retry 行为、错误分桶、prompt mutation
# TESTED IN: gateway PULSE refactor P0+ TDD net must-add #2 (2026-06-18)
#
# 锁住 server.py L7703-7755 的契约:
#   - retry loop 跑 2 次,validator reject / 40% sanity reject 路径触发 prompt mutation 后再试
#   - 2 次都失败时按 errlow 关键词分 4 桶(auth/quota/timeout/generic)
#   - 任一桶失败上报 _report_silent_failure(error_type, msg, context)
#   - 最终 raise HTTPException(500) detail 含 cfg name
#
# refactor 守门:P3 把 _self_evolve_run 搬到 pulse_evolve.py 后,这套契约必须一字不变;
# 任一分桶关键词、retry prompt 后缀、HTTPException(500)/detail 漂走 → 这里红。
#
# fixture 走 tests/conftest.py — 跨 P2 refactor 鲁棒(patch dict item + module 常量兜底)

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402

from conftest import VALID_PULSE  # noqa: E402


# ── 准备:写一份合法旧 PULSE 让走 non-bootstrap 路径(有 ts) ─────────────
OLD_PULSE = (
    "<!-- ts:2026-06-10 -->\n"
    "# 一句话\n旧的协作日记\n\n"
    "## 现在\n🟡 in progress · v0\n\n"
    "## Cannot break\n- 旧 ts 在那\n"
    "## 历史阶段\n5.3-5.12 第一阶段\n"
    "## 不要做的事\n- 不要凭感觉\n"
)

# 不合规返(没 ts 标记) → _pulse_validate 第一步就拒
NO_TS_BAD = "# 一句话\n这里没 ts 标记\n## 现在\n卡住了\n"

# 过短返(<40% old)
TOO_SHORT_BAD = (
    "<!-- ts:2026-06-18 -->\n# 短\n少\n"
)


# ── retry 1: validator reject → retry → succeed ─────────────────────────

def test_retry_after_validator_reject_then_succeeds(stubbed_llm, isolated_pulse_paths):
    """第一次 LLM 返没 ts → _pulse_validate 拒;第二次返合规 → ok"""
    isolated_pulse_paths.user.write_text(OLD_PULSE, encoding="utf-8")
    stubbed_llm.chat.responses = [NO_TS_BAD, VALID_PULSE]

    result = server._self_evolve_run("user_pulse", "对话原文")

    assert result["ok"] is True
    assert result.get("skipped") is not True
    # 真的试了 2 次
    assert len(stubbed_llm.chat.calls) == 2, \
        f"应跑 2 次 LLM,实际 {len(stubbed_llm.chat.calls)} 次"
    # 第二次 prompt 含 retry 标记(prompt mutation 真生效)
    second_prompt = stubbed_llm.chat.calls[1]["messages"][0]["content"]
    assert "上次返回被校验拒了" in second_prompt, \
        "retry prompt 应拼上 validator 错误反馈"
    # 没上报 silent failure(最终 ok)
    assert stubbed_llm.silent_calls == []


# ── retry 2: 40% sanity reject → retry → succeed ─────────────────────────

def test_retry_after_too_short_reject_then_succeeds(stubbed_llm, isolated_pulse_paths):
    """第一次 LLM 返过短(<40% old) → 拒;第二次返合规 → ok"""
    isolated_pulse_paths.user.write_text(OLD_PULSE, encoding="utf-8")
    stubbed_llm.chat.responses = [TOO_SHORT_BAD, VALID_PULSE]

    result = server._self_evolve_run("user_pulse", "对话原文")

    assert result["ok"] is True
    assert len(stubbed_llm.chat.calls) == 2
    # 第二次 prompt 含 "内容腰斩了"(sanity reject 的 retry feedback)
    second_prompt = stubbed_llm.chat.calls[1]["messages"][0]["content"]
    assert "内容腰斩了" in second_prompt, \
        "40% sanity reject 应拼上'内容腰斩了'到 retry prompt"
    assert stubbed_llm.silent_calls == []


# ── error 分桶 4 路 ─────────────────────────────────────────────────────

@pytest.mark.parametrize("exc_message, expected_bucket", [
    ("401 Unauthorized", "self_evolve_call_auth"),
    ("403 Forbidden access", "self_evolve_call_auth"),
    ("429 Too Many Requests", "self_evolve_call_quota"),
    ("quota exceeded for project", "self_evolve_call_quota"),
    ("rate limit hit", "self_evolve_call_quota"),
    ("Read timeout after 120s", "self_evolve_call_timeout"),
    ("Connection reset by peer", "self_evolve_llm_call_failed"),
])
def test_two_attempts_all_fail_bucketed_and_raises_500(
    stubbed_llm, isolated_pulse_paths, exc_message, expected_bucket
):
    """2 次都抛同类异常 → 按 errlow 关键词分桶上报 + raise HTTPException(500)"""
    isolated_pulse_paths.user.write_text(OLD_PULSE, encoding="utf-8")
    # 两次都抛同款异常
    stubbed_llm.chat.responses = [
        Exception(exc_message), Exception(exc_message)
    ]

    with pytest.raises(HTTPException) as exc_info:
        server._self_evolve_run("user_pulse", "对话")

    # HTTP 500 + detail 含 cfg name
    assert exc_info.value.status_code == 500
    cfg_name = server._SELF_EVOLVE_TARGETS["user_pulse"]["name"]
    assert cfg_name in str(exc_info.value.detail), \
        f"500 detail 应含 cfg name '{cfg_name}',实际 {exc_info.value.detail!r}"

    # 真试了 2 次
    assert len(stubbed_llm.chat.calls) == 2

    # silent-failure 上报 1 次,分桶正确
    assert len(stubbed_llm.silent_calls) == 1
    et, msg, context = stubbed_llm.silent_calls[0]
    assert et == expected_bucket, \
        f"errlow={exc_message.lower()!r} 应进 {expected_bucket} 桶,实际 {et}"
    # context 含 target
    assert context is not None and context.get("target") == "user_pulse"


# ── 边界:context 应携带 model + attempts 字段(撞 spec) ────────────────

def test_silent_failure_context_carries_model_and_attempts(
    stubbed_llm, isolated_pulse_paths
):
    """分桶上报的 context 应含 target / model / attempts(workflow B #3 的反馈通道契约)"""
    isolated_pulse_paths.user.write_text(OLD_PULSE, encoding="utf-8")
    stubbed_llm.chat.responses = [
        Exception("401 Unauthorized"), Exception("401 Unauthorized")
    ]

    with pytest.raises(HTTPException):
        server._self_evolve_run("user_pulse", "对话")

    assert len(stubbed_llm.silent_calls) == 1
    _, _, context = stubbed_llm.silent_calls[0]
    assert context["target"] == "user_pulse"
    assert "model" in context, "context 应含 model 字段(stub 返 fake-model)"
    assert context["model"] == "fake-model"
    assert context.get("attempts") == 2, \
        "context attempts 应固定为 2(retry loop 上限)"


# ── 边界:reject 后 retry succeed 不该上报 silent failure ───────────────

def test_validator_reject_then_succeed_no_silent_failure(
    stubbed_llm, isolated_pulse_paths
):
    """retry succeed 路径不该误报 silent failure(only 2 次都失败才上报)"""
    isolated_pulse_paths.user.write_text(OLD_PULSE, encoding="utf-8")
    stubbed_llm.chat.responses = [NO_TS_BAD, VALID_PULSE]

    server._self_evolve_run("user_pulse", "对话")

    assert stubbed_llm.silent_calls == [], \
        "成功的 retry 路径不该污染 silent-failure 通道"


# ── 边界:第二次仍 reject(validator 双拒) → 走 generic 桶 ──────────────

def test_two_validator_rejects_bucket_generic_and_500(
    stubbed_llm, isolated_pulse_paths
):
    """2 次 LLM 都返不合规(非异常,validator 拒) → last_err 不含 auth/quota/timeout
    → 进 self_evolve_llm_call_failed 桶 + raise 500"""
    isolated_pulse_paths.user.write_text(OLD_PULSE, encoding="utf-8")
    stubbed_llm.chat.responses = [NO_TS_BAD, NO_TS_BAD]

    with pytest.raises(HTTPException) as exc_info:
        server._self_evolve_run("user_pulse", "对话")

    assert exc_info.value.status_code == 500
    assert len(stubbed_llm.chat.calls) == 2
    # validator err 不含分桶关键词 → 落 generic 桶
    assert len(stubbed_llm.silent_calls) == 1
    et, msg, context = stubbed_llm.silent_calls[0]
    assert et == "self_evolve_llm_call_failed"
    # msg 应反映 validator 拒的原因(没 ts 标记)
    assert "ts" in msg.lower() or "标记" in msg
