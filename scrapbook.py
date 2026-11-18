"""scrapbook — 当日图卡(用户拖图/抠图的 attachment 元数据)读写。

从 server.py 抽出。每天一个 JSON 文件,损坏 = 当日图卡全失 → 写盘走 _safe_write_text(原子+滚动备份)。
endpoint(`/api/scrapbook` GET/POST/DELETE)留 server.py,本模块只持有 4 个 helper。

目录、原子写和失败上报通过窄参数注入；server 保留兼容签名。
"""
import json
import uuid
from pathlib import Path


def _scrapbook_path(date_str: str, *, scrapbook_dir) -> Path:
    return Path(scrapbook_dir) / f"{date_str}.json"


def _load_scrapbook(date_str: str, *, path_for_date, report_failure) -> list:
    p = path_for_date(date_str)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        report_failure("scrapbook_parse_failed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"date": date_str, "file_size_kb": p.stat().st_size // 1024})
        return []


def _save_scrapbook(
    date_str: str,
    items: list,
    *,
    scrapbook_dir,
    path_for_date,
    write_text,
):
    """A-H1: scrapbook 是用户拖图/抠图的 attachment 元数据,损坏 = 当日图卡全失"""
    scrapbook_dir.mkdir(parents=True, exist_ok=True)
    write_text(
        path_for_date(date_str),
        json.dumps(items, indent=2, ensure_ascii=False),
        rotate=True,
    )


def _scrapbook_id() -> str:
    return uuid.uuid4().hex[:12]
