# TEST PATTERN: boundary + contract — untrusted WidgetSpec enters a read-only broker
# USE WHEN: an LLM-authored declarative document selects a local capability

from datetime import datetime, timedelta
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import server
import widget_runtime
from prompt_builder import build_system_prompt
from tool_specs import TOOLS


VALID_SPEC = {
    "schema_version": "1.0",
    "id": "task-completion-7d",
    "title": "七日打卡",
    "slot": "care",
    "data": {
        "capability": "daily_tasks.completion_summary",
        "params": {"days": 7},
    },
    "view": {
        "type": "metric_sparkline",
        "metric": {"path": "summary.rate", "format": "percent"},
        "caption": {"path": "summary.caption"},
        "series": {"path": "days", "value": "rate"},
    },
}

MEMO_SPEC = {
    "schema_version": "1.0",
    "id": "memo-reference",
    "title": "备忘",
    "slot": "care",
    "data": {"capability": "memo.overview", "params": {"limit": 4}},
    "view": {
        "type": "memo_list",
        "items": {"path": "items"},
        "caption": {"path": "caption"},
        "empty_text": "还没有备忘",
        "add_label": "告诉 AI",
    },
}

@pytest.fixture(autouse=True)
def restore_widget_runtime_effects():
    names = (
        "_NOW",
        "_FIND_JOURNAL",
        "_TOP_SECTION_BOUNDS",
        "_SPECS_PATH",
        "_WRITE_TEXT",
        "_LIST_MEMOS",
        "_SET_SYSTEM_WIDGET_ENABLED",
    )
    previous = {name: getattr(widget_runtime, name) for name in names}
    yield
    for name, value in previous.items():
        setattr(widget_runtime, name, value)


def test_validate_widget_spec_accepts_v1_and_rejects_code_or_unknown_capability():
    assert widget_runtime.validate_widget_spec(VALID_SPEC) == []

    with_script = {**VALID_SPEC, "script": "fetch('/api/setup/current')"}
    assert widget_runtime.validate_widget_spec(with_script) == [
        {"path": "script", "code": "unknown_field"}
    ]

    unknown = json.loads(json.dumps(VALID_SPEC))
    unknown["data"]["capability"] = "setup.current"
    assert widget_runtime.validate_widget_spec(unknown) == [
        {"path": "data.capability", "code": "unsupported_capability"}
    ]
    assert widget_runtime.validate_widget_spec(MEMO_SPEC) == []
    mismatch = {
        **MEMO_SPEC,
        "data": {
            "capability": "daily_tasks.completion_summary",
            "params": {"days": 4},
        },
    }
    assert {"path": "view.type", "code": "capability_mismatch"} in (
        widget_runtime.validate_widget_spec(mismatch)
    )


def test_completion_summary_reads_only_top_task_section(tmp_path):
    files = {}
    texts = {
        "2026-07-24": "- [x] 喝水\n- [x] 鱼油\n- [ ] 维生素D\n- [ ] (添加你的第一个打卡项)\n\n# 08:00\n- [x] 正文里的框不算\n",
        "2026-07-25": "- [x] 鱼油\n- [x] 维生素D\n\n# 08:00\n正文\n",
    }
    for date, text in texts.items():
        path = tmp_path / f"{date}.md"
        path.write_text(text, encoding="utf-8")
        files[date] = path

    widget_runtime.configure_effects(
        now=lambda: datetime(2026, 7, 26, 10, 0),
        find_journal=lambda day: files.get(day.strftime("%Y-%m-%d")),
        top_section_bounds=lambda text: (0, text.splitlines().index("")),
    )

    result = widget_runtime.query_widget(VALID_SPEC)

    assert result["days"] == [
        {"date": "2026-07-20", "completed": 0, "total": 0, "rate": None},
        {"date": "2026-07-21", "completed": 0, "total": 0, "rate": None},
        {"date": "2026-07-22", "completed": 0, "total": 0, "rate": None},
        {"date": "2026-07-23", "completed": 0, "total": 0, "rate": None},
        {"date": "2026-07-24", "completed": 1, "total": 2, "rate": 0.5},
        {"date": "2026-07-25", "completed": 2, "total": 2, "rate": 1.0},
        {"date": "2026-07-26", "completed": 0, "total": 0, "rate": None},
    ]
    assert result["summary"] == {
        "completed": 3,
        "total": 4,
        "rate": 0.75,
        "caption": "近 7 天完成 3/4",
    }


def test_widget_runtime_queries_memos_through_named_capability():
    calls = []
    widget_runtime.configure_effects(
        now=lambda: datetime(2026, 7, 26),
        find_journal=lambda day: None,
        top_section_bounds=lambda text: None,
        list_memos=lambda args: (
            calls.append(args)
            or {
                "ok": True,
                "items": [],
                "total": 0,
                "caption": "后台 AI 唤醒尚未启用",
            }
        ),
    )

    result = widget_runtime.query_widget(MEMO_SPEC)

    assert calls == [{"limit": 4}]
    assert result["caption"] == "后台 AI 唤醒尚未启用"


