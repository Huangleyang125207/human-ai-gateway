"""scrapbook — 当日图卡(用户拖图/抠图的 attachment 元数据)读写。

从 server.py 抽出。每天一个 JSON 文件,损坏 = 当日图卡全失 → 写盘走 _safe_write_text(原子+滚动备份)。
endpoint(`/api/scrapbook` GET/POST/DELETE)留 server.py,本模块只持有 4 个 helper。

外部依赖(函数体内 lazy import 避循环):
  - server.SCRAPBOOK_DIR          — 数据目录
  - server._safe_write_text       — 原子写 + rotate 备份
  - server._report_silent_failure — parse 失败上报
"""
import json
import uuid
from pathlib import Path


def _scrapbook_path(date_str: str) -> Path:
    from server import SCRAPBOOK_DIR
    return SCRAPBOOK_DIR / f"{date_str}.json"


def _load_scrapbook(date_str: str) -> list:
    from server import _report_silent_failure
    p = _scrapbook_path(date_str)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        _report_silent_failure("scrapbook_parse_failed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"date": date_str, "file_size_kb": p.stat().st_size // 1024})
        return []


def _save_scrapbook(date_str: str, items: list):
    """A-H1: scrapbook 是用户拖图/抠图的 attachment 元数据,损坏 = 当日图卡全失"""
    from server import SCRAPBOOK_DIR, _safe_write_text
    SCRAPBOOK_DIR.mkdir(parents=True, exist_ok=True)
    _safe_write_text(
        _scrapbook_path(date_str),
        json.dumps(items, indent=2, ensure_ascii=False),
        rotate=True,
    )


def _scrapbook_id() -> str:
    return uuid.uuid4().hex[:12]
