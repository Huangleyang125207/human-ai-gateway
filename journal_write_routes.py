"""HTTP mapping for journal write operations."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from journal_write_service import JournalWriteError, JournalWriteRejected


def create_journal_write_router(service_provider) -> APIRouter:
    router = APIRouter(tags=["journal"])

    @router.post("/api/journal/new-day")
    async def journal_new_day(req: Request):
        body = {}
        try:
            body = await req.json()
        except Exception:
            pass
        return service_provider().new_day(
            (body or {}).get("date", ""),
        )

    async def run_write(req: Request, method_name: str):
        body = await req.json()
        try:
            return getattr(service_provider(), method_name)(body)
        except JournalWriteRejected as e:
            return JSONResponse(status_code=400, content=e.payload)
        except JournalWriteError as e:
            raise HTTPException(e.status_code, e.detail) from e

    @router.post("/api/journal/insert-block")
    async def journal_insert_block(req: Request):
        return await run_write(req, "insert")

    @router.post("/api/journal/delete-block")
    async def journal_delete_block(req: Request):
        return await run_write(req, "delete")

    @router.post("/api/journal/patch")
    async def journal_patch(req: Request):
        return await run_write(req, "patch")

    return router
