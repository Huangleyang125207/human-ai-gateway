# TEST PATTERN: characterization — TOOLS schema 数据 + 与 TOOL_IMPL 的 wiring
# USE WHEN: 锁 LLM 工具 schema 列表,守 TOOLS 抽到 tool_specs.py(§ 9,纯数据 leaf)
# TESTED IN: gateway tool_specs extraction (2026-06-25)
#
# TOOLS 是纯数据(386 行 JSON schema),抽到 tool_specs.py 后 server `from tool_specs import TOOLS`。
# 唯一消费者 _active_tools(server)。锁两条:① 数据 shape ② schema 名 ↔ TOOL_IMPL 实现 wiring 不漂。

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
import tool_registry  # noqa: E402
from tool_specs import TOOLS  # noqa: E402


def test_tool_registry_module_does_not_import_server():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import tool_registry; "
            "raise SystemExit(1 if 'server' in sys.modules else 0)",
        ],
        cwd=Path(__file__).resolve().parent.parent,
        check=False,
    )

    assert result.returncode == 0


def test_tools_is_list_of_function_specs():
    assert isinstance(TOOLS, list) and len(TOOLS) >= 15
    for t in TOOLS:
        assert t["type"] == "function"
        assert t["function"]["name"]
        assert "parameters" in t["function"]


def test_tools_schema_matches_tool_impl_wiring():
    """每个 schema 工具名都要有 TOOL_IMPL 实现。
    抽 TOOLS 后名字漂了 → 模型调一个没 impl 的工具 → dispatch unknown。这条守住。"""
    schema_names = {t["function"]["name"] for t in TOOLS}
    impl_names = set(server.TOOL_IMPL)
    orphans = schema_names - impl_names
    assert not orphans, f"schema 有名但无 TOOL_IMPL 实现: {orphans}"


def test_active_tools_returns_tools_subset():
    """_active_tools(server)是唯一消费者:返 TOOLS 子集,抽出后仍 resolve。"""
    tools = tool_registry._active_tools(set())
    names = {t["function"]["name"] for t in tools}
    assert names, "_active_tools(空组) 应至少返 bootstrap 工具"
    assert names <= {t["function"]["name"] for t in TOOLS}   # 是 TOOLS 子集


# ── 7.23 尾缀注入铁律:schema 全量常驻 + 派发硬闸(对齐 RN toolParity T2/T2b/T2c)──

def test_active_tools_static_regardless_of_groups():
    """前缀稳定契约:任意 action_context 下 tools 列表逐字节一致 —— KV 缓存前缀
    永不因组加载失效。组的"未加载"由 _dispatch_tool 派发闸拦(尾部错误注入)。"""
    import json
    from tool_registry import _active_tools
    boot = json.dumps(_active_tools(set()), sort_keys=True)
    assert json.dumps(_active_tools({"write_journal"}), sort_keys=True) == boot
    assert json.dumps(_active_tools({"write_journal", "images", "widgets_and_tasks"}), sort_keys=True) == boot
    assert len(_active_tools(set())) == len(TOOLS)


def test_domain_management_tools_are_registered():
    names = {item["function"]["name"] for item in TOOLS}
    assert {
        "manage_tag_aggregate",
        "get_daily_care_state",
        "manage_scrapbook",
        "delete_journal_entry",
        "manage_mood",
    } <= names
    assert {"search_text", "read_text"} <= names
    assert "search_journal" not in names


def test_widget_install_dispatches_without_policy_confirmation(monkeypatch):
    from tool_registry import _dispatch_tool

    calls = []

    def install(args):
        calls.append(args)
        return {"ok": True}

    monkeypatch.setattr(server, "TOOL_IMPL", {"install_widget_spec": install})
    args = {"spec": {"id": "fixture"}}
    quota = {}
    result = _dispatch_tool(
        "install_widget_spec", args, {"origin": "user", "user_text": "看看今天"}, quota,
    )
    assert result == {"ok": True}
    assert calls == [args]
    assert quota == {}


def test_dispatch_uses_call_time_impl_and_failure_reporter(monkeypatch):
    reports = []

    def boom(args):
        raise RuntimeError("probe")

    monkeypatch.setattr(server, "TOOL_IMPL", {"search_text": boom})
    monkeypatch.setattr(
        server,
        "_report_silent_failure",
        lambda *args, **kwargs: reports.append((args, kwargs)),
    )

    result = server._dispatch_tool(
        "search_text", {}, {"origin": "user", "user_text": "搜索"}, {},
    )

    assert result == {"error": "probe"}
    assert reports[0][0][0] == "tool_dispatch_exception"
