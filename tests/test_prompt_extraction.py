"""RED LINE net for the prompt-text Extract Module (2026-07-22).

baseline / protocol_index / tool_catalog (prompt_builder.build_system_prompt) and the
vision WORKFLOW block (chat_routes._build_vision_workflow_block) moved from inline
f-strings to gateway/prompts/*.md, rendered at call time. These tests pin the exact
byte output for a clean install without a personal vault, so any future edit to
prompts/*.md or the render glue that changes output is caught immediately.
"""
import subprocess
import sys
from pathlib import Path

import pytest
from datetime import datetime

import prompt_builder
from prompt_builder import _week_calendar_hint

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
import chat_routes as cr  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


@pytest.fixture(autouse=True)
def isolate_prompt_user_context(monkeypatch, tmp_path):
    for attr in ("_AGENT_CONTEXT_PATH", "_PROJECT_PULSE_PATH", "_USER_PULSE_PATH"):
        monkeypatch.setattr(prompt_builder, attr, tmp_path / attr)
    monkeypatch.setattr(prompt_builder, "_MEMORY_DIR", tmp_path / "memory")
    monkeypatch.setattr(prompt_builder, "_USER_CTX_CACHE", {"sig": None, "content": ""})


def test_prompt_builder_module_does_not_import_server():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import prompt_builder; "
            "raise SystemExit(1 if 'server' in sys.modules else 0)",
        ],
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0


def test_generated_prompt_and_tool_contracts_are_fresh():
    for script in ("generate_prompt_contract.py", "generate_tool_contracts.py"):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_clean_install_system_prompt_byte_matches_golden():
    golden = (GOLDEN_DIR / "system_prompt_baseline.txt").read_text(encoding="utf-8")
    out = server.build_system_prompt(None, model_id=None)
    assert out == golden


def test_build_system_prompt_includes_shared_journal_writing_contract():
    out = server.build_system_prompt(None, model_id=None)
    shared = (ROOT / "prompts" / "journal_writing.md").read_text(encoding="utf-8")
    assert shared in out


def test_tag_vocabulary_is_not_in_the_baseline_system_prompt():
    aggregate = (
        "# 标签聚合\n\n## #跑步\n\n> 说明：跑步训练\n"
        "> 适用范围：跑步、配速与恢复\n\n"
        "| 日期 | 时间 | 链接 | 内容 |\n|---|---|---|---|\n"
    )
    out = server.build_system_prompt(None, model_id=None)

    assert "TAG_VOCABULARY" not in out
    assert "#跑步｜跑步训练" not in out


def test_vision_workflow_block_renders_current_prompt_source_byte_identically():
    golden = (ROOT / "prompts" / "vision_workflow.md").read_text(encoding="utf-8").format(
        view_date="2026-07-22"
    )
    out = cr._build_vision_workflow_block("2026-07-22")
    assert out == golden


def test_vision_workflow_block_view_date_interpolation():
    # {view_date} placeholder must substitute at both call sites (STEP A pin path read +
    # place_scrapbook_image date=, and the supplement kind's read_today_schedule date=).
    out = cr._build_vision_workflow_block("2099-01-01")
    assert out.count("2099-01-01") == 3
    assert "{view_date}" not in out


def test_week_calendar_hint_resolves_current_week_without_model_arithmetic():
    hint = _week_calendar_hint(datetime(2026, 8, 5, 19, 52))
    assert "今天=周三" in hint
    assert "周一=2026-08-03" in hint
    assert "周二=2026-08-04" in hint
    assert "周日=2026-08-09" in hint
    assert "上周/下周=本表日期-7/+7天" in hint
