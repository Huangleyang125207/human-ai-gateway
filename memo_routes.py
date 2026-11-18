"""Thin HTTP adapter for the memo state machine shared by GUI and AI."""

from fastapi import APIRouter, HTTPException


def create_memo_router(domain_tools):
    router = APIRouter(prefix="/api/memos", tags=["memos"])

    def checked(result: dict):
        if not result.get("ok"):
            raise HTTPException(
                status_code=400,
                detail={"code": result.get("error") or "memo_operation_failed"},
            )
        return result

    @router.get("")
    def list_memos(limit: int = 8):
        return checked(domain_tools.list_memos({"limit": limit}))

    @router.post("")
    def create_memo(body: dict):
        return checked(domain_tools.create_memo(dict(body)))

    @router.put("/series/{series_id}/occurrences/{occurrence_id}")
    def update_memo(series_id: str, occurrence_id: str, body: dict):
        args = dict(body)
        args.update({
            "series_id": series_id,
            "occurrence_id": occurrence_id,
        })
        return checked(domain_tools.update_memo(args))

    @router.post("/occurrences/{occurrence_id}/actions")
    def act_on_memo(occurrence_id: str, body: dict):
        args = dict(body)
        args["occurrence_id"] = occurrence_id
        return checked(domain_tools.act_on_memo(args))

    @router.post("/series/{series_id}/actions")
    def manage_memo_series(series_id: str, body: dict):
        args = dict(body)
        args["series_id"] = series_id
        return checked(domain_tools.manage_memo_series(args))

    return router
