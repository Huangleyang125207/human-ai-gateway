# TEST PATTERN: characterization — daily-tasks HTTP endpoints golden behavior
# USE WHEN: 锁 /api/daily-tasks/* + /api/water-cup 现行行为,守 daily_tasks_routes 抽出(§ 9)
# TESTED IN: gateway daily-tasks extraction (2026-06-24), § T7 characterization
#
# § T7 GREEN-LOCK:这些测试在 monolith server.py 上先 GREEN,daily_tasks_routes.py 抽出后
# STAY GREEN。任何 RED = 行为漂移 = revert。
#
# 同时是移动 parity oracle:标 [parity] 的断言,mobile/mobile-api.js 的 shim 必须满足。
# 已知 mobile 背离(测试会暴露):is_writable=date>=todayIso(L454)、daily_dose 恒 1。
#
# 端点:catalog / check / meta / backfill-progress / delete / history + water-cup GET+POST
# 关键:io-map(_load/_save_task_*_map)、_apply_task_op、LLM tools 抽出时 *留 server.py*。
#       T9 是 tripwire:验它们没被误移(误移 = _audit_vault + chat dispatch 崩)。

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


@pytest.fixture
def dt(monkeypatch, tmp_path):
    """daily-task 状态隔离到 tmp + 可控 now。
    patch 的都是 server module 级常量(call 时动态查找)→ helper 留 server.py 后仍命中。"""
    journal_dir = tmp_path / "journal"; journal_dir.mkdir()
    data_dir = tmp_path / "data"; data_dir.mkdir()
    images_dir = data_dir / "daily-task-images"; images_dir.mkdir()
    images_map = data_dir / "daily-task-images.json"
    meta_map = data_dir / "daily-task-meta.json"
    template = tmp_path / "daily-tasks.md"

    monkeypatch.setattr(server, "JOURNAL_DIR", journal_dir)
    monkeypatch.setattr(server, "DAILY_TASK_IMAGES_DIR", images_dir)
    monkeypatch.setattr(server, "DAILY_TASK_IMAGES_MAP", images_map)
    monkeypatch.setattr(server, "DAILY_TASK_META_MAP", meta_map)
    monkeypatch.setattr(server, "SCHEDULE_TEMPLATE_PATH", template)
    monkeypatch.setattr(server, "DAILY_TASKS_SOURCE", template, raising=False)
    monkeypatch.setattr(server, "PLATFORM_ROOT", tmp_path, raising=False)
    # 不碰真 git
    monkeypatch.setattr(server.vault_git, "commit_after_write", lambda *a, **k: None)

    ns = SimpleNamespace(journal_dir=journal_dir, data_dir=data_dir, images_dir=images_dir,
                         images_map=images_map, meta_map=meta_map, template=template, now=None)

    def set_now(d):
        class _Fixed(datetime):
            @classmethod
            def now(cls, tz=None):
                return d
        monkeypatch.setattr(server, "datetime", _Fixed)
        ns.now = d

    def _prefix(d):
        return f"{str(d.year)[-2:]}.{d.month}.{d.day}"

    def write_day(tasks, d=None):
        d = d or ns.now or datetime.now()
        f = journal_dir / f"{_prefix(d)}(test).md"
        lines = [f"# {_prefix(d)} test", ""]
        for t in tasks:
            box = "x" if (isinstance(t, dict) and t.get("checked")) else " "
            name = t["name"] if isinstance(t, dict) else t
            lines.append(f"- [{box}] {name}")
        lines += ["", "---", "", "# 7：30", "晨", ""]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return f

    def write_template(tasks):
        lines = ["# 每日补剂", ""] + [f"- [ ] {t}" for t in tasks] + ["", "---", ""]
        template.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_meta(d):
        meta_map.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    def write_images(d):
        images_map.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    def read_meta():
        return json.loads(meta_map.read_text(encoding="utf-8")) if meta_map.exists() else {}

    def read_images():
        return json.loads(images_map.read_text(encoding="utf-8")) if images_map.exists() else {}

    def read_day_md(d=None):
        d = d or ns.now or datetime.now()
        fs = list(journal_dir.glob(f"{_prefix(d)}*.md"))
        return fs[0].read_text(encoding="utf-8") if fs else None

    ns.set_now = set_now
    ns.write_day = write_day
    ns.write_template = write_template
    ns.write_meta = write_meta
    ns.write_images = write_images
    ns.read_meta = read_meta
    ns.read_images = read_images
    ns.read_day_md = read_day_md
    return ns


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(server.app)


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _yesterday():
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


# ── T1: catalog shape + is_writable [parity] ─────────────────────────

