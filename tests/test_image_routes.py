# TEST PATTERN: characterization — 图像簇 /api/attachments + /api/cutout + /api/vision/classify
# USE WHEN: 锁图像端点现行行为,守 image_routes 抽出(§ 9)+ **同时是移动 parity N4-N8 oracle**
# TESTED IN: gateway image_routes extraction (2026-06-25), § T7 characterization
#
# 双份回报:这组既是 image_routes 抽出的 GREEN-LOCK,也是移动 parity 台账 N4-N8 缺的 oracle
# (vision/classify=N4 · uploads/list=N5 · search=N6 · delete=N7 · attachments/get=N8 · cutout↔set-image=N2)。
# helper(_load/_save_attachments_index / _index_attachment / _deepseek_classify_image /
# _get_or_create_processed_attachment / io-map)抽出时 *留 server.py*(chat_routes 也 lazy-import)。

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
import chat_routes  # noqa: E402
import journal_task_tools  # noqa: E402
import vision_tools  # noqa: E402
from attachment_service import resolve_attachment_url  # noqa: E402
from image_service_errors import ImageServiceError  # noqa: E402


def test_image_modules_do_not_import_server():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import attachment_service, attachment_routes, "
            "cutout_service, cutout_routes, vision_service, vision_routes, vision_tools; "
            "raise SystemExit(1 if 'server' in sys.modules else 0)",
        ],
        cwd=Path(__file__).resolve().parent.parent,
        check=False,
    )

    assert result.returncode == 0


@pytest.fixture
def img(monkeypatch, tmp_path):
    adir = tmp_path / "attachments"; adir.mkdir()
    monkeypatch.setattr(server, "ATTACHMENTS_DIR", adir)
    monkeypatch.setattr(server, "ATTACHMENTS_INDEX", adir / "_index.json")
    monkeypatch.setattr(server, "CURATOR_SYSTEM_PATH", adir / "_curator.txt", raising=False)
    imgdir = tmp_path / "task-imgs"; imgdir.mkdir()
    monkeypatch.setattr(server, "DAILY_TASK_IMAGES_DIR", imgdir)
    monkeypatch.setattr(server, "DAILY_TASK_IMAGES_MAP", tmp_path / "imgmap.json")
    monkeypatch.setattr(server, "DAILY_TASK_META_MAP", tmp_path / "metamap.json")
    monkeypatch.setattr(server, "PLATFORM_ROOT", tmp_path, raising=False)
    ns = SimpleNamespace(adir=adir, imgdir=imgdir, tmp=tmp_path, mp=monkeypatch)

    def put(date, name, data=b"\x89PNG\r\n"):
        d = adir / date; d.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(data); return d / name

    def write_index(arr):
        (adir / "_index.json").write_text(json.dumps(arr, ensure_ascii=False), encoding="utf-8")

    def read_index():
        f = adir / "_index.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []

    ns.put = put; ns.write_index = write_index; ns.read_index = read_index
    return ns


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(server.app)


# ── N8: GET /attachments/{date}/{name} ───────────────────────────────

def test_get_attachment_serves_bytes(client, img):
    img.put("2026-06-25", "a.png", b"PNGDATA")
    r = client.get("/attachments/2026-06-25/a.png")
    assert r.status_code == 200 and r.content == b"PNGDATA"


def test_get_attachment_bad_date_400(client, img):
    assert client.get("/attachments/not-a-date/a.png").status_code == 400


def test_get_attachment_traversal_404_or_400(client, img):
    # FastAPI 路由不会把 .. 当 name 段;直接 /attachments/d/..%2f 之类 → 400/404,绝不越权读
    assert client.get("/attachments/2026-06-25/missing.png").status_code == 404


def test_attachment_resolver_rejects_traversal_backslash_and_symlink_escape(img):
    outside = img.tmp / "secret.png"
    outside.write_bytes(b"secret")
    day = img.adir / "2026-06-25"
    day.mkdir()
    (day / "link.png").symlink_to(outside)
    for url in (
        "/attachments/../secret.png",
        "/attachments/2026-06-25/..\\secret.png",
        "/attachments/2026-06-25/link.png",
    ):
        with pytest.raises(ImageServiceError):
            resolve_attachment_url(img.adir, url)


# ── N5: GET /api/attachments (list) ──────────────────────────────────

