"""Read-only capability broker for declarative WidgetSpec documents."""

import json
import re


_NOW = None
_FIND_JOURNAL = None
_TOP_SECTION_BOUNDS = None
_SPECS_PATH = None
_WRITE_TEXT = None
_LIST_MEMOS = None
_SET_SYSTEM_WIDGET_ENABLED = None

# Code-backed widgets are owned by the application release. AI-authored specs may
# replace only other AI-authored specs with the same id.
_SYSTEM_WIDGET_IDS = {
    "ctrl-c-v-bridge", "memo-reference", "mood", "steps", "supplements",
    "task-completion-7d",
}

CAPABILITIES = [{
    "name": "daily_tasks.completion_summary",
    "mode": "read",
    "description": (
        "Aggregate top-section daily task completion over a bounded "
        "recent-day window."
    ),
    "params": {
        "days": {
            "type": "integer",
            "minimum": 1,
            "maximum": 30,
            "default": 7,
        },
    },
    "returns": {
        "days": "Array<{date, completed, total, rate}>",
        "summary": "{completed, total, rate, caption}",
    },
}, {
    "name": "memo.overview",
    "mode": "read",
    "description": (
        "List current AI-managed memo occurrences. Widget interactions are "
        "returned to the AI; the widget cannot mutate memo state directly."
    ),
    "params": {
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 8,
            "default": 4,
        },
    },
    "returns": {
        "items": (
            "Array<{occurrence_id,series_id,text,due_at,state,"
            "overdue,schedule_label}>"
        ),
        "caption": "string",
    },
}]

_ROOT_FIELDS = {"schema_version", "id", "title", "slot", "data", "view"}
_DATA_FIELDS = {"capability", "params"}
_VIEW_FIELDS = {
    "type", "metric", "caption", "series", "items", "empty_text",
    "add_label",
}
_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TASK_RE = re.compile(r"^-\s*\[([ x])\]\s*(.+)")
_PLACEHOLDER_TASKS = {
    "(添加你的第一个打卡项)",
    "（添加你的第一个打卡项）",
}


def configure_effects(
    *,
    now,
    find_journal,
    top_section_bounds,
    specs_path=None,
    write_text=None,
    list_memos=None,
    set_system_widget_enabled=None,
) -> None:
    global _NOW, _FIND_JOURNAL, _TOP_SECTION_BOUNDS, _SPECS_PATH, _WRITE_TEXT
    global _LIST_MEMOS, _SET_SYSTEM_WIDGET_ENABLED
    _NOW = now
    _FIND_JOURNAL = find_journal
    _TOP_SECTION_BOUNDS = top_section_bounds
    _SPECS_PATH = specs_path
    _WRITE_TEXT = write_text
    _LIST_MEMOS = list_memos
    _SET_SYSTEM_WIDGET_ENABLED = set_system_widget_enabled


def _error(path: str, code: str) -> dict:
    return {"path": path, "code": code}


def _unknown_fields(value, allowed: set[str], prefix: str = "") -> list[dict]:
    if not isinstance(value, dict):
        return []
    return [
        _error(f"{prefix}.{key}" if prefix else key, "unknown_field")
        for key in sorted(set(value) - allowed)
    ]