def test_catalog_shape_and_is_writable(client, dt):
    dt.write_day(["鱼油", "维生素D"])
    r = client.get("/api/daily-tasks")
    assert r.status_code == 200
    d = r.json()
    assert d["date"] == _today()
    assert d["is_today"] is True
    assert d["is_writable"] is True  # 今天总可写
    names = {t["name"]: t for t in d["tasks"]}
    assert set(names) == {"鱼油", "维生素D"}
    t = names["鱼油"]
    # fresh task 默认状态 — mobile shim 必须返同样的键
    assert t["checked"] is False
    assert t["image_url"] is None
    assert t["total_pills"] is None
    assert t["daily_dose"] == 1
    assert t["today_intake"] == 0
    assert t["remaining"] is None


# ── T2: 补卡窗口 ★Cannot-break [parity] ──────────────────────────────

def test_check_backfill_window_yesterday_before_noon_else_403(client, dt):
    """次日 12:00 前可补昨天,过点 403。server 端 TZ 算 — mobile is_writable=date>=today 背离此契约。"""
    base = datetime.now()
    dt.write_day(["鱼油"], d=base)

    # 11:00 — 昨天在补卡窗口内 → 200
    dt.set_now(base.replace(hour=11, minute=0, second=0, microsecond=0))
    r_ok = client.post("/api/daily-tasks/check",
                       json={"task_name": "鱼油", "date": _yesterday(), "checked": True})
    assert r_ok.status_code == 200
    assert dt.read_meta()["鱼油"]["intake_log"].get(_yesterday()) == 1  # 昨天打卡落账

    # 13:00 — 过点,昨天不再可补 → 400
    dt.set_now(base.replace(hour=13, minute=0, second=0, microsecond=0))
    r_no = client.post("/api/daily-tasks/check",
                       json={"task_name": "鱼油", "date": _yesterday(), "checked": True})
    assert r_no.status_code == 400


# ── T3: check intake / increment / clamp + md box [parity] ───────────

def test_check_intake_increment_clamp_and_md_box(client, dt):
    dt.write_day(["鱼油", "维生素D"])

    # checked=True → md 行变 [x],intake 置满 daily_dose(默认 1)
    r = client.post("/api/daily-tasks/check", json={"task_name": "鱼油", "checked": True})
    s = r.json()
    assert s["ok"] is True and s["checked"] is True
    assert s["today_intake"] == s["daily_dose"] == 1
    assert "- [x] 鱼油" in dt.read_day_md()

    # daily_dose=2 的 task:intake 超量 clamp 到 dose
    client.post("/api/daily-tasks/meta", json={"task_name": "维生素D", "daily_dose": 2})
    s2 = client.post("/api/daily-tasks/check", json={"task_name": "维生素D", "intake": 5}).json()
    assert s2["today_intake"] == 2  # clamp 到 daily_dose
    assert s2["checked"] is True    # 2>=2 → md [x]
    assert "- [x] 维生素D" in dt.read_day_md()

    # increment -1 → 1 < dose 2 → md 退回 [ ]
    s3 = client.post("/api/daily-tasks/check", json={"task_name": "维生素D", "increment": -1}).json()
    assert s3["today_intake"] == 1
    assert s3["checked"] is False
    assert "- [ ] 维生素D" in dt.read_day_md()

    # intake=0 → 从 intake_log pop 当日 key
    client.post("/api/daily-tasks/check", json={"task_name": "维生素D", "intake": 0})
    assert _today() not in (dt.read_meta().get("维生素D", {}).get("intake_log") or {})


# ── T4: meta total_pills / daily_dose / clear [parity] ───────────────

def test_meta_update_total_pills_daily_dose_and_clear(client, dt):
    dt.write_day(["鱼油"])
    s = client.post("/api/daily-tasks/meta",
                    json={"task_name": "鱼油", "total_pills": 60, "daily_dose": 2}).json()
    assert s["total_pills"] == 60 and s["daily_dose"] == 2

    # total_pills="" → pop(None)
    s2 = client.post("/api/daily-tasks/meta", json={"task_name": "鱼油", "total_pills": ""}).json()
    assert s2["total_pills"] is None
    assert s2["daily_dose"] == 2  # 没传的字段不动

    # 非 int → 400
    assert client.post("/api/daily-tasks/meta",
                       json={"task_name": "鱼油", "total_pills": "abc"}).status_code == 400
    assert client.post("/api/daily-tasks/meta",
                       json={"task_name": "鱼油", "daily_dose": "x"}).status_code == 400


# ── T5: history per-day oldest-first [parity] ────────────────────────

