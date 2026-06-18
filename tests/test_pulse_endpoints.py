# TEST PATTERN: contract + e2e — 7 个 PULSE endpoint golden shape + 端到端流转
# USE WHEN: 验 PULSE 路由层(/api/pulse/* + /api/pulse)的响应形状契约 + e2e
# TESTED IN: gateway PULSE refactor P0 TDD net (2026-06-18)
#
# 重构(引入 APIRouter)最容易漂的就是 endpoint 路径 / 响应字段。本测把现在的形状
# 固化:status_code、JSON 字段、缺/错时的 4xx 行为。重构后跑这一刀,任何漂移都会被抓。
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
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


# ── fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(server.app)


class _FakeLLMResp:
    def __init__(self, text):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=text))]


class _FakeChat:
    def __init__(self, text):
        self._text = text
        self.completions = self
    def create(self, **_kw):
        return _FakeLLMResp(self._text)


class _FakeClient:
    def __init__(self, text):
        self.chat = _FakeChat(text)


@pytest.fixture
def stubbed_llm(monkeypatch):
    """所有 endpoint 后面的 LLM 调用都假掉,返合规 PULSE。"""
    valid_pulse = (
        "<!-- ts:2026-06-18 -->\n# 一句话\n协作日记\n## Cannot break\n- ts 在\n"
    )
    monkeypatch.setattr(server, "get_profile",
                        lambda *a, **k: {"model": "fake"})
    monkeypatch.setattr(server, "get_client",
                        lambda profile: _FakeClient(valid_pulse))
    monkeypatch.setattr(server.vault_git, "commit_after_write",
                        lambda *a, **k: None)
    monkeypatch.setattr(server, "_push_notification",
                        lambda *a, **k: None)
    return valid_pulse


@pytest.fixture
def isolated_paths(monkeypatch, tmp_path):
    """所有 PULSE 真源路径 + PULSE_DIR mirror 路径都隔离到 tmp"""
    user_p = tmp_path / "USER_PULSE.md"
    proj_p = tmp_path / "PROJECT_PULSE.md"
    agent_p = tmp_path / "AGENT_CONTEXT.md"
    mirror_dir = tmp_path / "pulse-mirror"
    mirror_dir.mkdir()
    monkeypatch.setattr(server, "_USER_PULSE_PATH", user_p)
    monkeypatch.setattr(server, "_PROJECT_PULSE_PATH", proj_p)
    monkeypatch.setattr(server, "_AGENT_CONTEXT_PATH", agent_p)
    monkeypatch.setattr(server, "PULSE_DIR", mirror_dir)
    return user_p, proj_p, agent_p, mirror_dir


# ── T1: dashboard GET /api/pulse ─────────────────────────────────────

def test_dashboard_empty_mirror_returns_warning(client, isolated_paths):
    _, _, _, mirror_dir = isolated_paths
    # mirror 存在但空 → 返 projects=[],不报错
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


def test_dashboard_reads_pulse_md(client, isolated_paths):
    """放一份 PULSE.md 到 mirror → dashboard 解析返"""
    _, _, _, mirror_dir = isolated_paths
    (mirror_dir / "myproject.md").write_text(
        "# 项目\n\n## 一句话\n这是个项目\n\nLast refreshed: 2026-06-18\n",
        encoding="utf-8")
    r = client.get("/api/pulse")
    assert r.status_code == 200
    projects = r.json()["projects"]
    assert len(projects) == 1
    p = projects[0]
    # _parse_pulse_md 必返这些 key
    for k in ("name", "tagline", "status_emoji", "now_line", "heartbeat", "last_refreshed"):
        assert k in p
    assert p["name"] == "myproject"
    assert p["last_refreshed"] == "2026-06-18"