def validate_widget_spec(spec) -> list[dict]:
    """Validate the intentionally small v1 surface without executing content."""
    if not isinstance(spec, dict):
        return [_error("$", "must_be_object")]

    errors = _unknown_fields(spec, _ROOT_FIELDS)
    for field in sorted(_ROOT_FIELDS - set(spec)):
        errors.append(_error(field, "required"))
    if errors:
        return errors

    if spec["schema_version"] != "1.0":
        errors.append(_error("schema_version", "unsupported_version"))
    widget_id = spec["id"]
    if (
        not isinstance(widget_id, str)
        or len(widget_id) > 64
        or not _ID_RE.fullmatch(widget_id)
    ):
        errors.append(_error("id", "invalid_id"))
    title = spec["title"]
    if not isinstance(title, str) or not (1 <= len(title.strip()) <= 40):
        errors.append(_error("title", "invalid_title"))
    if spec["slot"] != "care":
        errors.append(_error("slot", "unsupported_slot"))

    data = spec["data"]
    if not isinstance(data, dict):
        errors.append(_error("data", "must_be_object"))
    else:
        errors.extend(_unknown_fields(data, _DATA_FIELDS, "data"))
        capability = data.get("capability")
        if capability not in {
            "daily_tasks.completion_summary", "memo.overview"
        }:
            errors.append(
                _error("data.capability", "unsupported_capability")
            )
        params = data.get("params")
        if not isinstance(params, dict):
            errors.append(_error("data.params", "must_be_object"))
        else:
            if capability == "daily_tasks.completion_summary":
                errors.extend(
                    _unknown_fields(params, {"days"}, "data.params")
                )
                days = params.get("days")
                if (
                    not isinstance(days, int)
                    or isinstance(days, bool)
                    or not 1 <= days <= 30
                ):
                    errors.append(
                        _error("data.params.days", "out_of_range")
                    )
            elif capability == "memo.overview":
                errors.extend(
                    _unknown_fields(params, {"limit"}, "data.params")
                )
                limit = params.get("limit")
                if (
                    not isinstance(limit, int)
                    or isinstance(limit, bool)
                    or not 1 <= limit <= 8
                ):
                    errors.append(
                        _error("data.params.limit", "out_of_range")
                    )

    view = spec["view"]
    if not isinstance(view, dict):
        errors.append(_error("view", "must_be_object"))
    else:
        errors.extend(_unknown_fields(view, _VIEW_FIELDS, "view"))
        view_type = view.get("type")
        if view_type not in {"metric_sparkline", "memo_list"}:
            errors.append(_error("view.type", "unsupported_view"))
        elif view_type == "metric_sparkline":
            if set(view) != {"type", "metric", "caption", "series"}:
                errors.append(_error("view", "invalid_shape"))
            if view.get("metric") != {
                "path": "summary.rate",
                "format": "percent",
            }:
                errors.append(_error("view.metric", "unsupported_binding"))
            if view.get("caption") != {"path": "summary.caption"}:
                errors.append(_error("view.caption", "unsupported_binding"))
            if view.get("series") != {"path": "days", "value": "rate"}:
                errors.append(_error("view.series", "unsupported_binding"))
            if isinstance(data, dict) and data.get(
                "capability"
            ) == "memo.overview":
                errors.append(_error("view.type", "capability_mismatch"))
        elif view_type == "memo_list":
            if set(view) != {
                "type", "items", "caption", "empty_text", "add_label"
            }:
                errors.append(_error("view", "invalid_shape"))
            if view.get("items") != {"path": "items"}:
                errors.append(_error("view.items", "unsupported_binding"))
            if view.get("caption") != {"path": "caption"}:
                errors.append(_error("view.caption", "unsupported_binding"))
            if (
                not isinstance(view.get("empty_text"), str)
                or not 1 <= len(view["empty_text"].strip()) <= 40
            ):
                errors.append(_error("view.empty_text", "invalid_text"))
            if (
                not isinstance(view.get("add_label"), str)
                or not 1 <= len(view["add_label"].strip()) <= 20
            ):
                errors.append(_error("view.add_label", "invalid_text"))
            if isinstance(data, dict) and data.get(
                "capability"
            ) == "daily_tasks.completion_summary":
                errors.append(_error("view.type", "capability_mismatch"))
    return errors


def _day_completion(path) -> tuple[int, int]:
    if not path:
        return 0, 0
    try:
        text = path.read_text(encoding="utf-8")
        bounds = _TOP_SECTION_BOUNDS(text)
        if not bounds:
            return 0, 0
        completed = 0
        total = 0
        for line in text.splitlines()[bounds[0]:bounds[1]]:
            match = _TASK_RE.match(line)
            if not match:
                continue
            name = match.group(2).strip()
            if name == "喝水" or name in _PLACEHOLDER_TASKS:
                continue
            total += 1
            completed += match.group(1) == "x"
        return completed, total
    except (OSError, UnicodeError):
        return 0, 0


