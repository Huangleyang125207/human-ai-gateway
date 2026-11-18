# PATTERN: service — cutout persistence with OCR metadata side effect
# USE WHEN: changing processed task images or OCR-derived pill totals
# COPY THIS: inject image, task-map, OCR, config, and logging effects

from pathlib import Path

from attachment_service import resolve_attachment_url
from image_service_errors import ImageServiceError


class CutoutService:
    def __init__(
        self,
        *,
        attachments_dir,
        task_images_dir,
        process_attachment,
        sanitize_task_filename,
        pretty_rel,
        load_image_map,
        save_image_map,
        load_meta_map,
        save_meta_map,
        ocr_text,
        parse_pill_count,
        load_config,
        logger,
    ):
        self.attachments_dir = Path(attachments_dir)
        self.task_images_dir = Path(task_images_dir)
        self.process_attachment = process_attachment
        self.sanitize_task_filename = sanitize_task_filename
        self.pretty_rel = pretty_rel
        self.load_image_map = load_image_map
        self.save_image_map = save_image_map
        self.load_meta_map = load_meta_map
        self.save_meta_map = save_meta_map
        self.ocr_text = ocr_text
        self.parse_pill_count = parse_pill_count
        self.load_config = load_config
        self.logger = logger

    def cutout(self, body: dict) -> dict:
        url = (body.get("attachment_url") or "").strip()
        task_name = (body.get("task_name") or "").strip()
        if not url or not task_name:
            raise ImageServiceError(
                400,
                "need {attachment_url, task_name}",
            )
        source = resolve_attachment_url(self.attachments_dir, url)
        processed, error = self.process_attachment(url)
        if error:
            raise ImageServiceError(502, error)
        self.task_images_dir.mkdir(parents=True, exist_ok=True)
        stem = self.sanitize_task_filename(task_name)
        output = self.task_images_dir / f"{stem}.png"
        output.write_bytes(processed.read_bytes())
        relative = self.pretty_rel(output)
        image_map = self.load_image_map()
        image_map[task_name] = relative
        self.save_image_map(image_map)
        self.load_config()
        pill_count = None
        try:
            pill_count = self.parse_pill_count(self.ocr_text(source))
            if pill_count:
                meta_map = self.load_meta_map()
                current = meta_map.get(task_name) or {}
                if not current.get("total_pills"):
                    current["total_pills"] = pill_count
                    meta_map[task_name] = current
                    self.save_meta_map(meta_map)
        except Exception as e:
            self.logger.warning(
                f"cutout OCR sidecar failed: {type(e).__name__}: {e}"
            )
        return {
            "ok": True,
            "task_name": task_name,
            "image_url": f"/{relative}",
            "ocr_pill_count": pill_count,
        }
