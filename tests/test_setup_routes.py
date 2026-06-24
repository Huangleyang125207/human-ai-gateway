# TEST PATTERN: characterization — setup / config endpoints golden behavior
# USE WHEN: 锁 /api/setup* + /api/models 现行行为,守 setup_routes 抽出(§ 9 refactor)
# TESTED IN: gateway setup_routes extraction (2026-06-19), § T7 characterization
#
# § T7 GREEN-LOCK:这些测试在 monolith server.py 上先 GREEN,setup_routes.py 抽出后
# STAY GREEN。任何 RED = 行为漂移 = revert。
#
# 10 endpoint:
#   GET  /api/setup-status        — configured 三态判定
#   GET  /api/setup/templates     — deepseek/bailian/templates 结构
#   POST /api/setup/test          — 测 LLM profile(mock client)
#   POST /api/setup/test-baidu    — 测百度 key(mock token)
#   GET  /api/setup/current       — 返 config 字段 shape
#   POST /api/setup/save-partial  — 部分更新 + 空值删字段
#   POST /api/setup/save-gemini   — 存 gemini key
#   POST /api/setup/test-gemini   — 测 gemini(mock requests)
#   POST /api/setup/save          — 完整保存 + id 自动生成 + 占位符拒
#   GET  /api/models              — profiles + default_id

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


# ── 最简 LLM fake(setup/test 只取 choices[0].message.content[:80])──
class _FakeChat:
    def __init__(self, reply="pong"):
        self.completions = self
        self._reply = reply

    def create(self, **kw):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._reply))])


class _FakeClient:
    def __init__(self, reply="pong"):
        self.chat = _FakeChat(reply)


@pytest.fixture
def mem_config(monkeypatch):
    """in-memory config:load_config / _save_config / list_model_profiles 全走内存 dict。
    handler 内 lazy `from server import load_config` → patch server.* 命中(G1 表第3行)。"""
    store = {"cfg": None}

    monkeypatch.setattr(server, "load_config",
                        lambda: dict(store["cfg"]) if store["cfg"] else None)

    def _save(cfg):
        store["cfg"] = dict(cfg)
    monkeypatch.setattr(server, "_save_config", _save)
    return store


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(server.app)


# ── GET /api/setup-status — 三态 ─────────────────────────────────────

def test_status_no_config(client, mem_config):
    mem_config["cfg"] = None
    r = client.get("/api/setup-status")
    assert r.status_code == 200
    d = r.json()
    assert d["configured"] is False
    assert "config" in d["reason"]


def test_status_all_placeholder(client, mem_config):
    mem_config["cfg"] = {"models": [{"id": "x", "api_key": "YOUR_KEY", "model": "m"}]}
    r = client.get("/api/setup-status")
    d = r.json()
    assert d["configured"] is False
    assert "占位符" in d["reason"]


def test_status_configured(client, mem_config):
    mem_config["cfg"] = {"models": [
        {"id": "x", "api_key": "sk-real", "model": "m"},
        {"id": "y", "api_key": "YOUR_K", "model": "m2"},
    ]}
    r = client.get("/api/setup-status")
    d = r.json()
    assert d["configured"] is True
    assert d["profile_count"] == 2


# ── GET /api/setup/templates — 结构契约 ──────────────────────────────

def test_templates_shape(client):
    r = client.get("/api/setup/templates")
    assert r.status_code == 200
    d = r.json()
    assert "deepseek" in d and "bailian" in d
    assert "base_url" in d["deepseek"] and "models" in d["deepseek"]
    assert isinstance(d["templates"], list)
    # templates 由 DEEPSEEK_MODELS 派生,每条带 base_url + model
    if d["templates"]:
        assert "base_url" in d["templates"][0] and "model" in d["templates"][0]


# ── POST /api/setup/test — LLM profile 测通 ──────────────────────────

def test_setup_test_happy(client, monkeypatch):
    monkeypatch.setattr(server, "get_client", lambda p: _FakeClient("pong-reply"))
    r = client.post("/api/setup/test", json={
        "api_key": "sk-real", "model": "deepseek-chat", "base_url": "https://x"})
    d = r.json()
    assert d["ok"] is True
    assert d["reply"] == "pong-reply"
    assert d["model"] == "deepseek-chat"


def test_setup_test_placeholder_key_rejected(client):
    r = client.post("/api/setup/test", json={
        "api_key": "YOUR_KEY", "model": "m", "base_url": "https://x"})
    d = r.json()
    assert d["ok"] is False
    assert "占位符" in d["reason"]


def test_setup_test_missing_model_rejected(client):
    r = client.post("/api/setup/test", json={"api_key": "sk-real", "base_url": "https://x"})
    d = r.json()
    assert d["ok"] is False


# ── POST /api/setup/test-baidu ───────────────────────────────────────

def test_test_baidu_happy(client, monkeypatch):
    import ocr
    monkeypatch.setattr(ocr, "_get_access_token", lambda a, s: "tok-123")
    r = client.post("/api/setup/test-baidu", json={"api_key": "a", "secret_key": "b"})
    assert r.json()["ok"] is True


def test_test_baidu_no_token(client, monkeypatch):
    import ocr
    monkeypatch.setattr(ocr, "_get_access_token", lambda a, s: None)
    r = client.post("/api/setup/test-baidu", json={"api_key": "a", "secret_key": "b"})
    assert r.json()["ok"] is False


