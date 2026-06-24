# TEST PATTERN: characterization — /api/journal/* + /api/tag-aggregate/* HTTP 契约
# USE WHEN: 锁 journal/tag-aggregate handler 现行行为,守 journal_routes 抽出(§ 9)
# TESTED IN: gateway journal_routes extraction (2026-06-24), § T7 characterization
#
# § T7 GREEN-LOCK:monolith 上先 GREEN,journal_routes.py 抽出后 STAY GREEN。核心簇 target 4
# (移动 parity 价值最高,mobile 真迁 /api/journal/*)。
#
# 分工:authorship 边界 + sha-lock + H2-guard 的危险 helper(_patch_block/_insert_block/
# _append_comment_to_block/_check_author)*留 server.py 不动*,已由 test_authorship(13)/
# test_patch_h2_rename/test_insert_block_body 在 helper 层覆盖。本文件只锁 *handler 层 HTTP 契约*:
# date 路由(不传 date 才 today)、HTTP=user-trust(author='user')、400/404、dedup、vault_git。

import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402

JOURNAL_MD = """# 9：00

## #思考 早醒 @user
昨晚睡得晚。

# 10：00

## #投资 KV cache @ai
推 RDMA 思路。
"""


@pytest.fixture
def jn(monkeypatch, tmp_path):
    jdir = tmp_path / "journal"; jdir.mkdir()
    monkeypatch.setattr(server, "JOURNAL_DIR", jdir)
    monkeypatch.setattr(server, "VAULT_DIR", tmp_path)
    monkeypatch.setattr(server, "TAG_AGGREGATE_PATH", tmp_path / "标签聚合.md")
    monkeypatch.setattr(server, "load_config", lambda: {})
    vgit = []
    monkeypatch.setattr(server.vault_git, "commit_after_write",
                        lambda *a, **k: vgit.append((a, k)))
    ns = SimpleNamespace(jdir=jdir, vault=tmp_path, vgit=vgit)

    def write_day(content=JOURNAL_MD, d=None):
        d = d or datetime.now()
        f = jdir / f"{str(d.year)[-2:]}.{d.month}.{d.day}(t).md"
        f.write_text(content, encoding="utf-8")
        return f

    def read_day(d=None):
        d = d or datetime.now()
        fs = list(jdir.glob(f"{str(d.year)[-2:]}.{d.month}.{d.day}*.md"))
        return fs[0].read_text(encoding="utf-8") if fs else None

    def write_aggregate(text="# 标签聚合\n\n---\n"):
        (tmp_path / "标签聚合.md").write_text(text, encoding="utf-8")

    ns.write_day = write_day
    ns.read_day = read_day
    ns.write_aggregate = write_aggregate
    return ns


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(server.app)


def _today():
    return datetime.now().strftime("%Y-%m-%d")


# ── reads ────────────────────────────────────────────────────────────

def test_today_returns_blocks(client, jn):
    jn.write_day()
    d = client.get("/api/journal/today").json()
    assert d["date"] == _today()
    assert any("早醒" in str(b) for b in d["blocks"])


def test_days_lists_files(client, jn):
    jn.write_day()
    jn.write_day(d=datetime.now() - timedelta(days=3))
    d = client.get("/api/journal/days").json()
    assert len(d["days"]) == 2


def test_tag_stats_top_and_default_for_new_user(client, jn):
    # 空 vault → 兜底默认 5 tag,带 default=True
    d0 = client.get("/api/journal/tag-stats").json()
    assert all(t.get("default") for t in d0["tags"])
    # 有 tag → 统计 top
    jn.write_day()
    d1 = client.get("/api/journal/tag-stats", params={"limit": 5}).json()
    names = {t["tag"] for t in d1["tags"]}
    assert "思考" in names and "投资" in names


# ── new-day ──────────────────────────────────────────────────────────

