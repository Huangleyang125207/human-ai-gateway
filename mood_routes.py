"""HTTP adapter for the mood state shared by GUI and AI tools."""
from datetime import datetime, timedelta

from fastapi import APIRouter


def create_mood_router(domain_tools):
    router = APIRouter()

    @router.get("/api/mood")
    def get_mood(date: str = "", days: int = 9):
        target = date or datetime.now().strftime("%Y-%m-%d")
        try:
            end = datetime.strptime(target, "%Y-%m-%d")
        except ValueError:
            return {"ok": False, "error": "date must be YYYY-MM-DD"}
        count = max(1, min(int(days), 30))
        series = []
        for offset in range(count - 1, -1, -1):
            day = (end - timedelta(days=offset)).strftime("%Y-%m-%d")
            result = domain_tools.manage_mood({"action": "get", "date": day})
            series.append({"date": day, "value": result.get("value")})
        return {"ok": True, "date": target, "value": series[-1]["value"], "series": series}

    @router.post("/api/mood")
    def write_mood(body: dict):
        action = "clear" if body.get("value") in (None, "") else "set"
        return domain_tools.manage_mood({"action": action, "date": body.get("date"), "value": body.get("value")})

    return router
