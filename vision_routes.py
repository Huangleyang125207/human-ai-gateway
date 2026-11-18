"""HTTP mapping for direct vision classification."""

from fastapi import APIRouter, HTTPException, Request

from image_service_errors import ImageServiceError


def create_vision_router(service_provider) -> APIRouter:
    router = APIRouter(tags=["image"])

    @router.post("/api/vision/classify")
    async def vision_classify(req: Request):
        try:
            return service_provider().classify(await req.json())
        except ImageServiceError as e:
            raise HTTPException(e.status_code, e.detail) from e

    return router