def test_new_day_creates_then_idempotent(client, jn):
    r1 = client.post("/api/journal/new-day", json={"date": "2026-06-22"}).json()
    assert r1["ok"] is True and r1["created"] is True
    assert list(jn.jdir.glob("26.6.22*.md"))
    r2 = client.post("/api/journal/new-day", json={"date": "2026-06-22"}).json()
    assert r2["ok"] is True and r2["created"] is False   # 幂等


# ── insert-block(HTTP=user trust)────────────────────────────────────

def test_insert_block_http_stamps_user(client, jn):
    jn.write_day()
    r = client.post("/api/journal/insert-block",
                    json={"time": "11:00", "tag": "工作", "title": "新条目", "body": "正文"})
    assert r.status_code == 200
    md = jn.read_day()
    assert "## #工作 新条目 @user" in md          # HTTP 路径 stamp @user(非 @ai)


def test_insert_block_missing_time_400(client, jn):
    jn.write_day()
    assert client.post("/api/journal/insert-block", json={"title": "x"}).status_code == 400


def test_insert_block_no_journal_404(client, jn):
    assert client.post("/api/journal/insert-block",
                       json={"time": "11:00", "title": "x"}).status_code == 404


# ── delete-block ─────────────────────────────────────────────────────

def test_delete_block_clears_to_placeholder(client, jn):
    jn.write_day()
    r = client.post("/api/journal/delete-block", json={"time": "9:00"})
    assert r.status_code == 200 and r.json()["cleared"] == "9:00"
    md = jn.read_day()
    assert "早醒" not in md                          # 9:00 内容清空
    assert "推 RDMA 思路" in md                       # 10:00 不动


def test_delete_block_unknown_time_404(client, jn):
    jn.write_day()
    assert client.post("/api/journal/delete-block", json={"time": "23:30"}).status_code == 404


# ── patch(HTTP=user 可改任何块,含 @ai)+ date 路由 ──────────────────

def test_patch_http_user_can_patch_ai_block(client, jn):
    jn.write_day()
    r = client.post("/api/journal/patch", json={
        "time": "10:00", "new_md": "## #投资 user 接管 @user\n人改了。"})
    assert r.status_code == 200 and "error" not in r.json()
    assert "人改了" in jn.read_day()


def test_patch_routes_by_date_not_today(client, jn):
    """date 参数决定写哪天(5.x 修:历史视图编辑不能打到今天 md)。"""
    past = datetime.now() - timedelta(days=5)
    jn.write_day(d=past)                              # 只建过去那天的文件,今天没有
    r = client.post("/api/journal/patch", json={
        "time": "10:00", "new_md": "## #投资 历史改 @user\n改过去。",
        "date": past.strftime("%Y-%m-%d")})
    assert r.status_code == 200
    assert "改过去" in jn.read_day(d=past)
    assert jn.read_day() is None                      # 今天文件没被误建


def test_patch_missing_new_md_400(client, jn):
    jn.write_day()
    assert client.post("/api/journal/patch", json={"time": "10:00"}).status_code == 400


# ── tag-aggregate register/get ───────────────────────────────────────

def test_tag_register_appends_and_commits(client, jn):
    jn.write_aggregate()
    r = client.post("/api/tag-aggregate/register", json={"tag": "yanpai"})
    assert r.json()["ok"] is True
    assert "## #yanpai" in (jn.vault / "标签聚合.md").read_text(encoding="utf-8")
    assert len(jn.vgit) == 1                          # vault_git audit chain 触发


def test_tag_register_rejects_dup_and_subtag(client, jn):
    jn.write_aggregate("# 标签聚合\n\n## #yanpai\n\n---\n")
    assert client.post("/api/tag-aggregate/register", json={"tag": "yanpai"}).json()["ok"] is False
    assert client.post("/api/tag-aggregate/register", json={"tag": "yanpai/传播"}).json()["ok"] is False


def test_tag_aggregate_get_sections(client, jn):
    jn.write_aggregate("# 标签聚合\n\n## #yanpai\n\n| 日期 | 时间 | 链接 | 内容 |\n|--|--|--|--|\n\n---\n")
    d = client.get("/api/tag-aggregate").json()
    assert any(s["tag"] == "yanpai" for s in d["sections"])
