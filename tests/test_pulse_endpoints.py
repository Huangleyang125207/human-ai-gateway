# TEST PATTERN: contract + e2e — 7 个 PULSE endpoint golden shape + 端到端流转
# USE WHEN: 验 PULSE 路由层(/api/pulse/* + /api/pulse)的响应形状契约 + e2e
# TESTED IN: gateway PULSE refactor P0 TDD net (2026-06-18)
#
# 重构(引入 APIRouter)最容易漂的就是 endpoint 路径 / 响应字段。本测把现在的形状
# 固化:status_code、JSON 字段、缺/错时的 4xx 行为。重构后跑这一刀,任何漂移都会被抓。
#
# fixture 走 tests/conftest.py — 跨 P2-P4 refactor 鲁棒
#
# 7 endpoint:
#   GET  /api/pulse                       — dashboard,返 {projects: []}
#   GET  /api/pulse/{name}                — detail,返 {name, markdown}
#   POST /api/pulse/user-update           — _self_evolve_run("user_pulse")
#   POST /api/pulse/project-update        — _self_evolve_run("project_pulse")
#   POST /api/pulse/agent-context-update  — _self_evolve_run("agent_context")
#   POST /api/pulse/compact-summary       — 200 字摘要
#   POST /api/pulse/refresh-mirror        — vault PULSE → app-state mirror

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


# ── T1: dashboard GET /api/pulse ─────────────────────────────────────

def test_dashboard_empty_mirror_returns_empty(client, isolated_pulse_paths):
    """mirror 存在但空 → 返 projects=[],不报错"""
    r = client.get("/api/pulse")
    assert r.status_code == 200
    data = r.json()
    assert "projects" in data
    assert data["projects"] == []


def test_dashboard_missing_mirror_returns_warning(client, monkeypatch, tmp_path):
    """mirror 目录都不存在 → 返 projects=[]+warning"""
    monkeypatch.setattr(server, "PULSE_DIR", tmp_path / "nonexistent")
    r = client.get("/api/pulse")
    assert r.status_code == 200
    data = r.json()
    assert data["projects"] == []
    assert "warning" in data
    assert "not found" in data["warning"]


def test_dashboard_reads_pulse_md_with_full_sections(client, isolated_pulse_paths):
    """放一份完整 PULSE.md → 不只验 key 存在,验 _parse_pulse_md 真解析出值
    (fix_existing #5:assertion 太弱 — 加 tagline/status_emoji/heartbeat 等真值断言)
    """
    (isolated_pulse_paths.mirror / "myproject.md").write_text(
        "# 项目 myproject\n\n"
        "## 一句话\n这是个项目\n\n"
        "## 现在\n🟡 in progress · 半成品\n\n"
        "## 心跳\n- 第一条\n- 第二条\n- 第三条\n\n"
        "Last refreshed: 2026-06-18\n",
        encoding="utf-8")
    r = client.get("/api/pulse")
    assert r.status_code == 200
    projects = r.json()["projects"]
    assert len(projects) == 1
    p = projects[0]
    # _parse_pulse_md 必返这些 key
    for k in ("name", "tagline", "status_emoji", "now_line", "heartbeat", "last_refreshed"):
        assert k in p
    # 真值断言(fix_existing #5)
    assert p["name"] == "myproject"
    assert p["tagline"] == "这是个项目", \
        "_parse_pulse_md 必须从「一句话」section 抽出真值"
    assert p["now_line"] == "🟡 in progress · 半成品"
    assert p["status_emoji"] == "🟡"
    assert p["heartbeat"] == ["第一条", "第二条", "第三条"]
    assert p["last_refreshed"] == "2026-06-18"


def test_dashboard_heartbeat_capped_at_5(client, isolated_pulse_paths):
    """心跳上限 5 条"""
    hb_lines = "\n".join(f"- 第{i}条" for i in range(1, 9))
    (isolated_pulse_paths.mirror / "many.md").write_text(
        f"# 项目\n\n## 心跳\n{hb_lines}\n", encoding="utf-8")
    r = client.get("/api/pulse")
    p = r.json()["projects"][0]
    assert len(p["heartbeat"]) == 5, "心跳上限是 5 条,_parse_pulse_md 这条契约不能漂"


def test_dashboard_skips_INDEX_all_case(client, isolated_pulse_paths):
    """INDEX/index/Index 都跳(case-insensitive)"""
    (isolated_pulse_paths.mirror / "INDEX.md").write_text("# 索引", encoding="utf-8")
    (isolated_pulse_paths.mirror / "real.md").write_text("# 真\n", encoding="utf-8")
    r = client.get("/api/pulse")
    projects = r.json()["projects"]
    names = [p["name"] for p in projects]
    assert "real" in names
    assert not any(n.lower() == "index" for n in names)


# ── T1: detail GET /api/pulse/{name} ─────────────────────────────────

def test_detail_returns_markdown(client, isolated_pulse_paths):
    (isolated_pulse_paths.mirror / "foo.md").write_text("# 详情正文\n", encoding="utf-8")
    r = client.get("/api/pulse/foo")
    assert r.status_code == 200
    data = r.json()
    assert data == {"name": "foo", "markdown": "# 详情正文\n"}