def test_attachments_list_sorted_desc_with_total_and_limit(client, img):
    img.write_index([
        {"date": "2026-06-20", "filename": "a.png", "ocr_text": ""},
        {"date": "2026-06-25", "filename": "b.png", "ocr_text": ""},
        {"date": "2026-06-22", "filename": "c.png", "ocr_text": ""},
    ])
    d = client.get("/api/attachments", params={"limit": 2}).json()
    assert d["total"] == 3 and len(d["items"]) == 2
    assert d["items"][0]["date"] == "2026-06-25"          # 降序


def test_attachments_list_date_filter(client, img):
    img.write_index([{"date": "2026-06-10", "filename": "a"}, {"date": "2026-06-25", "filename": "b"}])
    d = client.get("/api/attachments", params={"date_from": "2026-06-20"}).json()
    assert {x["filename"] for x in d["items"]} == {"b"}


# ── N6: GET /api/attachments/search ──────────────────────────────────

def test_attachments_search_matches_filename_original_ocr(client, img):
    img.write_index([
        {"date": "2026-06-25", "filename": "x.png", "original": "鱼油瓶.jpg", "ocr_text": ""},
        {"date": "2026-06-25", "filename": "y.png", "original": "", "ocr_text": "维生素 D3 60 粒"},
    ])
    assert {x["filename"] for x in client.get("/api/attachments/search", params={"q": "鱼油"}).json()["items"]} == {"x.png"}
    assert {x["filename"] for x in client.get("/api/attachments/search", params={"q": "维生素"}).json()["items"]} == {"y.png"}


def test_attachments_search_empty_q(client, img):
    assert client.get("/api/attachments/search", params={"q": ""}).json()["items"] == []


# ── N7: POST /api/attachments/delete ★data-loss ──────────────────────

def test_attachments_delete_removes_file_and_index(client, img):
    f = img.put("2026-06-25", "a.png")
    img.write_index([{"date": "2026-06-25", "filename": "a.png"},
                     {"date": "2026-06-25", "filename": "keep.png"}])
    r = client.post("/api/attachments/delete", json={"date": "2026-06-25", "filename": "a.png"})
    assert r.json()["ok"] is True
    assert not f.exists()                                  # 文件删了
    assert [x["filename"] for x in img.read_index()] == ["keep.png"]   # 索引条目删了,别的留


def test_attachments_delete_traversal_400(client, img):
    assert client.post("/api/attachments/delete",
                       json={"date": "2026-06-25", "filename": "../../etc/passwd"}).status_code == 400


# ── reindex ──────────────────────────────────────────────────────────

def test_reindex_indexes_missing_skips_existing(client, img, monkeypatch):
    img.put("2026-06-25", "new.png")
    img.put("2026-06-25", "old.png")
    img.write_index([{"date": "2026-06-25", "filename": "old.png"}])
    monkeypatch.setattr(server, "_index_attachment", lambda *a, **k: None)  # 不真跑 OCR
    d = client.post("/api/attachments/reindex").json()
    assert d["ok"] is True and d["indexed"] == 1 and d["skipped"] == 1


def test_reindex_skips_symlink_escapes(client, img, monkeypatch):
    outside_dir = img.tmp / "outside"
    outside_dir.mkdir()
    (outside_dir / "secret.png").write_bytes(b"secret")
    (img.adir / "2026-06-24").symlink_to(outside_dir, target_is_directory=True)
    safe_day = img.adir / "2026-06-25"
    safe_day.mkdir()
    (safe_day / "link.png").symlink_to(outside_dir / "secret.png")
    indexed = []
    monkeypatch.setattr(server, "_index_attachment", lambda *args: indexed.append(args))
    d = client.post("/api/attachments/reindex").json()
    assert d == {"ok": True, "indexed": 0, "skipped": 0}
    assert indexed == []


def test_ai_photo_history_keeps_original_and_excludes_cutout_cache(client, img, monkeypatch):
    original = img.put("2026-06-25", "meal.jpg", b"original")
    cutout = img.put("2026-06-25", "meal.jpg.cutout.png", b"derived")
    original_url = "/attachments/2026-06-25/meal.jpg"
    cutout_url = "/attachments/2026-06-25/meal.jpg.cutout.png"
    img.write_index([
        {"date": "2026-06-25", "filename": original.name, "url": original_url,
         "vision": {"description": "午餐"}},
        {"date": "2026-06-25", "filename": cutout.name, "url": cutout_url,
         "vision": {"description": "抠出的午餐"}, "vision_pending": True},
    ])
    monkeypatch.setattr(server, "_index_attachment", lambda *a, **k: None)

    # Reconcile cleans only the AI index; the cutout remains a usable UI asset.
    assert server._reconcile_existing_attachments()["discovered"] == 1
    assert cutout.exists()
    assert [row["filename"] for row in img.read_index()] == ["meal.jpg"]
    assert [row["url"] for row in client.get("/api/attachments").json()["items"]] == [original_url]
    assert client.post("/api/attachments/reindex").json()["indexed"] == 0

    monkeypatch.setattr(vision_tools, "_ATTACHMENTS_DIR", lambda: img.adir)
    monkeypatch.setattr(vision_tools, "_INDEX_UPSERT", server._index_upsert)
    assert vision_tools.tool_record_image_observation({
        "attachment_url": cutout_url, "kind": "photo", "description": "must not index",
    })["error"].startswith("derived attachment")


