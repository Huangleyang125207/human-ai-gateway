# PATTERN: service — attachment-backed vision classification
# USE WHEN: validating attachment URLs before invoking a vision backend
# COPY THIS: inject attachment root and classifier

from attachment_service import resolve_attachment_url
from image_service_errors import ImageServiceError


class VisionService:
    def __init__(self, *, attachments_dir, classify_image):
        self.attachments_dir = attachments_dir
        self.classify_image = classify_image

    def classify(self, body: dict):
        url = (body.get("attachment_url") or "").strip()
        extra_question = (body.get("extra_question") or "").strip()
        if not url:
            raise ImageServiceError(400, "need attachment_url")
        path = resolve_attachment_url(self.attachments_dir, url)
        return self.classify_image(path, extra_question)
