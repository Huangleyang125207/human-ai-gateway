"""Host integrity checks for registered AI tools.

Skills describe workflows. Domain writes are not gated by keyword matching or
confirmation; their authorship, schema and persistence guards stay owned by
the domain. This boundary only rejects unknown tools and image observations
that do not refer to an attachment visible in the current turn.
"""
from __future__ import annotations

from datetime import date, datetime


READ = "read"
LOCAL_WRITE = "local_reversible_write"
DESTRUCTIVE = "destructive"
EXTERNAL_WRITE = "external_write"

TOOL_EFFECTS = {
    # Widget
    "list_widgets": READ,
    "search_widget_capabilities": READ,
    "validate_widget_spec": READ,
    "install_widget_spec": LOCAL_WRITE,
    "set_widget_enabled": LOCAL_WRITE,
    "remove_widget": DESTRUCTIVE,
    # Memo
    "list_memos": READ,
    "create_memo": LOCAL_WRITE,
    "update_memo": LOCAL_WRITE,
    "act_on_memo": LOCAL_WRITE,
    "manage_memo_series": LOCAL_WRITE,
    # Journal and care
    "read_today_schedule": READ,
    "list_recent_days": READ,
    "search_text": READ,
    "read_text": READ,
    "patch_journal_block": LOCAL_WRITE,
    "insert_journal_block": LOCAL_WRITE,
    "append_journal_comment": LOCAL_WRITE,
    "manage_daily_task": LOCAL_WRITE,
    "check_daily_task": LOCAL_WRITE,
    "set_daily_task_meta": LOCAL_WRITE,
    "set_daily_task_image": LOCAL_WRITE,
    "set_water_cup_image": LOCAL_WRITE,
    "manage_tag_aggregate": LOCAL_WRITE,
    "get_daily_care_state": READ,
    "delete_journal_entry": DESTRUCTIVE,
    "manage_mood": LOCAL_WRITE,
    # Photos
    "record_image_observation": LOCAL_WRITE,
    "vision_classify": READ,
    "list_my_uploads": READ,
    "search_my_uploads": READ,
    "ask_photo_curator": READ,
    "place_scrapbook_image": LOCAL_WRITE,
    "manage_scrapbook": LOCAL_WRITE,
    "delete_attachment": DESTRUCTIVE,
    # Web and runtime
    "web_search": READ,
    "fetch_url": READ,
    "search_skills": READ,
    "load_skill": READ,
    "read_skill_resource": READ,
    "load_protocol": READ,
}

def _valid_iso_date(value: object) -> str | None:
    raw = str(value or "").strip()
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None
    return parsed.isoformat() if parsed.isoformat() == raw else None


def build_action_context(
    user_text: str,
    context: dict | None = None,
    recent_user_texts: list[str] | None = None,
) -> dict:
    """Build policy context only from trusted user-turn fields, never tool output."""
    current = str(user_text or "")
    trusted_view_date = _valid_iso_date((context or {}).get("view_date"))
    return {
        "origin": "user",
        "user_text": current,
        "scope_text": current,
        "has_image_refs": any(
            isinstance(ref, dict) and ref.get("kind") == "image"
            for ref in (context or {}).get("refs", [])
        ),
        "image_urls": [
            str((ref.get("payload") or {}).get("url") or "")
            for ref in (context or {}).get("refs", [])
            if isinstance(ref, dict) and ref.get("kind") == "image"
        ],
        "view_date": trusted_view_date,
    }


def authorize_tool(
    name: str, args: dict | None, action_context: dict | None, *, today: date | None = None,
) -> dict | None:
    effect = TOOL_EFFECTS.get(name)
    if effect is None:
        return {"ok": False, "error": f"tool policy missing: {name}", "effect": "unknown"}
    if name == "record_image_observation":
        url = str((args or {}).get("attachment_url") or "")
        if url not in set((action_context or {}).get("image_urls") or []):
            return {
                "ok": False,
                "error": "host policy blocked record_image_observation: attachment is not visible in this turn",
                "effect": LOCAL_WRITE,
                "requires_confirmation": False,
            }
        return None
    return None
