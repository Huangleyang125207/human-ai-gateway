"""Scrapbook CRUD HTTP routes."""

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["scrapbook"])

_LOAD = None
_SAVE = None
_NEW_ID = None


def configure_effects(*, load, save, new_id) -> None:
    global _LOAD, _SAVE, _NEW_ID
    _LOAD = load
    _SAVE = save
    _NEW_ID = new_id


@router.get("/api/scrapbook")
def scrapbook_get(date: str):
    return {"date": date, "items": _LOAD(date)}


@router.post("/api/scrapbook/upsert")
async def scrapbook_upsert(req: Request):
    body = await req.json()
    date = (body.get("date") or "").strip()
    if not date:
        raise HTTPException(400, "need date")
    items = _LOAD(date)
    if body.get("id"):
        index = next(
            (
                index
                for index, item in enumerate(items)
                if item.get("id") == body["id"]
            ),
            -1,
        )
        if index < 0:
            raise HTTPException(404, f"id {body['id']} not found")
        item = items[index]
        for key in (
            "src", "x_pct", "y_px", "w", "h", "size_pct", "rotation",
            "cutout", "anchor_time", "z", "align", "x", "y",
        ):
            if key in body:
                item[key] = body[key]
        if "y_px" in body:
            item["auto_y"] = False
        items[index] = item
    else:
        item = {
            "id": _NEW_ID(),
            "src": body.get("src", ""),
            "x_pct": float(body.get("x_pct", 75)),
            "y_px": float(body.get("y_px", 0)),
            "w": int(body.get("w", 200)),
            "h": int(body.get("h", 200)),
            "size_pct": float(body.get("size_pct", 18)),
            "rotation": float(body.get("rotation", 0)),
            "cutout": bool(body.get("cutout", True)),
            "anchor_time": body.get("anchor_time", ""),
            "z": int(body.get("z", 1)),
        }
        items.append(item)
    _SAVE(date, items)
    return {"ok": True, "item": item}


@router.post("/api/scrapbook/delete")
async def scrapbook_delete(req: Request):
    body = await req.json()
    date = (body.get("date") or "").strip()
    item_id = (body.get("id") or "").strip()
    if not date or not item_id:
        raise HTTPException(400, "need date + id")
    items = [
        item for item in _LOAD(date) if item.get("id") != item_id
    ]
    _SAVE(date, items)
    return {"ok": True, "removed": item_id}
