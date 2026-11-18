# TEST PATTERN: architecture contract — production imports may only shrink
# USE WHEN: strangling a god module without allowing new reverse dependencies
# COPY THIS: update the exact baseline only in the same change that removes an import
#
# This is a ratchet, not the end state. Final state is an empty mapping: server.py is the
# composition root, and production modules never import it.

import ast
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_ROOTS = {
    ".git",
    ".venv-build",
    ".venv-test",
    "archive",
    "dist-pyinstaller",
    "scripts",
    "tests",
}

# Characterization baseline captured 2026-07-26. Keep exact counts so adding a second
# lazy import inside an already-allowed file also fails, rather than slipping past a
# file-only allowlist.
EXPECTED_SERVER_IMPORTS = {}

DECOUPLED_MODULES = (
    "attachments_index",
    "board_routes",
    "chat_routes",
    "compact_summary",
    "config_store",
    "consent_routes",
    "cutout",
    "daily_task_store",
    "daily_tasks_routes",
    "day_create",
    "history_summary",
    "journal_core",
    "journal_task_tools",
    "migration_routes",
    "migration_telemetry_routes",
    "notification_routes",
    "ocr",
    "prompt_builder",
    "pulse_eval",
    "pulse_evolve",
    "pulse_io",
    "pulse_routes",
    "safe_io",
    "scrapbook",
    "scrapbook_routes",
    "search_tools",
    "setup_routes",
    "startup_hooks",
    "system_routes",
    "tag_aggregate",
    "telemetry",
    "thread_routes",
    "tool_registry",
    "vault_audit_routes",
    "vault_config_routes",
    "vault_git",
    "vision_tools",
    "web_tools",
    "widget_routes",
    "widget_runtime",
    "widget_runtime_routes",
)


def _server_import_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in EXCLUDED_ROOTS or rel.parts[0].startswith(".venv"):
            continue
        # Older checkouts retain this archived WebView test harness at the root.
        if rel.parts[:2] == ("mobile", "parity"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(rel))
        count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "server":
                count += 1
            elif isinstance(node, ast.Import):
                count += sum(alias.name == "server" for alias in node.names)
        if count:
            counts[rel.as_posix()] = count
    return counts


def test_production_server_imports_match_declining_baseline():
    assert _server_import_counts() == EXPECTED_SERVER_IMPORTS


def test_decoupled_modules_cold_import_without_composition_root():
    code = (
        "import importlib, sys\n"
        f"modules = {DECOUPLED_MODULES!r}\n"
        "for module in modules:\n"
        "    importlib.import_module(module)\n"
        "    if 'server' in sys.modules:\n"
        "        raise SystemExit(f'{module} loaded server')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_composition_root_has_no_reexport_only_imports():
    tree = ast.parse(
        (ROOT / "server.py").read_text(encoding="utf-8"),
        filename="server.py",
    )
    imported = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(
                alias.asname or alias.name.split(".")[0]
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            imported.update(alias.asname or alias.name for alias in node.names)
    loaded = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }

    assert imported - loaded == set()


def test_composition_root_declares_no_http_handlers():
    tree = ast.parse(
        (ROOT / "server.py").read_text(encoding="utf-8"),
        filename="server.py",
    )
    decorated_functions = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.decorator_list
    ]

    assert decorated_functions == []