def test_detail_404_for_missing(client, isolated_pulse_paths):
    r = client.get("/api/pulse/doesntexist")
    assert r.status_code == 404


@pytest.mark.parametrize("bad_name", [
    "..",                        # 纯 ..
    "..%2Fetc",                  # URL encoded /
    "..%2F..%2Fetc%2Fpasswd",    # 深度 traversal
    "INDEX", "Index", "index",   # case-insensitive index 块
    "foo%2Fbar",                 # 中间 /
    "foo%00",                    # null byte
])
def test_detail_rejects_bad_names(client, isolated_pulse_paths, bad_name):
    """fix_existing #4:path-traversal 加宽 + 显式断言 status(不是 in (400, 404))"""
    r = client.get(f"/api/pulse/{bad_name}")
    # 应被守门拦下 → 400 'bad name'(或 404 因 FastAPI 路由先解码)
    # 关键:绝不能 200(否则真路径触达 = path traversal 真发生)
    assert r.status_code in (400, 404), \
        f"name={bad_name!r} 必须被拦,实际 status={r.status_code}"
    # 真路径不能命中:若返了 markdown 字段,守门坏了
    if r.status_code == 200:
        pytest.fail(f"path traversal!{bad_name!r} 返了 200")


def test_detail_accepts_normal_names(client, isolated_pulse_paths):
    """合法 name(无 / 无 .. 非 index)→ 404(因文件不存在)而非 400"""
    for valid in ("foo", "foo-bar", "foo_bar"):
        r = client.get(f"/api/pulse/{valid}")
        assert r.status_code == 404, \
            f"name={valid!r} 应是 404(文件不存在),不是 400(name 守门)"


# ── T1+T2: POST /api/pulse/{user,project,agent-context}-update ────────

def test_user_update_missing_creates(stubbed_llm, isolated_pulse_paths, client):
    r = client.post("/api/pulse/user-update",
                    json={"conversation": "本轮对话原文"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data.get("skipped") is not True  # user_pulse create_if_absent
    assert data["target"] == "user_pulse"
    assert data["bootstrap"] is True
    assert isolated_pulse_paths.user.exists()


def test_project_update_missing_skips(stubbed_llm, isolated_pulse_paths, client):
    r = client.post("/api/pulse/project-update",
                    json={"conversation": "原文"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["skipped"] is True
    assert data["target"] == "project_pulse"
    assert not isolated_pulse_paths.project.exists()


def test_agent_context_update_missing_skips(stubbed_llm, isolated_pulse_paths, client):
    r = client.post("/api/pulse/agent-context-update",
                    json={"conversation": "原文"})
    assert r.status_code == 200
    data = r.json()
    assert data["skipped"] is True
    assert data["target"] == "agent_context"


def test_update_empty_conversation_rejects(client):
    """空 conversation → 400(三 endpoint 一致)"""
    for ep in ("user-update", "project-update", "agent-context-update"):
        r = client.post(f"/api/pulse/{ep}", json={"conversation": ""})
        assert r.status_code == 400, f"{ep} 空 conv 应 400"


# ── T1: POST /api/pulse/compact-summary ──────────────────────────────

def test_compact_summary_empty_short_circuits(client):
    """空 conversation → 不调 LLM,直接返 empty summary"""
    r = client.post("/api/pulse/compact-summary", json={"conversation": ""})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "summary": ""}


# ── T1: POST /api/pulse/refresh-mirror ───────────────────────────────

def test_refresh_mirror_returns_shape(client, isolated_pulse_paths, stubbed_llm):
    """返 scanned/updated/files 三字段"""
    r = client.post("/api/pulse/refresh-mirror")
    assert r.status_code == 200
    data = r.json()
    for k in ("scanned", "updated", "files"):
        assert k in data
    assert isinstance(data["files"], list)


# ── T6: e2e 全 PULSE 流转 ─────────────────────────────────────────────

def test_e2e_user_update_then_dashboard_then_detail(
        stubbed_llm, isolated_pulse_paths, client):
    """user_pulse 创建后,通过 mirror sync 到 dashboard 应可见(模拟全链路)"""
    # 1) POST user-update 创建 USER_PULSE
    r1 = client.post("/api/pulse/user-update",
                     json={"conversation": "对话"})
    assert r1.json()["ok"]
    assert isolated_pulse_paths.user.exists()
    # 2) 模拟 mirror(refresh-mirror 在沙盒里源候选可能空 — 拷贝直接模拟)
    (isolated_pulse_paths.mirror / "user.md").write_text(
        isolated_pulse_paths.user.read_text(encoding="utf-8"),
        encoding="utf-8")
    # 3) dashboard 看到
    r2 = client.get("/api/pulse")
    projects = r2.json()["projects"]
    assert any(p["name"] == "user" for p in projects)
    # 4) detail 拿到原文
    r3 = client.get("/api/pulse/user")
    assert r3.status_code == 200
    assert "ts:2026-06-18" in r3.json()["markdown"]
