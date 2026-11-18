"""AI-owned memo series and occurrence persistence.

The deterministic store owns state transitions. The model only supplies
semantic intent through the tool wrappers below.
"""

import calendar
import json
import threading
import uuid
from datetime import datetime, timedelta


_PATH = None
_WRITE_TEXT = None
_NOW = None
_NEW_ID = None
_RECORD_COMPLETION = None
_LOCK = threading.Lock()

_SERIES_STATES = {"active", "paused", "archived"}
_OCCURRENCE_STATES = {"pending", "snoozed", "completed", "skipped"}
_SCHEDULE_KINDS = {"once", "daily", "weekdays", "weekly", "monthly"}


class MemoStateError(RuntimeError):
    """The persisted memo envelope exists but cannot be trusted."""


def configure_effects(
    *,
    path,
    write_text,
    now,
    record_completion,
    new_id=None,
) -> None:
    global _PATH, _WRITE_TEXT, _NOW, _NEW_ID, _RECORD_COMPLETION
    _PATH = path
    _WRITE_TEXT = write_text
    _NOW = now
    _NEW_ID = new_id or (lambda: uuid.uuid4().hex)
    _RECORD_COMPLETION = record_completion


def _empty() -> dict:
    return {"version": 1, "series": [], "occurrences": []}


def _valid_stored_data(data) -> bool:
    if not isinstance(data, dict) or data.get("version") != 1:
        return False
    series_items = data.get("series")
    occurrences = data.get("occurrences")
    if not isinstance(series_items, list) or not isinstance(occurrences, list):
        return False
    series_ids = set()
    for item in series_items:
        if not isinstance(item, dict):
            return False
        series_id = item.get("id")
        schedule = item.get("schedule")
        if (
            not isinstance(series_id, str) or not series_id
            or series_id in series_ids
            or not isinstance(item.get("text"), str)
            or item.get("state") not in _SERIES_STATES
            or not isinstance(item.get("notification_enabled"), bool)
            or _normalize_schedule(schedule) != schedule
            or not _parse_datetime(item.get("created_at"))
            or not _parse_datetime(item.get("updated_at"))
        ):
            return False
        series_ids.add(series_id)
    occurrence_ids = set()
    for item in occurrences:
        if not isinstance(item, dict):
            return False
        occurrence_id = item.get("id")
        if (
            not isinstance(occurrence_id, str) or not occurrence_id
            or occurrence_id in occurrence_ids
            or item.get("series_id") not in series_ids
            or item.get("state") not in _OCCURRENCE_STATES
            or not _parse_datetime(item.get("due_at"))
            or not _parse_datetime(item.get("created_at"))
            or not _parse_datetime(item.get("updated_at"))
            or (
                item.get("completed_at") is not None
                and not _parse_datetime(item.get("completed_at"))
            )
            or (
                item.get("skipped_at") is not None
                and not _parse_datetime(item.get("skipped_at"))
            )
        ):
            return False
        occurrence_ids.add(occurrence_id)
    return True


def _load() -> dict:
    path = _PATH()
    if not path.exists():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if _valid_stored_data(data):
            return data
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError) as exc:
        raise MemoStateError("memo_state_corrupt") from exc
    raise MemoStateError("memo_state_corrupt")


def _try_load() -> tuple[dict | None, dict | None]:
    try:
        return _load(), None
    except MemoStateError:
        return None, {"ok": False, "error": "memo_state_corrupt"}


def _save(data: dict) -> None:
    _WRITE_TEXT(
        _PATH(),
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        rotate=True,
    )


