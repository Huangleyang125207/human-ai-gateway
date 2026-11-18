"""HTTP mapping for thread-history persistence."""

from fastapi import APIRouter, HTTPException, Request

from thread_history import ThreadHistoryConflict, ThreadHistoryNotCorrupt


def create_thread_router(service_provider) -> APIRouter:
    router = APIRouter(tags=["thread"])

    @router.get("/api/thread/history")
    def thread_history_get():
        return service_provider().get()

    @router.post("/api/thread/restore-from-bak")
    async def thread_history_restore(req: Request):
        body = await req.json()
        idx = int(body.get("bak_index") or 0)
        if idx < 1 or idx > 5:
            raise HTTPException(400, "bak_index 必须是 1..5")
        try:
            return service_provider().restore(idx)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @router.post("/api/thread/start-fresh")
    def thread_history_start_fresh():
        try:
            return service_provider().start_fresh()
        except ThreadHistoryNotCorrupt as e:
            raise HTTPException(409, str(e)) from e

    @router.post("/api/thread/save")
    async def thread_history_save(req: Request):
        body = await req.json()
        history = body.get("history")
        if not isinstance(history, list):
            raise HTTPException(400, "history must be a list")
        try:
            return service_provider().save(
                history,
                body.get("base_mtime"),
                body.get("compact"),
            )
        except ThreadHistoryConflict as e:
            raise HTTPException(status_code=409, detail={
                "conflict": True,
                "current_mtime": e.current_mtime,
                "message": (
                    "stale base_mtime — reload server history before saving"
                ),
            }) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    return router