# ── GET /api/setup/current — shape ───────────────────────────────────

def test_current_shape(client, mem_config):
    mem_config["cfg"] = {"models": [{"id": "x"}], "default_model_id": "x",
                         "dashscope_api_key": "dk"}
    r = client.get("/api/setup/current")
    d = r.json()
    for k in ("models", "default_model_id", "dashscope_api_key", "dashscope_base_url",
              "dashscope_vision_model", "baidu_cutout_api_key", "baidu_cutout_secret_key"):
        assert k in d
    assert d["default_model_id"] == "x"
    assert d["dashscope_api_key"] == "dk"


# ── POST /api/setup/save-partial — 删字段 ────────────────────────────

def test_save_partial_updates_and_clears(client, mem_config):
    mem_config["cfg"] = {"models": [], "dashscope_api_key": "old"}
    # 设 models + 清空 dashscope_api_key("" → pop)
    r = client.post("/api/setup/save-partial", json={
        "models": [{"id": "n"}], "dashscope_api_key": ""})
    assert r.json()["ok"] is True
    saved = mem_config["cfg"]
    assert saved["models"] == [{"id": "n"}]
    assert "dashscope_api_key" not in saved  # 空值被 pop


# ── POST /api/setup/save-gemini ──────────────────────────────────────

def test_save_gemini_happy(client, mem_config):
    mem_config["cfg"] = {}
    r = client.post("/api/setup/save-gemini", json={"api_key": "g-real"})
    assert r.json()["ok"] is True
    assert mem_config["cfg"]["gemini_api_key"] == "g-real"


def test_save_gemini_placeholder_400(client, mem_config):
    mem_config["cfg"] = {}
    r = client.post("/api/setup/save-gemini", json={"api_key": "YOUR_K"})
    assert r.status_code == 400


# ── POST /api/setup/test-gemini ──────────────────────────────────────

def test_test_gemini_happy(client, monkeypatch):
    monkeypatch.setattr(server.requests, "post",
                        lambda *a, **k: SimpleNamespace(status_code=200, text="pong"))
    r = client.post("/api/setup/test-gemini", json={"api_key": "g-real"})
    assert r.json()["ok"] is True


def test_test_gemini_http_error(client, monkeypatch):
    monkeypatch.setattr(server.requests, "post",
                        lambda *a, **k: SimpleNamespace(status_code=403, text="forbidden"))
    r = client.post("/api/setup/test-gemini", json={"api_key": "g-real"})
    assert r.json()["ok"] is False


# ── POST /api/setup/save — 核心:id 生成 + 占位符拒 + cfg 结构 ────────

def test_save_rejects_empty_profiles(client, mem_config):
    r = client.post("/api/setup/save", json={"models": []})
    assert r.status_code == 400


def test_save_rejects_all_placeholder(client, mem_config):
    r = client.post("/api/setup/save", json={
        "models": [{"id": "x", "api_key": "YOUR_K", "model": "m"}]})
    assert r.status_code == 400


def test_save_autogenerates_id_and_builds_cfg(client, mem_config):
    r = client.post("/api/setup/save", json={
        "models": [{"label": "DeepSeek Chat", "api_key": "sk-real",
                    "model": "deepseek-chat", "base_url": "https://api.deepseek.com"}]})
    assert r.json()["ok"] is True
    cfg = mem_config["cfg"]
    # id 从 label 自动生成
    assert cfg["models"][0]["id"] == "deepseek-chat"
    # default = 第一个 profile id
    assert cfg["default_model_id"] == "deepseek-chat"
    # 顶层 chat key/url/model 取 default profile
    assert cfg["api_key"] == "sk-real"
    assert cfg["base_url"] == "https://api.deepseek.com"
    assert cfg["model"] == "deepseek-chat"


def test_save_dashscope_and_baidu_passthrough(client, mem_config):
    r = client.post("/api/setup/save", json={
        "models": [{"id": "m1", "api_key": "sk-real", "model": "m"}],
        "dashscope_api_key": "dk-real",
        "baidu_cutout_api_key": "bd-real", "baidu_cutout_secret_key": "bs-real"})
    assert r.json()["ok"] is True
    cfg = mem_config["cfg"]
    assert cfg["dashscope_api_key"] == "dk-real"
    assert cfg["baidu_cutout_api_key"] == "bd-real"


def test_save_skips_placeholder_dashscope(client, mem_config):
    r = client.post("/api/setup/save", json={
        "models": [{"id": "m1", "api_key": "sk-real", "model": "m"}],
        "dashscope_api_key": "YOUR_DASH"})
    assert r.json()["ok"] is True
    assert "dashscope_api_key" not in mem_config["cfg"]


# ── GET /api/models ──────────────────────────────────────────────────

def test_models_default_id(client, mem_config):
    mem_config["cfg"] = {
        "models": [{"id": "a", "api_key": "sk-1", "model": "m1", "base_url": "u"},
                   {"id": "b", "api_key": "sk-2", "model": "m2", "base_url": "u"}],
        "default_model_id": "b"}
    r = client.get("/api/models")
    d = r.json()
    assert d["default_id"] == "b"
    assert len(d["models"]) == 2
