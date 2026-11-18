# TEST PATTERN: boundary — small leaf modules remain app-root independent
# USE WHEN: changing scrapbook or summary effect injection

import subprocess
import sys
from pathlib import Path

from compact_summary import compact_summary_run
from safe_io import _safe_write_text
from scrapbook import (
    _load_scrapbook,
    _save_scrapbook,
    _scrapbook_path,
)


ROOT = Path(__file__).resolve().parent.parent


def test_small_leaf_modules_do_not_import_server():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import history_summary, scrapbook, compact_summary; "
            "raise SystemExit(1 if 'server' in sys.modules else 0)",
        ],
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0


def test_scrapbook_explicit_storage_roundtrip(tmp_path):
    path_for_date = lambda date: _scrapbook_path(
        date,
        scrapbook_dir=tmp_path,
    )
    items = [{"id": "one", "src": "/attachments/a.png"}]

    _save_scrapbook(
        "2026-07-26",
        items,
        scrapbook_dir=tmp_path,
        path_for_date=path_for_date,
        write_text=_safe_write_text,
    )

    assert _load_scrapbook(
        "2026-07-26",
        path_for_date=path_for_date,
        report_failure=lambda *args, **kwargs: None,
    ) == items


def test_compact_summary_reports_missing_profile():
    reports = []

    result = compact_summary_run(
        "conversation",
        get_profile=lambda *args: None,
        get_client=lambda profile: None,
        report_failure=lambda *args, **kwargs: reports.append(
            (args, kwargs)
        ),
        logger=type("Logger", (), {"warning": lambda *args: None})(),
    )

    assert result == ""
    assert reports[0][0][0] == "compact_summary_no_profile"
