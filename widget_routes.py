"""Widget selection and marketplace routes."""

import json

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["widgets"])

_USER_WIDGETS_PATH = None
_WIDGETS_DIR = None
_WRITE_TEXT = None
_EXPERIMENT_VARIANT = None


def configure_effects(
    *,
    user_widgets_path,
    widgets_dir,
    write_text,
    experiment_variant=lambda: "reference",
) -> None:
    global _USER_WIDGETS_PATH, _WIDGETS_DIR, _WRITE_TEXT
    global _EXPERIMENT_VARIANT
    _USER_WIDGETS_PATH = user_widgets_path
    _WIDGETS_DIR = widgets_dir
    _WRITE_TEXT = write_text
    _EXPERIMENT_VARIANT = experiment_variant


def _load_user_widgets() -> dict:
    path = _USER_WIDGETS_PATH()
    if not path.exists():
        return {"active": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"active": []}


@router.get("/api/user-widgets")
def get_user_widgets():
    return _load_user_widgets()


@router.get("/api/widgets/catalog")
def widgets_catalog():
    active = _load_user_widgets().get("active", []) or []
    disabled = _load_user_widgets().get("disabled", []) or []
    items = []
    widgets_dir = _WIDGETS_DIR()
    if widgets_dir.exists():
        for directory in sorted(widgets_dir.iterdir()):
            manifest = directory / "manifest.json"
            if not (directory.is_dir() and manifest.exists()):
                continue
            try:
                metadata = json.loads(
                    manifest.read_text(encoding="utf-8")
                )
            except Exception:
                continue
            name = metadata.get("name", directory.name)
            default_loaded = bool(metadata.get("default_loaded", False))
            if (
                name == "memo-reference"
                and _EXPERIMENT_VARIANT() == "reference"
            ):
                default_loaded = True
            items.append({
                "name": name,
                "title": metadata.get("title", directory.name),
                "description": metadata.get("description", ""),
                "audience": metadata.get("audience", ""),
                "category": metadata.get("category", "uncategorized"),
                "default_loaded": default_loaded,
                "slot": metadata.get("slot", ""),
                "status": metadata.get("status", "stable"),
                "active": (
                    (name in active or default_loaded)
                    and name not in disabled
                ),
            })
    return {"widgets": items, "active": active}


@router.post("/api/widgets/toggle")
async def widgets_toggle(req: Request):
    body = await req.json()
    return set_widget_enabled(body)


def set_widget_enabled(body: dict) -> dict:
    """Shared state transition for HTTP, GUI and model-tool callers."""
    name = (body.get("name") or body.get("id") or "").strip()
    enable = bool(body.get("enable", body.get("enabled")))
    if not name:
        raise HTTPException(400, "need name")
    manifest = _WIDGETS_DIR() / name / "manifest.json"
    if not manifest.exists():
        raise HTTPException(404, f"widget '{name}' not found")
    try:
        if json.loads(
            manifest.read_text(encoding="utf-8")
        ).get("status") == "wip":
            raise HTTPException(
                403,
                f"widget '{name}' 仍在开发中,审核通过后才能启用",
            )
    except HTTPException:
        raise
    except Exception:
        pass

    config = _load_user_widgets()
    active = config.get("active", []) or []
    disabled = config.get("disabled", []) or []
    if enable:
        if name not in active:
            active.append(name)
        disabled = [item for item in disabled if item != name]
    elif not enable and name in active:
        active = [item for item in active if item != name]
    if not enable and name not in disabled:
        disabled.append(name)
    config["active"] = active
    if disabled:
        config["disabled"] = disabled
    else:
        config.pop("disabled", None)
    _WRITE_TEXT(
        _USER_WIDGETS_PATH(),
        json.dumps(config, indent=2, ensure_ascii=False),
        rotate=True,
    )
    return {
        "ok": True,
        "name": name,
        "enabled": enable,
        "active": active,
        "disabled": disabled,
    }