def _completion_summary(days: int) -> dict:
    from datetime import timedelta

    today = _NOW()
    rows = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        completed, total = _day_completion(_FIND_JOURNAL(day))
        rows.append({
            "date": day.strftime("%Y-%m-%d"),
            "completed": completed,
            "total": total,
            "rate": round(completed / total, 4) if total else None,
        })
    completed = sum(row["completed"] for row in rows)
    total = sum(row["total"] for row in rows)
    rate = round(completed / total, 4) if total else None
    caption = (
        f"近 {days} 天完成 {completed}/{total}"
        if total
        else f"近 {days} 天暂无打卡"
    )
    return {
        "days": rows,
        "summary": {
            "completed": completed,
            "total": total,
            "rate": rate,
            "caption": caption,
        },
    }


def query_widget(spec: dict) -> dict:
    errors = validate_widget_spec(spec)
    if errors:
        raise ValueError(errors)
    data = spec["data"]
    if data["capability"] == "memo.overview":
        if not _LIST_MEMOS:
            raise RuntimeError("memo capability unavailable")
        return _LIST_MEMOS({"limit": data["params"]["limit"]})
    return _completion_summary(data["params"]["days"])


def _load_raw_spec_items() -> tuple[list, str | None]:
    if not _SPECS_PATH:
        return [], None
    path = _SPECS_PATH()
    if not path.exists():
        return [], None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload.get("items", [])
        if not isinstance(items, list):
            return [], "widget spec items must be an array"
        return items, None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [], f"cannot read widget spec storage: {exc}"


def list_installed_specs() -> list[dict]:
    items, error = _load_raw_spec_items()
    if error:
        return []
    return [
            item for item in items
            if isinstance(item, dict)
            and isinstance(item.get("spec"), dict)
            and not validate_widget_spec(item["spec"])
    ]


def tool_list_widgets(legacy_result: dict | None = None) -> dict:
    """Return an edit-oriented inventory without exposing legacy code files."""
    widgets = []
    seen = set()
    for item in (legacy_result or {}).get("widgets", []):
        if not isinstance(item, dict):
            continue
        widget_id = str(item.get("id") or item.get("name") or "").strip()
        if not widget_id or widget_id in seen:
            continue
        seen.add(widget_id)
        widgets.append({
            "id": widget_id,
            "title": item.get("title") or widget_id,
            "enabled": item.get("enabled", item.get("active", True)) is not False,
            "source": "system",
            "editable": False,
        })
    for item in list_installed_specs():
        spec = item["spec"]
        widget_id = spec["id"]
        if widget_id in seen:
            continue
        seen.add(widget_id)
        widgets.append({
            "id": widget_id,
            "title": spec["title"],
            "enabled": item.get("enabled") is not False,
            "source": "ai-added",
            "editable": True,
            "spec": spec,
            "revision": int(item.get("revision") or 1),
        })
    return {"ok": True, "widgets": widgets}


def tool_search_widget_capabilities(args: dict) -> dict:
    query = str((args or {}).get("query") or "").strip().lower()
    items = CAPABILITIES
    if query:
        items = [
            item for item in items
            if query in item["name"].lower()
            or query in item["description"].lower()
        ]
    return {"version": "1.0", "capabilities": items}


def tool_validate_widget_spec(args: dict) -> dict:
    spec = (args or {}).get("spec")
    errors = validate_widget_spec(spec)
    return {"ok": not errors, "errors": errors}