def test_widget_runtime_http_contract(monkeypatch, tmp_path):
    monkeypatch.setattr(widget_runtime, "_NOW", lambda: datetime(2026, 7, 26))
    monkeypatch.setattr(widget_runtime, "_FIND_JOURNAL", lambda day: None)
    monkeypatch.setattr(widget_runtime, "_TOP_SECTION_BOUNDS", lambda text: None)
    client = TestClient(server.app)

    capabilities = client.get("/api/widget-runtime/capabilities")
    validated = client.post("/api/widget-runtime/validate", json=VALID_SPEC)
    queried = client.post("/api/widget-runtime/query", json=VALID_SPEC)

    assert capabilities.status_code == 200
    assert capabilities.json()["capabilities"][0]["name"] == (
        "daily_tasks.completion_summary"
    )
    assert validated.json() == {"ok": True, "errors": []}
    assert queried.status_code == 200
    assert queried.json()["spec_id"] == "task-completion-7d"
    assert queried.json()["data"]["summary"]["rate"] is None


def test_install_widget_spec_persists_only_valid_declarations(tmp_path):
    custom_spec = {**VALID_SPEC, "id": "my-task-completion"}
    target = tmp_path / "widget-specs.json"
    widget_runtime.configure_effects(
        now=lambda: datetime(2026, 7, 26),
        find_journal=lambda day: None,
        top_section_bounds=lambda text: None,
        specs_path=lambda: target,
        write_text=lambda path, text, rotate=False: path.write_text(
            text,
            encoding="utf-8",
        ),
    )

    installed = widget_runtime.tool_install_widget_spec({"spec": custom_spec})
    rejected = widget_runtime.tool_install_widget_spec({
        "spec": {**VALID_SPEC, "script": "evil()"},
    })

    assert installed == {
        "ok": True,
        "installed": "my-task-completion",
        "operation": "installed",
        "enabled": True,
    }
    assert rejected["ok"] is False
    assert rejected["errors"] == [
        {"path": "script", "code": "unknown_field"}
    ]
    assert widget_runtime.list_installed_specs() == [{
        "spec": custom_spec,
        "enabled": True,
        "revision": 1,
    }]


def test_install_widget_spec_updates_in_place_and_preserves_visibility(tmp_path):
    original = {**VALID_SPEC, "id": "my-task-completion"}
    revised = json.loads(json.dumps(original))
    revised["title"] = "十四日打卡"
    revised["data"]["params"]["days"] = 14
    target = tmp_path / "widget-specs.json"
    widget_runtime.configure_effects(
        now=lambda: datetime(2026, 7, 26),
        find_journal=lambda day: None,
        top_section_bounds=lambda text: None,
        specs_path=lambda: target,
        write_text=lambda path, text, rotate=False: path.write_text(
            text,
            encoding="utf-8",
        ),
    )

    assert widget_runtime.tool_install_widget_spec({"spec": original}) == {
        "ok": True,
        "installed": "my-task-completion",
        "operation": "installed",
        "enabled": True,
    }
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["items"][0]["enabled"] = False
    target.write_text(json.dumps(payload), encoding="utf-8")

    assert widget_runtime.tool_install_widget_spec({"spec": revised}) == {
        "ok": True,
        "installed": "my-task-completion",
        "operation": "updated",
        "enabled": False,
    }
    assert widget_runtime.list_installed_specs() == [{
        "spec": revised,
        "enabled": False,
        "revision": 2,
    }]


def test_install_widget_spec_cannot_replace_system_widget(tmp_path):
    target = tmp_path / "widget-specs.json"
    widget_runtime.configure_effects(
        now=lambda: datetime(2026, 7, 26),
        find_journal=lambda day: None,
        top_section_bounds=lambda text: None,
        specs_path=lambda: target,
        write_text=lambda path, text, rotate=False: path.write_text(
            text,
            encoding="utf-8",
        ),
    )

    assert widget_runtime.tool_install_widget_spec({"spec": VALID_SPEC}) == {
        "ok": False,
        "error": "cannot replace a system widget",
    }
    assert not target.exists()


