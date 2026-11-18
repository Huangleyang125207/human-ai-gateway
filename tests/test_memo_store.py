"""Boundary tests for the AI-owned memo series/occurrence store."""

import json
from datetime import datetime

import pytest

import memo_store
import server


@pytest.fixture(autouse=True)
def isolated_memos(tmp_path):
    path = tmp_path / "memos.v1.json"
    journal = []
    clock = lambda: datetime.fromisoformat("2026-07-28T10:00:00+08:00")
    memo_store.configure_effects(
        path=lambda: path,
        write_text=lambda target, text, rotate=False: target.write_text(
            text, encoding="utf-8"
        ),
        now=clock,
        new_id=iter(["series-1", "series-2"]).__next__,
        record_completion=lambda text, occurrence_id: (
            journal.append((text, occurrence_id)) or {"ok": True}
        ),
    )
    yield path, journal


def test_create_persists_series_and_one_occurrence(isolated_memos):
    path, _ = isolated_memos
    result = memo_store.tool_create_memo({
        "text": "晚上跑步",
        "due_at": "2026-07-28T20:00:00+08:00",
        "schedule": {"kind": "weekly", "weekdays": [1, 3, 5]},
    })

    assert result["ok"] is True
    assert result["series"]["state"] == "active"
    assert result["occurrence"]["state"] == "pending"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["version"] == 1
    assert len(saved["series"]) == 1
    assert len(saved["occurrences"]) == 1


def test_rejects_ambiguous_or_invalid_schedule():
    assert memo_store.tool_create_memo({
        "text": "",
        "due_at": "2026-07-28T20:00:00+08:00",
        "schedule": {"kind": "once"},
    }) == {"ok": False, "error": "text_invalid"}
    assert memo_store.tool_create_memo({
        "text": "跑步",
        "due_at": "tomorrow",
        "schedule": {"kind": "once"},
    }) == {"ok": False, "error": "due_at_invalid"}
    assert memo_store.tool_create_memo({
        "text": "跑步",
        "due_at": "2026-07-28T20:00:00+08:00",
        "schedule": {"kind": "weekly", "weekdays": [0, 8]},
    }) == {"ok": False, "error": "schedule_invalid"}


def test_complete_records_journal_then_advances_recurring_occurrence(
    isolated_memos,
):
    _, journal = isolated_memos
    created = memo_store.tool_create_memo({
        "text": "晚上跑步",
        "due_at": "2026-07-28T20:00:00+08:00",
        "schedule": {"kind": "daily"},
    })
    occurrence_id = created["occurrence"]["id"]

    result = memo_store.tool_act_on_memo({
        "occurrence_id": occurrence_id,
        "action": "complete",
    })

    assert result["ok"] is True
    assert result["occurrence"]["state"] == "completed"
    assert result["next_occurrence"]["due_at"] == (
        "2026-07-29T20:00:00+08:00"
    )
    assert journal == [("晚上跑步", occurrence_id)]


def test_completion_does_not_mutate_state_when_journal_write_fails():
    memo_store._RECORD_COMPLETION = lambda *_: {"error": "journal failed"}
    created = memo_store.tool_create_memo({
        "text": "吃药",
        "due_at": "2026-07-28T20:00:00+08:00",
        "schedule": {"kind": "once"},
    })
    occurrence_id = created["occurrence"]["id"]

    result = memo_store.tool_act_on_memo({
        "occurrence_id": occurrence_id,
        "action": "complete",
    })

    assert result == {"ok": False, "error": "journal failed"}
    current = memo_store.tool_list_memos({})["items"][0]
    assert current["occurrence_id"] == occurrence_id
    assert current["state"] == "pending"


def test_snooze_and_series_lifecycle_are_distinct():
    created = memo_store.tool_create_memo({
        "text": "交报告",
        "due_at": "2026-07-28T09:00:00+08:00",
        "schedule": {"kind": "once"},
    })
    occurrence_id = created["occurrence"]["id"]
    series_id = created["series"]["id"]

    snoozed = memo_store.tool_act_on_memo({
        "occurrence_id": occurrence_id,
        "action": "snooze",
        "snooze_until": "2026-07-28T11:00:00+08:00",
    })
    assert snoozed["occurrence"]["state"] == "snoozed"
    assert memo_store.tool_list_memos({})["items"][0]["overdue"] is False

    assert memo_store.tool_manage_memo_series({
        "series_id": series_id,
        "action": "pause",
    })["series"]["state"] == "paused"
    assert memo_store.tool_list_memos({})["items"] == []
    assert memo_store.tool_manage_memo_series({
        "series_id": series_id,
        "action": "resume",
    })["series"]["state"] == "active"
    assert len(memo_store.tool_list_memos({})["items"]) == 1


