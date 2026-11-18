# PATTERN: service — read-only journal queries with explicit dependencies
# USE WHEN: serving journal day lists, parsed days, or tag statistics
# COPY THIS: inject journal query functions and journal directory

import re
from pathlib import Path


# 与移动 shim tag-stats 兜底 + 移动 UI 建议列表同一套；改一处必须同步三处。
DEFAULT_TAGS = ["工作", "生活", "健康", "心情", "运动"]


class JournalReadService:
    def __init__(self, *, journal_for_date, list_journal_files, journal_dir):
        self.journal_for_date = journal_for_date
        self.list_journal_files = list_journal_files
        self.journal_dir = Path(journal_dir)

    def today(self, date_arg=None):
        return self.journal_for_date(date_arg)

    def days(self) -> dict:
        return {"days": self.list_journal_files()}

    def tag_stats(self, limit: int = 5) -> dict:
        counts = {}
        if self.journal_dir.exists():
            for path in self.journal_dir.glob("*.md"):
                try:
                    text = path.read_text(encoding="utf-8")
                except Exception:
                    continue
                for line in text.splitlines():
                    if line.startswith("## "):
                        for tag in re.findall(r"#(\S+)", line[3:]):
                            counts[tag] = counts.get(tag, 0) + 1
        top = sorted(counts.items(), key=lambda item: -item[1])[
            :max(1, limit)
        ]
        if not top:
            return {
                "tags": [
                    {"tag": tag, "count": 0, "default": True}
                    for tag in DEFAULT_TAGS
                ]
            }
        return {
            "tags": [{"tag": tag, "count": count} for tag, count in top]
        }