def test_legacy_photo_reconcile_registers_and_queues_only_missing_semantics(img):
    img.put("2026-06-23", "missing.jpg", b"legacy")
    img.put("2026-06-24", "indexed.png", b"indexed")
    img.put("2026-06-25", "old-webview.webp", b"old")
    img.write_index([
        {"date": "2026-06-24", "filename": "indexed.png", "url": "/attachments/2026-06-24/indexed.png",
         "ocr_text": "keep deterministic OCR", "vision": {"description": "already searchable"}},
        {"date": "2026-06-25", "filename": "old-webview.webp",
         "vision_result": {"kind": "receipt", "ocr_text": "legacy OCR"}, "vision_pending": True},
    ])

    first = server._reconcile_existing_attachments()
    by_name = {row["filename"]: row for row in img.read_index()}

    assert first["discovered"] == 3
    assert first["registered"] == 1
    assert first["queued"] == 1
    assert by_name["missing.jpg"]["vision_pending"] is True
    assert by_name["missing.jpg"]["size"] == 6
    assert by_name["indexed.png"]["ocr_text"] == "keep deterministic OCR"
    assert by_name["indexed.png"].get("vision_pending") is not True
    assert by_name["old-webview.webp"]["vision"]["kind"] == "receipt"
    assert by_name["old-webview.webp"]["vision_pending"] is False

    assert server._reconcile_existing_attachments() == {
        "discovered": 3, "registered": 0, "updated": 0, "queued": 0,
    }


def test_legacy_photo_reconcile_ignores_non_image_invalid_day_and_symlinks(img):
    img.put("2026-06-25", "note.txt", b"not image")
    img.put("bad-day", "photo.png", b"bad day")
    outside = img.tmp / "outside.jpg"
    outside.write_bytes(b"outside")
    (img.adir / "2026-06-25" / "link.jpg").symlink_to(outside)

    result = server._reconcile_existing_attachments()

    assert result["discovered"] == 0
    assert img.read_index() == []


def test_legacy_photo_reconcile_runs_after_legacy_state_migration():
    handlers = server.app.router.on_startup
    assert handlers.index(server._startup_migrate_state) < handlers.index(
        server._startup_retry_pending_vision
    )


def test_vision_startup_schedules_reconcile_then_bounded_retry(monkeypatch):
    import asyncio
    import threading

    calls = []
    done = threading.Event()
    monkeypatch.setattr(server, "_reconcile_existing_attachments", lambda: calls.append("reconcile"))

    def retry(limit):
        calls.append(limit)
        done.set()

    monkeypatch.setattr(chat_routes, "retry_pending_vision", retry)

    async def run_startup():
        await server._startup_retry_pending_vision()
        assert await asyncio.to_thread(done.wait, 2)

    asyncio.run(run_startup())
    assert calls == ["reconcile", 3]


def test_pending_vision_retry_is_bounded_and_prioritizes_current_photo(img, monkeypatch):
    rows = []
    for day, name in (("2026-06-21", "old.jpg"), ("2026-06-22", "mid.jpg"), ("2026-06-23", "current.jpg")):
        img.put(day, name)
        rows.append({"date": day, "filename": name,
                     "url": f"/attachments/{day}/{name}", "vision_pending": True})
    img.write_index(rows)
    seen = []
    monkeypatch.setattr(chat_routes, "_refs_to_vision_hints",
                        lambda refs: seen.extend((r["payload"]["url"] for r in refs)) or [])

    processed = chat_routes.retry_pending_vision(
        2, ["/attachments/2026-06-23/current.jpg"]
    )

    assert processed == 2
    assert seen == [
        "/attachments/2026-06-23/current.jpg",
        "/attachments/2026-06-21/old.jpg",
    ]


# ── N4: POST /api/vision/classify ────────────────────────────────────

