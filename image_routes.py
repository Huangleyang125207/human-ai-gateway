"""image_routes — APIRouter for 图像簇:/api/attachments* + /api/cutout + /api/vision/classify.

Extract Module(ctrl-c-v § 9):图片/附件/抠图/AI看图 7 个 HTTP 端点从 server.py 抽出。
**双份回报**:缩 server + 这组 characterization 正好是移动 parity 台账缺的 N4-N8 oracle。
索引/vision/cutout helper + 常量全留 server.py(chat_routes 也 lazy-import),本模块走 function-body
lazy from server import(AST 精确探测,排除参数/本地名防 shadow)。HTTP-only → 不 re-export。
characterization:tests/test_image_routes.py(13)。
"""
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter(tags=["image"])

@router.get("/attachments/{date}/{name}")
def get_attachment(date: str, name: str):
    from server import ATTACHMENTS_DIR
    """serve uploaded images. date 必须 YYYY-MM-DD 格式,name 必须不含 path traversal。"""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise HTTPException(400, "bad date")
    if "/" in name or ".." in name:
        raise HTTPException(400, "bad name")
    f = ATTACHMENTS_DIR / date / name
    if not f.exists():
        raise HTTPException(404, "not found")
    return FileResponse(f)

@router.get("/api/attachments")
def attachments_list(date_from: str = "", date_to: str = "", limit: int = 100):
    from server import _load_attachments_index
    """前端 / AI 列 attachments(带 OCR 摘要)"""
    arr = _load_attachments_index()
    if date_from:
        arr = [x for x in arr if x.get("date", "") >= date_from]
    if date_to:
        arr = [x for x in arr if x.get("date", "") <= date_to]
    arr = sorted(arr, key=lambda x: (x.get("date", ""), x.get("filename", "")), reverse=True)
    return {"items": arr[:limit], "total": len(arr)}

@router.get("/api/attachments/search")
def attachments_search(q: str, limit: int = 30):
    from server import _load_attachments_index
    """grep 文件名 / 原名 / OCR 文本。"""
    if not q:
        return {"items": [], "query": q}
    arr = _load_attachments_index()
    ql = q.lower()
    hits = []
    for x in arr:
        hay = (x.get("filename", "") + " " + x.get("original", "") + " " + x.get("ocr_text", "")).lower()
        if ql in hay:
            hits.append(x)
    hits = sorted(hits, key=lambda x: x.get("date", ""), reverse=True)
    return {"items": hits[:limit], "query": q, "total": len(hits)}

@router.post("/api/attachments/delete")
async def attachments_delete(req: Request):
    from server import ATTACHMENTS_DIR, _load_attachments_index, _save_attachments_index
    """删 attachment 文件 + 索引条目。body: {date, filename}"""
    body = await req.json()
    date = (body.get("date") or "").strip()
    filename = (body.get("filename") or "").strip()
    if not date or not filename or "/" in filename or ".." in filename:
        raise HTTPException(400, "need {date, filename} (no path traversal)")
    f = ATTACHMENTS_DIR / date / filename
    if f.exists():
        try:
            f.unlink()
        except Exception as e:
            raise HTTPException(500, f"delete file failed: {e}")
    arr = _load_attachments_index()
    arr = [x for x in arr if not (x.get("date") == date and x.get("filename") == filename)]
    _save_attachments_index(arr)
    return {"ok": True, "removed": filename}

@router.post("/api/attachments/reindex")
def attachments_reindex():
    from server import ATTACHMENTS_DIR, _index_attachment, _load_attachments_index
    """扫 attachments 目录,把没进索引的图都补 OCR 一遍。
    用户首次启用文件管理,或索引丢了,调一次。"""
    if not ATTACHMENTS_DIR.exists():
        return {"ok": True, "indexed": 0, "skipped": 0}
    existing = _load_attachments_index()
    existing_keys = {(x.get("date"), x.get("filename")) for x in existing}
    indexed = 0
    skipped = 0
    for day_dir in sorted(ATTACHMENTS_DIR.iterdir()):
        if not day_dir.is_dir() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_dir.name):
            continue
        for f in sorted(day_dir.iterdir()):
            if not f.is_file() or f.name.startswith("_") or f.name.startswith("."):
                continue
            key = (day_dir.name, f.name)
            if key in existing_keys:
                skipped += 1
                continue
            _index_attachment(day_dir.name, f.name, "", f.stat().st_size)
            indexed += 1
    return {"ok": True, "indexed": indexed, "skipped": skipped}

