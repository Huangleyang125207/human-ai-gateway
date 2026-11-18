"""Contract tests for the memo GUI HTTP adapter."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from memo_routes import create_memo_router


class _MemoTools:
    def __init__(self):
        self.calls = []
        self.result = {"ok": True}

    def list_memos(self, args):
        self.calls.append(("list", args))
        return self.result

    def create_memo(self, args):
        self.calls.append(("create", args))
        return self.result

    def update_memo(self, args):
        self.calls.append(("update", args))
        return self.result

    def act_on_memo(self, args):
        self.calls.append(("act", args))
        return self.result

    def manage_memo_series(self, args):
        self.calls.append(("series", args))
        return self.result


def _client(tools):
    app = FastAPI()
    app.include_router(create_memo_router(tools))
    return TestClient(app)


def test_list_and_create_delegate_to_the_memo_owner():
    tools = _MemoTools()
    client = _client(tools)

    assert client.get("/api/memos?limit=12").json() == {"ok": True}
    body = {
        "text": "晚上跑步",
        "due_at": "2026-08-11T20:00:00+08:00",
        "schedule": {"kind": "once"},
        "notification_enabled": True,
    }
    assert client.post("/api/memos", json=body).json() == {"ok": True}
    assert tools.calls == [("list", {"limit": 12}), ("create", body)]


def test_update_uses_path_ids_instead_of_trusting_the_body():
    tools = _MemoTools()
    client = _client(tools)
    body = {
        "series_id": "body-series",
        "occurrence_id": "body-occurrence",
        "text": "改后的备忘",
        "due_at": "2026-08-12T09:30:00+08:00",
        "schedule": {"kind": "daily"},
    }

    response = client.put(
        "/api/memos/series/path-series/occurrences/path-occurrence",
        json=body,
    )

    assert response.json() == {"ok": True}
    assert tools.calls == [("update", {
        **body,
        "series_id": "path-series",
        "occurrence_id": "path-occurrence",
    })]


def test_occurrence_and_series_actions_use_path_ids():
    tools = _MemoTools()
    client = _client(tools)

    complete = client.post(
        "/api/memos/occurrences/occ-1/actions",
        json={"occurrence_id": "wrong", "action": "complete"},
    )
    archive = client.post(
        "/api/memos/series/series-1/actions",
        json={"series_id": "wrong", "action": "archive"},
    )

    assert complete.json() == {"ok": True}
    assert archive.json() == {"ok": True}
    assert tools.calls == [
        ("act", {"occurrence_id": "occ-1", "action": "complete"}),
        ("series", {"series_id": "series-1", "action": "archive"}),
    ]


def test_domain_failures_become_stable_http_errors():
    tools = _MemoTools()
    tools.result = {"ok": False, "error": "occurrence_not_actionable"}
    response = _client(tools).post(
        "/api/memos/occurrences/occ-1/actions",
        json={"action": "complete"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": {"code": "occurrence_not_actionable"}
    }
