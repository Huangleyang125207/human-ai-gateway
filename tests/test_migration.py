# TEST PATTERN: contract + effect — post-update MD migration
# USE WHEN: 验证 migration_plan.py 的 LLM-驱动迁移流 + sidecar SSE
# COPY THIS: 改 fixture templates / vault 路径
# TESTED IN: gateway (2026-06-08, RED first)
#
# 测的边界:
#   T1 SSE progress events  — 启动 → 推 plan_ready / file_done / migration_done 事件
#   T2 idempotent           — .last-migrated-version == APP_VERSION → 立即 return,不调 LLM
#   T3 LLM rewrite + backup — fake template + fake user MD → 按 plan 重写 + 留 .bak
#   T4 LLM failure soft     — LLM raise → user MD 原样 + .bak 不丢 + error 事件
#   T5 background non-block — 迁移跑时 /api/health 仍秒回(不阻塞 event loop)

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 故意 import 一个尚未存在的 module —— RED 状态。T-D 写完就绿。
import migration_plan  # noqa: E402


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def bundle_dir(tmp_path: Path) -> Path:
    """模拟 binary bundle 自带的 templates/ 目录."""
    d = tmp_path / "bundle" / "templates"
    d.mkdir(parents=True)
    (d / "SCHEDULE_TEMPLATE.md").write_text(
        "# 半小时复盘模板 v2\n\n## 新增区段:补剂打卡\n- [ ] 鱼油\n",
        encoding="utf-8",
    )
    (d / "PULSE_TEMPLATE.md").write_text(
        "# PULSE v2\n\n## Cannot break\n## 新增:Can play\n",
        encoding="utf-8",
    )
    return tmp_path / "bundle"


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    """模拟用户的 vault — 已有几个 MD 实例."""
    d = tmp_path / "vault"
    (d / "半小时复盘").mkdir(parents=True)
    (d / "半小时复盘" / "26.6.7.md").write_text(
        "# 半小时复盘 v1\n\n## 9：30\nuser 自己写的内容\n",
        encoding="utf-8",
    )
    (d / "PULSE.md").write_text(
        "# PULSE v1\n\n## Cannot break\nuser 的红线 1\n",
        encoding="utf-8",
    )
    return d


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    """对应 ~/.human-ai/."""
    d = tmp_path / "state"
    d.mkdir()
    return d


class FakeLLM:
    """可控 LLM 客户端 — plan + rewrite 返回预置内容,或抛错."""

    def __init__(self, plan: list[dict], rewrites: dict[str, str], raise_on=None):
        self.plan = plan
        self.rewrites = rewrites
        self.raise_on = raise_on  # 'plan' / 'rewrite' / None
        self.calls = {"plan": 0, "rewrite": 0}

    async def call_plan(self, templates, vault):
        self.calls["plan"] += 1
        if self.raise_on == "plan":
            raise RuntimeError("LLM 5xx")
        return self.plan

    async def call_rewrite(self, plan_item):
        self.calls["rewrite"] += 1
        if self.raise_on == "rewrite":
            raise RuntimeError("LLM 5xx")
        return self.rewrites[plan_item["user_file"]]


# ─── T1 · SSE progress events ────────────────────────────────────────


@pytest.mark.asyncio
async def test_T1_sse_emits_progress_events(bundle_dir, vault_dir, state_dir):
    """启动迁移 → 顺序推 plan_ready / file_started / file_done / migration_done."""
    fake_llm = FakeLLM(
        plan=[
            {
                "user_file": str(vault_dir / "PULSE.md"),
                "target_template": "PULSE_TEMPLATE.md",
                "action": "migrate",
                "reason": "v1→v2,加 Can play 段",
            }
        ],
        rewrites={
            str(vault_dir / "PULSE.md"): "# PULSE v2\n\n## Cannot break\nuser 的红线 1\n## Can play\n"
        },
    )
    events: list[dict] = []

    async def progress_cb(ev):
        events.append(ev)

    await migration_plan.run_migration(
        app_version="0.1.25",
        bundle_dir=bundle_dir,
        vault_dir=vault_dir,
        state_dir=state_dir,
        llm_client=fake_llm,
        progress_callback=progress_cb,
    )

    kinds = [e["kind"] for e in events]
    assert "plan_ready" in kinds, f"缺 plan_ready: {kinds}"
    assert "file_started" in kinds, f"缺 file_started: {kinds}"
    assert "file_done" in kinds, f"缺 file_done: {kinds}"
    assert kinds[-1] == "migration_done", f"末尾不是 migration_done: {kinds}"


