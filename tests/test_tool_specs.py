# TEST PATTERN: characterization — TOOLS schema 数据 + 与 TOOL_IMPL 的 wiring
# USE WHEN: 锁 LLM 工具 schema 列表,守 TOOLS 抽到 tool_specs.py(§ 9,纯数据 leaf)
# TESTED IN: gateway tool_specs extraction (2026-06-25)
#
# TOOLS 是纯数据(386 行 JSON schema),抽到 tool_specs.py 后 server `from tool_specs import TOOLS`。
# 唯一消费者 _active_tools(server)。锁两条:① 数据 shape ② schema 名 ↔ TOOL_IMPL 实现 wiring 不漂。

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


def test_tools_is_list_of_function_specs():
    assert isinstance(server.TOOLS, list) and len(server.TOOLS) >= 15
    for t in server.TOOLS:
        assert t["type"] == "function"
        assert t["function"]["name"]
        assert "parameters" in t["function"]


def test_tools_schema_matches_tool_impl_wiring():
    """每个 schema 工具名都要有 TOOL_IMPL 实现(load_tool_group 是 dispatch 特例除外)。
    抽 TOOLS 后名字漂了 → 模型调一个没 impl 的工具 → dispatch unknown。这条守住。"""
    schema_names = {t["function"]["name"] for t in server.TOOLS}
    impl_names = set(server.TOOL_IMPL)
    orphans = schema_names - impl_names - {"load_tool_group"}
    assert not orphans, f"schema 有名但无 TOOL_IMPL 实现: {orphans}"


def test_active_tools_returns_tools_subset():
    """_active_tools(server)是唯一消费者:返 TOOLS 子集,抽出后仍 resolve。"""
    tools = server._active_tools(set())
    names = {t["function"]["name"] for t in tools}
    assert names, "_active_tools(空组) 应至少返 bootstrap 工具"
    assert names <= {t["function"]["name"] for t in server.TOOLS}   # 是 TOOLS 子集