def tool_install_widget_spec(args: dict) -> dict:
    """Persist a validated declaration; generated code never reaches disk."""
    spec = (args or {}).get("spec")
    errors = validate_widget_spec(spec)
    if errors:
        return {"ok": False, "errors": errors}
    if spec["id"] in _SYSTEM_WIDGET_IDS:
        return {"ok": False, "error": "cannot replace a system widget"}
    if not _SPECS_PATH or not _WRITE_TEXT:
        return {"ok": False, "error": "widget spec storage unavailable"}

    items, storage_error = _load_raw_spec_items()
    if storage_error:
        return {"ok": False, "error": storage_error}
    by_id = {
        item.get("spec", {}).get("id"): item
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("spec"), dict)
        and not validate_widget_spec(item["spec"])
    }
    previous = by_id.get(spec["id"])
    revision = int((previous or {}).get("revision") or 0) + 1
    enabled = (previous or {}).get("enabled") is not False
    by_id[spec["id"]] = {
        "spec": spec,
        "enabled": enabled,
        "revision": revision,
    }
    if len(by_id) > 20:
        return {"ok": False, "error": "最多安装 20 个动态组件"}
    retained_unknown = [
        item for item in items
        if not (
            isinstance(item, dict)
            and isinstance(item.get("spec"), dict)
            and not validate_widget_spec(item["spec"])
        )
    ]
    _write_installed_specs(retained_unknown + [by_id[key] for key in sorted(by_id)])
    return {
        "ok": True,
        "installed": spec["id"],
        "operation": "updated" if previous else "installed",
        "enabled": enabled,
    }


def _write_installed_specs(items: list[dict]) -> None:
    _WRITE_TEXT(
        _SPECS_PATH(),
        json.dumps({"version": 1, "items": items}, ensure_ascii=False, indent=2),
        rotate=True,
    )


def tool_set_widget_enabled(args: dict) -> dict:
    widget_id = str((args or {}).get("id") or "").strip()
    enabled = (args or {}).get("enabled")
    if not widget_id or not isinstance(enabled, bool):
        return {"ok": False, "error": "id and boolean enabled are required"}
    items, storage_error = _load_raw_spec_items()
    if storage_error:
        return {"ok": False, "error": storage_error}
    for item in items:
        if (
            isinstance(item, dict)
            and isinstance(item.get("spec"), dict)
            and not validate_widget_spec(item["spec"])
            and item["spec"]["id"] == widget_id
        ):
            item["enabled"] = enabled
            if not _SPECS_PATH or not _WRITE_TEXT:
                return {"ok": False, "error": "widget spec storage unavailable"}
            _write_installed_specs(items)
            return {"ok": True, "id": widget_id, "enabled": enabled, "source": "ai-added"}
    if not _SET_SYSTEM_WIDGET_ENABLED:
        return {"ok": False, "error": f"widget '{widget_id}' not found"}
    try:
        result = _SET_SYSTEM_WIDGET_ENABLED({"id": widget_id, "enabled": enabled})
        return {**result, "id": widget_id, "source": "system"}
    except Exception as exc:
        return {"ok": False, "error": str(getattr(exc, "detail", exc))}


def tool_remove_widget(args: dict) -> dict:
    widget_id = str((args or {}).get("id") or "").strip()
    if not widget_id:
        return {"ok": False, "error": "id is required"}
    if widget_id in _SYSTEM_WIDGET_IDS:
        return {"ok": False, "error": "system widgets can be disabled but not removed"}
    if not _SPECS_PATH or not _WRITE_TEXT:
        return {"ok": False, "error": "widget spec storage unavailable"}
    items, storage_error = _load_raw_spec_items()
    if storage_error:
        return {"ok": False, "error": storage_error}
    kept = [
        item for item in items
        if not (
            isinstance(item, dict)
            and isinstance(item.get("spec"), dict)
            and not validate_widget_spec(item["spec"])
            and item["spec"]["id"] == widget_id
        )
    ]
    if len(kept) == len(items):
        return {"ok": False, "error": f"widget '{widget_id}' not found"}
    _write_installed_specs(kept)
    return {"ok": True, "removed": widget_id}
