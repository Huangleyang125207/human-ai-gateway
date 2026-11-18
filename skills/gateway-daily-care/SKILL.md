---
name: gateway-daily-care
description: Manage recurring daily tasks, completion state, dosage metadata, and task imagery. Load for check-ins, supplements, exercise habits, water-cup appearance, task creation, rename, or deletion.
---

# Gateway Daily Care

Read today's schedule before changing a task. Resolve the current task name from
the returned candidates instead of inventing a name.
Use `get_daily_care_state` when the answer needs current inventory, water, or recent history.

- Use `manage_daily_task` to add, rename, or delete a recurring task.
- Use `check_daily_task` to check or uncheck today's occurrence.
- Use `set_daily_task_meta` for daily dose and inventory.
- Use `set_daily_task_image` or `set_water_cup_image` only with a user-owned image.
- Use `manage_mood` for the dated mood value; it is the same state used by the mood GUI.
- Delete or rename only when the user explicitly requests it.
- Let the host verify that the active user request authorizes each write; do not
  try to unlock tools from inside the model workflow.
