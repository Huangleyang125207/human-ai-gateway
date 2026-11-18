# TEST PATTERN: policy boundary — user request scope gates model side effects.
from action_policy import TOOL_EFFECTS, authorize_tool, build_action_context
from tool_specs import TOOLS
from datetime import date


def test_every_registered_tool_has_an_effect_and_model_cannot_self_authorize():
    names = {item["function"]["name"] for item in TOOLS}

    assert set(TOOL_EFFECTS) == names
    assert "load_tool_group" not in names
    assert "read_skill_resource" in names


def test_non_widget_tools_bypass_action_intent_review():
    chat = build_action_context("今天怎么样？", {})

    assert authorize_tool("read_today_schedule", {}, chat) is None
    assert authorize_tool("insert_journal_block", {}, chat) is None
    assert authorize_tool("patch_journal_block", {"new_md": "##"}, chat) is None
    assert authorize_tool("manage_daily_task", {"action": "del"}, chat) is None
    assert authorize_tool("delete_attachment", {}, chat) is None


def test_ai_writes_do_not_require_keyword_or_confirmation_authorization():
    query = build_action_context("今天怎么样？", {})

    for name, args in (
        ("install_widget_spec", {}),
        ("set_widget_enabled", {"id": "memo", "enabled": False}),
        ("remove_widget", {"id": "memo"}),
        ("delete_journal_entry", {"time": "10:00", "entry_index": 0, "date": "2099-01-01"}),
        ("manage_scrapbook", {"action": "remove", "id": "x"}),
        ("patch_journal_block", {"date": "2099-01-01", "new_md": "## 更新"}),
        ("insert_journal_block", {"date": "not-a-date", "new_md": "## 更新"}),
        ("append_journal_comment", {"date": "2000-01-01", "comment": "备注"}),
    ):
        assert authorize_tool(name, args, query, today=date(2026, 8, 19)) is None


def test_unknown_tools_fail_closed():
    denied = authorize_tool("not_registered", {}, build_action_context("执行", {}))
    assert denied["error"] == "tool policy missing: not_registered"




def test_patch_journal_schema_exposes_date_used_by_prompt_and_executor():
    patch = next(item for item in TOOLS if item["function"]["name"] == "patch_journal_block")

    assert "date" in patch["function"]["parameters"]["properties"]


def test_image_observation_is_scoped_to_current_visible_refs():
    url = "/attachments/2026-08-23/current.png"
    context = build_action_context("看看这张图", {"refs": [{
        "kind": "image", "payload": {"url": url},
    }]})
    assert authorize_tool("record_image_observation", {"attachment_url": url}, context) is None
    denied = authorize_tool(
        "record_image_observation",
        {"attachment_url": "/attachments/2026-08-01/history.png"}, context,
    )
    assert denied["requires_confirmation"] is False
