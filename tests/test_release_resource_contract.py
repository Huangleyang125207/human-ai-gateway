"""Release boundary contracts for frozen desktop resources."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _resource_paths(relative_path: str) -> set[str]:
    text = (ROOT / relative_path).read_text(encoding="utf-8")
    return {
        match.group(1)
        for match in re.finditer(r'--add-data\s+"([^":;]+)[:;][^"]*"', text)
    }


def test_all_frozen_resource_manifests_reference_existing_sources():
    manifests = (
        "build-sidecar.sh",
        "build-mac-pyinstaller.sh",
        ".github/workflows/build-win.yml",
    )

    for manifest in manifests:
        missing = sorted(
            path for path in _resource_paths(manifest) if not (ROOT / path).exists()
        )
        assert missing == [], f"{manifest} references missing resources: {missing}"


def test_windows_and_mac_freeze_the_same_runtime_resources():
    expected = _resource_paths("build-sidecar.sh")

    assert _resource_paths("build-mac-pyinstaller.sh") == expected
    assert _resource_paths(".github/workflows/build-win.yml") == expected


def test_local_installer_propagates_sidecar_pipeline_failures():
    script = (ROOT / "scripts" / "release-mac-local.sh").read_text(
        encoding="utf-8"
    )

    assert re.search(r"^set -[^\n]*o pipefail$", script, re.MULTILINE)


def test_release_tag_builds_both_platforms_and_runtime_inputs_trigger_windows():
    mac = (ROOT / ".github" / "workflows" / "build-mac.yml").read_text(
        encoding="utf-8"
    )
    windows = (ROOT / ".github" / "workflows" / "build-win.yml").read_text(
        encoding="utf-8"
    )

    assert "tags: ['v*']" in mac
    assert "tags: ['v*']" in windows
    for path_filter in (
        "prompts/**",
        "skills/**",
        "docs/ARCHITECTURE_LEDGER.md",
        "PRIVACY.md",
        "README.md",
        "LICENSE",
    ):
        assert f"- '{path_filter}'" in windows


def test_release_builds_gate_packaging_on_tests_and_generated_freshness():
    for workflow in ("build-mac.yml", "build-win.yml"):
        text = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        test_at = text.index("Test runtime + generated contract freshness")
        package_at = min(
            pos for marker in ("Build sidecar", "Tauri build")
            if (pos := text.find(marker)) >= 0
        )
        assert test_at < package_at
        assert "python -m pytest -q" in text
        assert "node --test" in text
        assert "pip install -r requirements-test.txt" in text

    test_requirements = (ROOT / "requirements-test.txt").read_text(encoding="utf-8")
    assert "pytest==" in test_requirements
    assert "pytest-asyncio==" in test_requirements


def test_generated_contract_fingerprints_are_committed_for_standalone_ci():
    for name in ("prompt-contract.sha256", "tool-contracts.sha256"):
        value = (ROOT / "docs" / "contracts" / name).read_text(encoding="utf-8").strip()
        assert re.fullmatch(r"[0-9a-f]{64}", value)
