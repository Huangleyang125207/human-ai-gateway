# TEST PATTERN: boundary — day creation remains app-root independent
# USE WHEN: changing day-one or new-day dependency injection

import subprocess
import sys
from pathlib import Path

from day_create import _get_day_one, _new_day_create


ROOT = Path(__file__).resolve().parent.parent


def test_day_create_module_does_not_import_server():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import day_create; "
            "raise SystemExit(1 if 'server' in sys.modules else 0)",
        ],
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0


def test_new_day_uses_explicit_paths_and_day_one(tmp_path):
    journal_dir = tmp_path / "vault" / "半小时复盘"
    vault_dir = tmp_path / "vault"

    result = _new_day_create(
        "2026-07-26",
        get_day_one=lambda date: _get_day_one(
            date,
            load_config=lambda: {},
            list_journal_files=lambda: [],
        ),
        journal_dir=journal_dir,
        vault_dir=vault_dir,
        pretty_rel=lambda path: path.name,
    )

    assert result["created"] is True
    assert result["file"] == "26.7.26(第一天).md"
    assert (journal_dir / result["file"]).exists()
