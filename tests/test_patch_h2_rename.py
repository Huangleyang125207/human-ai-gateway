# TEST PATTERN: boundary — patch_journal_block H2 rename gate
# USE WHEN: 改 _patch_block H2 比对 / allow_h2_rename 默认值
# 背景:
#   5.29 16:00 "AI 误用 patch 当 insert" 把联想 entry 吃掉 → 加 H2 严格匹配
#   6.4 22:00 user dogfood:"AI 改 17:00 标题"被这条 guard 卡到崩溃 →
#   加 allow_h2_rename 旁路,默认 false 保 5.29 防御,user 明示 rename 时 true
# TESTED IN: gateway (2026-06-04)

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import server  # noqa: E402


@pytest.fixture
def existing_journal(tmp_path):
    """模拟一个 schedule md,17:00 块有 entry,可被 patch / rename 测试。"""
    f = tmp_path / "26.6.4(测试).md"
    f.write_text(
        "# 16：30\n\n##\n\n---\n\n"
        "# 17：00\n\n"
        "## #探索 小红书 AI 产业链预警 @ai\n\n"
        "把昨天讨论的 capex 消费齿轮论降维发上去了。\n\n"
        "---\n\n"
        "# 17：30\n\n##\n",
        encoding="utf-8"
    )
    return f


# ─── T1 · 默认 H2 异 → 拒(保 5.29 防御) ───────────────────

def test_patch_rejects_h2_mismatch_by_default(existing_journal):
    """同 #探索 tag 但 title 异(AI 产业链预警 → 牛奶 Omega-3 科普)→
    默认 allow_h2_rename=false 应拒,防 AI 误用 patch 把原 entry 吃掉。
    """
    result = server._patch_block(
        existing_journal, "17:00",
        "## #探索 小红书牛奶 Omega-3 科普 @ai\n\n实际发的是悦鲜活牛奶的冷知识。",
        author="ai",
    )
    assert "error" in result, "默认必须拒 H2 异,这是 5.29 防御"
    assert "已有 H2" in result["error"]


# ─── T2 · allow_h2_rename=True → 允许 + 真改了文件 ──────

def test_patch_allows_h2_rename_with_flag(existing_journal):
    """user 明示改标题 → AI 传 allow_h2_rename=true → patch 直接 rename,
    新 H2 + 新 body 写入,原 entry 替换。
    """
    new_md = (
        "## #探索 小红书牛奶 Omega-3 科普 @ai\n\n"
        "把悦鲜活牛奶 ALA 转化率 9-27mg 的冷知识发上去了。"
    )
    result = server._patch_block(
        existing_journal, "17:00", new_md, author="ai",
        allow_h2_rename=True,
    )
    assert "error" not in result, f"allow_h2_rename=true 应该让改名通过: {result}"
    text = existing_journal.read_text(encoding="utf-8")
    assert "## #探索 小红书牛奶 Omega-3 科普 @ai" in text
    assert "## #探索 小红书 AI 产业链预警 @ai" not in text, "原 H2 应该被替换"
    assert "悦鲜活" in text


# ─── T3 · 同 H2 patch(典型补散文措辞)— 无 flag 也通过 ──

def test_patch_same_h2_passes_without_flag(existing_journal):
    """同 H2 标题 + 改 body(典型用例) — 不需要 allow_h2_rename。"""
    new_md = (
        "## #探索 小红书 AI 产业链预警 @ai\n\n"
        "改了散文措辞,标题不变。"
    )
    result = server._patch_block(
        existing_journal, "17:00", new_md, author="ai",
    )
    assert "error" not in result, f"同 H2 patch 应该直接通过: {result}"
    text = existing_journal.read_text(encoding="utf-8")
    assert "改了散文措辞" in text


# ─── T4 · tool spec 含 allow_h2_rename 字段 + use case 说明 ────

def test_tool_spec_documents_allow_h2_rename():
    """schema 必须告诉 model 这个 flag 的存在 + use case,不然 model 永远不传。"""
    import re as _re
    src = (ROOT / "server.py").read_text()
    m = _re.search(
        r'"name":\s*"patch_journal_block".*?"properties":\s*\{(.*?)\}\s*,\s*\}\s*,\s*\}',
        src, _re.DOTALL,
    )
    assert m, "找不到 patch_journal_block tool spec"
    props = m.group(1)
    assert "allow_h2_rename" in props, "schema 必含 allow_h2_rename 字段"
    # description 必须含 use case (用户明示 / rename)
    assert "rename" in props.lower() or "改标题" in props or "改 H2" in props
