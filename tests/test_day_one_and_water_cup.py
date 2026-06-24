# TEST PATTERN: contract + boundary — 第N天 baseline + 水杯工具路由
# USE WHEN: 改 _get_day_one 解析优先级 / 删 water-cup workflow hint / 删 tool
# 背景:
#   - 5.3 hardcoded baseline 让新用户装机第 33 天(should be 第一天)→ 0.1.7 改成动态
#   - DeepSeek 看 set_water_cup_image 工具 spec 但不调,workflow hint 漏水杯路径
#     → 加 "用户消息含水杯关键字 → 直接调 set_water_cup_image" 提示
# TESTED IN: gateway (2026-06-04)

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import server  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════
# Part 1 · _get_day_one 解析优先级 (config > vault 最早 > 今天)
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture
def isolated_vault(tmp_path, monkeypatch):
    """每个测试独立 vault 目录,避免污染。"""
    jdir = tmp_path / "vault" / "半小时复盘"
    jdir.mkdir(parents=True)
    monkeypatch.setattr(server, "JOURNAL_DIR", jdir)
    monkeypatch.setattr(server, "load_config", lambda: {})
    return jdir


# ─── T1 · 空 vault → 当天 ───────────────────────────────────

def test_empty_vault_day_one_is_today(isolated_vault):
    d = server._get_day_one("2026-06-04")
    assert d.strftime("%Y-%m-%d") == "2026-06-04", (
        "新装机空 vault 时 day-one 必须 = 今天,这样第一次 new-day 是'第一天'"
    )


# ─── T2 · vault 有老 schedule → 用最早那天 ─────────────────

def test_vault_with_old_schedules_uses_earliest(isolated_vault):
    (isolated_vault / "26.5.3(第一天).md").touch()
    (isolated_vault / "26.5.4(第二天).md").touch()
    (isolated_vault / "26.6.4.md").touch()
    d = server._get_day_one("2026-06-04")
    assert d.strftime("%Y-%m-%d") == "2026-05-03", (
        "葱鸭 backward-compat 场景:vault 已有 5.3+ schedule,day-one 仍是 5.3"
    )


# ─── T3 · config explicit 覆盖 vault ────────────────────

def test_config_explicit_overrides_vault(isolated_vault, monkeypatch):
    (isolated_vault / "26.5.3(第一天).md").touch()  # vault 最早 5.3
    monkeypatch.setattr(server, "load_config",
                        lambda: {"vault_day_one": "2026-04-01"})
    d = server._get_day_one("2026-06-04")
    assert d.strftime("%Y-%m-%d") == "2026-04-01", (
        "config 显式指定优先级最高(给老用户迁移 vault 用)"
    )


# ─── T4 · config 格式错 → fallback 到 vault 最早 ────────

def test_config_bad_format_falls_back_to_vault(isolated_vault, monkeypatch):
    (isolated_vault / "26.5.3(第一天).md").touch()
    monkeypatch.setattr(server, "load_config",
                        lambda: {"vault_day_one": "not-a-date"})
    d = server._get_day_one("2026-06-04")
    assert d.strftime("%Y-%m-%d") == "2026-05-03", (
        "config 字段格式坏不能整个崩,降级到 vault 扫"
    )


# ─── T5 · 空 vault + 空 config → 当天兜底 ────────────────

def test_empty_vault_empty_config_falls_back_to_today(isolated_vault, monkeypatch):
    monkeypatch.setattr(server, "load_config", lambda: {})
    d = server._get_day_one("2026-07-15")
    assert d.strftime("%Y-%m-%d") == "2026-07-15"


# ─── T6 · _new_day_create 端到端:文件名带正确 '第N天' ────

def test_new_day_filename_uses_dynamic_day_one(isolated_vault):
    """空 vault 装机当天创建 → 文件名应含 '第一天',不是 '第33天'。"""
    result = server._new_day_create("2026-06-04")
    assert result.get("ok"), result
    file_path = result.get("file", "")
    assert "第一天" in file_path, f"应是第一天,实际: {file_path}"


def test_new_day_filename_with_existing_vault(isolated_vault):
    """vault 已有 5.3 → 6.4 应是 第33天(葱鸭 backward-compat)。"""
    (isolated_vault / "26.5.3(第一天).md").touch()
    result = server._new_day_create("2026-06-04")
    assert result.get("ok"), result
    # 第 33 天没在 _DAY_CN 表(只到 30),会用阿拉伯数字 "33"
    file_path = result.get("file", "")
    assert "33" in file_path or "三十三" in file_path, (
        f"5.3 起算 6.4 应是第 33 天,实际: {file_path}"
    )


# ═══════════════════════════════════════════════════════════════════════
# Part 2 · 水杯工具路由 — schema + workflow hint
# ═══════════════════════════════════════════════════════════════════════

# ─── T7 · 工具注册:set_water_cup_image 在 images group + dispatcher ────

def test_set_water_cup_image_registered_in_images_group():
    """删工具会触发本测 — 防 marketplace 改 group 时手滑漏掉。"""
    assert "set_water_cup_image" in server.TOOL_GROUPS["images"]


def test_set_water_cup_image_dispatcher_wired():
    """tool name → impl 函数映射必须挂上,不然 model 调了 server 返 unknown tool。"""
    assert "set_water_cup_image" in server.TOOL_IMPL
    assert callable(server.TOOL_IMPL["set_water_cup_image"])


# ─── T8 · 工具 schema 完整(attachment_url 必填字段) ──────

def test_set_water_cup_image_tool_schema_minimum():
    """OpenAI tool spec 必含 name + description + parameters.required[attachment_url]"""
    src = (ROOT / "server.py").read_text()
    # 抓 set_water_cup_image 这个 function spec 的 properties 段
    m = re.search(
        r'"name":\s*"set_water_cup_image".*?"required":\s*\[(.*?)\]',
        src, re.DOTALL,
    )
    assert m, "找不到 set_water_cup_image tool spec"
    required = m.group(1)
    assert "attachment_url" in required, (
        "set_water_cup_image 必须强制 attachment_url 参数,不然 model 漏传会炸"
    )


# ─── T9 · workflow hint 含水杯路径(回归锁今天加的硬约束) ───

def test_workflow_hint_includes_water_cup_path():
    """vision-pre-router workflow hint 字符串必含水杯引导,不然 DeepSeek 又调不动。
    今天 user dogfood 报"DeepSeek 不调 set_water_cup_image" 的根治。
    """
    # workflow hint 6.24 随 chat() 抽到 chat_routes.py;源码级断言读两处合并
    src = (ROOT / "server.py").read_text() + (ROOT / "chat_routes.py").read_text()
    # 关键字三连击:'水杯' + 'set_water_cup_image' + 触发词列表
    assert "水杯" in src, "源码必有'水杯'字 — 它在 workflow hint 里"
    assert "set_water_cup_image" in src
    # workflow hint 那段应该提到至少一个触发词('我的水杯' / '这是我的水杯' / '打卡水杯')
    hint_section = re.search(
        r'WORKFLOW.*?set_water_cup_image.*?supplement',
        src, re.DOTALL,
    )
    assert hint_section, "workflow hint 段没包含 set_water_cup_image 引导 — DeepSeek 会再次不调"
    hint_text = hint_section.group(0)
    triggers = ["水杯", "我的杯", "这是我的水杯", "打卡水杯"]
    matched = [t for t in triggers if t in hint_text]
    assert matched, (
        f"workflow hint 必须至少含一个水杯触发关键字让 model 锚定路径,实际未含:{triggers}"
    )
