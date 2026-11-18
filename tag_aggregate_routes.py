"""HTTP mapping for tag aggregate operations."""

from fastapi import APIRouter, Request


def create_tag_aggregate_router(service_provider) -> APIRouter:
    router = APIRouter(tags=["journal"])

    @router.post("/api/tag-aggregate/register")
    async def tag_aggregate_register(req: Request):
        return service_provider().register(await req.json())

    @router.post("/api/tag-aggregate/refresh")
    def tag_aggregate_refresh():
        return service_provider().refresh()

    @router.get("/api/tag-aggregate")
    def tag_aggregate():
        return service_provider().get()

    return router
