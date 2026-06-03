# TEST PATTERN: effect — upload endpoint dedups by sha256
# USE WHEN: 改 upload 路径 / index helper 时,这套测试确保同字节图不再产
#           多 record(5.16 哈士奇站客厅 1 张照片被存成 5 record 的回归防御)
# TESTED IN: gateway (2026-06-03)

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import server  # noqa: E402


@pytest.fixture
def isolated_attachments(tmp_path, monkeypatch):
    """让 upload + index 写到隔离的 tmp 目录,不动真 live 索引。"""
    fake_dir = tmp_path / "attachments"
    fake_dir.mkdir(parents=True)
    monkeypatch.setattr(server, "ATTACHMENTS_DIR", fake_dir)
    monkeypatch.setattr(server, "ATTACHMENTS_INDEX", fake_dir / "_index.json")
    monkeypatch.setattr(server, "CURATOR_SYSTEM_PATH", fake_dir / "_curator_system.txt")
    # 别让背景 OCR 真跑(端侧 binary 不一定在路径),给个 noop
    monkeypatch.setattr(server, "_ocr_text", lambda p: "")
    monkeypatch.setattr(server, "_rebuild_curator_system_prompt", lambda: None)
    return fake_dir


# ─── T1 · 同字节 upload 两次,返同 url(dedup 命中) ──────────

def test_same_bytes_upload_twice_returns_same_url(isolated_attachments):
    client = TestClient(server.app)
    payload = b"\x89PNG\r\n\x1a\n" + b"A" * 200  # 一坨假 PNG bytes
    r1 = client.post("/api/chat/upload-image",
                     files={"file": ("first.jpg", payload, "image/jpeg")})
    assert r1.status_code == 200, r1.text
    j1 = r1.json()
    assert j1["deduped"] is False

    r2 = client.post("/api/chat/upload-image",
                     files={"file": ("renamed_later.jpg", payload, "image/jpeg")})
    assert r2.status_code == 200, r2.text
    j2 = r2.json()
    assert j2["url"] == j1["url"], f"dedup 没生效: {j1['url']} vs {j2['url']}"
    assert j2["deduped"] is True
    assert j2.get("deduped_to"), "dedup 应该回报指向 keep 那条的 date/filename"


# ─── T2 · 不同字节 upload,创建独立 record ────────────────

def test_different_bytes_upload_creates_distinct(isolated_attachments):
    client = TestClient(server.app)
    r1 = client.post("/api/chat/upload-image",
                     files={"file": ("a.jpg", b"AAAAA" * 100, "image/jpeg")})
    r2 = client.post("/api/chat/upload-image",
                     files={"file": ("b.jpg", b"BBBBB" * 100, "image/jpeg")})
    j1, j2 = r1.json(), r2.json()
    assert j1["url"] != j2["url"], "不同字节应该写两份"
    assert j1["deduped"] is False
    assert j2["deduped"] is False
    files = sorted((isolated_attachments).rglob("*.jpg"))
    assert len(files) == 2, f"应该两个独立物理文件: {files}"


# ─── T3 · 同字节 dedup 时,不写新物理文件 ─────────────────

def test_dedup_does_not_write_new_file(isolated_attachments):
    client = TestClient(server.app)
    payload = b"identical" * 50
    client.post("/api/chat/upload-image",
                files={"file": ("first.jpg", payload, "image/jpeg")})
    files_after_first = sorted(isolated_attachments.rglob("*.jpg"))

    client.post("/api/chat/upload-image",
                files={"file": ("dup.jpg", payload, "image/jpeg")})
    files_after_second = sorted(isolated_attachments.rglob("*.jpg"))

    assert files_after_first == files_after_second, (
        f"dedup 不该写新文件,实际多了: "
        f"{set(files_after_second) - set(files_after_first)}"
    )


# ─── T4 · 新 upload 的 index record 必带 hash 字段 ─────────

def test_new_upload_index_record_has_hash(isolated_attachments):
    client = TestClient(server.app)
    payload = b"some unique bytes here" + b"X" * 100
    client.post("/api/chat/upload-image",
                files={"file": ("a.jpg", payload, "image/jpeg")})
    # TestClient 会等 BackgroundTasks 跑完,所以 index 该有 hash 了
    idx = server._load_attachments_index()
    assert idx, "index 空"
    rec = idx[0]
    assert rec.get("hash"), f"新 upload 没记 hash 字段: {rec}"
    assert len(rec["hash"]) == 64, f"hash 应该是 sha256 hex (64 字符): len={len(rec['hash'])}"
    # 字符全 hex
    int(rec["hash"], 16)  # 不抛即合法 hex


# ─── T5 · _find_by_hash helper 合约 ─────────────────────

def test_find_by_hash_empty_returns_none(isolated_attachments):
    assert server._find_by_hash("") is None
    assert server._find_by_hash("a" * 64) is None  # 空 index 找不着


def test_find_by_hash_finds_existing(isolated_attachments):
    # 直接 upsert 一个 record
    server._index_upsert("2026-06-03", "fake.jpg",
                        url="/attachments/2026-06-03/fake.jpg",
                        hash="b" * 64, size=123)
    rec = server._find_by_hash("b" * 64)
    assert rec is not None
    assert rec["filename"] == "fake.jpg"
    # 别的 hash 找不着
    assert server._find_by_hash("c" * 64) is None
