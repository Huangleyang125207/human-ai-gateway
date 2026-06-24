# TEST PATTERN: characterization — /api/eval/* 留言板/eval endpoints golden behavior
# USE WHEN: 锁 eval list/today/test/run 现行行为,守 board_routes 抽出(§ 9)
# TESTED IN: gateway board_routes extraction (2026-06-24), § T7 characterization
#
# § T7 GREEN-LOCK:monolith 上先 GREEN,board_routes.py 抽出后 STAY GREEN。
# 这是核心簇拆分 target 3(eval/留言板;desktop-only,不在移动 shim)。
# 所有 _eval_* helper + EVAL_LOG_DIR 已在 pulse_eval.py(server re-export)→ 纯 handler 搬迁。
# 端点抽出后走 lazy from server import,patch server.X 仍命中(含 re-export 的 pulse_eval 符号)。
#
# eval_test/run 是 LLM 编排(2-call + json 清洗 + 错误分桶);past_boards 注入在
# _eval_build_messages(pulse_eval)里,端点只需"调它" → spy 验路径到达(Cannot-break)。

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


# ── 最简 LLM fake(eval _call_json 取 choices[0].message.content 再 json.loads)──
class _FakeChat:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.completions = self

    def create(self, **kw):
        self.calls.append(kw)
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        text = self.responses[idx]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class _FakeClient:
    def __init__(self, chat):
        self.chat = SimpleNamespace(completions=chat)


@pytest.fixture
def ev(monkeypatch, tmp_path):
    eval_dir = tmp_path / "eval-log"; eval_dir.mkdir()
    journal_dir = tmp_path / "journal"; journal_dir.mkdir()
    monkeypatch.setattr(server, "EVAL_LOG_DIR", eval_dir)
    monkeypatch.setattr(server, "JOURNAL_DIR", journal_dir)
    ns = SimpleNamespace(eval_dir=eval_dir, journal_dir=journal_dir, mp=monkeypatch)

    def write_eval(date_str, md="# eval\n复盘"):
        (eval_dir / f"{date_str}.md").write_text(md, encoding="utf-8")

    def write_journal(d):
        prefix = f"{str(d.year)[-2:]}.{d.month}.{d.day}"
        (journal_dir / f"{prefix}(t).md").write_text("# 7：30\n晨\n", encoding="utf-8")

    def setup_llm(responses):
        chat = _FakeChat(responses)
        monkeypatch.setattr(server, "get_profile", lambda *a, **k: {"model": "m"})
        monkeypatch.setattr(server, "get_client", lambda p: _FakeClient(chat))
        monkeypatch.setattr(server, "get_model", lambda p: "fake-model")
        return chat

    def spy_builders():
        calls = {"eval": [], "fi": []}
        monkeypatch.setattr(server, "_eval_build_messages",
                            lambda target, model_id=None: (calls["eval"].append((target, model_id))
                                                           or [{"role": "user", "content": "EVAL"}]))
        monkeypatch.setattr(server, "_eval_build_feature_intro_messages",
                            lambda target: (calls["fi"].append(target) or [{"role": "user", "content": "FI"}]))
        return calls

    ns.write_eval = write_eval
    ns.write_journal = write_journal
    ns.setup_llm = setup_llm
    ns.spy_builders = spy_builders
    return ns


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(server.app)


def _today():
    return datetime.now().strftime("%Y-%m-%d")


# ── GET /api/eval/list ───────────────────────────────────────────────

def test_eval_list_empty_no_dir(client, ev, monkeypatch):
    # EVAL_LOG_DIR 存在但空 → items []
    d = client.get("/api/eval/list").json()
    assert d == {"items": []}


def test_eval_list_happy_desc(client, ev):
    ev.write_eval(_today())
    ev.write_eval("2026-06-20")
    ev.write_eval("2026-06-18")
    d = client.get("/api/eval/list", params={"n": 14}).json()
    dates = [it["date"] for it in d["items"]]
    assert dates == sorted(dates, reverse=True)        # 降序
    assert dates[0] == _today()
    assert d["items"][0]["is_today"] is True
    assert "复盘" in d["items"][0]["markdown"]


