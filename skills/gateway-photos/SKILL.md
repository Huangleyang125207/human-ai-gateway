---
name: gateway-photos
description: Classify, retrieve, place, and explicitly delete user-owned images. Load for photo lookup, OCR-like inspection, scrapbook placement, visual classification, or attachment deletion.
---

# Gateway Photos

Use only URLs returned by the current user message or photo tools.

- Use `ask_photo_curator` for semantic or cross-name lookup.
- Use `search_my_uploads` for exact filename, OCR, or keyword lookup.
- Use `list_my_uploads` to establish the available inventory.
- New images are read directly by the main model. After actually seeing a current-turn image,
  call `record_image_observation` once with its logical attachment URL, an objective description,
  visible OCR text, and any supported structured fields. The host rejects historical or missing
  attachments and merges this observation without erasing deterministic metadata.
- Use `vision_classify` only when cached classification is insufficient or an older image needs
  explicit reclassification. A durable pending queue retries missed indexing after restart.
- Use `place_scrapbook_image` only after resolving date and anchor time.
- Use `manage_scrapbook` to list or reposition an existing sticker; remove only on an explicit deletion request.
- Use `delete_attachment` only on an explicit deletion request.
- Display every returned photo with its exact relative URL; never invent a host.
