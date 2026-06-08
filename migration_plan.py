"""v0.1.25 起的 MD 迁移核心 — LLM 弹性 scope。

跟 server.py `_run_schema_migration_if_needed` 那套 schema-version marker
机制并存:这里**不依赖任何 marker**,scope 全交给 LLM 在 runtime 决定:
新版 binary 带的 canonical templates/ + 用户 vault 实际 MD 文件 → LLM
classify+plan → per-file rewrite → backup 兜底。

入口 `run_migration(...)` 跑 6 步:
  ① 读 .last-migrated-version,== app_version → emit migration_skipped 返回
  ② enumerate templates dir 跟 vault dir
  ③ llm_client.call_plan(...) 得 [{user_file, target_template, action, reason}, ...]
     emit plan_ready
  ④ for action == "migrate":
       emit file_started
       try llm_client.call_rewrite → 新内容
       try 保存 .bak 备份 → 写新内容
       emit file_done(成功)or file_error(任意一步失败)
  ⑤ 全部 file 成功 → 写 .last-migrated-version,失败时不写(下次重试)
  ⑥ emit migration_done {success, had_errors, files_done, files_error}

事件 kind 全集:
  plan_ready          {plan: [...]}
  file_started        {user_file, target_template}
  file_done           {user_file, target_template, backup}
  file_error          {user_file, target_template, error}
  migration_done      {success, had_errors, files_done, files_error}
  migration_skipped   {reason: "version_already_migrated"}

llm_client 协议:
  async call_plan(templates: list[Path], vault: list[Path]) -> list[dict]
    返回 [{user_file: str, target_template: str, action: "migrate"|"skip", reason: str}]
  async call_rewrite(plan_item: dict) -> str
    返回 user_file 的新 MD 内容(LLM 已 preserve 原 user content + 应用新结构)

progress_callback 自适应 sync / async,接受 dict event。
"""
from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Union

ProgressCallback = Optional[Callable[[dict], Union[None, Awaitable[None]]]]


# ─── 状态文件读写 ────────────────────────────────────────────────────


def _read_last_migrated_version(state_dir: Path) -> Optional[str]:
    p = state_dir / ".last-migrated-version"
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8").strip() or None
    except Exception:
        return None


def _write_last_migrated_version(state_dir: Path, version: str) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    p = state_dir / ".last-migrated-version"
    # atomic write:tmp + rename(POSIX/Win 都 atomic);跟 Rust write_updater_pending 同套路
    tmp = p.parent / (p.name + ".tmp")
    tmp.write_text(version, encoding="utf-8")
    tmp.replace(p)


# ─── 文件枚举 ────────────────────────────────────────────────────────


def discover_templates(bundle_dir: Path) -> list[Path]:
    """binary bundle 自带的 canonical templates。约定路径 `<bundle>/templates/*.md`。"""
    d = bundle_dir / "templates"
    if not d.exists():
        return []
    return sorted(d.glob("*.md"))


def inventory_vault(vault_dir: Path) -> list[Path]:
    """用户 vault 里所有 .md 文件(递归)。"""
    if not vault_dir.exists():
        return []
    return sorted(vault_dir.rglob("*.md"))


# ─── 备份命名 ────────────────────────────────────────────────────────


def _backup_path(user_file: Path, app_version: str) -> Path:
    """`PULSE.md` → `PULSE.md.bak.before-0.1.25`.

    Path.with_suffix 替换最后一段后缀,这里把原后缀(.md)拼上 .bak.before-X
    就得到 .md.bak.before-X。
    """
    return user_file.with_suffix(user_file.suffix + f".bak.before-{app_version}")


# ─── progress callback 自适应 ────────────────────────────────────────


async def _emit(cb: ProgressCallback, ev: dict) -> None:
    if cb is None:
        return
    try:
        res = cb(ev)
        if inspect.isawaitable(res):
            await res
    except Exception:
        # progress callback 失败不能炸主流程
        pass


# ─── 主入口 ──────────────────────────────────────────────────────────


async def run_migration(
    *,
    app_version: str,
    bundle_dir: Path,
    vault_dir: Path,
    state_dir: Path,
    llm_client: Any,
    progress_callback: ProgressCallback = None,
) -> dict:
    """跑一轮 MD 迁移。返回 {status: skipped|done|partial|plan_error, files_done, files_error}。"""
    # ① idempotent check
    last_v = _read_last_migrated_version(state_dir)
    if last_v == app_version:
        await _emit(progress_callback, {"kind": "migration_skipped", "reason": "version_already_migrated"})
        return {"status": "skipped", "files_done": 0, "files_error": 0}

    # ② 枚举
    templates = discover_templates(bundle_dir)
    vault = inventory_vault(vault_dir)

    # ③ LLM 出 plan
    try:
        plan = await llm_client.call_plan(templates, vault)
    except Exception as e:
        await _emit(progress_callback, {
            "kind": "migration_done",
            "success": False,
            "had_errors": True,
            "files_done": 0,
            "files_error": 0,
            "error": f"plan_call_failed: {type(e).__name__}: {e}",
        })
        return {"status": "plan_error", "files_done": 0, "files_error": 0}

    await _emit(progress_callback, {"kind": "plan_ready", "plan": plan})

    # ④ per-file rewrite
    files_done = 0
    files_error = 0
    for item in plan or []:
        if item.get("action") != "migrate":
            continue

        user_file = Path(item["user_file"])
        target_template = item.get("target_template", "")
        await _emit(progress_callback, {
            "kind": "file_started",
            "user_file": str(user_file),
            "target_template": target_template,
        })

        # LLM rewrite
        try:
            new_content = await llm_client.call_rewrite(item)
        except Exception as e:
            await _emit(progress_callback, {
                "kind": "file_error",
                "user_file": str(user_file),
                "target_template": target_template,
                "error": f"rewrite_failed: {type(e).__name__}: {e}",
            })
            files_error += 1
            continue

        # 备份 + 写
        try:
            bak = _backup_path(user_file, app_version)
            if user_file.exists():
                bak.write_text(user_file.read_text(encoding="utf-8"), encoding="utf-8")
            user_file.write_text(new_content, encoding="utf-8")
            await _emit(progress_callback, {
                "kind": "file_done",
                "user_file": str(user_file),
                "target_template": target_template,
                "backup": str(bak),
            })
            files_done += 1
        except Exception as e:
            await _emit(progress_callback, {
                "kind": "file_error",
                "user_file": str(user_file),
                "target_template": target_template,
                "error": f"write_failed: {type(e).__name__}: {e}",
            })
            files_error += 1

    # ⑤ 全 ok 才更新版本(任一文件失败 → 下次启动重试,不堵塞)
    if files_error == 0:
        try:
            _write_last_migrated_version(state_dir, app_version)
        except Exception:
            pass

    # ⑥ 终态事件
    await _emit(progress_callback, {
        "kind": "migration_done",
        "success": files_error == 0,
        "had_errors": files_error > 0,
        "files_done": files_done,
        "files_error": files_error,
    })

    return {
        "status": "done" if files_error == 0 else "partial",
        "files_done": files_done,
        "files_error": files_error,
    }