@router.post("/api/cutout")
async def cutout_image(req: Request):
    from server import ATTACHMENTS_DIR, DAILY_TASK_IMAGES_DIR, _get_or_create_processed_attachment, _load_task_image_map, _load_task_meta_map, _ocr_text, _parse_pill_count_from_ocr, _pretty_rel, _sanitize_task_filename, _save_task_image_map, _save_task_meta_map, load_config, log
    """对一张已经上传的图(/attachments/...)做去背,存为某 task 的 image。
    body: {attachment_url: "/attachments/YYYY-MM-DD/xxx.jpg", task_name: "鱼油（Swisse）"}
    成功返 {ok, task_name, image_url}
    """
    body = await req.json()
    url = (body.get("attachment_url") or "").strip()
    task_name = (body.get("task_name") or "").strip()
    if not url or not task_name:
        raise HTTPException(400, "need {attachment_url, task_name}")

    m = re.match(r"^/attachments/([^/]+)/([^/]+)$", url)
    if not m:
        raise HTTPException(400, f"bad attachment_url: {url}")
    src = ATTACHMENTS_DIR / m.group(1) / m.group(2)
    if not src.exists():
        raise HTTPException(404, f"attachment not found: {url}")

    processed, err = _get_or_create_processed_attachment(url)
    if err:
        raise HTTPException(502, err)

    DAILY_TASK_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    stem = _sanitize_task_filename(task_name)
    out_file = DAILY_TASK_IMAGES_DIR / f"{stem}.png"
    out_file.write_bytes(processed.read_bytes())

    rel = _pretty_rel(out_file)
    image_map = _load_task_image_map()
    image_map[task_name] = rel
    _save_task_image_map(image_map)

    # 顺带跑 OCR 抽颗数(用原图,不用抠图后的)。失败/无识别都不阻断 cutout 流。
    cfg = load_config() or {}
    ocr_pill_count = None
    try:
        ocr_text = _ocr_text(src)
        ocr_pill_count = _parse_pill_count_from_ocr(ocr_text)
        if ocr_pill_count:
            # 只在 meta 还没填过 total 时自动写入(尊重用户已有手填)
            meta_map = _load_task_meta_map()
            cur = meta_map.get(task_name) or {}
            if not cur.get("total_pills"):
                cur["total_pills"] = ocr_pill_count
                meta_map[task_name] = cur
                _save_task_meta_map(meta_map)
    except Exception as e:
        log.warning(f"cutout OCR sidecar failed: {type(e).__name__}: {e}")

    return {
        "ok": True,
        "task_name": task_name,
        "image_url": f"/{rel}",
        "ocr_pill_count": ocr_pill_count,
    }

@router.post("/api/vision/classify")
async def vision_classify_endpoint(req: Request):
    from server import ATTACHMENTS_DIR, _gemini_classify_image
    """直接给前端用,不走 AI tool 那条路。
    body: {attachment_url, extra_question?}
    """
    body = await req.json()
    url = (body.get("attachment_url") or "").strip()
    extra_q = (body.get("extra_question") or "").strip()
    if not url:
        raise HTTPException(400, "need attachment_url")
    m = re.match(r"^/attachments/([^/]+)/([^/]+)$", url)
    if not m:
        raise HTTPException(400, f"bad attachment_url: {url}")
    f = ATTACHMENTS_DIR / m.group(1) / m.group(2)
    return _gemini_classify_image(f, extra_q)