# ─── T2 · idempotent ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_T2_idempotent_when_version_matches(bundle_dir, vault_dir, state_dir):
    """`.last-migrated-version` == APP_VERSION → 不调 LLM 直接返回."""
    (state_dir / ".last-migrated-version").write_text("0.1.25", encoding="utf-8")
    fake_llm = FakeLLM(plan=[], rewrites={})
    events: list[dict] = []

    await migration_plan.run_migration(
        app_version="0.1.25",
        bundle_dir=bundle_dir,
        vault_dir=vault_dir,
        state_dir=state_dir,
        llm_client=fake_llm,
        progress_callback=lambda e: events.append(e),
    )

    assert fake_llm.calls["plan"] == 0, "idempotent 失败:版本对上还调了 LLM"
    assert fake_llm.calls["rewrite"] == 0
    assert events == [] or events[-1]["kind"] == "migration_skipped"


# ─── T3 · rewrite + backup ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_T3_rewrites_md_and_keeps_backup(bundle_dir, vault_dir, state_dir):
    """按 plan 重写 MD,原文件落 .bak.before-0.1.25."""
    target = vault_dir / "PULSE.md"
    original = target.read_text(encoding="utf-8")
    new_content = "# PULSE v2\n\n## Cannot break\nuser 的红线 1\n## Can play\n"

    fake_llm = FakeLLM(
        plan=[
            {
                "user_file": str(target),
                "target_template": "PULSE_TEMPLATE.md",
                "action": "migrate",
                "reason": "v1→v2",
            }
        ],
        rewrites={str(target): new_content},
    )

    await migration_plan.run_migration(
        app_version="0.1.25",
        bundle_dir=bundle_dir,
        vault_dir=vault_dir,
        state_dir=state_dir,
        llm_client=fake_llm,
        progress_callback=lambda e: None,
    )

    assert target.read_text(encoding="utf-8") == new_content, "MD 没被重写"
    bak = target.with_suffix(".md.bak.before-0.1.25")
    assert bak.exists(), f"备份不在: {bak}"
    assert bak.read_text(encoding="utf-8") == original, "备份内容跟原 MD 不一致"
    last = (state_dir / ".last-migrated-version").read_text(encoding="utf-8").strip()
    assert last == "0.1.25", f".last-migrated-version 没更新: {last}"


# ─── T4 · LLM failure soft ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_T4_llm_failure_preserves_user_md(bundle_dir, vault_dir, state_dir):
    """LLM rewrite 抛错 → user MD 不动 + error event 推出去."""
    target = vault_dir / "PULSE.md"
    original = target.read_text(encoding="utf-8")

    fake_llm = FakeLLM(
        plan=[
            {
                "user_file": str(target),
                "target_template": "PULSE_TEMPLATE.md",
                "action": "migrate",
                "reason": "v1→v2",
            }
        ],
        rewrites={},
        raise_on="rewrite",
    )

    events: list[dict] = []

    await migration_plan.run_migration(
        app_version="0.1.25",
        bundle_dir=bundle_dir,
        vault_dir=vault_dir,
        state_dir=state_dir,
        llm_client=fake_llm,
        progress_callback=lambda e: events.append(e),
    )

    # 用户文件保持原样
    assert target.read_text(encoding="utf-8") == original, "LLM 失败但 user MD 被改了"
    # 错误事件
    error_events = [e for e in events if e.get("kind") == "file_error"]
    assert len(error_events) >= 1, f"没推 file_error 事件: {events}"
    # 即使失败,version 也不能写进 .last-migrated-version(否则下次没机会重试)
    assert not (state_dir / ".last-migrated-version").exists() or (
        state_dir / ".last-migrated-version"
    ).read_text().strip() != "0.1.25", "失败时不该把 .last-migrated-version 改成新版"


# ─── T5 · background non-block ───────────────────────────────────────


@pytest.mark.asyncio
async def test_T5_runs_in_background_no_block(bundle_dir, vault_dir, state_dir):
    """迁移期间其它 coroutine 也能调度(不阻塞 event loop)."""

    class SlowLLM:
        def __init__(self):
            self.calls = {"plan": 0, "rewrite": 0}

        async def call_plan(self, templates, vault):
            await asyncio.sleep(0.3)
            self.calls["plan"] += 1
            return [
                {
                    "user_file": str(vault_dir / "PULSE.md"),
                    "target_template": "PULSE_TEMPLATE.md",
                    "action": "migrate",
                    "reason": "slow",
                }
            ]

        async def call_rewrite(self, plan_item):
            await asyncio.sleep(0.3)
            self.calls["rewrite"] += 1
            return "# PULSE v2 slow\n"

    slow_llm = SlowLLM()
    counter = {"n": 0}

    async def heartbeat():
        for _ in range(10):
            await asyncio.sleep(0.05)
            counter["n"] += 1

    migration_task = asyncio.create_task(
        migration_plan.run_migration(
            app_version="0.1.25",
            bundle_dir=bundle_dir,
            vault_dir=vault_dir,
            state_dir=state_dir,
            llm_client=slow_llm,
            progress_callback=lambda e: None,
        )
    )
    heartbeat_task = asyncio.create_task(heartbeat())

    await asyncio.gather(migration_task, heartbeat_task)

    assert counter["n"] >= 8, f"heartbeat 没跑够 → migration 阻塞了 event loop: {counter['n']}"