def test_vision_classify_delegates_and_validates(client, img, monkeypatch):
    img.put("2026-06-25", "p.png")
    monkeypatch.setattr(vision_tools, "_deepseek_classify_image",
                        lambda f, q="": {"kind": "supplement", "description": f"desc q={q}"})
    d = client.post("/api/vision/classify",
                    json={"attachment_url": "/attachments/2026-06-25/p.png", "extra_question": "啥牌子"}).json()
    assert d["kind"] == "supplement" and "啥牌子" in d["description"]
    assert client.post("/api/vision/classify", json={}).status_code == 400          # 缺 url
    assert client.post("/api/vision/classify", json={"attachment_url": "bad"}).status_code == 400


def test_vision_and_cutout_http_reject_attachment_traversal(client, img, monkeypatch):
    outside = img.tmp / "secret.png"
    outside.write_bytes(b"secret")
    classified = []
    monkeypatch.setattr(vision_tools, "_deepseek_classify_image", lambda f, q="": classified.append(f) or {})
    url = "/attachments/../secret.png"
    assert client.post("/api/vision/classify", json={"attachment_url": url}).status_code == 400
    assert client.post("/api/cutout", json={"attachment_url": url, "task_name": "x"}).status_code == 400
    assert classified == []


def test_ai_and_chat_consumers_reject_attachment_traversal(img, monkeypatch):
    outside = img.tmp / "secret.png"
    outside.write_bytes(b"secret")
    url = "/attachments/../secret.png"
    monkeypatch.setattr(vision_tools, "_PICK_ATTACHMENT_URL", lambda args: url)
    monkeypatch.setattr(vision_tools, "_ATTACHMENTS_DIR", lambda: img.adir)
    classified = []
    monkeypatch.setattr(vision_tools, "_deepseek_classify_image", lambda f, q="": classified.append(f) or {})
    assert "error" in vision_tools.tool_vision_classify({"attachment_url": url})

    monkeypatch.setattr(journal_task_tools, "_ATTACHMENTS_DIR", lambda: img.adir)
    assert "error" in journal_task_tools.tool_place_scrapbook_image({
        "attachment_url": url, "date": "2026-06-25", "anchor_time": "10:00",
    })

    monkeypatch.setattr(chat_routes, "_ATTACHMENTS_DIR", lambda: img.adir)
    ocr_calls = []
    monkeypatch.setattr(chat_routes, "_OCR_TEXT", lambda f: ocr_calls.append(f) or "secret")
    refs = [{"kind": "image", "payload": {"url": url}}]
    assert chat_routes._refs_to_image_blocks(refs) == []
    assert ocr_calls == [] and classified == []


def test_chat_vision_cache_miss_upserts_once(img, monkeypatch):
    image = img.put("2026-08-19", "safe.png", b"safe")
    url = "/attachments/2026-08-19/safe.png"
    index = []
    classify_calls = []

    monkeypatch.setattr(chat_routes, "_ATTACHMENTS_DIR", lambda: img.adir)
    monkeypatch.setattr(chat_routes, "_LOAD_ATTACHMENTS_INDEX", lambda: index)
    monkeypatch.setattr(
        chat_routes,
        "_VISION_CLASSIFY_IMAGE",
        lambda path: classify_calls.append(path) or {"description": "safe image"},
    )

    def upsert(date, filename, **fields):
        index.append({"date": date, "filename": filename, **fields})

    monkeypatch.setattr(chat_routes, "_INDEX_UPSERT", upsert)
    monkeypatch.setattr(chat_routes, "_LOGGER", lambda: SimpleNamespace(warning=lambda *_: None))
    monkeypatch.setattr(chat_routes, "_REPORT_FAILURE", lambda *args, **kwargs: None)
    refs = [{"kind": "image", "payload": {"url": url, "original": "photo.png"}}]

    first = chat_routes._refs_to_vision_hints(refs)
    second = chat_routes._refs_to_vision_hints(refs)

    assert first[0]["vision"] == {"description": "safe image"}
    assert second[0]["vision"] == {"description": "safe image"}
    assert classify_calls == [image]
    assert index == [{
        "date": "2026-08-19",
        "filename": "safe.png",
            "vision": {"description": "safe image"},
            "vision_pending": False,
        "url": url,
        "original": "photo.png",
        "size": 4,
    }]


