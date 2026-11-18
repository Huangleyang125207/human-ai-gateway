# PATTERN: service — attachment file/index operations with explicit effects
# USE WHEN: changing attachment serve/list/search/delete/reindex behavior
# COPY THIS: inject directory and index functions

import re
from pathlib import Path

from image_service_errors import ImageServiceError


def _is_ai_visible_attachment(item: dict) -> bool:
    return (item.get("asset_role") != "derived"
            and not str(item.get("filename") or item.get("original") or "").lower().endswith(".cutout.png"))


def resolve_attachment_path(attachments_dir, date: str, name: str, *, require_exists: bool = True) -> Path:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(date or "")):
        raise ImageServiceError(400, "bad date")
    name = str(name or "")
    if not name or "/" in name or "\\" in name or ".." in name:
        raise ImageServiceError(400, "bad name")
    root = Path(attachments_dir).resolve()
    path = (root / date / name).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ImageServiceError(400, "attachment escapes root") from exc
    if require_exists and (not path.exists() or not path.is_file()):
        raise ImageServiceError(404, "not found")
    return path


def resolve_attachment_url(attachments_dir, url: str, *, require_exists: bool = True) -> Path:
    match = re.fullmatch(r"/attachments/([^/]+)/([^/]+)", str(url or "").strip())
    if not match:
        raise ImageServiceError(400, f"bad attachment_url: {url}")
    return resolve_attachment_path(
        attachments_dir,
        match.group(1),
        match.group(2),
        require_exists=require_exists,
    )


class AttachmentService:
    def __init__(
        self,
        *,
        attachments_dir,
        load_index,
        save_index,
        index_attachment,
    ):
        self.attachments_dir = Path(attachments_dir)
        self.load_index = load_index
        self.save_index = save_index
        self.index_attachment = index_attachment

    def resolve_file(self, date: str, name: str) -> Path:
        return resolve_attachment_path(self.attachments_dir, date, name)

    def list(self, date_from: str, date_to: str, limit: int) -> dict:
        items = [item for item in self.load_index() if _is_ai_visible_attachment(item)]
        if date_from:
            items = [
                item
                for item in items
                if item.get("date", "") >= date_from
            ]
        if date_to:
            items = [
                item
                for item in items
                if item.get("date", "") <= date_to
            ]
        items = sorted(
            items,
            key=lambda item: (
                item.get("date", ""),
                item.get("filename", ""),
            ),
            reverse=True,
        )
        return {"items": items[:limit], "total": len(items)}

    def search(self, query: str, limit: int) -> dict:
        if not query:
            return {"items": [], "query": query}
        query_lower = query.lower()
        hits = []
        for item in self.load_index():
            if not _is_ai_visible_attachment(item):
                continue
            haystack = (
                item.get("filename", "")
                + " "
                + item.get("original", "")
                + " "
                + item.get("ocr_text", "")
            ).lower()
            if query_lower in haystack:
                hits.append(item)
        hits = sorted(
            hits,
            key=lambda item: item.get("date", ""),
            reverse=True,
        )
        return {
            "items": hits[:limit],
            "query": query,
            "total": len(hits),
        }

    def delete(self, body: dict) -> dict:
        date = (body.get("date") or "").strip()
        filename = (body.get("filename") or "").strip()
        if not date or not filename:
            raise ImageServiceError(400, "need {date, filename} (no path traversal)")
        path = resolve_attachment_path(
            self.attachments_dir,
            date,
            filename,
            require_exists=False,
        )
        if path.exists():
            try:
                path.unlink()
            except Exception as e:
                raise ImageServiceError(
                    500,
                    f"delete file failed: {e}",
                ) from e
        items = [
            item
            for item in self.load_index()
            if not (
                item.get("date") == date
                and item.get("filename") == filename
            )
        ]
        self.save_index(items)
        return {"ok": True, "removed": filename}

    def reindex(self) -> dict:
        if not self.attachments_dir.exists():
            return {"ok": True, "indexed": 0, "skipped": 0}
        existing_keys = {
            (item.get("date"), item.get("filename"))
            for item in self.load_index()
        }
        indexed = 0
        skipped = 0
        for day_dir in sorted(self.attachments_dir.iterdir()):
            if (
                day_dir.is_symlink()
                or
                not day_dir.is_dir()
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_dir.name)
            ):
                continue
            for entry in sorted(day_dir.iterdir()):
                if (entry.name.startswith("_") or entry.name.startswith(".")
                        or entry.name.lower().endswith(".cutout.png")):
                    continue
                try:
                    path = resolve_attachment_path(self.attachments_dir, day_dir.name, entry.name)
                except ImageServiceError:
                    continue
                key = (day_dir.name, entry.name)
                if key in existing_keys:
                    skipped += 1
                    continue
                self.index_attachment(
                    day_dir.name,
                    entry.name,
                    "",
                    path.stat().st_size,
                )
                indexed += 1
        return {"ok": True, "indexed": indexed, "skipped": skipped}
