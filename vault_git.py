"""
vault_git.py — VAULT_DIR 的自动版本史

设计:
  - 每次 _patch_block / _insert_block / _append_comment / aggregate write 后,
    后台 thread 跑一次 git add + commit,signing 当前 author(@user/@ai)。
  - 首次启动若 VAULT_DIR 不是 git repo:init + .gitignore + baseline commit。
  - 异常吞掉:git 装没装 / 网络挂没挂 / 仓库锁住,都不许阻塞写入路径。
  - 用户已有 .git → 不再 init,只 add+commit,跟用户自己的 history merge 进同一个 trunk。

不做:
  - 不 push 到 remote(那是用户自己的事 — 想跨设备同步自己加 origin)
  - 不做 branch / merge(单 trunk 就够)
  - 不做 GC / squash(让 git 自己管)
  - 不 sign(无 gpg key 时 commit 会卡住)
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger("gateway.vault_git")

_GITIGNORE = """\
# vault auto-managed — 别动这个文件除非你知道在干嘛
.DS_Store
*.swp
*~
.obsidian/workspace*
.obsidian/cache

# 镜像类目录(真源在 APP_STATE_DIR,这里被覆盖):
PULSE/

# legacy 上传位置(已迁到 APP_STATE_DIR/attachments):
attachments/
"""

_NOOP_REASONS = {"no_git", "init_failed", "no_changes"}


def _git_available() -> bool:
    return shutil.which("git") is not None


def _run(args: list[str], cwd: Path, timeout: float = 10.0) -> tuple[int, str, str]:
    """跑 git,返 (rc, stdout, stderr)。失败不抛。"""
    try:
        p = subprocess.run(
            args, cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return -1, "", f"{type(e).__name__}: {e}"


def _is_repo(vault_dir: Path) -> bool:
    return (vault_dir / ".git").exists()


def ensure_repo(vault_dir: Path) -> str:
    """确保 VAULT_DIR 是 git repo。第一次:init + .gitignore + baseline commit。
    返 "ready" / "no_git" / "init_failed" / "existing"。
    """
    if not vault_dir.exists():
        return "no_vault"
    if not _git_available():
        log.warning("[vault_git] git not on PATH — autocommit disabled")
        return "no_git"
    if _is_repo(vault_dir):
        # 用户已 init 过(或我们之前 init 过),只确保 .gitignore 存在
        gi = vault_dir / ".gitignore"
        if not gi.exists():
            try:
                gi.write_text(_GITIGNORE, encoding="utf-8")
            except Exception:
                pass
        return "existing"
    # 首次 init
    rc, _, err = _run(["git", "init", "-q"], vault_dir)
    if rc != 0:
        log.warning(f"[vault_git] git init failed: {err.strip()}")
        return "init_failed"
    # 不依赖全局 user.name/email — 设 repo-local 兜底
    _run(["git", "config", "user.name", "human-ai-gateway"], vault_dir)
    _run(["git", "config", "user.email", "gateway@human-ai.local"], vault_dir)
    try:
        (vault_dir / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")
    except Exception:
        pass
    _run(["git", "add", "-A"], vault_dir, timeout=30)
    rc, _, err = _run(
        ["git", "commit", "-q", "-m", "baseline: human-ai vault auto-init"],
        vault_dir, timeout=30,
    )
    if rc != 0:
        # baseline 失败不致命 — 后续 commit 还能 add 这些文件
        log.info(f"[vault_git] baseline commit: {err.strip() or 'empty?'}")
        _report_silent("vault_git_baseline_commit_failed", err.strip()[:120] or "empty?")
    log.info(f"[vault_git] initialized git repo at {vault_dir}")
    return "ready"


def _report_silent(error_type: str, message: str = "", context: dict = None):
    """lazy 调 server._report_silent_failure 避免循环 import。
    vault_git 由 server 在 thread 里调用,触发时 server 已 fully loaded。"""
    try:
        from server import _report_silent_failure
        _report_silent_failure(error_type, message, context)
    except Exception:
        pass  # 反馈通道自己挂了不报错(避免递归)


def commit_after_write(vault_dir: Path, summary: str, author: str = "ai",
                       paths: list[Path] | None = None) -> None:
    """非阻塞:后台 thread 跑 git add + commit。
    summary: 一行简述,如 "patch 26.5.24 17:30 #思考"
    author:  "user" / "ai" / "system" — 进 commit msg 作 trailer
    paths:   只 add 这些路径(相对/绝对都接);None → add -A
    """
    if not vault_dir.exists() or not _git_available():
        return
    t = threading.Thread(
        target=_commit_sync,
        args=(vault_dir, summary, author, paths),
        daemon=True,
    )
    t.start()


def _commit_sync(vault_dir: Path, summary: str, author: str,
                 paths: list[Path] | None) -> None:
    """实际跑 git 的同步函数。在 background thread 里执行。"""
    try:
        if not _is_repo(vault_dir):
            # 写第一次时 vault 还没 init(用户改 vault 后才启动 gateway 那种边缘)
            ensure_repo(vault_dir)
        # add
        if paths:
            add_args = ["git", "add", "--"]
            for p in paths:
                pp = Path(p)
                if pp.is_absolute():
                    try:
                        pp = pp.relative_to(vault_dir)
                    except ValueError:
                        continue
                add_args.append(str(pp))
        else:
            add_args = ["git", "add", "-A"]
        rc, _, err = _run(add_args, vault_dir, timeout=15)
        if rc != 0:
            log.info(f"[vault_git] add failed: {err.strip()}")
            _report_silent("vault_git_add_failed", err.strip()[:120],
                context={"author": author, "summary": summary[:60]})
            return
        # 没变化 → skip(git diff --cached --quiet 返 1 表示有变化)
        rc, _, _ = _run(["git", "diff", "--cached", "--quiet"], vault_dir, timeout=10)
        if rc == 0:
            return  # no_changes
        msg = f"{summary} @{author}\n\nauto-commit by gateway at {datetime.now().isoformat(timespec='seconds')}"
        rc, _, err = _run(["git", "commit", "-q", "-m", msg], vault_dir, timeout=15)
        if rc != 0:
            log.info(f"[vault_git] commit failed: {err.strip()[:200]}")
            _report_silent("vault_git_commit_failed", err.strip()[:200],
                context={"author": author, "summary": summary[:60]})
    except Exception as e:
        log.info(f"[vault_git] commit thread crashed: {type(e).__name__}: {e}")
        _report_silent("vault_git_thread_crashed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"author": author, "summary": summary[:60]})
