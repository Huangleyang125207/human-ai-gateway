# TEST PATTERN: contract — _pulse_validate 守门
# USE WHEN: 验 LLM 重写 PULSE 时的 budget / ts 格式 / strict 模式 / frozen / placeholder
# TESTED IN: gateway PULSE refactor P0 TDD net (2026-06-18)
#
# 现状(L6976):锁住六类规则:① 长度 ≤ budget ② 必含至少一条 ts ③ ts 格式合法
# ④ strict 模式 ts/H2 不腰斩 ⑤ frozen 段 byte-equal ⑥ placeholder 数量不减
# 重构后这六条必须一字不变 — 任何漂移都说明 _pulse_validate 行为变了。

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


# ── 基本守门 ─────────────────────────────────────────────────────────

def test_over_budget_rejects():
    text = "<!-- ts:2026-06-18 -->\n" + "x" * 100
    ok, err = server._pulse_validate(text, budget=80)
    assert not ok
    assert "budget" in err.lower()


def test_no_ts_marker_rejects():
    text = "# 全是散文,没 ts 注释\n这一段长但缺标记。"
    ok, err = server._pulse_validate(text, budget=200)
    assert not ok
    assert "ts" in err.lower()


def test_bad_ts_format_rejects():
    text = "<!-- ts:2026/06/18 -->\n# 用斜杠不是横线"
    ok, err = server._pulse_validate(text, budget=200)
    # 这格式不被 _TS_RE 抓 → 等同于没找到任何 ts
    assert not ok


def test_invalid_calendar_date_rejects():
    # 格式对但日期非法(2 月 30 日)
    text = "<!-- ts:2026-02-30 -->\n# 日期非法"
    ok, err = server._pulse_validate(text, budget=200)
    assert not ok
    assert "ts" in err.lower() or "合法" in err


def test_happy_path():
    text = "<!-- ts:2026-06-18 -->\n# 段落\n内容。"
    ok, err = server._pulse_validate(text, budget=200)
    assert ok, f"应过,但 err={err}"


# ── strict 模式(传 old_text 才生效) ──────────────────────────────────

def test_strict_ts_halved_rejects():
    # old 有 10 个 ts,new 只剩 4 个(< 50%) → 拒
    old = "\n".join(f"<!-- ts:2026-06-1{i % 10} -->\n# H{i}\n内容\n" for i in range(10))
    new = "<!-- ts:2026-06-18 -->\n# 仅一段\n内容\n" + "<!-- ts:2026-06-18 -->\n## 二\n" * 3
    ok, err = server._pulse_validate(new, budget=20000, old_text=old, strict=True)
    assert not ok
    assert "ts" in err.lower() and "腰斩" in err


def test_strict_h2_halved_rejects():
    # old 有 10 个 H2,new 只剩 2 → 拒
    old_ts = "\n".join(f"<!-- ts:2026-06-{i:02d} -->" for i in range(1, 11))
    old_h2 = "\n".join(f"## H2-{i}\n内容\n" for i in range(10))
    old = old_ts + "\n" + old_h2
    new_ts = "\n".join(f"<!-- ts:2026-06-{i:02d} -->" for i in range(1, 11))  # ts 没腰斩
    new = new_ts + "\n## H2-1\n短\n## H2-2\n短\n"  # H2 从 10 → 2
    ok, err = server._pulse_validate(new, budget=20000, old_text=old, strict=True)
    assert not ok
    assert "H2" in err and "腰斩" in err


# ── frozen 段(协议手册区,byte-equal) ────────────────────────────────

def test_frozen_byte_equal_required():
    frozen = "<!-- frozen-start -->\n协议手册原文\n<!-- frozen-end -->"
    old = f"<!-- ts:2026-06-18 -->\n# 头\n{frozen}\n## 用户区\n旧"
    new = f"<!-- ts:2026-06-18 -->\n# 头\n<!-- frozen-start -->\n协议被改了\n<!-- frozen-end -->\n## 用户区\n新"
    ok, err = server._pulse_validate(new, budget=20000, old_text=old)
    assert not ok
    assert "frozen" in err.lower()


def test_frozen_unchanged_passes():
    frozen = "<!-- frozen-start -->\n手册\n<!-- frozen-end -->"
    old = f"<!-- ts:2026-06-18 -->\n{frozen}\n## 用户区\n旧"
    new = f"<!-- ts:2026-06-18 -->\n{frozen}\n## 用户区\n新内容"
    ok, err = server._pulse_validate(new, budget=20000, old_text=old)
    assert ok, f"frozen 字节相等应过,err={err}"


# ── placeholder 数量不能减少 ─────────────────────────────────────────

def test_placeholder_eaten_rejects():
    old = ("<!-- ts:2026-06-18 -->\n"
           "<!-- placeholder: 槽 A -->\n<!-- placeholder: 槽 B -->\n")
    new = "<!-- ts:2026-06-18 -->\n<!-- placeholder: 槽 A -->\n"  # 吃了 B
    ok, err = server._pulse_validate(new, budget=20000, old_text=old)
    assert not ok
    assert "placeholder" in err.lower()