def _parse_datetime(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _normalize_schedule(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    kind = value.get("kind")
    if kind not in _SCHEDULE_KINDS:
        return None
    allowed = {"kind", "weekdays"}
    if set(value) - allowed:
        return None
    weekdays = value.get("weekdays", [])
    if kind in {"weekdays", "weekly"}:
        if kind == "weekdays" and not weekdays:
            weekdays = [1, 2, 3, 4, 5]
        if (
            not isinstance(weekdays, list)
            or not weekdays
            or any(
                not isinstance(day, int)
                or isinstance(day, bool)
                or day < 1
                or day > 7
                for day in weekdays
            )
        ):
            return None
        weekdays = sorted(set(weekdays))
    elif weekdays:
        return None
    return {"kind": kind, **({"weekdays": weekdays} if weekdays else {})}


def _new_occurrence(series_id: str, due_at: datetime, now: datetime) -> dict:
    due_text = due_at.isoformat()
    return {
        "id": f"{series_id}@{due_text}",
        "series_id": series_id,
        "due_at": due_text,
        "state": "pending",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }


def _next_due(due: datetime, schedule: dict, now: datetime) -> datetime | None:
    kind = schedule["kind"]
    if kind == "once":
        return None
    if kind == "daily":
        candidate = due + timedelta(days=1)
        while candidate <= now:
            candidate += timedelta(days=1)
        return candidate
    if kind in {"weekdays", "weekly"}:
        weekdays = set(schedule.get("weekdays") or [due.isoweekday()])
        candidate = due + timedelta(days=1)
        while candidate <= now or candidate.isoweekday() not in weekdays:
            candidate += timedelta(days=1)
        return candidate
    if kind == "monthly":
        year, month = due.year, due.month + 1
        if month == 13:
            year, month = year + 1, 1
        while True:
            day = min(due.day, calendar.monthrange(year, month)[1])
            candidate = due.replace(year=year, month=month, day=day)
            if candidate > now:
                return candidate
            month += 1
            if month == 13:
                year, month = year + 1, 1
    return None


def tool_create_memo(args: dict) -> dict:
    args = args or {}
    text = str(args.get("text") or "").strip()
    due = _parse_datetime(args.get("due_at"))
    schedule = _normalize_schedule(args.get("schedule") or {"kind": "once"})
    if not 1 <= len(text) <= 200:
        return {"ok": False, "error": "text_invalid"}
    if not due:
        return {"ok": False, "error": "due_at_invalid"}
    if not schedule:
        return {"ok": False, "error": "schedule_invalid"}

    now = _NOW()
    series_id = _NEW_ID()
    series = {
        "id": series_id,
        "text": text,
        "schedule": schedule,
        "notification_enabled": bool(args.get("notification_enabled", True)),
        "state": "active",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    occurrence = _new_occurrence(series_id, due, now)
    with _LOCK:
        data, error = _try_load()
        if error:
            return error
        data["series"].append(series)
        data["occurrences"].append(occurrence)
        _save(data)
    return {"ok": True, "series": series, "occurrence": occurrence}


def _schedule_label(schedule: dict) -> str:
    kind = schedule.get("kind")
    if kind == "once":
        return "单次"
    if kind == "daily":
        return "每天"
    if kind == "weekdays":
        return "工作日"
    if kind == "monthly":
        return "每月"
    days = "、".join(str(day) for day in schedule.get("weekdays", []))
    return f"每周 {days}"


def tool_list_memos(args: dict) -> dict:
    limit = (args or {}).get("limit", 8)
    if not isinstance(limit, int) or isinstance(limit, bool):
        limit = 8
    limit = max(1, min(limit, 20))
    now = _NOW()
    data, error = _try_load()
    if error:
        return error
    active = {
        item["id"]: item
        for item in data["series"]
        if isinstance(item, dict) and item.get("state") == "active"
    }
    items = []
    for occurrence in data["occurrences"]:
        series = active.get(occurrence.get("series_id"))
        due = _parse_datetime(occurrence.get("due_at"))
        if (
            not series
            or occurrence.get("state") not in {"pending", "snoozed"}
            or not due
        ):
            continue
        items.append({
            "occurrence_id": occurrence["id"],
            "series_id": series["id"],
            "text": series["text"],
            "due_at": occurrence["due_at"],
            "state": occurrence["state"],
            "overdue": due < now,
            "schedule": series["schedule"],
            "schedule_label": _schedule_label(series["schedule"]),
            "notification_enabled": series["notification_enabled"],
        })
    items.sort(key=lambda item: item["due_at"])
    return {
        "ok": True,
        "items": items[:limit],
        "total": len(items),
        "caption": "后台 AI 唤醒尚未启用",
    }


def tool_act_on_memo(args: dict) -> dict:
    args = args or {}
    occurrence_id = str(args.get("occurrence_id") or "")
    action = args.get("action")
    if action not in {"complete", "skip", "snooze"}:
        return {"ok": False, "error": "action_invalid"}
    now = _NOW()
    with _LOCK:
        data, error = _try_load()
        if error:
            return error
        occurrence = next(
            (
                item for item in data["occurrences"]
                if item.get("id") == occurrence_id
            ),
            None,
        )
        if not occurrence or occurrence.get("state") not in {
            "pending", "snoozed"
        }:
            return {"ok": False, "error": "occurrence_not_actionable"}
        series = next(
            (
                item for item in data["series"]
                if item.get("id") == occurrence.get("series_id")
            ),
            None,
        )
        if not series:
            return {"ok": False, "error": "series_not_found"}

        if action == "snooze":
            snooze_until = _parse_datetime(args.get("snooze_until"))
            if not snooze_until or snooze_until <= now:
                return {"ok": False, "error": "snooze_until_invalid"}
            occurrence["state"] = "snoozed"
            occurrence["due_at"] = snooze_until.isoformat()
            occurrence["updated_at"] = now.isoformat()
            _save(data)
            return {"ok": True, "occurrence": occurrence}

        if action == "complete":
            journal_result = _RECORD_COMPLETION(series["text"], occurrence_id)
            if not journal_result or journal_result.get("error"):
                return {
                    "ok": False,
                    "error": (journal_result or {}).get(
                        "error", "journal_write_failed"
                    ),
                }

        occurrence["state"] = "completed" if action == "complete" else "skipped"
        occurrence["updated_at"] = now.isoformat()
        occurrence[f"{occurrence['state']}_at"] = now.isoformat()
        next_occurrence = None
        if series.get("state") == "active":
            due = _parse_datetime(occurrence["due_at"])
            next_due = _next_due(due, series["schedule"], now) if due else None
            if next_due:
                next_occurrence = _new_occurrence(series["id"], next_due, now)
                data["occurrences"].append(next_occurrence)
        _save(data)
    result = {"ok": True, "occurrence": occurrence}
    if next_occurrence:
        result["next_occurrence"] = next_occurrence
    return result


def tool_update_memo(args: dict) -> dict:
    args = args or {}
    text = str(args.get("text") or "").strip()
    due = _parse_datetime(args.get("due_at"))
    schedule = _normalize_schedule(args.get("schedule"))
    if not 1 <= len(text) <= 200:
        return {"ok": False, "error": "text_invalid"}
    if not due:
        return {"ok": False, "error": "due_at_invalid"}
    if not schedule:
        return {"ok": False, "error": "schedule_invalid"}
    now = _NOW()
    with _LOCK:
        data, error = _try_load()
        if error:
            return error
        series = next((
            item for item in data["series"]
            if item.get("id") == args.get("series_id")
            and item.get("state") != "archived"
        ), None)
        if not series:
            return {"ok": False, "error": "series_not_found"}
        occurrence = next((
            item for item in data["occurrences"]
            if item.get("id") == args.get("occurrence_id")
            and item.get("series_id") == series["id"]
        ), None)
        if not occurrence or occurrence.get("state") not in {"pending", "snoozed"}:
            return {"ok": False, "error": "occurrence_not_actionable"}
        series["text"] = text
        series["schedule"] = schedule
        series["notification_enabled"] = bool(
            args.get("notification_enabled", True)
        )
        series["updated_at"] = now.isoformat()
        occurrence["due_at"] = due.isoformat()
        occurrence["state"] = "pending"
        occurrence["updated_at"] = now.isoformat()
        _save(data)
    return {"ok": True, "series": series, "occurrence": occurrence}


def tool_manage_memo_series(args: dict) -> dict:
    args = args or {}
    series_id = str(args.get("series_id") or "")
    action = args.get("action")
    target_state = {
        "pause": "paused",
        "resume": "active",
        "archive": "archived",
    }.get(action)
    if not target_state:
        return {"ok": False, "error": "action_invalid"}
    with _LOCK:
        data, error = _try_load()
        if error:
            return error
        series = next(
            (item for item in data["series"] if item.get("id") == series_id),
            None,
        )
        if not series:
            return {"ok": False, "error": "series_not_found"}
        series["state"] = target_state
        series["updated_at"] = _NOW().isoformat()
        _save(data)
    return {"ok": True, "series": series}
