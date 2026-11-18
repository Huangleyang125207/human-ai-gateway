from fastapi.testclient import TestClient

import server
import vault_config_routes


def test_vault_status_and_set_use_route_owner(
    monkeypatch,
    tmp_path,
):
    active = tmp_path / "active"
    target = tmp_path / "target"
    monkeypatch.setattr(server, "DATA_HOME", active)
    monkeypatch.setattr(
        vault_config_routes.vault_config,
        "list_known",
        lambda: [{"name": "probe", "path": str(active)}],
    )
    monkeypatch.setattr(
        vault_config_routes.vault_config,
        "setup_required",
        lambda: False,
    )
    monkeypatch.setattr(
        vault_config_routes.vault_config,
        "config_path",
        lambda: tmp_path / "config.json",
    )
    saved = []
    monkeypatch.setattr(
        vault_config_routes.vault_config,
        "set_active",
        lambda path, name: (
            saved.append((path, name))
            or {"active_vault": path}
        ),
    )

    client = TestClient(server.app)
    status = client.get("/api/vault")
    changed = client.post(
        "/api/vault/set",
        json={"path": str(target), "name": "target"},
    )

    assert status.status_code == 200
    assert status.json()["active_vault"] == str(active)
    assert changed.status_code == 200
    assert changed.json()["needs_restart"] is True
    assert saved == [(str(target), "target")]
    assert not (target / ".human-ai-write-test").exists()
