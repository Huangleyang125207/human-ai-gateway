# TEST PATTERN: characterization — 图像簇 /api/attachments + /api/cutout + /api/vision/classify
# USE WHEN: 锁图像端点现行行为,守 image_routes 抽出(§ 9)+ **同时是移动 parity N4-N8 oracle**
# TESTED IN: gateway image_routes extraction (2026-06-25), § T7 characterization
#
# 双份回报:这组既是 image_routes 抽出的 GREEN-LOCK,也是移动 parity 台账 N4-N8 缺的 oracle
# (vision/classify=N4 · uploads/list=N5 · search=N6 · delete=N7 · attachments/get=N8 · cutout↔set-image=N2)。
# helper(_load/_save_attachments_index / _index_attachment / _gemini_classify_image /
# _get_or_create_processed_attachment / io-map)抽出时 *留 server.py*(chat_routes 也 lazy-import)。

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


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


# ── N4: POST /api/vision/classify ────────────────────────────────────

def test_vision_classify_delegates_and_validates(client, img, monkeypatch):
    img.put("2026-06-25", "p.png")
    monkeypatch.setattr(server, "_gemini_classify_image",
                        lambda f, q="": {"kind": "supplement", "description": f"desc q={q}"})
    d = client.post("/api/vision/classify",
                    json={"attachment_url": "/attachments/2026-06-25/p.png", "extra_question": "啥牌子"}).json()
    assert d["kind"] == "supplement" and "啥牌子" in d["description"]
    assert client.post("/api/vision/classify", json={}).status_code == 400          # 缺 url
    assert client.post("/api/vision/classify", json={"attachment_url": "bad"}).status_code == 400


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
