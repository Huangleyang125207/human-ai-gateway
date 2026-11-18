---
name: gateway-memo
description: Create and manage one-time or recurring memos through deterministic series and occurrence transitions. Load for reminders, recurrence, snoozing, completion, skipping, pausing, or archiving.
---

# Gateway Memo

Use `list_memos` before updating or acting on an existing memo. Treat
`series_id` and `occurrence_id` as opaque values returned by the tool.

- Use `create_memo` with timezone-bearing ISO time and an explicit schedule.
- Use `update_memo` for text, due time, recurrence, or reminder preference.
- Use `act_on_memo` for complete, skip, or snooze.
- Use `manage_memo_series` for pause, resume, or archive.
- Do not claim that reminders wake the app; the background AI scheduler is not implemented.
- Do not create from OCR until the user confirms the extracted text and time.
