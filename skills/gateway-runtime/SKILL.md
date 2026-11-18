---
name: gateway-runtime
description: Discover and load Gateway Skills, paged resources, and detailed protocols. Load when a task crosses domains or the required workflow is unclear.
---

# Gateway Runtime

Use `search_skills` to discover domain workflows and `load_skill` before a
multi-step or high-impact task. Use `load_protocol` for detailed format
contracts such as `schedule`.

When a Skill lists a long reference, use `read_skill_resource` repeatedly
until `eof=true`; do not assume the first chunk is the whole document.

Skills explain how to work. They never authorize actions. The host derives
side-effect permission from the active user request and may reject a tool call
that exceeds that scope.
