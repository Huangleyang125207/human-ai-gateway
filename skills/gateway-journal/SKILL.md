---
name: gateway-journal
description: Read, search, add, revise, and comment on journal entries while preserving Markdown structure and authorship. Load for diary lookup, scheduling, entry creation, correction, or commentary.
---

# Gateway Journal

Read before writing. Use `read_today_schedule`, `list_recent_days`, or
`search_text` to locate the target date, block, and author. Use `read_text`
only when a search result needs more surrounding lines.

Before `patch_journal_block` or `insert_journal_block`, load the `schedule`
protocol. Preserve time-block structure and authorship markers.

- Use `insert_journal_block` for a new entry.
- Use `patch_journal_block` only for an existing editable block.
- Set `allow_h2_rename=true` only when the user explicitly requests a title change.
- Use `append_journal_comment` when the original user-authored entry must remain intact.
- Use `delete_journal_entry` only after identifying the exact time and H2 index and only when the user explicitly asks to delete it.
- Use `manage_tag_aggregate` to list registered project tags; registering a tag also backfills its historical rows.
- Report success only after the tool returns success.
