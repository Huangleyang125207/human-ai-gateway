# TEST PATTERN: boundary — PC 端同步移动端 7.10 审计发现的 3 个同类漏洞守卫
# USE WHEN: 移动端修了 H3/M9/M10,PC oracle 侧同病未修,防回归 + 锁住修复
# 背景: 2026-07-10 移动端全量审计,5 个并行 agent 对照 PC 代码,确认 H3(widget XSS)/
#       M9(切日竞态)/M10(标签聚合并发丢写)在 PC 端同样存在。前端 JS 无独立测试套件,
#       沿用 test_port_url_discipline.py 的源码静态守卫范式;M10 后端用结构守卫锁"读在锁内"。
# TESTED IN: gateway (2026-07-10)
import inspect
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import server  # noqa: E402
from tag_aggregate_service import TagAggregateService  # noqa: E402


def test_tag_aggregate_module_does_not_import_server():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import tag_aggregate; "
            "raise SystemExit(1 if 'server' in sys.modules else 0)",
        ],
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0


# ── H3:动态 widget 裸 innerHTML XSS ────────────────────────────────
# 移动端修法:AI widget 模板进 innerHTML 前过 DOMPurify.sanitize。PC 的
# shared/widget-loader.js 是全站唯一绕过 gatewayMd/DOMPurify 的 XSS 面。
def test_h3_widget_loader_sanitizes_ai_html():
    src = (ROOT / "shared" / "widget-loader.js").read_text(encoding="utf-8")
    assert "DOMPurify.sanitize" in src, \
        "widget-loader 未见 DOMPurify.sanitize — AI add_widget 可注入 <img onerror> → XSS → 偷 API key"
    assert not re.search(r"\.innerHTML\s*=\s*html\s*;", src), \
        "仍存在裸 wrapper.innerHTML = html(未消毒的 AI HTML)"


# ── M9:切日竞态(慢响应盖当前日)────────────────────────────────────
# 两层前端都缺陈旧守卫:journal.js fetchJournal/render、ritual.js loadDay。
def test_m9_journal_guards_stale_day_response():
    src = (ROOT / "shared" / "journal.js").read_text(encoding="utf-8")
    assert re.search(r"data\.date\s*!==\s*currentDate|currentDate\s*!==\s*data\.date", src), \
        "journal.js 切日响应回填前无 currentDate 陈旧守卫 — 连点两天慢响应盖当前日"


def test_m9_ritual_guards_stale_day_response():
    src = (ROOT / "shared" / "ritual.js").read_text(encoding="utf-8")
    assert re.search(r"_viewDate\s*!==\s*dateISO|dateISO\s*!==\s*_viewDate", src), \
        "ritual.js loadDay await 回填前无 _viewDate 陈旧守卫 — 切日 tasks/water 被慢响应盖"


# ── M10:标签聚合并发丢写(register/refresh 无锁 RMW)────────────────
# 修法对齐同文件 _patch_block:read→compute→write 整段进 _get_vault_md_lock,
# 且 read 必须在锁内(锁外读=已丢锁的意义,后写仍覆盖先写)。
def _read_pos_after_lock(
    src,
    read_needle=".read_text",
    lock_needle="with _get_vault_md_lock",
):
    assert lock_needle in src, "未在锁内做 read-modify-write"
    lock_pos = src.index(lock_needle)
    read_pos = src.index(read_needle)
    return read_pos > lock_pos, lock_pos, read_pos


def test_m10_register_rmw_under_lock():
    src = inspect.getsource(TagAggregateService.register)
    inside, lp, rp = _read_pos_after_lock(
        src,
        lock_needle="with self.lock_factory",
    )
    assert inside, f"register 的 TAG_AGGREGATE 读在锁外(lock@{lp} read@{rp})— 并发丢标签"


def test_m10_refresh_rmw_under_lock():
    src = inspect.getsource(server._refresh_tag_aggregate)
    inside, lp, rp = _read_pos_after_lock(src)
    assert inside, f"refresh 的 TAG_AGGREGATE 读在锁外(lock@{lp} read@{rp})— 并发丢行"