def test_ai_widget_can_be_hidden_then_removed_but_system_widget_only_hidden(tmp_path):
    custom = {**VALID_SPEC, "id": "my-task-completion"}
    target = tmp_path / "widget-specs.json"
    system_calls = []
    widget_runtime.configure_effects(
        now=lambda: datetime(2026, 7, 26),
        find_journal=lambda day: None,
        top_section_bounds=lambda text: None,
        specs_path=lambda: target,
        write_text=lambda path, text, rotate=False: path.write_text(text, encoding="utf-8"),
        set_system_widget_enabled=lambda args: system_calls.append(args) or {
            "ok": True, "name": args["id"], "enabled": args["enabled"],
        },
    )
    widget_runtime.tool_install_widget_spec({"spec": custom})

    assert widget_runtime.tool_set_widget_enabled({
        "id": "my-task-completion", "enabled": False,
    }) == {
        "ok": True, "id": "my-task-completion", "enabled": False,
        "source": "ai-added",
    }
    assert widget_runtime.list_installed_specs()[0]["enabled"] is False
    assert widget_runtime.tool_remove_widget({"id": "my-task-completion"}) == {
        "ok": True, "removed": "my-task-completion",
    }
    assert widget_runtime.list_installed_specs() == []

    result = widget_runtime.tool_set_widget_enabled({"id": "mood", "enabled": False})
    assert result["ok"] is True
    assert result["source"] == "system"
    assert system_calls == [{"id": "mood", "enabled": False}]
    assert widget_runtime.tool_remove_widget({"id": "mood"}) == {
        "ok": False, "error": "system widgets can be disabled but not removed",
    }


def test_widget_mutations_preserve_unknown_future_schema_entries(tmp_path):
    custom = {**VALID_SPEC, "id": "my-task-completion"}
    future = {"spec": {"schema_version": "2.0", "id": "future"}, "future": True}
    target = tmp_path / "widget-specs.json"
    target.write_text(json.dumps({
        "version": 1,
        "items": [future, {"spec": custom, "enabled": True, "revision": 1}],
    }), encoding="utf-8")
    widget_runtime.configure_effects(
        now=lambda: datetime(2026, 7, 26),
        find_journal=lambda day: None,
        top_section_bounds=lambda text: None,
        specs_path=lambda: target,
        write_text=lambda path, text, rotate=False: path.write_text(text, encoding="utf-8"),
    )

    assert widget_runtime.tool_set_widget_enabled({
        "id": "my-task-completion", "enabled": False,
    })["ok"] is True
    assert json.loads(target.read_text(encoding="utf-8"))["items"][0] == future


def test_widget_inventory_exposes_editable_specs_and_read_only_system_widgets(
    tmp_path,
):
    custom = {**VALID_SPEC, "id": "my-task-completion"}
    target = tmp_path / "widget-specs.json"
    target.write_text(json.dumps({
        "version": 1,
        "items": [{"spec": custom, "enabled": False, "revision": 2}],
    }), encoding="utf-8")
    widget_runtime.configure_effects(
        now=lambda: datetime(2026, 7, 26),
        find_journal=lambda day: None,
        top_section_bounds=lambda text: None,
        specs_path=lambda: target,
    )

    result = widget_runtime.tool_list_widgets({
        "widgets": [{"name": "mood", "active": True}],
    })
    by_id = {item["id"]: item for item in result["widgets"]}
    assert by_id["mood"]["editable"] is False
    assert by_id["mood"]["source"] == "system"
    assert by_id["my-task-completion"]["editable"] is True
    assert by_id["my-task-completion"]["enabled"] is False
    assert by_id["my-task-completion"]["spec"] == custom

def test_widget_prompt_discloses_safe_authoring_guide_on_demand():
    prompt = build_system_prompt({"type": "widget-edit"})

    assert "gateway-widgets" in prompt
    assert "Use search_skills" in prompt
    assert "WidgetSpec v1 authoring" not in prompt
    assert "full HTML+inline style" not in prompt

    loaded = server.TOOL_IMPL["load_skill"]({"name": "gateway-widgets"})
    assert loaded["ok"] is True
    assert "validate_widget_spec" in loaded["content"]
    assert "install_widget_spec" in loaded["content"]

    install = next(
        item["function"] for item in TOOLS
        if item["function"]["name"] == "install_widget_spec"
    )
    assert "replace an existing AI-authored WidgetSpec" in install["description"]


def test_legacy_generated_code_tools_are_not_exposed_or_dispatchable():
    names = {item["function"]["name"] for item in TOOLS}

    assert "add_widget" not in names
    assert "patch_widget" not in names
    assert "tool policy missing" in server._dispatch_tool(
        "add_widget",
        {},
        {"origin": "user", "user_text": "添加 widget"},
        {},
    )["error"]


def test_widget_contract_copy_matches_mobile_repo():
    root = Path(__file__).resolve().parents[1]
    mobile_repo = root.parent / "gateway-rn"
    if not mobile_repo.exists():
        pytest.skip("sibling gateway-rn checkout is absent")
    mobile = mobile_repo / "services" / "contracts"
    for filename in (
        "widget-spec.v1.schema.json",
        "widget-capabilities.v1.json",
    ):
        assert (root / "docs" / "contracts" / filename).read_bytes() == (
            mobile / filename
        ).read_bytes()
