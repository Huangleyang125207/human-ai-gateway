# TEST PATTERN: boundary — runtime paths are resolved without importing the app root
# USE WHEN: changing source/frozen resource roots or OS app-state conventions

import subprocess
import sys
from pathlib import Path

import runtime_paths


def test_runtime_paths_does_not_import_server():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import runtime_paths; "
            "raise SystemExit(1 if 'server' in sys.modules else 0)",
        ],
        cwd=Path(__file__).resolve().parent.parent,
        check=False,
    )

    assert result.returncode == 0


def test_app_state_env_override_expands_user(monkeypatch):
    monkeypatch.setenv("HUMAN_AI_STATE", "~/custom-human-ai-state")

    assert runtime_paths._default_app_state_dir() == (
        Path.home() / "custom-human-ai-state"
    )


def test_linux_app_state_uses_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.delenv("HUMAN_AI_STATE", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(runtime_paths.sys, "platform", "linux")

    assert runtime_paths._default_app_state_dir() == tmp_path / "HumanAI"


def test_macos_frozen_gateway_prefers_resources(monkeypatch, tmp_path):
    frameworks = tmp_path / "HumanAI.app" / "Contents" / "Frameworks"
    resources = frameworks.parent / "Resources"
    frameworks.mkdir(parents=True)
    resources.mkdir()
    monkeypatch.setattr(runtime_paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        runtime_paths.sys, "_MEIPASS", str(frameworks), raising=False
    )
    monkeypatch.setattr(runtime_paths.sys, "platform", "darwin")

    assert runtime_paths._resolve_gateway_dir() == resources.resolve()