def test_history_per_day_oldest_first(client, dt):
    base = datetime.now()
    dt.write_day([{"name": "鱼油", "checked": True}], d=base)              # 今天:勾
    dt.write_day([{"name": "鱼油", "checked": False}], d=base - timedelta(days=2))  # 前天:没勾
    # 昨天:无文件 → checked None

    d = client.get("/api/daily-tasks/history", params={"name": "鱼油", "days": 3}).json()
    assert d["name"] == "鱼油"
    days = d["days"]
    assert len(days) == 3
    assert [x["date"] for x in days] == [  # 最早 → 最新
        (base - timedelta(days=2)).strftime("%Y-%m-%d"),
        _yesterday(), _today()]
    assert days[0]["checked"] is False   # 前天有文件没勾
    assert days[1]["checked"] is None    # 昨天无文件
    assert days[2]["checked"] is True    # 今天勾


# ── T6: water-cup reserved-key roundtrip [parity] ────────────────────

def test_water_cup_get_set_roundtrip_reserved_key(client, dt, monkeypatch):
    src = dt.data_dir / "src.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
    # 抠图 dispatcher mock(留 server 的 lazy-import 再 resolve 一次)
    monkeypatch.setattr(server, "_get_or_create_processed_attachment", lambda url: (src, None))
    monkeypatch.setattr(server, "_pretty_rel", lambda p: f"data/daily-task-images/{Path(p).name}")

    assert client.post("/api/water-cup", json={}).status_code == 400  # 缺 url
    r = client.post("/api/water-cup", json={"attachment_url": "/attachments/x/y.png"})
    assert r.status_code == 200 and r.json()["ok"] is True
    # 保留 key 落账
    assert server.WATER_CUP_KEY in dt.read_images()
    g = client.get("/api/water-cup").json()
    assert g["image_url"] is not None


# ── T7: delete cascade md+image+meta 双写目标 (5.15 肌酸丢 guard) ─────

def test_delete_cascade_md_image_meta(client, dt):
    dt.write_template(["鱼油", "维生素D"])
    dt.write_day(["鱼油", "维生素D"])
    dt.write_meta({"鱼油": {"daily_dose": 1, "intake_log": {_today(): 1}}})
    img = dt.images_dir / "yuyou.png"; img.write_bytes(b"x")
    dt.write_images({"鱼油": "data/daily-task-images/yuyou.png"})

    r = client.post("/api/daily-tasks/delete", json={"task_name": "鱼油"})
    assert r.status_code == 200 and r.json()["image_removed"] is True
    # md 两个目标都删了 鱼油 行,维生素D 还在
    assert "鱼油" not in dt.read_day_md() and "维生素D" in dt.read_day_md()
    assert "鱼油" not in dt.template.read_text(encoding="utf-8")
    assert "维生素D" in dt.template.read_text(encoding="utf-8")
    # image map + 文件 + meta 全清
    assert "鱼油" not in dt.read_images()
    assert not img.exists()
    assert "鱼油" not in dt.read_meta()


# ── T8: backfill-progress idempotent ─────────────────────────────────

def test_backfill_progress_idempotent(client, dt):
    dt.write_day(["维生素D"])
    dt.write_meta({"维生素D": {"daily_dose": 3, "intake_log": {_today(): 2}}})

    first = client.post("/api/daily-tasks/backfill-progress").json()
    assert first["ok"] is True
    assert first["touched_count"] >= 1  # dose>1 展开子 box
    # 再跑 → 幂等,0 改动
    second = client.post("/api/daily-tasks/backfill-progress").json()
    assert second["touched_count"] == 0


# ── T9: LLM tool 仍 wired tripwire(抽出后这些 *留* server.py)─────────

def test_llm_tool_check_stays_wired(client, dt):
    # 结构:dispatch 表 + 双 group 成员(不许 dedupe)
    assert server.TOOL_IMPL["check_daily_task"] is server.tool_check_daily_task
    assert "check_daily_task" in server.TOOL_GROUPS["write_journal"]
    assert "check_daily_task" in server.TOOL_GROUPS["images"]  # 故意双挂

    # 功能:模糊名解析 + 勾 md(走 _resolve_task_name/_safe_write_text,都留 server)
    dt.write_day(["鱼油（Swisse）"])
    out = server.tool_check_daily_task({"task_name": "鱼油", "checked": True})
    assert out.get("ok") is True
    assert out["task_name"] == "鱼油（Swisse）"
    assert out.get("resolved_from") == "鱼油"
    assert "- [x] 鱼油（Swisse）" in dt.read_day_md()