def test_record_image_observation_merges_index_and_stays_searchable(img, monkeypatch):
    img.put("2026-08-23", "run.png", b"image")
    url = "/attachments/2026-08-23/run.png"
    img.write_index([{
        "date": "2026-08-23", "filename": "run.png", "url": url,
        "original": "morning.png", "hash": "sha-kept", "ocr_text": "晨跑 5km",
        "vision": {"ocr_text": "旧识别文字", "suggested_action": "keep-me"},
    }])
    monkeypatch.setattr(vision_tools, "_ATTACHMENTS_DIR", lambda: img.adir)
    monkeypatch.setattr(vision_tools, "_INDEX_UPSERT", server._index_upsert)

    result = vision_tools.tool_record_image_observation({
        "attachment_url": url,
        "kind": "exercise",
        "description": "清晨户外跑步记录",
        "brand": "Garmin",
        "ocr_text": "配速 5:30",
    })

    assert result == {"ok": True, "indexed": url}
    row = img.read_index()[0]
    assert row["hash"] == "sha-kept"
    assert row["ocr_text"] == "晨跑 5km"  # 模型观察不能覆盖确定性 OCR 真源
    assert row["vision"]["description"] == "清晨户外跑步记录"
    assert row["vision"]["suggested_action"] == "keep-me"
    assert vision_tools.tool_search_my_uploads({"query": "garmin"})["matched"] == 1
    assert vision_tools.tool_search_my_uploads({"query": "配速"})["matched"] == 1


def test_record_image_observation_rejects_unregistered_or_missing_attachment(img, monkeypatch):
    monkeypatch.setattr(vision_tools, "_ATTACHMENTS_DIR", lambda: img.adir)
    monkeypatch.setattr(vision_tools, "_INDEX_UPSERT", server._index_upsert)
    assert "error" in vision_tools.tool_record_image_observation({
        "attachment_url": "/attachments/2026-08-23/missing.png",
        "kind": "photo",
        "description": "不存在",
    })


def test_pending_vision_survives_failure_and_retry_clears_it(img, monkeypatch):
    img.put("2026-08-23", "retry.png", b"image")
    url = "/attachments/2026-08-23/retry.png"
    img.write_index([{"date": "2026-08-23", "filename": "retry.png", "url": url,
                      "original": "retry.png", "vision_pending": True}])
    monkeypatch.setattr(chat_routes, "_ATTACHMENTS_DIR", lambda: img.adir)
    monkeypatch.setattr(chat_routes, "_LOAD_ATTACHMENTS_INDEX", img.read_index)
    monkeypatch.setattr(chat_routes, "_INDEX_UPSERT", server._index_upsert)
    monkeypatch.setattr(chat_routes, "_VISION_CLASSIFY_IMAGE", lambda _f: {"error": "offline"})
    assert chat_routes.retry_pending_vision() == 1
    assert img.read_index()[0]["vision_pending"] is True
    monkeypatch.setattr(chat_routes, "_VISION_CLASSIFY_IMAGE", lambda _f: {
        "description": "重试成功", "ocr_text": "发票编号 A123",
    })
    assert chat_routes.retry_pending_vision() == 1
    assert img.read_index()[0]["vision_pending"] is False
    assert vision_tools.tool_search_my_uploads({"query": "A123"})["matched"] == 1


# ── N2: POST /api/cutout(↔ daily-tasks/set-image)─────────────────────

def test_cutout_writes_image_map_and_ocr_pill_count(client, img, monkeypatch):
    src = img.put("2026-06-25", "yuyou.jpg")
    processed = img.tmp / "proc.png"; processed.write_bytes(b"\x89PNGCUT")
    monkeypatch.setattr(server, "_get_or_create_processed_attachment", lambda url: (processed, None))
    monkeypatch.setattr(server, "_ocr_text", lambda f: "鱼油 60 粒")
    monkeypatch.setattr(server, "load_config", lambda: {})
    r = client.post("/api/cutout", json={"attachment_url": "/attachments/2026-06-25/yuyou.jpg",
                                         "task_name": "鱼油（Swisse）"})
    d = r.json()
    assert d["ok"] is True and d["ocr_pill_count"] == 60          # OCR 抽颗数
    # image_map[task] 写了 + meta total_pills 自动填(原图 OCR)
    imap = json.loads((img.tmp / "imgmap.json").read_text(encoding="utf-8"))
    assert "鱼油（Swisse）" in imap
    meta = json.loads((img.tmp / "metamap.json").read_text(encoding="utf-8"))
    assert meta["鱼油（Swisse）"]["total_pills"] == 60


def test_cutout_missing_args_400(client, img):
    assert client.post("/api/cutout", json={"attachment_url": "/attachments/x/y.png"}).status_code == 400
    assert client.post("/api/cutout", json={"task_name": "x"}).status_code == 400