def test_gui_and_ai_share_one_update_path(isolated_memos):
    created = memo_store.tool_create_memo({
        "text": "交报告",
        "due_at": "2026-07-28T20:00:00+08:00",
        "schedule": {"kind": "once"},
    })

    updated = memo_store.tool_update_memo({
        "series_id": created["series"]["id"],
        "occurrence_id": created["occurrence"]["id"],
        "text": "交最终报告",
        "due_at": "2026-07-29T09:30:00+08:00",
        "schedule": {"kind": "weekdays"},
        "notification_enabled": False,
    })

    assert updated["ok"] is True
    item = memo_store.tool_list_memos({})["items"][0]
    assert item["text"] == "交最终报告"
    assert item["due_at"] == "2026-07-29T09:30:00+08:00"
    assert item["schedule"] == {
        "kind": "weekdays",
        "weekdays": [1, 2, 3, 4, 5],
    }
    assert item["notification_enabled"] is False


def test_invalid_update_leaves_existing_memo_unchanged(isolated_memos):
    created = memo_store.tool_create_memo({
        "text": "交报告",
        "due_at": "2026-07-28T20:00:00+08:00",
        "schedule": {"kind": "once"},
    })
    rejected = memo_store.tool_update_memo({
        "series_id": created["series"]["id"],
        "occurrence_id": created["occurrence"]["id"],
        "text": "",
        "due_at": "tomorrow",
        "schedule": {"kind": "once"},
        "notification_enabled": True,
    })
    assert rejected["ok"] is False
    assert memo_store.tool_list_memos({})["items"][0]["text"] == "交报告"


@pytest.mark.parametrize("operation", ["create", "list", "act", "update", "manage"])
@pytest.mark.parametrize("corrupt", [
    "{broken",
    '{"version":1,"series":[1],"occurrences":[]}',
    '{"version":1,"series":[],"occurrences":[{"id":"orphan"}]}',
    '{"version":1,"series":[{"id":"s","text":"x","schedule":{"kind":"once"},"notification_enabled":true,"state":"active","created_at":"2026-07-28T00:00:00Z","updated_at":"2026-07-28T00:00:00Z"}],"occurrences":[{"id":"o","series_id":"s","due_at":"2026-07-28T20:00:00+08:00","state":"completed","created_at":"2026-07-28T00:00:00Z","updated_at":"2026-07-28T00:00:00Z","completed_at":42}]}',
])
def test_corrupt_state_fails_closed_without_overwrite(
    isolated_memos, operation, corrupt,
):
    path, _ = isolated_memos
    path.write_text(corrupt, encoding="utf-8")
    calls = {
        "create": lambda: memo_store.tool_create_memo({
            "text": "新备忘", "due_at": "2026-07-28T20:00:00+08:00",
            "schedule": {"kind": "once"},
        }),
        "list": lambda: memo_store.tool_list_memos({}),
        "act": lambda: memo_store.tool_act_on_memo({
            "occurrence_id": "missing", "action": "complete",
        }),
        "update": lambda: memo_store.tool_update_memo({
            "series_id": "missing", "occurrence_id": "missing", "text": "x",
            "due_at": "2026-07-28T20:00:00+08:00", "schedule": {"kind": "once"},
        }),
        "manage": lambda: memo_store.tool_manage_memo_series({
            "series_id": "missing", "action": "archive",
        }),
    }

    assert calls[operation]() == {"ok": False, "error": "memo_state_corrupt"}
    assert path.read_text(encoding="utf-8") == corrupt


def test_production_completion_effect_reuses_existing_journal_marker(
    tmp_path, monkeypatch,
):
    occurrence_id = "series-1@2026-07-28T20:00:00+08:00"
    marker = f"<!-- memo:{occurrence_id} -->"
    journal = tmp_path / "day.md"
    journal.write_text(f"# day\n\n{marker}\n", encoding="utf-8")
    inserted = []
    monkeypatch.setattr(server, "find_today_journal", lambda: journal)
    monkeypatch.setattr(
        server.journal_task_tools,
        "tool_insert_journal_block",
        lambda *args, **kwargs: inserted.append((args, kwargs)) or {"ok": True},
    )

    result = server._record_memo_completion("晚上跑步", occurrence_id)

    assert result == {"ok": True, "already_recorded": True}
    assert inserted == []
