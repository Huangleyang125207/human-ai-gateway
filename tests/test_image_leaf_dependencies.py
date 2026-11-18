# TEST PATTERN: boundary — image dispatcher leaves remain app-root independent
# USE WHEN: changing OCR/cutout dispatcher dependency injection

import subprocess
import sys
from pathlib import Path

from cutout import _get_or_create_processed_attachment
from ocr import _ocr_text


ROOT = Path(__file__).resolve().parent.parent


def test_image_leaf_modules_do_not_import_server():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import ocr, cutout; "
            "raise SystemExit(1 if 'server' in sys.modules else 0)",
        ],
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0


def test_cutout_dispatcher_uses_explicit_attachment_directory(tmp_path):
    bucket = tmp_path / "2026-08-19"
    bucket.mkdir()
    source = bucket / "photo.png"
    source.write_bytes(b"image")

    path, error = _get_or_create_processed_attachment(
        "/attachments/2026-08-19/photo.png",
        cutout=False,
        attachments_dir=tmp_path,
        load_config=lambda: {},
    )

    assert (path, error) == (source, None)


def test_cutout_dispatcher_rejects_attachment_traversal(tmp_path):
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"secret")
    path, error = _get_or_create_processed_attachment(
        "/attachments/../secret.png",
        cutout=False,
        attachments_dir=tmp_path / "attachments",
        load_config=lambda: {},
    )
    assert path is None
    assert "bad attachment_url" in error


def test_ocr_dispatcher_uses_explicit_config_loader(monkeypatch, tmp_path):
    config_reads = []

    monkeypatch.setattr(
        "ocr_local.ocr_local",
        lambda path: None,
    )

    result = _ocr_text(
        tmp_path / "photo.png",
        load_config=lambda: config_reads.append(True) or {},
    )

    assert result == ""
    assert config_reads == [True]
