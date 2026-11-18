from fastapi.testclient import TestClient

import server


def test_scrapbook_crud_uses_injected_storage(monkeypatch, tmp_path):
    scrapbook_dir = tmp_path / "scrapbook"
    monkeypatch.setattr(server, "SCRAPBOOK_DIR", scrapbook_dir)
    client = TestClient(server.app)

    created = client.post(
        "/api/scrapbook/upsert",
        json={"date": "2026-07-26", "src": "/attachments/probe.png"},
    )
    item_id = created.json()["item"]["id"]
    updated = client.post(
        "/api/scrapbook/upsert",
        json={
            "date": "2026-07-26",
            "id": item_id,
            "y_px": 42,
        },
    )
    loaded = client.get("/api/scrapbook?date=2026-07-26")
    deleted = client.post(
        "/api/scrapbook/delete",
        json={"date": "2026-07-26", "id": item_id},
    )

    assert created.status_code == 200
    assert updated.json()["item"]["auto_y"] is False
    assert loaded.json()["items"][0]["y_px"] == 42
    assert deleted.json() == {"ok": True, "removed": item_id}
    assert client.get(
        "/api/scrapbook?date=2026-07-26"
    ).json()["items"] == []
