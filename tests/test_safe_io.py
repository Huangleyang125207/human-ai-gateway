# TEST PATTERN: boundary — atomic storage stays independent of the app root
# USE WHEN: changing atomic writes, backup rotation, or display-relative paths

from pathlib import Path

import safe_io
import server


def test_direct_safe_write_rotates_previous_bytes(tmp_path):
    target = tmp_path / "state.json"
    target.write_bytes(b'{"version": 1}')

    safe_io._safe_write_text(target, '{"version": 2}', rotate=True)

    assert target.read_bytes() == b'{"version": 2}'
    assert Path(f"{target}.bak.1").read_bytes() == b'{"version": 1}'


def test_server_adapter_keeps_rotate_patch_point(monkeypatch, tmp_path):
    target = tmp_path / "state.txt"
    calls = []
    monkeypatch.setattr(server, "_rotate_backup", lambda path: calls.append(path))

    server._safe_write_text(target, "new", rotate=True)

    assert calls == [target]
    assert target.read_text(encoding="utf-8") == "new"


def test_server_pretty_rel_uses_runtime_patch_points(monkeypatch, tmp_path):
    app_state = tmp_path / "app-state"
    monkeypatch.setattr(server, "APP_STATE_DIR", app_state)

    assert server._pretty_rel(app_state / "data" / "item.json") == (
        "data/item.json"
    )
