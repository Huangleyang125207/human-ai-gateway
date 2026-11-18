# PATTERN: api — search/journal 检索/杂项 LLM 工具 extracted from god module (Parallel Change)
# USE WHEN: grep-like Markdown 检索/读取 / delete_attachment / task meta / load_protocol 工具面改动
# COPY THIS: 无 — 本模块是 server.py §8(清册01)的搬迁体,契约在 server re-export
#
# 抽出记录(2026-07-21, 清册01-§8):
# - 原址 server.py L1486–1567 + L1581–1587;server.py 保留同名 re-export(Parallel Change)。
# - VAULT/attachments/索引/meta/protocol 通过命名 provider 由组装根注入；
#   不使用可访问任意属性的 service locator。

from attachment_service import resolve_attachment_path
from image_service_errors import ImageServiceError


_VAULT_DIR = None
_ATTACHMENTS_DIR = None
_LOAD_ATTACHMENTS_INDEX = None
_SAVE_ATTACHMENTS_INDEX = None
_LOAD_TASK_META = None
_SAVE_TASK_META = None
_TASK_META_STATE = None
_PROTOCOLS = None
_LOAD_PROTOCOL = None


def configure_effects(
    *,
    vault_dir,
    attachments_dir,
    load_attachments_index,
    save_attachments_index,
    load_task_meta,
    save_task_meta,
    task_meta_state,
    protocols,
    load_protocol,
) -> None:
    global _VAULT_DIR, _ATTACHMENTS_DIR
    global _LOAD_ATTACHMENTS_INDEX, _SAVE_ATTACHMENTS_INDEX
    global _LOAD_TASK_META, _SAVE_TASK_META, _TASK_META_STATE
    global _PROTOCOLS, _LOAD_PROTOCOL
    _VAULT_DIR = vault_dir
    _ATTACHMENTS_DIR = attachments_dir
    _LOAD_ATTACHMENTS_INDEX = load_attachments_index
    _SAVE_ATTACHMENTS_INDEX = save_attachments_index
    _LOAD_TASK_META = load_task_meta
    _SAVE_TASK_META = save_task_meta
    _TASK_META_STATE = task_meta_state
    _PROTOCOLS = protocols
    _LOAD_PROTOCOL = load_protocol


def _clamp_int(value, default, low, high):
    try:
        return max(low, min(int(value), high))
    except (TypeError, ValueError):
        return default


def _is_visible_markdown(relative):
    return (
        relative.suffix.lower() == ".md"
        and "attachments" not in relative.parts
        and ".git" not in relative.parts
        and not any(part.startswith(".") for part in relative.parts)
    )


def _visible_markdown_files():
    vault = _VAULT_DIR().resolve()
    if not vault.exists():
        return vault, []
    visible = []
    for candidate in vault.rglob("*.md"):
        try:
            resolved = candidate.resolve()
            relative = resolved.relative_to(vault)
        except (OSError, ValueError):
            continue
        if resolved.is_file() and _is_visible_markdown(relative):
            visible.append((relative.as_posix(), resolved))
    visible.sort(key=lambda item: item[0])
    return vault, visible


def _resolve_visible_markdown(file_arg):
    raw = str(file_arg or "").strip()
    vault = _VAULT_DIR().resolve()
    if not raw or not vault.exists():
        return None
    try:
        candidate = (vault / raw).resolve()
        relative = candidate.relative_to(vault)
    except (OSError, ValueError):
        return None
    if not candidate.is_file() or not _is_visible_markdown(relative):
        return None
    return relative.as_posix(), candidate


def tool_search_text(args):
    """Grep-like literal search over the current Markdown source of truth."""
    q = (args.get("query") or "").strip()
    if not q:
        return {"error": "need query"}
    limit = _clamp_int(args.get("limit"), 20, 1, 100)
    context_lines = _clamp_int(args.get("context_lines"), 2, 0, 5)
    case_sensitive = bool(args.get("case_sensitive", False))
    needle = q if case_sensitive else q.lower()
    vault_dir, files = _visible_markdown_files()
    if not vault_dir.exists():
        return {"error": "vault not found"}

    hits = []
    for relative, path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for i, line in enumerate(lines):
            haystack = line if case_sensitive else line.lower()
            if needle in haystack:
                ctx_start = max(0, i - context_lines)
                ctx_end = min(len(lines), i + context_lines + 1)
                ctx = "\n".join(lines[ctx_start:ctx_end])
                hits.append({
                    "file": relative,
                    "line": i + 1,
                    "context": ctx,
                })
    return {"ok": True, "matches": hits[:limit], "total_hits": len(hits), "truncated": len(hits) > limit}


def tool_read_text(args):
    """Read a bounded line range from a visible Markdown file in the vault."""
    resolved = _resolve_visible_markdown(args.get("file"))
    if not resolved:
        return {"error": "file is not a readable Markdown path"}
    relative, path = resolved
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return {"error": "failed to read Markdown file"}
    start = _clamp_int(args.get("start_line"), 1, 1, max(1, len(lines) + 1))
    count = _clamp_int(args.get("line_count"), 80, 1, 200)
    chunk = lines[start - 1:start - 1 + count]
    end = start + len(chunk) - 1
    return {
        "ok": True,
        "file": relative,
        "start_line": start,
        "end_line": end,
        "total_lines": len(lines),
        "content": "\n".join(chunk),
        "eof": start - 1 + len(chunk) >= len(lines),
    }


def tool_delete_attachment(args):
    date = (args.get("date") or "").strip()
    filename = (args.get("filename") or "").strip()
    if not date or not filename:
        return {"error": "need {date, filename} (no path traversal)"}
    try:
        f = resolve_attachment_path(_ATTACHMENTS_DIR(), date, filename, require_exists=False)
    except ImageServiceError as exc:
        return {"error": exc.detail}
    if f.exists():
        try:
            f.unlink()
        except Exception as e:
            return {"error": f"delete failed: {e}"}
    arr = _LOAD_ATTACHMENTS_INDEX()
    arr = [x for x in arr if not (x.get("date") == date and x.get("filename") == filename)]
    _SAVE_ATTACHMENTS_INDEX(arr)
    return {"ok": True, "removed": filename}


def tool_set_daily_task_meta(args):
    name = (args.get("task_name") or "").strip()
    if not name:
        return {"error": "need task_name"}
    meta_map = _LOAD_TASK_META()
    entry = dict(meta_map.get(name) or {})
    if "total_pills" in args and args["total_pills"] not in (None, "", 0):
        try:
            entry["total_pills"] = max(1, int(args["total_pills"]))
        except (TypeError, ValueError):
            return {"error": "total_pills must be int"}
    if "daily_dose" in args and args["daily_dose"] is not None:
        try:
            entry["daily_dose"] = max(1, int(args["daily_dose"]))
        except (TypeError, ValueError):
            return {"error": "daily_dose must be int"}
    meta_map[name] = entry
    _SAVE_TASK_META(meta_map)
    return {"ok": True, "task_name": name, **_TASK_META_STATE(name, meta_map)}

def tool_load_protocol(args):
    """读 protocols/{name}.md 给 AI。延迟加载详细协议规则,baseline prompt 保持精简。"""
    name = (args.get("name") or "").strip()
    if not name:
        return {"error": "need name", "available": list(_PROTOCOLS().keys())}
    content = _LOAD_PROTOCOL(name)
    return {"name": name, "content": content}
