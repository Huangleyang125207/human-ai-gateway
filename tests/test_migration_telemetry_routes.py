# TEST PATTERN: contract + effect — migration telemetry routes use injected state
# USE WHEN: changing telemetry consent/reset route composition

import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

import server
import telemetry


ROOT = Path(__file__).resolve().parent.parent


def test_migration_telemetry_module_does_not_import_server():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import migration_telemetry_routes; "
            "raise SystemExit(1 if 'server' in sys.modules else 0)",
        ],
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0


def test_telemetry_consent_route_uses_call_time_state(monkeypatch):
    state = {"failures": False, "heartbeat": False, "consented_at": None}

    monkeypatch.setattr(server, "_telemetry_consent", lambda: dict(state))

    def save(failures, heartbeat):
        state.update(
            failures=failures,
            heartbeat=heartbeat,
            consented_at="probe",
        )

    monkeypatch.setattr(server, "_telemetry_save", save)
    response = TestClient(server.app).post(
        "/api/telemetry/consent",
        json={"failures": True, "heartbeat": False},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "failures": True,
        "heartbeat": False,
        "consented_at": "probe",
    }


def test_telemetry_get_and_recent_routes_use_authoritative_state(
    monkeypatch,
    tmp_path,
):
    failures_log = tmp_path / "silent-failures.jsonl"
    failures_log.write_text(
        '{"error_type":"first"}\nnot-json\n{"error_type":"last"}\n',
        encoding="utf-8",
    )
    heartbeat_path = tmp_path / "heartbeat.last"
    heartbeat_path.write_text("2026-07-26", encoding="utf-8")
    monkeypatch.setattr(telemetry, "SILENT_FAILURES_LOG", failures_log)
    monkeypatch.setattr(telemetry, "_HB_LAST_SENT_PATH", heartbeat_path)
    monkeypatch.setattr(telemetry, "_CLIENT_ID_CACHE", "test-client")

    client = TestClient(server.app)
    consent = client.get("/api/telemetry/consent")
    recent = client.get("/api/silent-failures/recent?n=2")

    assert consent.status_code == 200
    assert consent.json()["client_id"] == "test-client"
    assert consent.json()["silent_failures_local"] == 3
    assert consent.json()["heartbeat_last_day"] == "2026-07-26"
    assert recent.status_code == 200
    assert recent.json() == {
        "items": [{"error_type": "last"}],
        "total": 3,
        "client_id": "test-client",
    }


def test_reset_client_id_updates_file_cache_and_heartbeat(
    monkeypatch,
    tmp_path,
):
    client_id_path = tmp_path / "client-id.txt"
    heartbeat_path = tmp_path / "heartbeat.txt"
    heartbeat_path.write_text("old", encoding="utf-8")
    monkeypatch.setattr(telemetry, "CLIENT_ID_PATH", client_id_path)
    monkeypatch.setattr(telemetry, "_HB_LAST_SENT_PATH", heartbeat_path)
    monkeypatch.setattr(telemetry, "_CLIENT_ID_CACHE", "old")

    response = TestClient(server.app).post(
        "/api/telemetry/reset-client-id"
    )

    assert response.status_code == 200
    new_id = response.json()["client_id"]
    assert client_id_path.read_text(encoding="utf-8") == new_id
    assert telemetry._CLIENT_ID_CACHE == new_id
    assert not heartbeat_path.exists()
