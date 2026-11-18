"""HTTP boundary for the read-only WidgetSpec capability broker."""

from fastapi import APIRouter, HTTPException


router = APIRouter(prefix="/api/widget-runtime", tags=["widget-runtime"])

_CAPABILITIES = None
_VALIDATE = None
_QUERY = None
_INSTALLED = None


def configure_effects(*, capabilities, validate, query, installed) -> None:
    global _CAPABILITIES, _VALIDATE, _QUERY, _INSTALLED
    _CAPABILITIES = capabilities
    _VALIDATE = validate
    _QUERY = query
    _INSTALLED = installed


@router.get("/capabilities")
def capabilities():
    return {"version": "1.0", "capabilities": _CAPABILITIES()}


@router.post("/validate")
def validate(spec: dict):
    errors = _VALIDATE(spec)
    return {"ok": not errors, "errors": errors}


@router.post("/query")
def query(spec: dict):
    errors = _VALIDATE(spec)
    if errors:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_widget_spec", "errors": errors},
        )
    return {"spec_id": spec["id"], "data": _QUERY(spec)}


@router.get("/installed")
def installed():
    return {"version": 1, "widgets": _INSTALLED()}
