import json

from fastapi.testclient import TestClient

import server


def test_widget_catalog_and_toggle_use_injected_paths(
    monkeypatch,
    tmp_path,
):
    widgets_dir = tmp_path / "widgets"
    stable = widgets_dir / "stable-widget"
    stable.mkdir(parents=True)
    (stable / "manifest.json").write_text(
        json.dumps({
            "name": "stable-widget",
            "title": "Stable",
            "status": "stable",
        }),
        encoding="utf-8",
    )
    user_widgets = tmp_path / "user-widgets.json"
    monkeypatch.setattr(server, "WIDGETS_DIR", widgets_dir)
    monkeypatch.setattr(server, "USER_WIDGETS_PATH", user_widgets)

    client = TestClient(server.app)
    catalog = client.get("/api/widgets/catalog")
    toggled = client.post(
        "/api/widgets/toggle",
        json={"name": "stable-widget", "enable": True},
    )
    selected = client.get("/api/user-widgets")

    assert catalog.status_code == 200
    assert catalog.json()["widgets"][0]["active"] is False
    assert toggled.status_code == 200
    assert selected.json() == {"active": ["stable-widget"]}


def test_widget_toggle_rejects_wip(monkeypatch, tmp_path):
    widgets_dir = tmp_path / "widgets"
    wip = widgets_dir / "wip-widget"
    wip.mkdir(parents=True)
    (wip / "manifest.json").write_text(
        '{"name":"wip-widget","status":"wip"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "WIDGETS_DIR", widgets_dir)
    monkeypatch.setattr(
        server,
        "USER_WIDGETS_PATH",
        tmp_path / "user-widgets.json",
    )

    response = TestClient(server.app).post(
        "/api/widgets/toggle",
        json={"name": "wip-widget", "enable": True},
    )

    assert response.status_code == 403


def test_reference_variant_can_disable_default_without_deleting_data(
    monkeypatch,
    tmp_path,
):
    widgets_dir = tmp_path / "widgets"
    memo = widgets_dir / "memo-reference"
    memo.mkdir(parents=True)
    (memo / "manifest.json").write_text(
        '{"name":"memo-reference","status":"stable","default_loaded":false}',
        encoding="utf-8",
    )
    user_widgets = tmp_path / "user-widgets.json"
    monkeypatch.setattr(server, "WIDGETS_DIR", widgets_dir)
    monkeypatch.setattr(server, "USER_WIDGETS_PATH", user_widgets)
    client = TestClient(server.app)

    assert client.get("/api/widgets/catalog").json()["widgets"][0]["active"]
    client.post(
        "/api/widgets/toggle",
        json={"name": "memo-reference", "enable": False},
    )

    assert not client.get("/api/widgets/catalog").json()["widgets"][0]["active"]
    assert json.loads(user_widgets.read_text(encoding="utf-8")) == {
        "active": [],
        "disabled": ["memo-reference"],
    }
