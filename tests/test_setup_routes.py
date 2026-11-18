# TEST PATTERN: contract — DeepSeek BYOK setup and credential isolation
# USE WHEN: changing desktop AI connection/onboarding boundaries
# COPY THIS: change only the public setup fields and the expected profile shape
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


@pytest.fixture
def mem_config(monkeypatch):
    store = {"cfg": None, "env_synced": []}
    monkeypatch.setattr(server, "load_config", lambda: dict(store["cfg"]) if store["cfg"] else None)
    monkeypatch.setattr(server, "_save_config", lambda cfg: store.__setitem__("cfg", dict(cfg)))
    monkeypatch.setattr(server, "sync_env_secrets", lambda updates: store["env_synced"].append(dict(updates or {})))
    return store


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(server.app, base_url="http://127.0.0.1:4321", client=("127.0.0.1", 10000))


def test_setup_routes_module_does_not_import_server():
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import setup_routes; raise SystemExit(1 if 'server' in sys.modules else 0)"],
        cwd=Path(__file__).resolve().parent.parent,
        check=False,
    )
    assert result.returncode == 0


def test_cloud_only_settings_are_not_configured_and_reads_do_not_mutate(client, mem_config):
    legacy = {"gateway_url": "https://edge.example", "gateway_device_token": "old-fake-token"}
    mem_config["cfg"] = legacy.copy()
    assert client.get("/api/setup-status").json()["configured"] is False
    assert client.get("/api/config-status").json()["ok"] is False
    assert client.get("/api/models").json() == {"models": [], "default_id": None}
    assert server.get_profile() is None
    assert "old-fake-token" not in client.get("/api/setup/current").text
    assert mem_config["cfg"] == legacy
    assert mem_config["env_synced"] == []


def test_save_migrates_cloud_config_without_exposing_byok(client, mem_config):
    mem_config["cfg"] = {
        "gateway_url": "https://edge.example", "gateway_device_token": "old-fake-token",
        "another_setting": True,
    }
    key = "sk-fake-test-only"
    assert client.post("/api/setup/save", json={}).status_code == 400
    assert client.post("/api/setup/save", json={"api_key": key}).json()["ok"] is True
    assert mem_config["cfg"]["api_key"] == key
    assert mem_config["cfg"]["another_setting"] is True
    assert "gateway_url" not in mem_config["cfg"]
    assert "gateway_device_token" not in mem_config["cfg"]
    assert mem_config["env_synced"] == [{"api_key": key, "base_url": "https://api.deepseek.com/v1"}]
    assert client.get("/api/setup-status").json() == {"configured": True, "profile_count": 1}
    assert client.get("/api/config-status").json() == {
        "ok": True, "model": "deepseek-v4-flash-vision-exp", "provider": "https://api.deepseek.com/v1",
    }
    for path in ("/api/setup/current", "/api/setup/templates", "/api/models"):
        assert key not in client.get(path).text
    assert client.get("/api/setup/current").json()["has_deepseek_api_key"] is True


@pytest.mark.parametrize("payload", [
    {"api_key": "YOUR_DEEPSEEK_API_KEY"},
    {"api_key": "key\nheader"},
    {"api_key": "sk-fake-test-only", "base_url": "https://edge.example"},
    {"gateway_url": "https://edge.example", "gateway_device_token": "old-fake-token"},
    {"models": [{"api_key": "sk-fake-test-only"}]},
])
def test_setup_rejects_invalid_keys_and_legacy_transport_fields(client, mem_config, payload):
    assert client.post("/api/setup/save-partial", json=payload).status_code == 400
    assert mem_config["cfg"] is None


def test_optional_settings_and_empty_save_keep_existing_key(client, mem_config):
    mem_config["cfg"] = {"api_key": "sk-existing-test-key"}
    response = client.post("/api/setup/save-partial", json={"baidu_cutout_api_key": "fake-cutout"})
    assert response.json()["ok"] is True
    assert client.post("/api/setup/save", json={}).json()["ok"] is True
    assert mem_config["cfg"]["api_key"] == "sk-existing-test-key"
    assert mem_config["cfg"]["baidu_cutout_api_key"] == "fake-cutout"


def test_runtime_uses_direct_key_and_ignores_legacy_gateway(monkeypatch, mem_config):
    mem_config["cfg"] = {
        "api_key": "sk-explicit-test", "base_url": "https://unsafe.example/v1",
        "gateway_url": "https://edge.example", "gateway_device_token": "old-fake-token",
    }
    calls = []
    monkeypatch.setattr(server, "OpenAI", lambda **kwargs: calls.append(kwargs))
    assert server.get_profile() is None
    assert server.get_client() is None
    assert calls == []
    mem_config["cfg"]["base_url"] = "https://api.deepseek.com"
    server.get_client()
    assert calls[0]["api_key"] == "sk-explicit-test"
    assert calls[0]["base_url"] == "https://api.deepseek.com/v1"
    assert calls[0]["http_client"].follow_redirects is False
    calls[0]["http_client"].close()
    assert server.get_client({"api_key": "sk-explicit-test", "base_url": "https://api.deepseek.com.evil.example/v1"}) is None
    assert len(calls) == 1
    assert mem_config["env_synced"] == []


def test_runtime_accepts_only_official_legacy_profiles_and_never_exchanges_tokens(monkeypatch, mem_config):
    mem_config["cfg"] = {"models": [
        {"base_url": "https://unsafe.example", "api_key": "sk-wrong-source"},
        {"base_url": "https://api.deepseek.com", "api_key": "sk-correct-source"},
    ]}
    calls = []
    monkeypatch.setattr(server, "OpenAI", lambda **kwargs: calls.append(kwargs))

    def forbidden_exchange():
        pytest.fail("legacy token exchange must not run")

    server.get_client({
        **server.get_profile(), "access_token_provider": forbidden_exchange,
        "default_headers": {"Authorization": "Bearer should-not-override"},
    })
    assert calls[0]["api_key"] == "sk-correct-source"
    assert "default_headers" not in calls[0]
    calls[0]["http_client"].close()


def test_setup_requires_loopback_host_peer_and_same_origin(client, mem_config):
    from fastapi.testclient import TestClient
    payload = {"api_key": "sk-fake-test-only"}
    path = "/api/setup/save"
    assert client.post(path, json=payload, headers={"Origin": "https://unrelated.example"}).status_code == 403
    assert client.post(path, json=payload, headers={"Host": "unrelated.example"}).status_code == 403
    remote = TestClient(server.app, base_url="http://127.0.0.1:4321", client=("192.0.2.1", 10000))
    assert remote.post(path, json=payload).status_code == 403
    assert mem_config["cfg"] is None
    assert client.post(path, json=payload, headers={"Origin": "http://127.0.0.1:4321"}).status_code == 200


def test_transport_does_not_forward_to_custom_hosts_or_expose_provider_error_text():
    import httpx
    from config_store import DeepSeekTransport

    key = "sk-fake-echoed-test"
    calls = []

    def mock_provider(req):
        calls.append(req)
        return httpx.Response(401, json={"error": {"message": f"rejected {key}"}})

    with httpx.Client(transport=DeepSeekTransport(httpx.MockTransport(mock_provider))) as http_client:
        response = http_client.get("https://api.deepseek.com/v1/models", headers={"Authorization": f"Bearer {key}"})
        assert response.status_code == 401
        assert key not in response.text
        with pytest.raises(httpx.ConnectError):
            http_client.get("https://api.deepseek.com.evil.example", headers={"Authorization": f"Bearer {key}"})
    assert len(calls) == 1