def test_eval_list_include_missing_yesterday_card(client, ev):
    """昨天没 eval md 但有 schedule md → 追一条 missing 补跑卡。"""
    y = datetime.now() - timedelta(days=1)
    ev.write_journal(y)  # 昨天有日记,但没 eval
    d = client.get("/api/eval/list", params={"include_missing": True}).json()
    miss = [it for it in d["items"] if it.get("missing")]
    assert len(miss) == 1
    assert miss[0]["date"] == y.strftime("%Y-%m-%d")
    assert miss[0]["markdown"] is None


def test_eval_list_clamp_n(client, ev):
    for i in range(5):
        ev.write_eval(f"2026-05-{10+i:02d}")
    d = client.get("/api/eval/list", params={"n": 2}).json()
    assert len(d["items"]) == 2      # n clamp 生效(取最近 2)


# ── GET /api/eval/today ──────────────────────────────────────────────

def test_eval_today_exists(client, ev):
    ev.write_eval(_today(), md="# 今日复盘")
    d = client.get("/api/eval/today").json()
    assert d["date"] == _today() and d["is_today"] is True
    assert "今日复盘" in d["markdown"]


def test_eval_today_fallback_to_latest(client, ev):
    ev.write_eval("2026-06-15", md="# 旧的")
    d = client.get("/api/eval/today").json()
    assert d["date"] == "2026-06-15" and d["is_today"] is False
    assert "旧的" in d["markdown"]


def test_eval_today_none(client, ev):
    d = client.get("/api/eval/today").json()
    assert d == {"date": None, "is_today": False, "markdown": None}


# ── POST /api/eval/test — 2-call merge + builder 路径 ────────────────

def test_eval_test_2call_merge_and_builds_reached(client, ev):
    ev.setup_llm(['{"summary": "今天不错"}', '{"feature_intro": "新功能"}'])
    calls = ev.spy_builders()
    d = client.post("/api/eval/test", json={"date": "2026-06-20"}).json()
    assert d["ok"] is True
    assert d["parsed"]["summary"] == "今天不错"
    assert d["parsed"]["feature_intro"] == "新功能"   # call 2 merge 进来
    assert d["target_date"] == "2026-06-20"
    # ★past_boards 注入路径:端点必须调 _eval_build_messages(它内部注 past_boards)
    assert len(calls["eval"]) == 1
    assert len(calls["fi"]) == 1


def test_eval_test_json_fence_and_think_stripped(client, ev):
    # LLM 返带 ```json fence + <think> → 仍能 parse
    ev.setup_llm(['<think>嗯</think>\n```json\n{"summary": "ok"}\n```', '{"feature_intro": null}'])
    ev.spy_builders()
    d = client.post("/api/eval/test", json={}).json()
    assert d["parsed"]["summary"] == "ok"


# ── POST /api/eval/run — 持久化 + 通知 + parse_ok ───────────────────

def test_eval_run_persists_notifies_and_parse_ok(client, ev):
    ev.setup_llm(['{"summary": "落库"}', '{"feature_intro": "f"}'])
    ev.spy_builders()
    persisted, notified = [], []
    ev.mp.setattr(server, "_eval_persist",
                  lambda target, merged: (persisted.append((target, merged))
                                          or (ev.eval_dir / f"{target.strftime('%Y-%m-%d')}.md")))
    ev.mp.setattr(server, "_eval_notify", lambda target, merged: notified.append(target))

    d = client.post("/api/eval/run", json={"date": "2026-06-21"}).json()
    assert d["ok"] is True
    assert d["eval_parse_ok"] is True            # 主调用 JSON parse 成功
    assert d["target_date"] == "2026-06-21"
    assert len(persisted) == 1                   # 持久化被调
    assert len(notified) == 1                    # 通知被调
    assert d["parsed"]["summary"] == "落库"


def test_eval_run_parse_fail_still_ok_with_flag(client, ev):
    # 主调用返非 JSON → eval_parse_ok False,但端点不崩(graceful)
    ev.setup_llm(['这不是 JSON 只是 LLM 闲聊', '{"feature_intro": null}'])
    ev.spy_builders()
    ev.mp.setattr(server, "_eval_persist", lambda target, merged: ev.eval_dir / "x.md")
    ev.mp.setattr(server, "_eval_notify", lambda target, merged: None)
    d = client.post("/api/eval/run", json={"date": "2026-06-21"}).json()
    assert d["ok"] is True
    assert d["eval_parse_ok"] is False
