from pathlib import Path

from scripts import dedup_and_backfill_attachments as maintenance


def test_maintenance_rejects_unsafe_index_paths(tmp_path, monkeypatch):
    attachments = tmp_path / "attachments"
    attachments.mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"secret")
    monkeypatch.setattr(maintenance.server, "ATTACHMENTS_DIR", attachments)

    malicious = [
        {"date": "..", "filename": "secret.png", "url": "/attachments/../secret.png"},
        {"date": str(tmp_path), "filename": "secret.png", "url": "/attachments/absolute/secret.png"},
    ]
    maintenance.step1_hash_backfill(malicious, apply=False)
    assert all("hash" not in item for item in malicious)

    classified = []
    monkeypatch.setattr(
        maintenance.server,
        "_deepseek_classify_image",
        lambda path: classified.append(Path(path)) or {},
        raising=False,
    )
    maintenance.step3_vision_backfill(malicious, apply=True)
    assert classified == []
