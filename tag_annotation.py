"""AI-assisted tag metadata enrichment, isolated from aggregate persistence.

Model calls always happen outside the Markdown lock.  The writer then re-reads
the section and fills only fields that are still missing, so a human edit made
while the model was running always wins.
"""

import threading

from tag_vocabulary import (
    apply_tag_metadata,
    build_annotation_prompt,
    missing_metadata_tags,
    parse_annotation_response,
)


_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT: set[str] = set()


def enrich_tag_metadata(
    *,
    path,
    parse_aggregate,
    lock_factory,
    write_text,
    call_model,
    tags=None,
    commit_after_write=None,
) -> dict:
    with lock_factory(str(path)):
        if not path.exists():
            return {"ok": True, "enriched": [], "skipped": "missing aggregate"}
        snapshot = path.read_text(encoding="utf-8")
    sections = parse_aggregate(snapshot)
    pending = set(missing_metadata_tags(sections))
    if tags is not None:
        pending &= {str(tag) for tag in tags}
    by_tag = {section["tag"]: section for section in sections}
    enriched = []
    errors = {}
    for tag in sorted(pending):
        samples = [row.get("content", "") for row in by_tag[tag].get("rows", []) if row.get("content")]
        try:
            metadata = parse_annotation_response(
                call_model(build_annotation_prompt(tag, samples))
            )
            with lock_factory(str(path)):
                current = path.read_text(encoding="utf-8")
                current_sections = parse_aggregate(current)
                if tag not in missing_metadata_tags(current_sections):
                    continue
                next_text = apply_tag_metadata(current, tag, metadata, only_if_missing=True)
                if next_text != current:
                    write_text(path, next_text, rotate=True)
                    if commit_after_write:
                        commit_after_write(path, tag)
                    enriched.append(tag)
        except Exception as exc:
            errors[tag] = f"{type(exc).__name__}: {exc}"
    return {"ok": not errors, "enriched": enriched, "errors": errors}


def schedule_tag_metadata_enrichment(*, tags, runner, logger) -> bool:
    """Start one daemon task per tag at most; journal writes never wait for it."""
    requested = {str(tag) for tag in (tags or []) if str(tag)}
    if not requested:
        return False
    with _INFLIGHT_LOCK:
        fresh = requested - _INFLIGHT
        if not fresh:
            return False
        _INFLIGHT.update(fresh)

    def work():
        try:
            runner(fresh)
        except Exception:
            logger.exception("tag metadata enrichment failed")
        finally:
            with _INFLIGHT_LOCK:
                _INFLIGHT.difference_update(fresh)

    threading.Thread(target=work, name="tag-metadata", daemon=True).start()
    return True
