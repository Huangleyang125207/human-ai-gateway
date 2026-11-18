---
name: gateway-widgets
description: Discover capabilities and safely design, validate, install, revise, enable, disable, or remove declarative WidgetSpec components. Load whenever the user asks to create or change a widget.
---

# Gateway Widgets

Build only declarative WidgetSpec documents. Never generate or install HTML,
CSS, JavaScript, internal HTTP calls, or arbitrary file writes.

For a new widget:

1. Call `search_widget_capabilities`.
2. Create a spec using only returned capabilities and supported views.
3. Call `validate_widget_spec` and repair every reported error.
4. Explain the title, data range, and behavior briefly.
5. Call `install_widget_spec` only after the user has requested creation or installation.

For an existing widget, call `list_widgets` first. Preserve the original `id`
when revising an AI-authored spec. System implementation widgets may be enabled
or disabled but not replaced. Use `remove_widget` only for AI-authored widgets
and only on an explicit removal request.

Skill guidance does not grant write permission. The host independently checks
the active user request before installing, changing visibility, or removing a
widget.
