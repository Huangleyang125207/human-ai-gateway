#!/usr/bin/env python3
"""capture-golden.py — 跑桌面 canonical 端点,把"PC 真跑出来的实例"dump 进 golden/。

桌面是真相:同一输入,桌面产出的字节/JSON = mobile shim 必须复刻的开发边界。
这不是单元测试 —— 是"产品定义的可执行快照"。mobile self-test 拿这些 golden 当 ground truth。
改桌面后重跑刷新 golden。见 mobile/TEST_FIRST_MIGRATION.md。

用法:  <gateway>/.venv-test/bin/python mobile/parity/capture-golden.py
        加 -v 看每个 case 的 PASS/FAIL 细节。

隔离纪律(★绝不碰真 vault):每个 case 自建临时 home + 直接赋值 server.<常量>,跑完即弃。
确定性纪律:date-anchored 端点(响应含"今天")只把『写后 md 字节』当 golden;能传 date 的用固定
历史日期;daily-tasks 冻结 server.datetime;thread 的 mtime 字段归一化为 0。
"""
import datetime as _dt
import json
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # gateway/
sys.path.insert(0, str(ROOT))
GOLD = Path(__file__).resolve().parent / "golden"
GOLD.mkdir(exist_ok=True)
VERBOSE = "-v" in sys.argv

import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_RESULTS = []  # (name, ok, detail)


def write(name, content):
    if isinstance(content, (dict, list)):
        content = json.dumps(content, ensure_ascii=False, indent=2)
    (GOLD / name).write_text(content, encoding="utf-8")


def cap(name, fn):
    """跑一个 case,捕获异常 → 不让一个失败炸掉整批;记 PASS/FAIL。"""
    try:
        fn()
        _RESULTS.append((name, True, ""))
        if VERBOSE:
            print(f"  ✓ {name}")
    except Exception as e:
        _RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        print(f"  ✗ {name}  {type(e).__name__}: {e}")
        if VERBOSE:
            traceback.print_exc()


def fresh(prefix):
    return Path(tempfile.mkdtemp(prefix=f"parity-golden-{prefix}-"))


