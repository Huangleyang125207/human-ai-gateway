"""pulse_routes — APIRouter for all /api/pulse/* endpoints.

P1 of PULSE LARGE refactor:thin wrapper。每个 handler 仍调 server.py 现有 helper
(走 function-level lazy import 避循环),业务逻辑零变化。

后续阶段:
  P2 — pulse_io.py 抽 _parse_pulse_md / _pulse_validate / 路径常量
  P3 — pulse_eval.py 抽 _eval_*
  P4 — pulse_evolve.py 抽 _self_evolve_run + prompts + EVOLVE_LOCKS
  P5 — server.py 里 PULSE 相关归零,仅留 `from pulse_routes import router; app.include_router(router)`

为什么不在 P1 就动 helper:
  84 个 PULSE 测试都 patch `server.X` 命名空间。helper 留在 server.py + 后续
  re-export 让 fixture 跨阶段都生效(见 Active spec § Plan re-export checklist)。
"""
import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/pulse", tags=["pulse"])


# ── GET /api/pulse — dashboard(prefix + ""= /api/pulse) ───────────────
@router.get("")
def pulse_dashboard():
    """读 数据库/valut/PULSE/*.md(INDEX.md 除外),返回 dashboard 数组。
    失败 / 无目录 → 空列表 + warning。
    """
    from server import PULSE_DIR, _parse_pulse_md, _report_silent_failure, log
    if not PULSE_DIR.exists():
        return {"projects": [], "warning": f"PULSE dir not found: {PULSE_DIR}"}
    projects = []
    for f in sorted(PULSE_DIR.glob("*.md")):
        if f.stem.lower() == "index":
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception as e:
            log.warning(f"can't read PULSE {f}: {e}")
            # 项目从 dashboard 静默消失,用户看不出是缺还是没建
            _report_silent_failure("pulse_md_read_failed",
                f"{type(e).__name__}: {str(e)[:120]}",
                context={"project": f.stem})
            continue
        projects.append(_parse_pulse_md(text, f.stem))
    return {"projects": projects}


# ── GET /api/pulse/{name} — detail ────────────────────────────────────
@router.get("/{name}")
def pulse_detail(name: str):
    """返回某项目的完整 PULSE.md 原文,给详情 modal 用。"""
    from server import PULSE_DIR
    if "/" in name or ".." in name or name.lower() == "index":
        raise HTTPException(400, "bad name")
    f = PULSE_DIR / f"{name}.md"
    if not f.exists():
        raise HTTPException(404, f"PULSE for '{name}' not found")
    return {"name": name, "markdown": f.read_text(encoding="utf-8")}


# ── POST /api/pulse/{user,project,agent-context}-update ──────────────
# 三 endpoint 同款:body {conversation}, 空拒 400,async wrap _self_evolve_run

@router.post("/user-update")
async def pulse_user_update(req: Request):
    """LLM 重写 USER_PULSE — compact 前置步骤。
    body: { "conversation": "对话原文 (任意格式)" }
    LLM call 120s timeout × 同步 client,丢 threadpool 避免阻塞 event loop(#1)。
    """
    from server import _self_evolve_run
    body = await req.json()
    conversation = (body.get("conversation") or "").strip()
    if not conversation:
        raise HTTPException(400, "需要 conversation")
    return await asyncio.to_thread(_self_evolve_run, "user_pulse", conversation)


@router.post("/project-update")
async def pulse_project_update(req: Request):
    """LLM 重写项目 PULSE — compact 三件套之一。"""
    from server import _self_evolve_run
    body = await req.json()
    conversation = (body.get("conversation") or "").strip()
    if not conversation:
        raise HTTPException(400, "需要 conversation")
    return await asyncio.to_thread(_self_evolve_run, "project_pulse", conversation)


@router.post("/agent-context-update")
async def pulse_agent_context_update(req: Request):
    """LLM 重写 AGENT_CONTEXT — compact 三件套之一,长出协作偏好 / 用户角色。"""
    from server import _self_evolve_run
    body = await req.json()
    conversation = (body.get("conversation") or "").strip()
    if not conversation:
        raise HTTPException(400, "需要 conversation")
    return await asyncio.to_thread(_self_evolve_run, "agent_context", conversation)


# ── POST /api/pulse/compact-summary ──────────────────────────────────
@router.post("/compact-summary")
async def pulse_compact_summary(req: Request):
    """前端 compact 全成功后调,产 200 字摘要塞回 thread 开头,
    保留最后 5 轮 + 摘要 → 下一轮对话有上下文,不冷启。
    用 flash 模型 ~10s 出。失败返空,前端忽略。"""
    from server import _compact_summary_run
    body = await req.json()
    conversation = (body.get("conversation") or "").strip()
    if not conversation:
        return {"ok": True, "summary": ""}
    summary = await asyncio.to_thread(_compact_summary_run, conversation)
    return {"ok": True, "summary": summary}


# ── POST /api/pulse/refresh-mirror ───────────────────────────────────
@router.post("/refresh-mirror")
def pulse_refresh_mirror():
    """从真源 PULSE.md 同步到 pulse-mirror,变化的 file 自动 git commit。
    源路径:扫常见位置(可后续做 config)。
      - ~/agents创作平台/PULSE.md → INDEX 候选(若有)
      - ~/agents创作平台/agents/*/PULSE.md → 各 project 一个
    """
    from server import PULSE_DIR, _safe_write_text, _report_silent_failure, vault_git
    sources = []
    candidates = [
        Path.home() / "agents创作平台",
    ]
    for root in candidates:
        if not root.exists():
            continue
        # 项目级 PULSE
        agents_dir = root / "agents"
        if agents_dir.exists():
            for p in agents_dir.glob("*/PULSE.md"):
                sources.append((p.parent.name, p))
        # monorepo 根级 PULSE(如果 user 在 root 也放了)
        root_pulse = root / "PULSE.md"
        if root_pulse.exists():
            sources.append(("_root", root_pulse))

    if not sources:
        return {"updated": 0, "scanned": 0, "warning": "no source PULSE.md found"}

    PULSE_DIR.mkdir(parents=True, exist_ok=True)
    updated_files = []
    failed_files = []
    for name, src in sources:
        dest = PULSE_DIR / f"{name}.md"
        try:
            src_content = src.read_text(encoding="utf-8")
            if dest.exists() and dest.read_text(encoding="utf-8") == src_content:
                continue  # 没变,skip
            # A-M4: atomic;镜像中途崩 = 用户看 viewer PULSE 看到半截
            _safe_write_text(dest, src_content, rotate=False)
            updated_files.append(dest)
        except Exception as e:
            failed_files.append((dest.name, str(e)[:80]))
            _report_silent_failure("pulse_mirror_write_failed",
                f"{type(e).__name__}: {str(e)[:120]}",
                context={"op": "pulse_mirror_sync"})

    if updated_files:
        rel_names = ", ".join(f.stem for f in updated_files)
        vault_git.commit_after_write(
            PULSE_DIR,
            f"pulse refresh-mirror: {rel_names}",
            author="system",
            paths=updated_files,
        )

    return {
        "scanned": len(sources),
        "updated": len(updated_files),
        "files": [f.stem for f in updated_files],
    }
