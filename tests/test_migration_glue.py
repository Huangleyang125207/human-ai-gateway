# TEST PATTERN: characterization — migration glue(横幅状态机 + 启动闸 + 参考引导 + legacy 跳过门)
# USE WHEN: 锁 migration 编排现行行为,守 migration glue 抽到 migration_routes.py(§ 9)
# TESTED IN: gateway migration extraction (2026-06-25), § T7 characterization
#
# ★Cannot-break:这组锁 v0.1.25「3 步 timeline 横幅」状态机(replay→live→done,断了用户看到卡死横幅)
# + schema 迁移「当前版本不重跑」数据安全门(#2 铁律:不动 vault 真源)。engine 已外置 migration_plan.py。
#
# 抽出后 patch-where-used:搬走的(状态 + push_migration_event + _create_migration_llm + _startup +
# 横幅函数)走 `mig.`;被 monkeypatch 注入的 server 侧 lazy 依赖(get_client/GATEWAY_DIR/VAULT_DIR/
# vault_git/_push_notification)仍走 `server.`(migration_routes 在函数体 lazy from server import,
# 改 server 属性即生效)。注意:_startup 内部调的是 *mig._create_migration_llm*,要 stub 得打 mig。

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
import migration_routes as mig  # noqa: E402


@pytest.fixture(autouse=True)
def reset_migration_state():
    """每个测试前重置横幅状态 + lock(asyncio.Lock 必须在各自 asyncio.run 的 loop 里新建)。"""
    mig._migration_log = []
    mig._migration_consumers = []
    mig._migration_done = False
    mig._migration_lock = None
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(server.app)


# ── A · 横幅状态机(Cannot-break v0.1.25 timeline)──────────────────

def test_push_event_appends_to_log_and_fanouts_to_consumers():
    q: asyncio.Queue = asyncio.Queue()
    mig._migration_consumers.append(q)
    asyncio.run(mig.push_migration_event({"kind": "file_done", "name": "x"}))
    assert mig._migration_log[-1]["kind"] == "file_done"
    assert mig._migration_done is False              # 非终态不置 done
    assert q.get_nowait()["kind"] == "file_done"     # fanout 到已连客户端


def test_push_terminal_kind_marks_done():
    for kind in ("migration_done", "migration_skipped"):
        mig._migration_done = False
        asyncio.run(mig.push_migration_event({"kind": kind}))
        assert mig._migration_done is True


def test_stream_replays_snapshot_then_closes_on_terminal(client):
    # 已 done + log 有终态事件 → 新连接 replay 快照后立即收尾(不挂)
    mig._migration_log = [{"kind": "file_done", "name": "a"},
                          {"kind": "migration_done", "success": True}]
    mig._migration_done = True
    r = client.get("/api/migration/stream")
    assert r.status_code == 200
    assert "file_done" in r.text and "migration_done" in r.text


# ── B · 启动闸(无 key 跳过 · engine 抛异常也关横幅)────────────────

def test_create_migration_llm_none_when_no_client(monkeypatch):
    monkeypatch.setattr(server, "get_client", lambda *a, **k: None)   # lazy import 生效
    assert mig._create_migration_llm() is None


def test_startup_skips_run_migration_when_llm_none(monkeypatch):
    monkeypatch.setattr(server, "get_client", lambda *a, **k: None)   # → llm None
    import migration_plan
    called = []
    monkeypatch.setattr(migration_plan, "run_migration",
                        lambda **kw: called.append(kw) or asyncio.sleep(0))
    asyncio.run(mig._startup_v0125_md_migration())
    assert called == []                                  # 无 key 不跑迁移


def test_startup_closes_banner_on_engine_exception(monkeypatch):
    # engine 抛 → 必须 push migration_done(success=False)让 SSE 客户端收尾,不能卡横幅
    # _startup 调的是 mig._create_migration_llm(模块内),stub 要打 mig
    monkeypatch.setattr(mig, "_create_migration_llm", lambda: object())

    async def _boom(**kw):
        raise RuntimeError("engine 炸了")
    import migration_plan
    monkeypatch.setattr(migration_plan, "run_migration", _boom)
    asyncio.run(mig._startup_v0125_md_migration())
    assert mig._migration_done is True
    last = mig._migration_log[-1]
    assert last["kind"] == "migration_done" and last["success"] is False


# ── C · 参考文件引导(缺才补,已存在一字节不动)──────────────────────

@pytest.fixture
def iso_vault(monkeypatch, tmp_path):
    vault = tmp_path / "vault"; vault.mkdir()
    bundle = tmp_path / "gw"; (bundle / "reference").mkdir(parents=True)
    monkeypatch.setattr(server, "VAULT_DIR", vault)          # lazy 依赖留 server
    monkeypatch.setattr(server, "GATEWAY_DIR", bundle)
    monkeypatch.setattr(server, "_AGENT_CONTEXT_PATH", vault / "AGENT_CONTEXT.md")
    monkeypatch.setattr(server.vault_git, "commit_after_write", lambda *a, **k: None)
    monkeypatch.setattr(server, "_push_notification", lambda *a, **k: None)
    (bundle / "reference" / "AGENT_CONTEXT.md").write_text("schema bundle ctx", encoding="utf-8")
    (bundle / "reference" / "daily-tasks.md").write_text("bundle tasks", encoding="utf-8")
    (bundle / "reference" / "标签聚合.md").write_text("bundle tags", encoding="utf-8")
    return type("V", (), {"vault": vault, "bundle": bundle})


def test_reference_bootstrap_copies_missing(iso_vault):
    res = mig._ensure_vault_reference_files()
    assert (iso_vault.vault / "AGENT_CONTEXT.md").read_text(encoding="utf-8") == "schema bundle ctx"
    assert res["agent_context"].startswith("copied")


def test_reference_bootstrap_skips_existing_byte_untouched(iso_vault):
    keep = iso_vault.vault / "daily-tasks.md"
    keep.write_text("用户改过的内容", encoding="utf-8")     # 已存在
    res = mig._ensure_vault_reference_files()
    assert keep.read_text(encoding="utf-8") == "用户改过的内容"   # 一字节不动
    assert res["daily_tasks"] == "exists"


# ── D · legacy schema rewriter:当前版本不重跑(数据安全 #2)─────────

def test_schema_migration_noop_when_no_bundle_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "GATEWAY_DIR", tmp_path / "nope")   # reference dir 不在
    called = []
    monkeypatch.setattr(server, "get_client", lambda *a, **k: called.append(1))
    asyncio.run(mig._run_schema_migration_if_needed())
    assert called == []                                  # 无 bundle → 直接 return,不调 LLM


def test_schema_migration_skips_when_version_current(iso_vault, monkeypatch):
    # vault 内容 == bundle(版本相等)→ bundle_v <= vault_v → skip,绝不调 LLM、不动 vault
    ctx = iso_vault.vault / "AGENT_CONTEXT.md"
    bundle_ctx = iso_vault.bundle / "reference" / "AGENT_CONTEXT.md"
    ctx.write_text(bundle_ctx.read_text(encoding="utf-8"), encoding="utf-8")   # 一致
    before = ctx.read_text(encoding="utf-8")
    called = []
    monkeypatch.setattr(server, "get_client", lambda *a, **k: called.append(1))
    asyncio.run(mig._run_schema_migration_if_needed())
    assert called == []                                  # 当前版本不调 LLM
    assert ctx.read_text(encoding="utf-8") == before     # vault 真源不动
    assert not (iso_vault.vault / "AGENT_CONTEXT.proposed.md").exists()   # 没写 proposed
