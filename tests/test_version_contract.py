"""Keep every PC release surface on the same product version."""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pc_version_sources_and_legacy_builder_stay_in_sync():
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    tauri = json.loads(
        (ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )
    builder = (ROOT / "build-mac-app.sh").read_text(encoding="utf-8")
    server_version = re.search(
        r'^APP_VERSION\s*=\s*"([^"]+)"', server, re.MULTILINE
    ).group(1)

    assert server_version == tauri["version"]
    assert "APP_VERSION=" in builder
    assert "<string>${APP_VERSION}</string>" in builder
