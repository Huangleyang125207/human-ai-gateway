#!/usr/bin/env python3
"""capture-golden.py — 跑桌面 canonical 端点,把输出 dump 进 golden/ 给 JS oracle 字节比。

桌面是真相:同一输入,桌面产出 = mobile shim 必须复刻的字节。改桌面后重跑刷新 golden。
用法:  ~/.../.venv-test/bin/python mobile/parity/capture-golden.py
这是 ONE feature 的样板(daily-task check 写 md)。mobile session 照这个 pattern 加别的 case。
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # gateway/
sys.path.insert(0, str(ROOT))
GOLD = Path(__file__).resolve().parent / "golden"
GOLD.mkdir(exist_ok=True)

# 隔离:绝不碰真 vault(同 tests 的 dt fixture 手法)——临时 home,临时常量
import tempfile
TMP = Path(tempfile.mkdtemp(prefix="parity-golden-"))
(TMP / "journal").mkdir()
(TMP / "data").mkdir()

import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

server.JOURNAL_DIR = TMP / "journal"
server.DAILY_TASK_META_MAP = TMP / "data" / "daily-task-meta.json"
server.DAILY_TASK_IMAGES_MAP = TMP / "data" / "daily-task-images.json"
server.DAILY_TASK_IMAGES_DIR = TMP / "data" / "imgs"
server.SCHEDULE_TEMPLATE_PATH = TMP / "daily-tasks.md"
server.vault_git.commit_after_write = lambda *a, **k: None
client = TestClient(server.app)


def _today():
    d = datetime.now()
    return f"{str(d.year)[-2:]}.{d.month}.{d.day}"


def write(name, content):
    (GOLD / name).write_text(content, encoding="utf-8")
    print(f"  ✓ golden/{name} ({len(content)}B)")


# ── case: daily-task check intake clamp(维生素D daily_dose=2,intake=5 → clamp 2,md [x])──
def cap_daily_task_check_clamp():
    f = server.JOURNAL_DIR / f"{_today()}(g).md"
    f.write_text("# 9：00\n\n- [ ] 维生素D\n\n---\n\n# 7：30\n晨\n", encoding="utf-8")
    server.DAILY_TASK_META_MAP.write_text(
        json.dumps({"维生素D": {"daily_dose": 2}}, ensure_ascii=False), encoding="utf-8")
    r = client.post("/api/daily-tasks/check", json={"task_name": "维生素D", "intake": 5})
    # canonical:① 响应 JSON ② 写后的 md 字节
    write("daily_tasks__check_clamp.response.json", json.dumps(r.json(), ensure_ascii=False, indent=2))
    write("daily_tasks__check_clamp.md", f.read_text(encoding="utf-8"))


if __name__ == "__main__":
    print("capture goldens →", GOLD)
    cap_daily_task_check_clamp()
    # TODO(mobile session):照 cap_* pattern 加 journal patch / insert / thread save 等 case
    print("done. 改桌面 canonical 后重跑刷新。")
