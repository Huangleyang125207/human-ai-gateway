# TEST PATTERN: boundary + effect — search tools use named app effects
# USE WHEN: changing vault search or search_tools dependency wiring

import subprocess
import sys
from pathlib import Path

import search_tools


ROOT = Path(__file__).resolve().parent.parent


def test_search_tools_module_does_not_import_server():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import search_tools; "
            "raise SystemExit(1 if 'server' in sys.modules else 0)",
        ],
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0


def test_search_text_reads_current_markdown_with_context(tmp_path, monkeypatch):
    note = tmp_path / "半小时复盘" / "26.7.26.md"
    note.parent.mkdir()
    note.write_text("# 9：00\n\n## #思考 解耦完成\n正文\n", encoding="utf-8")

    monkeypatch.setattr(search_tools, "_VAULT_DIR", lambda: tmp_path)

    result = search_tools.tool_search_text({"query": "解耦完成", "context_lines": 1})

    assert result["total_hits"] == 1
    assert result["matches"][0]["file"] == "半小时复盘/26.7.26.md"
    assert result["matches"][0]["line"] == 3
    assert result["matches"][0]["context"] == "\n## #思考 解耦完成\n正文"


def test_search_text_is_literal_case_insensitive_and_has_no_index(tmp_path, monkeypatch):
    note = tmp_path / "notes.md"
    note.write_text("# ESP32 [draft]\n", encoding="utf-8")
    monkeypatch.setattr(search_tools, "_VAULT_DIR", lambda: tmp_path)

    assert search_tools.tool_search_text({"query": "esp32 [draft]"})["total_hits"] == 1
    note.write_text("# STM32\n", encoding="utf-8")
    assert search_tools.tool_search_text({"query": "esp32 [draft]"})["total_hits"] == 0


def test_read_text_pages_visible_markdown_and_rejects_traversal(tmp_path, monkeypatch):
    note = tmp_path / "半小时复盘" / "26.7.26.md"
    note.parent.mkdir()
    note.write_text("一\n二\n三\n四\n", encoding="utf-8")
    outside = tmp_path.parent / "secret.md"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(search_tools, "_VAULT_DIR", lambda: tmp_path)

    result = search_tools.tool_read_text({
        "file": "半小时复盘/26.7.26.md", "start_line": 2, "line_count": 2,
    })

    assert result == {
        "ok": True,
        "file": "半小时复盘/26.7.26.md",
        "start_line": 2,
        "end_line": 3,
        "total_lines": 4,
        "content": "二\n三",
        "eof": False,
    }
    assert "error" in search_tools.tool_read_text({"file": "../secret.md"})
    assert "error" in search_tools.tool_read_text({"file": "not-markdown.txt"})
