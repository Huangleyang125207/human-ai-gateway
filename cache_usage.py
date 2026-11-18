"""Privacy-safe DeepSeek prompt-cache observations and reports.

The JSONL contract intentionally excludes messages, prompts, responses and keys.
It is shared by runtime call sites and the reusable inspection CLI.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from runtime_paths import DATA_DIR


CACHE_USAGE_PATH = DATA_DIR / "llm-cache-usage.jsonl"
_MAX_BYTES = 2 * 1024 * 1024
_KEEP_LINES = 2000
_WRITE_LOCK = threading.Lock()


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def build_cache_record(response: Any, *, source: str, model: str | None = None) -> dict:
    usage = _field(response, "usage")
    has_hit = usage is not None and _field(usage, "prompt_cache_hit_tokens") is not None
    has_miss = usage is not None and _field(usage, "prompt_cache_miss_tokens") is not None
    hit = int(_field(usage, "prompt_cache_hit_tokens", 0) or 0)
    miss = int(_field(usage, "prompt_cache_miss_tokens", 0) or 0)
    prompt = int(_field(usage, "prompt_tokens", hit + miss) or (hit + miss))
    return {
        "at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "model": str(model or _field(response, "model", "unknown") or "unknown"),
        "request_id": _field(response, "id"),
        "system_fingerprint": _field(response, "system_fingerprint"),
        "hit_tokens": hit,
        "miss_tokens": miss,
        "prompt_tokens": prompt,
        "cache_fields_present": bool(has_hit and has_miss),
    }


def append_cache_record(row: dict, path: Path = CACHE_USAGE_PATH) -> None:
    with _WRITE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        if path.stat().st_size <= _MAX_BYTES:
            return
        lines = path.read_text(encoding="utf-8").splitlines()[-_KEEP_LINES:]
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(path)


def record_cache_usage(
    response: Any,
    *,
    source: str,
    model: str | None = None,
    path: Path = CACHE_USAGE_PATH,
) -> dict | None:
    if _field(response, "usage") is None:
        return None
    row = build_cache_record(response, source=source, model=model)
    append_cache_record(row, path)
    return row


def load_cache_records(
    path: Path = CACHE_USAGE_PATH,
    *,
    source: str | None = None,
    model: str | None = None,
    since: str | None = None,
) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(row, dict):
            continue
        if source and row.get("source") != source:
            continue
        if model and row.get("model") != model:
            continue
        if since and str(row.get("at") or "") < since:
            continue
        rows.append(row)
    return rows


def _summary(rows: Iterable[dict]) -> dict:
    items = list(rows)
    observed = [r for r in items if r.get("cache_fields_present")]
    hit = sum(int(r.get("hit_tokens") or 0) for r in observed)
    miss = sum(int(r.get("miss_tokens") or 0) for r in observed)
    token_total = hit + miss
    hit_requests = sum(1 for r in observed if int(r.get("hit_tokens") or 0) > 0)
    return {
        "requests": len(items),
        "observed_requests": len(observed),
        "missing_usage_requests": len(items) - len(observed),
        "hit_tokens": hit,
        "miss_tokens": miss,
        "token_hit_rate": (hit / token_total) if token_total else None,
        "request_hit_rate": (hit_requests / len(observed)) if observed else None,
    }


def summarize_cache_records(rows: Iterable[dict]) -> dict:
    items = list(rows)
    report = _summary(items)
    grouped: dict[str, list[dict]] = {}
    for row in items:
        key = f"{row.get('source', 'unknown')}|{row.get('model', 'unknown')}"
        grouped.setdefault(key, []).append(row)
    report["groups"] = {key: _summary(grouped[key]) for key in sorted(grouped)}
    return report
