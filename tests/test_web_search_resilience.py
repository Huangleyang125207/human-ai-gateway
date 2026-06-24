# TEST PATTERN: contract — web_search 降级链不被异常击穿
# USE WHEN: 验 lxml 缺失 / 360 parser 崩 时 _do_web_search 不硬挂、降级 + 上报
# TESTED IN: gateway (2026-06-10)
#
# 背景:_360_search/_sogou_wechat_search 顶部 `from lxml import html`(try 外),
# 生产包漏 lxml → ModuleNotFoundError 逃出 → 跳过 360→百炼→ddgs 整条链 + 不上报
# (feedback-sink 隐身)。本测守住"异常被吞 + 降级 + 上报"。

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
import web_tools  # noqa: E402

# patch 目标:_do_web_search 住在 web_tools,内部 lookup 走 web_tools namespace
# (search 后端函数 patch web_tools);_report_silent_failure 是函数体内 lazy
# `from server import _report_silent_failure` → 每次调用读 server 当前态,
# 测试 patch server 即可生效。


def test_360_lxml_crash_degrades_to_bailian_not_escape(monkeypatch):
    reported = []
    monkeypatch.setattr(server, "_report_silent_failure",
                        lambda et, msg="", context=None: reported.append(et))
    # 模拟生产真症状:_360_search 顶部 import lxml 崩
    def boom(*a, **k):
        raise ModuleNotFoundError("No module named 'lxml'")
    monkeypatch.setattr(web_tools, "_360_search", boom)
    monkeypatch.setattr(web_tools, "_bailian_web_search", lambda q: "百炼真结果")
    # 不该抛异常,且降级到百炼
    out = server._do_web_search("test query", 3, "general")
    assert out == "百炼真结果", "360 崩应降级到百炼,而不是把异常抛给 tool"
    assert "web_search_360_exception" in reported, "360 异常必须上报(否则 feedback-sink 隐身)"


def test_360_and_bailian_both_fail_falls_to_ddgs(monkeypatch):
    monkeypatch.setattr(server, "_report_silent_failure", lambda *a, **k: None)
    monkeypatch.setattr(web_tools, "_360_search",
                        lambda *a, **k: (_ for _ in ()).throw(ModuleNotFoundError("lxml")))
    monkeypatch.setattr(web_tools, "_bailian_web_search",
                        lambda q: (_ for _ in ()).throw(RuntimeError("no key")))
    monkeypatch.setattr(web_tools, "_ddgs_search", lambda q, n: "[ddgs 兜底结果]")
    out = server._do_web_search("q", 3, "general")
    assert out == "[ddgs 兜底结果]", "360+百炼都崩应落到 ddgs,全程不抛"


def test_wechat_lxml_crash_returns_clean_not_escape(monkeypatch):
    reported = []
    monkeypatch.setattr(server, "_report_silent_failure",
                        lambda et, msg="", context=None: reported.append(et))
    monkeypatch.setattr(web_tools, "_sogou_wechat_search",
                        lambda *a, **k: (_ for _ in ()).throw(ModuleNotFoundError("lxml")))
    out = server._do_web_search("q", 3, "wechat")
    assert out.startswith("[公众号搜索暂不可用"), "wechat 崩应返干净提示,不抛异常"
    assert "web_search_wechat_exception" in reported
