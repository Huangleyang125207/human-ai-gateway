# TEST PATTERN: contract — every model tool belongs to one progressively disclosed Skill.
# USE WHEN: tool registration and reusable workflow packages must stay in lockstep.

from pathlib import Path

import skill_runtime
from tool_specs import TOOLS


def test_skill_registry_covers_every_registered_tool_exactly_once():
    registered = {item["function"]["name"] for item in TOOLS}
    catalog = skill_runtime.skill_catalog()
    assigned = [tool for skill in catalog for tool in skill["tools"]]

    assert set(assigned) == registered
    assert len(assigned) == len(set(assigned))
    assert all(skill["description"] for skill in catalog)


def test_search_skills_returns_metadata_without_loading_bodies():
    result = skill_runtime.tool_search_skills({"query": "memo"})

    assert result["ok"] is True
    assert [item["name"] for item in result["skills"]] == ["gateway-memo"]
    assert "content" not in result["skills"][0]
    assert "create_memo" in result["skills"][0]["tools"]


def test_skill_index_does_not_open_unrequested_references(monkeypatch):
    monkeypatch.setattr(
        skill_runtime,
        "_safe_reference",
        lambda path: (_ for _ in ()).throw(AssertionError(path)),
    )

    assert "gateway-architecture" in {
        item["name"] for item in skill_runtime.skill_catalog()
    }


def test_load_skill_returns_workflow_and_live_architecture_reference():
    journal = skill_runtime.tool_load_skill({"name": "gateway-journal"})
    architecture = skill_runtime.tool_load_skill({"name": "gateway-architecture"})

    assert journal["ok"] is True
    assert "patch_journal_block" in journal["content"]
    assert architecture["ok"] is True
    assert architecture["references"][0]["path"] == "docs/ARCHITECTURE_LEDGER.md"
    assert "content" not in architecture["references"][0]
    assert architecture["references"][0]["chars"] == len((
        Path(__file__).resolve().parents[1]
        / "docs" / "ARCHITECTURE_LEDGER.md"
    ).read_text(encoding="utf-8"))


def test_long_skill_resource_can_be_reconstructed_without_tool_result_truncation():
    expected = (
        Path(__file__).resolve().parents[1] / "docs" / "ARCHITECTURE_LEDGER.md"
    ).read_text(encoding="utf-8")
    chunks = []
    cursor = 0
    while True:
        result = skill_runtime.tool_read_skill_resource({
            "name": "gateway-architecture",
            "path": "docs/ARCHITECTURE_LEDGER.md",
            "cursor": cursor,
            "limit": 3000,
        })
        assert result["ok"] is True
        assert len(result["content"]) <= 3000
        chunks.append(result["content"])
        if result["eof"]:
            break
        cursor = result["next_cursor"]
    assert "".join(chunks) == expected


def test_load_skill_rejects_unknown_names_and_lists_available_skills():
    result = skill_runtime.tool_load_skill({"name": "does-not-exist"})

    assert result["ok"] is False
    assert "gateway-journal" in result["available"]
