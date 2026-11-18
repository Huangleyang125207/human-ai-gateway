# TEST PATTERN: boundary — config storage takes narrow explicit dependencies
# USE WHEN: changing config paths, env precedence, recovery reporting, or client factory

import subprocess
import sys
from pathlib import Path

import config_store


def test_config_store_does_not_import_server():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import config_store; "
            "raise SystemExit(1 if 'server' in sys.modules else 0)",
        ],
        cwd=Path(__file__).resolve().parent.parent,
        check=False,
    )

    assert result.returncode == 0


def test_load_config_uses_explicit_path_and_overlay(tmp_path):
    config_path = tmp_path / "gateway-config.json"
    config_path.write_text('{"api_key": "json-key"}', encoding="utf-8")

    cfg = config_store.load_config(
        config_path=config_path,
        env_overlay=lambda: {"DEEPSEEK_API_KEY": "env-key"},
    )

    assert cfg["api_key"] == "env-key"


def test_corrupt_config_reports_successful_backup_recovery(tmp_path):
    config_path = tmp_path / "gateway-config.json"
    config_path.write_text("{broken", encoding="utf-8")
    Path(f"{config_path}.bak.1").write_text(
        '{"model": "recovered"}',
        encoding="utf-8",
    )
    reports = []

    cfg = config_store.load_config(
        config_path=config_path,
        env_overlay=lambda: {},
        reporter=lambda *args, **kwargs: reports.append((args, kwargs)),
    )

    assert cfg == {"model": "recovered"}
    assert reports[0][0][0] == "config_restored_from_bak1"


def test_get_client_uses_explicit_factory_and_profile_provider():
    calls = []

    def factory(**kwargs):
        calls.append(kwargs)
        return object()

    client = config_store.get_client(
        get_profile_fn=lambda: {
            "api_key": "sk-test",
            "base_url": "https://example.invalid/v1",
        },
        openai_factory=factory,
    )

    assert client is not None
    assert calls == [{
        "api_key": "sk-test",
        "base_url": "https://example.invalid/v1",
        "timeout": 120.0,
        "max_retries": 1,
    }]


def test_get_client_resolves_short_access_token_without_forwarding_device_credential():
    calls = []

    config_store.get_client(
        get_profile_fn=lambda: {
            "api_key": "gateway-device-token",
            "base_url": "https://staging-api.yanpaidb.cn/v1",
            "access_token_provider": lambda: "short-access",
        },
        openai_factory=lambda **kwargs: calls.append(kwargs) or object(),
    )

    assert calls[0]["base_url"] == "https://staging-api.yanpaidb.cn/v1"
    assert calls[0]["api_key"] == "short-access"
    assert "default_headers" not in calls[0]
