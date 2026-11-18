"""Progressively disclosed DeepSeek Skill registry.

The repository's ``skills/`` directory is the source of truth.  Search returns
only lightweight metadata; load returns the selected workflow and its explicit
live references.
"""
from __future__ import annotations

import json
from pathlib import Path

from runtime_paths import GATEWAY_DIR


SKILLS_DIR = GATEWAY_DIR / "skills"
REGISTRY_PATH = SKILLS_DIR / "registry.json"


def _parse_skill(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"missing YAML frontmatter: {path}")
    _, frontmatter, body = text.split("---\n", 2)
    meta: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip('"').strip("'")
    if not meta.get("name") or not meta.get("description"):
        raise ValueError(f"Skill needs name and description: {path}")
    return meta, body.lstrip()


def _safe_reference(relative: str) -> Path:
    candidate = (GATEWAY_DIR / relative).resolve()
    root = GATEWAY_DIR.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Skill reference escapes gateway: {relative}")
    return candidate


def _registry_items() -> list[dict]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if payload.get("version") != "1.0" or not isinstance(payload.get("skills"), list):
        raise ValueError("unsupported or invalid Skill registry")
    return payload["skills"]


def _entry(item: dict, *, references: bool) -> dict:
    name = str(item.get("name", ""))
    skill_file = SKILLS_DIR / name / "SKILL.md"
    meta, content = _parse_skill(skill_file)
    if meta["name"] != name:
        raise ValueError(f"registry/frontmatter name mismatch: {name}")
    result = {
        "name": name,
        "description": meta["description"],
        "tools": list(item.get("tools", [])),
        "content": content,
        "references": [],
    }
    if references:
        for relative in item.get("references", []):
            path = _safe_reference(relative)
            result["references"].append({
                "path": relative,
                "content": path.read_text(encoding="utf-8"),
            })
    else:
        result["references"] = [{"path": path} for path in item.get("references", [])]
    return result


def _find_item(name: str) -> dict | None:
    return next((item for item in _registry_items() if item.get("name") == name), None)


def skill_catalog() -> list[dict]:
    return [
        {"name": skill["name"], "description": skill["description"], "tools": list(skill["tools"])}
        for skill in (_entry(item, references=False) for item in _registry_items())
    ]


def render_skill_index() -> str:
    lines = [
        "=== Available Skills (load on demand) ===",
        "Use search_skills to discover a workflow, then load_skill before doing specialized work.",
        "Skills explain how to work; the host independently enforces the active user's action scope.",
    ]
    lines.extend(f"· {item['name']}: {item['description']}" for item in skill_catalog())
    return "\n".join(lines) + "\n"


def exported_skills() -> list[dict]:
    """Serializable full payload used by the RN generated prompt contract."""
    return [
        {**skill, "tools": list(skill["tools"]), "references": [dict(ref) for ref in skill["references"]]}
        for skill in (_entry(item, references=True) for item in _registry_items())
    ]


def tool_search_skills(args: dict | None) -> dict:
    query = str((args or {}).get("query", "")).strip().lower()
    skills = skill_catalog()
    if query:
        skills = [
            item for item in skills
            if query in " ".join([item["name"], item["description"], *item["tools"]]).lower()
        ]
    return {"ok": True, "version": "1.0", "skills": skills}


def tool_load_skill(args: dict | None) -> dict:
    name = str((args or {}).get("name", "")).strip()
    item = _find_item(name)
    if item:
        skill = _entry(item, references=False)
        refs = []
        for ref in skill["references"]:
            path = _safe_reference(ref["path"])
            refs.append({"path": ref["path"], "chars": len(path.read_text(encoding="utf-8"))})
        return {"ok": True, **skill, "references": refs}
    return {"ok": False, "error": f"unknown skill: {name}", "available": [str(s.get("name")) for s in _registry_items()]}


def tool_read_skill_resource(args: dict | None) -> dict:
    args = args or {}
    name = str(args.get("name", "")).strip()
    relative = str(args.get("path", "")).strip()
    try:
        cursor = max(0, int(args.get("cursor") or 0))
        limit = max(256, min(int(args.get("limit") or 3000), 3500))
    except (TypeError, ValueError):
        return {"ok": False, "error": "cursor and limit must be integers"}
    item = _find_item(name)
    if item:
        if relative not in item.get("references", []):
            return {"ok": False, "error": f"resource is not declared by {name}: {relative}"}
        content = _safe_reference(relative).read_text(encoding="utf-8")
        chunk = content[cursor:cursor + limit]
        next_cursor = cursor + len(chunk)
        return {
            "ok": True,
            "name": name,
            "path": relative,
            "cursor": cursor,
            "content": chunk,
            "next_cursor": next_cursor,
            "eof": next_cursor >= len(content),
            "total_chars": len(content),
        }
    return {"ok": False, "error": f"unknown skill: {name}", "available": [str(s.get("name")) for s in _registry_items()]}
