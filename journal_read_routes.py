"""HTTP mapping for read-only journal queries."""

from fastapi import APIRouter


def create_journal_read_router(service_provider) -> APIRouter:
    router = APIRouter(tags=["journal"])

    @router.get("/api/journal/today")
    def journal_today(date: str = None):
        return service_provider().today(date)

    @router.get("/api/journal/days")
    def journal_days():
        return service_provider().days()

    @router.get("/api/journal/tag-stats")
    def journal_tag_stats(limit: int = 5):
        return service_provider().tag_stats(limit)

    return router
