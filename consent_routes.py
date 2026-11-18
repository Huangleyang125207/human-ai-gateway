# PATTERN: routes — consent licenses CRUD + filter preview extracted from god module
# USE WHEN: /api/consent/* 端点或 license filter 逻辑改动
# COPY THIS: 无 — 本模块是 server.py §16(清册01)的搬迁体,契约在 server re-export
#
# 抽出记录(2026-07-21, 清册01-§16 第四刀,Parallel Change expand):
# - 原址 server.py L3617–3746(拆前行号);4 端点上 APIRouter(HTTP 路径不变),
#   4 个 helper + CONSENT_LICENSES_PATH 在 server.py 保留同名 re-export/权威绑定,
#   tests/test_consent.py 的 monkeypatch.setattr(server, "CONSENT_LICENSES_PATH", ...)
#   与 server._matches_filters 直调 一字不改。
# - license/data 路径与原子写由组装根以具名 provider 注入；端点直接调用本模块
#   helper，不再反向导入 server。
# MVP:存 license config + 给 filter 算 preview count。不真生成 export bundle
# (那是 Phase 2 + 加密签名)。consent.html 前端用这 4 个 endpoint。
import json
import secrets
from datetime import datetime

from fastapi import APIRouter, Request

router = APIRouter(tags=["consent"])

_LICENSES_PATH = None
_DATA_DIR = None
_SAFE_WRITE_TEXT = None


def configure_effects(*, licenses_path, data_dir, safe_write_text) -> None:
    global _LICENSES_PATH, _DATA_DIR, _SAFE_WRITE_TEXT
    _LICENSES_PATH = licenses_path
    _DATA_DIR = data_dir
    _SAFE_WRITE_TEXT = safe_write_text


def _load_licenses() -> list[dict]:
    licenses_path = _LICENSES_PATH()
    if not licenses_path.exists():
        return []
    try:
        return json.loads(licenses_path.read_text(encoding="utf-8")).get("licenses", [])
    except Exception:
        return []


def _save_licenses(licenses: list[dict]) -> None:
    licenses_path = _LICENSES_PATH()
    licenses_path.parent.mkdir(parents=True, exist_ok=True)
    _SAFE_WRITE_TEXT(
        licenses_path,
        json.dumps({"licenses": licenses}, ensure_ascii=False, indent=2),
        rotate=True,
    )


def _matches_filters(row: dict, f: dict) -> bool:
    """row 是 history_exporter 出的 jsonl row,f 是 license filter 字典。
    任一字段为空(None / [])= 不过滤(全包)。"""
    if f.get("sources") and row.get("source") not in f["sources"]:
        return False
    if f.get("authors") and row.get("author") not in f["authors"]:
        return False
    tags = set(row.get("tags") or [])
    if f.get("tags_include"):
        if not tags & set(f["tags_include"]):
            return False
    if f.get("tags_exclude"):
        if tags & set(f["tags_exclude"]):
            return False
    ts = row.get("ts") or ""
    if f.get("since") and ts < f["since"]:
        return False
    if f.get("until") and ts > f["until"]:
        return False
    return True


def _iter_all_rows() -> list[dict]:
    """从 history-exports/all.jsonl 读所有 row(consent preview / export 用)。"""
    p = _DATA_DIR() / "history-exports" / "all.jsonl"
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


@router.get("/api/consent/licenses")
def consent_list():
    """列出已保存的 license 配置(含每个的 preview_count snapshot)。"""
    return {"licenses": _load_licenses()}


@router.post("/api/consent/preview")
async def consent_preview(req: Request):
    """给 filter dict,返本次 license 涵盖多少 row + 3 行 sample。
    body: {sources, authors, tags_include, tags_exclude, since, until}
    任一为空数组/null = 全包。
    """
    body = await req.json()
    rows = _iter_all_rows()
    matched = [r for r in rows if _matches_filters(r, body)]
    sample = []
    for r in matched[:3]:
        sample.append({
            "commit": r.get("commit", "")[:12],
            "ts": r.get("ts"),
            "source": r.get("source"),
            "author": r.get("author"),
            "action": r.get("action"),
            "tags": r.get("tags"),
        })
    return {
        "total_rows": len(rows),
        "matched_count": len(matched),
        "sample": sample,
        "filters_applied": body,
    }


@router.post("/api/consent/licenses")
async def consent_save(req: Request):
    """新增或更新 license。body 不带 id → 新增;带 id → update 同 id。
    schema:{label, buyer, filters, expires?}
    """
    body = await req.json()
    licenses = _load_licenses()
    lid = body.get("id") or f"lic_{secrets.token_hex(6)}"
    # 计算 preview snapshot
    rows = _iter_all_rows()
    matched_count = sum(1 for r in rows if _matches_filters(r, body.get("filters") or {}))
    entry = {
        "id": lid,
        "label": (body.get("label") or "untitled").strip(),
        "buyer": (body.get("buyer") or "—").strip(),
        "created": datetime.now().isoformat(timespec="seconds"),
        "expires": body.get("expires"),
        "filters": body.get("filters") or {},
        "preview_count": matched_count,
    }
    # upsert
    out = [l for l in licenses if l.get("id") != lid]
    out.append(entry)
    _save_licenses(out)
    return entry


@router.delete("/api/consent/licenses/{lid}")
def consent_delete(lid: str):
    licenses = _load_licenses()
    out = [l for l in licenses if l.get("id") != lid]
    if len(out) == len(licenses):
        return {"deleted": False, "id": lid}
    _save_licenses(out)
    return {"deleted": True, "id": lid, "remaining": len(out)}