def freeze_now(d):
    """monkeypatch server.datetime.now() → 固定 d(daily-tasks 补卡窗口确定性必需)。"""
    class _F(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return d
    server.datetime = _F


def _real_now():
    return _dt.datetime(2026, 6, 26, 11, 0, 0)  # 固定"今天"基准,不用 wall-clock


def norm_mtime(d):
    """把 response 里的 mtime/current_mtime 归一化为 0(非确定字段)。"""
    if isinstance(d, dict):
        return {k: (0 if k in ("mtime", "current_mtime") else norm_mtime(v)) for k, v in d.items()}
    if isinstance(d, list):
        return [norm_mtime(x) for x in d]
    return d


# ╔══════════════════════════════════════════════════════════════════╗
# ║ daily_tasks 簇                                                      ║
# ╚══════════════════════════════════════════════════════════════════╝

def _dt_env():
    TMP = fresh("dt")
    (TMP / "journal").mkdir(); (TMP / "data").mkdir(); (TMP / "data" / "imgs").mkdir()
    server.JOURNAL_DIR = TMP / "journal"
    server.DAILY_TASK_META_MAP = TMP / "data" / "daily-task-meta.json"
    server.DAILY_TASK_IMAGES_MAP = TMP / "data" / "daily-task-images.json"
    server.DAILY_TASK_IMAGES_DIR = TMP / "data" / "imgs"
    server.SCHEDULE_TEMPLATE_PATH = TMP / "daily-tasks.md"
    server.DAILY_TASKS_SOURCE = TMP / "daily-tasks.md"
    server.PLATFORM_ROOT = TMP
    server.VAULT_DIR = TMP
    server.TAG_AGGREGATE_PATH = TMP / "标签聚合.md"
    server.vault_git.commit_after_write = lambda *a, **k: None
    return TMP


def _prefix(d):
    return f"{str(d.year)[-2:]}.{d.month}.{d.day}"


def _write_day(tasks, d):
    """tasks: list[str] 或 list[{name,checked}]。写 {YY.M.D}(g).md。"""
    lines = [f"# {_prefix(d)} test", ""]
    for t in tasks:
        if isinstance(t, dict):
            box = "x" if t.get("checked") else " "
            lines.append(f"- [{box}] {t['name']}")
        else:
            lines.append(f"- [ ] {t}")
    lines += ["", "---", "", "# 7：30", "晨", ""]
    f = server.JOURNAL_DIR / f"{_prefix(d)}(g).md"
    f.write_text("\n".join(lines), encoding="utf-8")
    return f


def _write_template(tasks):
    body = ["# 每日补剂", ""] + [f"- [ ] {t}" for t in tasks] + ["", "---", ""]
    server.SCHEDULE_TEMPLATE_PATH.write_text("\n".join(body), encoding="utf-8")


def _write_meta(d):
    server.DAILY_TASK_META_MAP.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _write_images(d):
    server.DAILY_TASK_IMAGES_MAP.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _iso(d):
    return d.date().isoformat()


def cap_dt_catalog_fresh():
    _dt_env(); now = _real_now().replace(hour=11); freeze_now(now)
    _write_day(["鱼油", "维生素D"], now)
    c = TestClient(server.app)
    r = c.get("/api/daily-tasks")
    write("daily_tasks__catalog_fresh.response.json", r.json())


def cap_dt_check_clamp():
    _dt_env(); now = _real_now().replace(hour=11); freeze_now(now)
    f = _write_day(["维生素D"], now); _write_meta({"维生素D": {"daily_dose": 2}})
    c = TestClient(server.app)
    r = c.post("/api/daily-tasks/check", json={"task_name": "维生素D", "intake": 5})
    write("daily_tasks__check_clamp.response.json", r.json())
    write("daily_tasks__check_clamp.md", f.read_text(encoding="utf-8"))


def cap_dt_check_default_dose1():
    _dt_env(); now = _real_now().replace(hour=11); freeze_now(now)
    f = _write_day(["鱼油"], now)
    c = TestClient(server.app)
    r = c.post("/api/daily-tasks/check", json={"task_name": "鱼油", "checked": True})
    write("daily_tasks__check_default_dose1.response.json", r.json())
    write("daily_tasks__check_default_dose1.md", f.read_text(encoding="utf-8"))


def cap_dt_check_decrement():
    _dt_env(); now = _real_now().replace(hour=11); freeze_now(now)
    f = _write_day(["维生素D"], now); _write_meta({"维生素D": {"daily_dose": 2}})
    c = TestClient(server.app)
    c.post("/api/daily-tasks/check", json={"task_name": "维生素D", "intake": 2})
    r = c.post("/api/daily-tasks/check", json={"task_name": "维生素D", "increment": -1})
    write("daily_tasks__check_decrement_unchecks.response.json", r.json())
    write("daily_tasks__check_decrement_unchecks.md", f.read_text(encoding="utf-8"))


def cap_dt_backfill_yesterday_ok():
    _dt_env(); now = _real_now().replace(hour=11); freeze_now(now)
    _write_day(["鱼油"], now)
    y = _iso(now - _dt.timedelta(days=1))
    c = TestClient(server.app)
    r = c.post("/api/daily-tasks/check", json={"task_name": "鱼油", "date": y, "checked": True})
    write("daily_tasks__check_backfill_yesterday_ok.response.json", {"__now__": now.isoformat(), "status": r.status_code, "body": r.json()})
    write("daily_tasks__check_backfill_yesterday_ok.meta.json", server.DAILY_TASK_META_MAP.read_text(encoding="utf-8"))


def cap_dt_backfill_closed():
    _dt_env(); now = _real_now().replace(hour=13); freeze_now(now)
    _write_day(["鱼油"], now)
    y = _iso(now - _dt.timedelta(days=1))
    c = TestClient(server.app, raise_server_exceptions=False)
    r = c.post("/api/daily-tasks/check", json={"task_name": "鱼油", "date": y, "checked": True})
    write("daily_tasks__check_backfill_yesterday_closed.response.json", {"__now__": now.isoformat(), "status": r.status_code, "body": r.json()})


def cap_dt_rejects_future_and_2ago():
    _dt_env(); now = _real_now().replace(hour=10); freeze_now(now)
    _write_day(["鱼油"], now)
    tmr = _iso(now + _dt.timedelta(days=1)); two = _iso(now - _dt.timedelta(days=2))
    c = TestClient(server.app, raise_server_exceptions=False)
    rf = c.post("/api/daily-tasks/check", json={"task_name": "鱼油", "date": tmr, "checked": True})
    rt = c.post("/api/daily-tasks/check", json={"task_name": "鱼油", "date": two, "checked": True})
    write("daily_tasks__check_rejects_future.response.json", {"__now__": now.isoformat(), "status": rf.status_code, "body": rf.json()})
    write("daily_tasks__check_rejects_two_days_ago.response.json", {"status": rt.status_code, "body": rt.json()})


def cap_dt_catalog_writable_window():
    _dt_env(); now = _real_now().replace(hour=10); freeze_now(now)
    _write_day(["鱼油"], now)
    y = _iso(now - _dt.timedelta(days=1)); tmr = _iso(now + _dt.timedelta(days=1))
    c = TestClient(server.app)
    ry = c.get("/api/daily-tasks", params={"date": y})
    rt = c.get("/api/daily-tasks", params={"date": tmr})
    write("daily_tasks__catalog_writable_yesterday.response.json", {"__now__": now.isoformat(), "is_writable": ry.json().get("is_writable")})
    write("daily_tasks__catalog_writable_tomorrow.response.json", {"is_writable": rt.json().get("is_writable")})


def cap_dt_meta_set_clear():
    _dt_env(); now = _real_now().replace(hour=11); freeze_now(now)
    _write_day(["鱼油"], now)
    c = TestClient(server.app)
    r1 = c.post("/api/daily-tasks/meta", json={"task_name": "鱼油", "total_pills": 60, "daily_dose": 2})
    r2 = c.post("/api/daily-tasks/meta", json={"task_name": "鱼油", "total_pills": ""})
    write("daily_tasks__meta_set.response.json", r1.json())
    write("daily_tasks__meta_clear_pills.response.json", r2.json())
    write("daily_tasks__meta_after.meta.json", server.DAILY_TASK_META_MAP.read_text(encoding="utf-8"))


def cap_dt_meta_non_int_400():
    _dt_env(); now = _real_now().replace(hour=11); freeze_now(now)
    _write_day(["鱼油"], now)
    c = TestClient(server.app, raise_server_exceptions=False)
    a = c.post("/api/daily-tasks/meta", json={"task_name": "鱼油", "total_pills": "abc"})
    b = c.post("/api/daily-tasks/meta", json={"task_name": "鱼油", "daily_dose": "x"})
    write("daily_tasks__meta_non_int_total_pills.response.json", {"status": a.status_code})
    write("daily_tasks__meta_non_int_daily_dose.response.json", {"status": b.status_code})


def cap_dt_check_non_int_500():
    _dt_env(); now = _real_now().replace(hour=11); freeze_now(now)
    _write_day(["鱼油"], now)
    c = TestClient(server.app, raise_server_exceptions=False)
    a = c.post("/api/daily-tasks/check", json={"task_name": "鱼油", "intake": "abc"})
    b = c.post("/api/daily-tasks/check", json={"task_name": "鱼油", "increment": "x"})
    write("daily_tasks__check_non_int_intake.response.json", {"status": a.status_code})
    write("daily_tasks__check_non_int_increment.response.json", {"status": b.status_code})


def cap_dt_history_oldest_first():
    _dt_env(); now = _real_now().replace(hour=11); freeze_now(now)
    _write_day([{"name": "鱼油", "checked": True}], now)
    _write_day([{"name": "鱼油", "checked": False}], now - _dt.timedelta(days=2))
    c = TestClient(server.app)
    r = c.get("/api/daily-tasks/history", params={"name": "鱼油", "days": 3})
    write("daily_tasks__history_oldest_first.response.json", {"__now__": now.isoformat(), "body": r.json()})


def cap_dt_water_cup_roundtrip():
    TMP = _dt_env(); now = _real_now().replace(hour=11); freeze_now(now)
    src = TMP / "data" / "src.png"; src.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
    server._get_or_create_processed_attachment = lambda url: (src, None)
    server._pretty_rel = lambda p: f"data/daily-task-images/{Path(p).name}"
    c = TestClient(server.app)
    rp = c.post("/api/water-cup", json={"attachment_url": "/attachments/x/y.png"})
    rg = c.get("/api/water-cup")
    write("daily_tasks__water_cup_post.response.json", rp.json())
    write("daily_tasks__water_cup_get.response.json", {"image_url_present": bool(rg.json().get("image_url"))})
    write("daily_tasks__water_cup.images.json", server.DAILY_TASK_IMAGES_MAP.read_text(encoding="utf-8"))


def cap_dt_water_cup_missing_400():
    _dt_env(); now = _real_now().replace(hour=11); freeze_now(now)
    c = TestClient(server.app, raise_server_exceptions=False)
    r = c.post("/api/water-cup", json={})
    write("daily_tasks__water_cup_missing_url.response.json", {"status": r.status_code})


def cap_dt_delete_cascade():
    _dt_env(); now = _real_now().replace(hour=11); freeze_now(now)
    _write_template(["鱼油", "维生素D"]); day = _write_day(["鱼油", "维生素D"], now)
    _write_meta({"鱼油": {"daily_dose": 1, "intake_log": {_iso(now): 1}}})
    img = server.DAILY_TASK_IMAGES_DIR / "yuyou.png"; img.write_bytes(b"x")
    _write_images({"鱼油": "data/daily-task-images/yuyou.png"})
    c = TestClient(server.app)
    r = c.post("/api/daily-tasks/delete", json={"task_name": "鱼油"})
    write("daily_tasks__delete_cascade.response.json", r.json())
    write("daily_tasks__delete_cascade.day.md", day.read_text(encoding="utf-8"))
    write("daily_tasks__delete_cascade.template.md", server.SCHEDULE_TEMPLATE_PATH.read_text(encoding="utf-8"))
    write("daily_tasks__delete_cascade.images.json", server.DAILY_TASK_IMAGES_MAP.read_text(encoding="utf-8"))
    write("daily_tasks__delete_cascade.meta.json", server.DAILY_TASK_META_MAP.read_text(encoding="utf-8"))


def cap_dt_backfill_progress():
    _dt_env(); now = _real_now().replace(hour=11); freeze_now(now)
    day = _write_day(["维生素D"], now)
    _write_meta({"维生素D": {"daily_dose": 3, "intake_log": {_iso(now): 2}}})
    c = TestClient(server.app)
    r1 = c.post("/api/daily-tasks/backfill-progress", json={})
    r2 = c.post("/api/daily-tasks/backfill-progress", json={})
    write("daily_tasks__backfill_progress_first.response.json", r1.json())
    write("daily_tasks__backfill_progress_second.response.json", r2.json())
    write("daily_tasks__backfill_progress.day.md", day.read_text(encoding="utf-8"))


def cap_dt_template_add_edit():
    _dt_env(); now = _real_now().replace(hour=11); freeze_now(now)
    _write_template(["鱼油"]); day = _write_day(["鱼油"], now)
    c = TestClient(server.app)
    r1 = c.post("/api/template/task", json={"action": "add", "text": "维生素D"})
    r2 = c.post("/api/template/task", json={"action": "edit", "old_text": "维生素D", "text": "维生素C"})
    write("daily_tasks__template_task_add.response.json", r1.json())
    write("daily_tasks__template_task_edit.response.json", r2.json())
    write("daily_tasks__template_task.template.md", server.SCHEDULE_TEMPLATE_PATH.read_text(encoding="utf-8"))
    write("daily_tasks__template_task.day.md", day.read_text(encoding="utf-8"))


def cap_vault_audit():
    _dt_env(); now = _real_now().replace(hour=11); freeze_now(now)
    _write_images({"鱼油": "data/daily-task-images/missing.png"})
    _write_meta({"幽灵": {"intake_log": {"2026-06-20": 1}}})
    c = TestClient(server.app)
    r = c.get("/api/vault/audit")
    write("vault__audit_orphans.response.json", r.json())


def cap_vault_repair():
    _dt_env(); now = _real_now().replace(hour=11); freeze_now(now)
    real = server.DAILY_TASK_IMAGES_DIR / "yuyou.png"; real.write_bytes(b"\x89PNG")
    _write_images({"鱼油": "data/daily-task-images/OLD/yuyou.png"})
    _write_day(["鱼油"], now)
    c = TestClient(server.app)
    rr = c.post("/api/vault/repair", json={})
    rc = c.get("/api/daily-tasks")
    img = next((t.get("image_url") for t in rc.json().get("tasks", []) if t.get("name") == "鱼油"), None)
    write("vault__repair.response.json", rr.json())
    write("vault__repair_catalog_after.response.json", {"鱼油_image_url_present": bool(img)})


# ╔══════════════════════════════════════════════════════════════════╗
# ║ journal 簇                                                          ║
# ╚══════════════════════════════════════════════════════════════════╝

JOURNAL_BOTH = ("# 9：00\n\n## #思考 早醒 @user\n昨晚 11:30 睡到 7:00,闹钟 7:40。躺着也没睡着。\n\n"
                "---\n\n# 10：00\n\n## #投资 #协作 KV cache @ai\n推 RDMA 思路。\n\n"
                "- #commit (葱鸭): 先验证可行性。\n- #commit (claude-opus-4.8): 注意带宽瓶颈。\n")
TODAY_CANON = ("# 9：00\n\n## #思考 早醒 @user\n昨晚睡得晚。\n\n# 10：00\n\n## #投资 KV cache @ai\n推 RDMA 思路。\n")


def _jn_env():
    TMP = fresh("journal")
    (TMP / "journal").mkdir()
    server.JOURNAL_DIR = TMP / "journal"
    server.VAULT_DIR = TMP
    server.TAG_AGGREGATE_PATH = TMP / "标签聚合.md"
    server.DAILY_TASKS_SOURCE = TMP / "daily-tasks.md"
    server.vault_git.commit_after_write = lambda *a, **k: None
    server.load_config = lambda: {}
    return TMP


def _today_stem(now=None):
    now = now or _real_now()
    return f"{str(now.year)[-2:]}.{now.month}.{now.day}(g).md"


def cap_jn_new_day():
    TMP = _jn_env()
    c = TestClient(server.app)
    r1 = c.post("/api/journal/new-day", json={"date": "2026-06-22"})
    write("journal__new_day_create.response.json", r1.json())
    f = TMP / "journal" / "26.6.22(第一天).md"
    if f.exists():
        write("journal__new_day_26.6.22.md", f.read_text(encoding="utf-8"))
    r2 = c.post("/api/journal/new-day", json={"date": "2026-06-22"})
    write("journal__new_day_idempotent.response.json", r2.json())


def cap_jn_insert_stamps_user():
    TMP = _jn_env()
    f = TMP / "journal" / _today_stem(); f.write_text(TODAY_CANON, encoding="utf-8")
    c = TestClient(server.app)
    r = c.post("/api/journal/insert-block", json={"time": "11:00", "tag": "工作", "title": "新条目", "body": "正文"})
    write("journal__insert_stamps_user.md", f.read_text(encoding="utf-8"))
    write("journal__insert_stamps_user.response.json", {"status": r.status_code, "ok": r.json().get("ok"), "inserted": r.json().get("inserted")})


def cap_jn_insert_missing_time():
    TMP = _jn_env()
    f = TMP / "journal" / _today_stem(); f.write_text(TODAY_CANON, encoding="utf-8")
    c = TestClient(server.app, raise_server_exceptions=False)
    r = c.post("/api/journal/insert-block", json={"title": "x"})
    write("journal__insert_missing_time.response.json", {"status": r.status_code})


def cap_jn_insert_no_journal():
    _jn_env()
    c = TestClient(server.app, raise_server_exceptions=False)
    r = c.post("/api/journal/insert-block", json={"time": "11:00", "title": "x"})
    write("journal__insert_no_journal.response.json", {"status": r.status_code})


def cap_jn_delete_clears():
    TMP = _jn_env()
    f = TMP / "journal" / _today_stem(); f.write_text(TODAY_CANON, encoding="utf-8")
    c = TestClient(server.app)
    r = c.post("/api/journal/delete-block", json={"time": "9:00"})
    write("journal__delete_clears.md", f.read_text(encoding="utf-8"))
    write("journal__delete_clears.response.json", {"ok": r.json().get("ok"), "cleared": r.json().get("cleared")})


def cap_jn_delete_unknown():
    TMP = _jn_env()
    f = TMP / "journal" / _today_stem(); f.write_text(TODAY_CANON, encoding="utf-8")
    c = TestClient(server.app, raise_server_exceptions=False)
    r = c.post("/api/journal/delete-block", json={"time": "23:30"})
    write("journal__delete_unknown.response.json", {"status": r.status_code})


def cap_jn_patch_by_date():
    TMP = _jn_env()
    hist = TMP / "journal" / "26.6.22(g).md"; hist.write_text(TODAY_CANON, encoding="utf-8")
    c = TestClient(server.app)
    r = c.post("/api/journal/patch", json={"time": "10:00", "new_md": "## #投资 历史改 @user\n改过去。", "date": "2026-06-22"})
    write("journal__patch_by_date.md", hist.read_text(encoding="utf-8"))
    write("journal__patch_by_date.response.json", {"patched": r.json().get("patched")})
    write("journal__patch_today_not_created.json", {"today_file_exists": (TMP / "journal" / _today_stem()).exists()})


def cap_jn_patch_missing_newmd():
    TMP = _jn_env()
    (TMP / "journal" / "26.6.22(g).md").write_text(TODAY_CANON, encoding="utf-8")
    c = TestClient(server.app, raise_server_exceptions=False)
    r = c.post("/api/journal/patch", json={"time": "10:00", "date": "2026-06-22"})
    write("journal__patch_missing_newmd.response.json", {"status": r.status_code})


def cap_jn_patch_ai_refuses_user():
    TMP = _jn_env()
    f = TMP / "journal" / "26.5.21(g).md"; f.write_text(JOURNAL_BOTH, encoding="utf-8")
    res = server._patch_block(f, "9:00", "## #思考 改了 @ai\n[AI hallucinated content]", author="ai")
    write("journal__patch_ai_refuses_user.result.json", res)
    write("journal__patch_ai_refuses_user.md", f.read_text(encoding="utf-8"))


def cap_jn_patch_ai_allows_ai():
    TMP = _jn_env()
    f = TMP / "journal" / "26.5.21(g).md"; f.write_text(JOURNAL_BOTH, encoding="utf-8")
    res = server._patch_block(f, "10:00", "## #投资 #协作 KV cache @ai\n新内容。", author="ai")
    write("journal__patch_ai_allows_ai.result.json", res)
    write("journal__patch_ai_allows_ai.md", f.read_text(encoding="utf-8"))


def cap_jn_patch_h2_rename():
    TMP = _jn_env()
    orig = ("# 16：30\n\n##\n\n---\n\n# 17：00\n\n## #探索 小红书 AI 产业链预警 @ai\n\n"
            "把昨天讨论的 capex 消费齿轮论降维发上去了。\n\n---\n\n# 17：30\n\n##\n")
    f = TMP / "journal" / "26.6.4(g).md"; f.write_text(orig, encoding="utf-8")
    new_md = "## #探索 小红书牛奶 Omega-3 科普 @ai\n\n实际发的是悦鲜活牛奶的冷知识。"
    blocked = server._patch_block(f, "17:00", new_md, author="ai")
    write("journal__patch_h2_rename_blocked.result.json", blocked)
    write("journal__patch_h2_rename_blocked.md", f.read_text(encoding="utf-8"))
    f.write_text(orig, encoding="utf-8")  # 复位
    allowed = server._patch_block(f, "17:00", new_md, author="ai", allow_h2_rename=True)
    write("journal__patch_h2_rename_allowed.result.json", allowed)
    write("journal__patch_h2_rename_allowed.md", f.read_text(encoding="utf-8"))


def cap_jn_insert_body():
    TMP = _jn_env()
    f = TMP / "journal" / "26.6.11(g).md"
    f.write_text("# 9：00\n\n##\n\n---\n\n# 9：30\n\n##\n\n---\n", encoding="utf-8")
    res = server._insert_block(f, "9:00", tag="探索", title="测试条目", author="ai", body="发生了什么。\n\n为什么重要。")
    write("journal__insert_body.result.json", res)
    write("journal__insert_body.md", f.read_text(encoding="utf-8"))


def cap_jn_append_comment():
    TMP = _jn_env()
    f = TMP / "journal" / "26.5.21c(g).md"; f.write_text(JOURNAL_BOTH, encoding="utf-8")
    res = server._append_comment_to_block(f, "9:00", comment_md="*AI 回看 5.22: 这条线还在跑*")
    write("journal__append_comment.result.json", res)
    write("journal__append_comment.md", f.read_text(encoding="utf-8"))


def cap_jn_tag_register():
    _jn_env()
    server.TAG_AGGREGATE_PATH.write_text("# 标签聚合\n\n---\n", encoding="utf-8")
    vgit = []
    server.vault_git.commit_after_write = lambda *a, **k: vgit.append(1)
    c = TestClient(server.app)
    r = c.post("/api/tag-aggregate/register", json={"tag": "yanpai"})
    write("journal__tag_register.response.json", r.json())
    write("journal__tag_register.aggregate.md", server.TAG_AGGREGATE_PATH.read_text(encoding="utf-8"))
    write("journal__tag_register.vgit_count.json", {"vgit_count": len(vgit)})


def cap_jn_tag_register_rejects():
    _jn_env()
    server.TAG_AGGREGATE_PATH.write_text("# 标签聚合\n\n## #yanpai\n\n---\n", encoding="utf-8")
    c = TestClient(server.app, raise_server_exceptions=False)
    dup = c.post("/api/tag-aggregate/register", json={"tag": "yanpai"})
    sub = c.post("/api/tag-aggregate/register", json={"tag": "yanpai/传播"})
    write("journal__tag_register_dup.response.json", {"status": dup.status_code, "body": dup.json()})
    write("journal__tag_register_subtag.response.json", {"status": sub.status_code, "body": sub.json()})


def cap_jn_tag_aggregate_get():
    _jn_env()
    server.TAG_AGGREGATE_PATH.write_text(
        "# 标签聚合\n\n## #yanpai\n\n| 日期 | 时间 | 链接 | 内容 |\n|--|--|--|--|\n\n---\n", encoding="utf-8")
    c = TestClient(server.app)
    r = c.get("/api/tag-aggregate")
    write("journal__tag_aggregate_get.response.json", r.json())


def cap_jn_tag_stats_default():
    _jn_env()
    c = TestClient(server.app)
    r = c.get("/api/journal/tag-stats")
    write("journal__tag_stats_default.response.json", r.json())


# ╔══════════════════════════════════════════════════════════════════╗
# ║ thread 簇                                                           ║
# ╚══════════════════════════════════════════════════════════════════╝

def _th_env():
    TMP = fresh("thread"); (TMP / "data").mkdir()
    server.THREAD_HISTORY_PATH = TMP / "data" / "thread-history.json"
    server.DATA_DIR = TMP / "data"
    server.vault_git.commit_after_write = lambda *a, **k: None
    return TMP


def cap_th_history_empty():
    _th_env()
    c = TestClient(server.app)
    r = c.get("/api/thread/history")
    write("thread__history_empty_no_file.response.json", norm_mtime(r.json()))


def cap_th_history_happy():
    _th_env()
    server.THREAD_HISTORY_PATH.write_text(
        json.dumps([{"role": "user", "content": "嗨"}, {"role": "assistant", "content": "在"}], ensure_ascii=False),
        encoding="utf-8")
    c = TestClient(server.app)
    r = c.get("/api/thread/history")
    j = r.json()
    write("thread__history_happy_returns_list.response.json", norm_mtime(j))
    write("thread__history_happy.asserts.json", {"mtime_gt_0": j.get("mtime", 0) > 0, "no_status_key": "status" not in j})


def cap_th_history_corrupt():
    TMP = _th_env()
    rung = []
    server._report_silent_failure = lambda et, msg="", context=None, **k: rung.append(et)
    server.THREAD_HISTORY_PATH.write_text('[{"role": BROKEN', encoding="utf-8")
    (TMP / "data" / "thread-history.json.bak.1").write_text(
        json.dumps([{"role": "user", "content": "旧好的"}]), encoding="utf-8")
    c = TestClient(server.app)
    r = c.get("/api/thread/history")
    j = norm_mtime(r.json())
    if "error" in j:
        j["error"] = "<elided>"
    if isinstance(j.get("baks"), list):
        j["baks"] = [{"index": b.get("index")} for b in j["baks"]]
    write("thread__history_corrupt_modal_payload.response.json", j)
    write("thread__history_corrupt.asserts.json", {"rang_thread_history_read_failed": "thread_history_read_failed" in rung})


def cap_th_history_corrupt_no_baks():
    _th_env()
    server._report_silent_failure = lambda *a, **k: None
    server.THREAD_HISTORY_PATH.write_text('{not json', encoding="utf-8")
    c = TestClient(server.app)
    r = c.get("/api/thread/history")
    j = norm_mtime(r.json())
    if "error" in j:
        j["error"] = "<elided>"
    write("thread__history_corrupt_no_baks.response.json", j)


def cap_th_restore_roundtrip():
    TMP = _th_env()
    server.THREAD_HISTORY_PATH.write_text("CORRUPT-CURRENT", encoding="utf-8")
    (TMP / "data" / "thread-history.json.bak.2").write_text(
        json.dumps([{"role": "assistant", "content": "bak.2 的内容"}], ensure_ascii=False), encoding="utf-8")
    c = TestClient(server.app)
    r = c.post("/api/thread/restore-from-bak", json={"bak_index": 2})
    write("thread__restore_from_bak_roundtrip.response.json", norm_mtime(r.json()))
    write("thread__restore_from_bak_roundtrip.history.json", server.THREAD_HISTORY_PATH.read_text(encoding="utf-8"))
    corrupted = list((TMP / "data").glob("thread-history.json.corrupted.*"))
    write("thread__restore_from_bak.asserts.json", {"corrupted_sibling_kept": len(corrupted) >= 1})


def cap_th_restore_bad_idx():
    _th_env()
    c = TestClient(server.app, raise_server_exceptions=False)
    lo = c.post("/api/thread/restore-from-bak", json={"bak_index": 0})
    hi = c.post("/api/thread/restore-from-bak", json={"bak_index": 6})
    miss = c.post("/api/thread/restore-from-bak", json={"bak_index": 3})
    write("thread__restore_bad_index_low.response.json", {"status": lo.status_code, "detail": lo.json().get("detail")})
    write("thread__restore_bad_index_high.response.json", {"status": hi.status_code, "detail": hi.json().get("detail")})
    write("thread__restore_missing_bak.response.json", {"status": miss.status_code, "detail": miss.json().get("detail")})


def cap_th_save_stale_409():
    _th_env()
    server.THREAD_HISTORY_PATH.write_text(
        json.dumps([{"role": "assistant", "content": "真实最新历史"}], ensure_ascii=False), encoding="utf-8")
    cur = server._thread_history_mtime_ms()
    c = TestClient(server.app, raise_server_exceptions=False)
    r = c.post("/api/thread/save", json={"history": [{"role": "user", "content": "陈旧标签页的旧内容"}], "base_mtime": cur - 999999})
    body = r.json()
    if isinstance(body.get("detail"), dict):
        body["detail"].pop("current_mtime", None)
    write("thread__save_stale_409.response.json", {"status": r.status_code, "detail": body.get("detail")})
    write("thread__save_stale_409.history_untouched.json", server.THREAD_HISTORY_PATH.read_text(encoding="utf-8"))


def cap_th_save_fresh():
    _th_env()
    server.THREAD_HISTORY_PATH.write_text(json.dumps([{"role": "user", "content": "旧"}], ensure_ascii=False), encoding="utf-8")
    cur = server._thread_history_mtime_ms()
    c = TestClient(server.app)
    r = c.post("/api/thread/save", json={"history": [{"role": "user", "content": "旧"}, {"role": "assistant", "content": "新增一条"}], "base_mtime": cur})
    write("thread__save_fresh_writes.response.json", norm_mtime(r.json()))
    write("thread__save_fresh_writes.history.json", server.THREAD_HISTORY_PATH.read_text(encoding="utf-8"))


def cap_th_save_non_list():
    _th_env()
    c = TestClient(server.app, raise_server_exceptions=False)
    a = c.post("/api/thread/save", json={"history": "oops"})
    b = c.post("/api/thread/save", json={})
    write("thread__save_non_list.response.json", {"history_str": a.status_code, "history_missing": b.status_code, "detail": a.json().get("detail")})


# ╔══════════════════════════════════════════════════════════════════╗
# ║ image 簇                                                            ║
# ╚══════════════════════════════════════════════════════════════════╝

def _img_env():
    TMP = fresh("img")
    adir = TMP / "attachments"; adir.mkdir()
    imgdir = TMP / "task-imgs"; imgdir.mkdir()
    server.ATTACHMENTS_DIR = adir
    server.ATTACHMENTS_INDEX = adir / "_index.json"
    server.CURATOR_SYSTEM_PATH = adir / "_curator.txt"
    server.DAILY_TASK_IMAGES_DIR = imgdir
    server.DAILY_TASK_IMAGES_MAP = TMP / "imgmap.json"
    server.DAILY_TASK_META_MAP = TMP / "metamap.json"
    server.PLATFORM_ROOT = TMP
    server.vault_git.commit_after_write = lambda *a, **k: None
    return TMP, adir, imgdir


def _img_put(adir, date, name, data=b"\x89PNG\r\n"):
    d = adir / date; d.mkdir(parents=True, exist_ok=True); (d / name).write_bytes(data); return d / name


def _img_index(adir, arr):
    (adir / "_index.json").write_text(json.dumps(arr, ensure_ascii=False), encoding="utf-8")


def cap_img_list():
    _, adir, _ = _img_env()
    _img_index(adir, [{"date": "2026-06-20", "filename": "a.png", "ocr_text": ""},
                      {"date": "2026-06-25", "filename": "b.png", "ocr_text": ""},
                      {"date": "2026-06-22", "filename": "c.png", "ocr_text": ""}])
    c = TestClient(server.app)
    write("attachments__list_sorted_desc_limit.response.json", c.get("/api/attachments", params={"limit": 2}).json())


def cap_img_list_filter():
    _, adir, _ = _img_env()
    _img_index(adir, [{"date": "2026-06-10", "filename": "a"}, {"date": "2026-06-25", "filename": "b"}])
    c = TestClient(server.app)
    write("attachments__list_date_from_filter.response.json", c.get("/api/attachments", params={"date_from": "2026-06-20"}).json())


def cap_img_search():
    _, adir, _ = _img_env()
    _img_index(adir, [{"date": "2026-06-25", "filename": "x.png", "original": "鱼油瓶.jpg", "ocr_text": ""},
                      {"date": "2026-06-25", "filename": "y.png", "original": "", "ocr_text": "维生素 D3 60 粒"}])
    c = TestClient(server.app)
    write("attachments__search_q_yuyou.response.json", c.get("/api/attachments/search", params={"q": "鱼油"}).json())
    write("attachments__search_q_weishengsu.response.json", c.get("/api/attachments/search", params={"q": "维生素"}).json())


def cap_img_search_empty():
    _, adir, _ = _img_env()
    _img_index(adir, [{"date": "2026-06-25", "filename": "x.png"}])
    c = TestClient(server.app)
    write("attachments__search_empty_q.response.json", c.get("/api/attachments/search", params={"q": ""}).json())


def cap_img_delete():
    _, adir, _ = _img_env()
    f = _img_put(adir, "2026-06-25", "a.png")
    _img_index(adir, [{"date": "2026-06-25", "filename": "a.png"}, {"date": "2026-06-25", "filename": "keep.png"}])
    c = TestClient(server.app)
    r = c.post("/api/attachments/delete", json={"date": "2026-06-25", "filename": "a.png"})
    write("attachments__delete_removes_file_and_index_entry.response.json", r.json())
    write("attachments__delete.index_after.json", json.loads((adir / "_index.json").read_text(encoding="utf-8")))
    write("attachments__delete.asserts.json", {"file_deleted": not f.exists()})


def cap_img_delete_traversal():
    _img_env()
    c = TestClient(server.app, raise_server_exceptions=False)
    r = c.post("/api/attachments/delete", json={"date": "2026-06-25", "filename": "../../etc/passwd"})
    write("attachments__delete_traversal_rejected.response.json", {"status": r.status_code})


def cap_img_reindex():
    _, adir, _ = _img_env()
    _img_put(adir, "2026-06-25", "new.png"); _img_put(adir, "2026-06-25", "old.png")
    _img_index(adir, [{"date": "2026-06-25", "filename": "old.png"}])
    server._index_attachment = lambda *a, **k: None
    c = TestClient(server.app)
    write("attachments__reindex_index_missing_skip_existing.response.json", c.post("/api/attachments/reindex", json={}).json())


def cap_img_vision():
    _, adir, _ = _img_env()
    _img_put(adir, "2026-06-25", "p.png")
    server._gemini_classify_image = lambda f, q="": {"kind": "supplement", "description": f"desc q={q}"}
    c = TestClient(server.app)
    r = c.post("/api/vision/classify", json={"attachment_url": "/attachments/2026-06-25/p.png", "extra_question": "啥牌子"})
    write("vision__classify_delegates_and_echoes_question.response.json", r.json())


def cap_img_vision_400():
    _img_env()
    c = TestClient(server.app, raise_server_exceptions=False)
    a = c.post("/api/vision/classify", json={})
    b = c.post("/api/vision/classify", json={"attachment_url": "bad"})
    write("vision__classify_missing_url.response.json", {"missing": a.status_code, "bad_format": b.status_code})


def cap_img_cutout():
    TMP, adir, imgdir = _img_env()
    _img_put(adir, "2026-06-25", "yuyou.jpg")
    processed = TMP / "proc.png"; processed.write_bytes(b"\x89PNGCUT")
    server._get_or_create_processed_attachment = lambda url: (processed, None)
    server._ocr_text = lambda f: "鱼油 60 粒"
    server.load_config = lambda: {}
    c = TestClient(server.app)
    r = c.post("/api/cutout", json={"attachment_url": "/attachments/2026-06-25/yuyou.jpg", "task_name": "鱼油（Swisse）"})
    j = r.json(); j.pop("image_url", None)  # 非确定,归一化掉
    write("cutout__writes_image_map_meta_and_ocr_pill_count.response.json", j)
    write("cutout__imgmap_after.json", {"has_key": "鱼油（Swisse）" in json.loads((TMP / "imgmap.json").read_text(encoding="utf-8"))})
    write("cutout__metamap_after.json", json.loads((TMP / "metamap.json").read_text(encoding="utf-8")))


def cap_img_cutout_400():
    _img_env()
    c = TestClient(server.app, raise_server_exceptions=False)
    a = c.post("/api/cutout", json={"attachment_url": "/attachments/x/y.png"})
    b = c.post("/api/cutout", json={"task_name": "x"})
    write("cutout__missing_args.response.json", {"missing_task_name": a.status_code, "missing_url": b.status_code})


def cap_img_get_attachment():
    _, adir, _ = _img_env()
    _img_put(adir, "2026-06-25", "a.png", b"PNGDATA")
    c = TestClient(server.app, raise_server_exceptions=False)
    ok = c.get("/attachments/2026-06-25/a.png")
    bad = c.get("/attachments/not-a-date/a.png")
    miss = c.get("/attachments/2026-06-25/missing.png")
    write("get_attachment__serves_bytes.response.json", {"status": ok.status_code, "body_matches": ok.content == b"PNGDATA"})
    write("get_attachment__statuses.response.json", {"bad_date": bad.status_code, "missing": miss.status_code})


CASES = [
    ("daily_tasks__catalog_fresh", cap_dt_catalog_fresh),
    ("daily_tasks__check_clamp", cap_dt_check_clamp),
    ("daily_tasks__check_default_dose1", cap_dt_check_default_dose1),
    ("daily_tasks__check_decrement_unchecks", cap_dt_check_decrement),
    ("daily_tasks__check_backfill_yesterday_ok", cap_dt_backfill_yesterday_ok),
    ("daily_tasks__check_backfill_yesterday_closed", cap_dt_backfill_closed),
    ("daily_tasks__check_rejects_future_and_two_days_ago", cap_dt_rejects_future_and_2ago),
    ("daily_tasks__catalog_is_writable_window", cap_dt_catalog_writable_window),
    ("daily_tasks__meta_set_and_clear", cap_dt_meta_set_clear),
    ("daily_tasks__meta_non_int_400", cap_dt_meta_non_int_400),
    ("daily_tasks__check_non_int_500", cap_dt_check_non_int_500),
    ("daily_tasks__history_oldest_first", cap_dt_history_oldest_first),
    ("daily_tasks__water_cup_roundtrip", cap_dt_water_cup_roundtrip),
    ("daily_tasks__water_cup_missing_url_400", cap_dt_water_cup_missing_400),
    ("daily_tasks__delete_cascade", cap_dt_delete_cascade),
    ("daily_tasks__backfill_progress_idempotent", cap_dt_backfill_progress),
    ("daily_tasks__template_task_add_edit", cap_dt_template_add_edit),
    ("vault__audit_orphans", cap_vault_audit),
    ("vault__repair_then_catalog", cap_vault_repair),
    ("journal__new_day_create_then_idempotent", cap_jn_new_day),
    ("journal__insert_block_http_stamps_user", cap_jn_insert_stamps_user),
    ("journal__insert_block_missing_time_400", cap_jn_insert_missing_time),
    ("journal__insert_block_no_journal_404", cap_jn_insert_no_journal),
    ("journal__delete_block_clears_to_placeholder", cap_jn_delete_clears),
    ("journal__delete_block_unknown_time_404", cap_jn_delete_unknown),
    ("journal__patch_routes_by_date_not_today", cap_jn_patch_by_date),
    ("journal__patch_missing_new_md_400", cap_jn_patch_missing_newmd),
    ("journal__patch_ai_refuses_user_block", cap_jn_patch_ai_refuses_user),
    ("journal__patch_ai_allows_ai_block", cap_jn_patch_ai_allows_ai),
    ("journal__patch_h2_rename_gate", cap_jn_patch_h2_rename),
    ("journal__insert_block_body_placement", cap_jn_insert_body),
    ("journal__append_comment_preserves_body", cap_jn_append_comment),
    ("journal__tag_register_appends_and_commits", cap_jn_tag_register),
    ("journal__tag_register_rejects_dup_and_subtag", cap_jn_tag_register_rejects),
    ("journal__tag_aggregate_get_sections", cap_jn_tag_aggregate_get),
    ("journal__tag_stats_default_for_new_user", cap_jn_tag_stats_default),
    ("thread__history_empty_no_file", cap_th_history_empty),
    ("thread__history_happy_returns_list", cap_th_history_happy),
    ("thread__history_corrupt_modal_payload", cap_th_history_corrupt),
    ("thread__history_corrupt_no_baks", cap_th_history_corrupt_no_baks),
    ("thread__restore_from_bak_roundtrip", cap_th_restore_roundtrip),
    ("thread__restore_bad_index", cap_th_restore_bad_idx),
    ("thread__save_stale_409_file_untouched", cap_th_save_stale_409),
    ("thread__save_fresh_writes", cap_th_save_fresh),
    ("thread__save_non_list_400", cap_th_save_non_list),
    ("attachments__list_sorted_desc_limit", cap_img_list),
    ("attachments__list_date_from_filter", cap_img_list_filter),
    ("attachments__search_filename_original_ocr", cap_img_search),
    ("attachments__search_empty_q", cap_img_search_empty),
    ("attachments__delete_removes_file_and_index_entry", cap_img_delete),
    ("attachments__delete_traversal_rejected_400", cap_img_delete_traversal),
    ("attachments__reindex_index_missing_skip_existing", cap_img_reindex),
    ("vision__classify_delegates_and_echoes_question", cap_img_vision),
    ("vision__classify_missing_url_400", cap_img_vision_400),
    ("cutout__writes_image_map_meta_and_ocr_pill_count", cap_img_cutout),
    ("cutout__missing_args_400", cap_img_cutout_400),
    ("get_attachment__serves_bytes_and_bad_date_400", cap_img_get_attachment),
]


if __name__ == "__main__":
    print(f"capture goldens → {GOLD}\n")
    for name, fn in CASES:
        cap(name, fn)
    ok = sum(1 for _, p, _ in _RESULTS if p)
    print(f"\n{'='*60}\n{ok}/{len(_RESULTS)} cases PASS · golden 文件 {len(list(GOLD.glob('*')))} 个")
    fails = [(n, d) for n, p, d in _RESULTS if not p]
    if fails:
        print("FAILS:")
        for n, d in fails:
            print(f"  ✗ {n}: {d}")
        sys.exit(1)
