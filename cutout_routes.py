"""HTTP mapping for task-image cutout."""

from fastapi import APIRouter, HTTPException, Request

from image_service_errors import ImageServiceError


def create_cutout_router(service_provider) -> APIRouter:
    router = APIRouter(tags=["image"])

    @router.post("/api/cutout")
    async def cutout_image(req: Request):
        try:
            return service_provider().cutout(await req.json())
        except ImageServiceError as e:
            raise HTTPException(e.status_code, e.detail) from e

    return router