def test_dashboard_skips_INDEX(client, isolated_paths):
    """INDEX.md 不算项目,被跳"""
    _, _, _, mirror_dir = isolated_paths
    (mirror_dir / "INDEX.md").write_text("# 索引", encoding="utf-8")
    (mirror_dir / "real.md").write_text("# 真\n", encoding="utf-8")
    r = client.get("/api/pulse")
    projects = r.json()["projects"]
    names = [p["name"] for p in projects]
    assert "real" in names
    assert "INDEX" not in names and "index" not in names


# ── T1: detail GET /api/pulse/{name} ─────────────────────────────────

def test_detail_returns_markdown(client, isolated_paths):
    _, _, _, mirror_dir = isolated_paths
    (mirror_dir / "foo.md").write_text("# 详情正文\n", encoding="utf-8")
    r = client.get("/api/pulse/foo")
    assert r.status_code == 200
    data = r.json()
    assert data == {"name": "foo", "markdown": "# 详情正文\n"}


def test_detail_404_for_missing(client, isolated_paths):
    r = client.get("/api/pulse/doesntexist")
    assert r.status_code == 404


def test_detail_rejects_path_traversal(client, isolated_paths):
    """守门:name 含 / 或 .. 拒"""
    assert client.get("/api/pulse/..%2Fetc").status_code in (400, 404)
    assert client.get("/api/pulse/INDEX").status_code == 400
    assert client.get("/api/pulse/index").status_code == 400


# ── T1+T2: POST /api/pulse/{user,project,agent-context}-update ────────

def test_user_update_missing_creates(stubbed_llm, isolated_paths, client):
    user_p, _, _, _ = isolated_paths
    r = client.post("/api/pulse/user-update",
                    json={"conversation": "本轮对话原文"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data.get("skipped") is not True  # user_pulse create_if_absent
    assert data["target"] == "user_pulse"
    assert data["bootstrap"] is True
    assert user_p.exists()


def test_project_update_missing_skips(stubbed_llm, isolated_paths, client):
    _, proj_p, _, _ = isolated_paths
    r = client.post("/api/pulse/project-update",
                    json={"conversation": "原文"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["skipped"] is True
    assert data["target"] == "project_pulse"
    assert not proj_p.exists()


def test_agent_context_update_missing_skips(stubbed_llm, isolated_paths, client):
    _, _, agent_p, _ = isolated_paths
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

def test_refresh_mirror_returns_shape(client, isolated_paths, monkeypatch):
    """无源时返 scanned/updated/files 三字段(空数组)"""
    # mock vault_git.commit_after_write 避免真 git
    monkeypatch.setattr(server.vault_git, "commit_after_write",
                        lambda *a, **k: None)
    r = client.post("/api/pulse/refresh-mirror")
    assert r.status_code == 200
    data = r.json()
    for k in ("scanned", "updated", "files"):
        assert k in data
    assert isinstance(data["files"], list)


# ── T6: e2e 全 PULSE 流转 ─────────────────────────────────────────────

def test_e2e_user_update_then_dashboard_then_detail(
        stubbed_llm, isolated_paths, client):
    """user_pulse 创建后,通过 mirror sync 到 dashboard 应可见(模拟全链路)"""
    user_p, _, _, mirror_dir = isolated_paths
    # 1) POST user-update 创建 USER_PULSE
    r1 = client.post("/api/pulse/user-update",
                     json={"conversation": "对话"})
    assert r1.json()["ok"]
    assert user_p.exists()
    # 2) 手动模拟 mirror(refresh-mirror 在沙盒里源候选可能空 — 直接拷贝模拟它的效果)
    (mirror_dir / "user.md").write_text(user_p.read_text(encoding="utf-8"),
                                        encoding="utf-8")
    # 3) dashboard 看到
    r2 = client.get("/api/pulse")
    projects = r2.json()["projects"]
    assert any(p["name"] == "user" for p in projects)
    # 4) detail 拿到原文
    r3 = client.get("/api/pulse/user")
    assert r3.status_code == 200
    assert "ts:2026-06-18" in r3.json()["markdown"]
