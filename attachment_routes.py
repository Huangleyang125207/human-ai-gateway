"""HTTP mapping for attachment file and index operations."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from image_service_errors import ImageServiceError


def create_attachment_router(service_provider) -> APIRouter:
    router = APIRouter(tags=["image"])

    def map_error(error: ImageServiceError):
        raise HTTPException(error.status_code, error.detail) from error

    @router.get("/attachments/{date}/{name}")
    def get_attachment(date: str, name: str):
        try:
            return FileResponse(service_provider().resolve_file(date, name))
        except ImageServiceError as e:
            map_error(e)

    @router.get("/api/attachments")
    def attachments_list(
        date_from: str = "",
        date_to: str = "",
        limit: int = 100,
    ):
        return service_provider().list(date_from, date_to, limit)

    @router.get("/api/attachments/search")
    def attachments_search(q: str, limit: int = 30):
        return service_provider().search(q, limit)

    @router.post("/api/attachments/delete")
    async def attachments_delete(req: Request):
        try:
            return service_provider().delete(await req.json())
        except ImageServiceError as e:
            map_error(e)

    @router.post("/api/attachments/reindex")
    def attachments_reindex():
        return service_provider().reindex()

    return router
