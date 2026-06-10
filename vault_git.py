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


def _push_broken_notification(detail: str):
    """A-H13: vault_git 连续失败到达阈值,弹用户必看的通知。
    audit chain 静默断 = 训练语料 + 日记追溯都没了,用户不知是大事。"""
    try:
        from server import _push_notification
        _push_notification(
            "vault-git-broken",
            f"vault 自动 commit 连续失败 — audit chain 暂停。检查 git 状态或重启 gateway。详: {detail[:120]}",
            {"detail": detail[:300]},
        )
    except Exception:
        pass


_INDEX_LOCK_NAME = "index.lock"
_INDEX_LOCK_MAX_AGE_SEC = 600  # 10 min — 比这老一定是孤儿
# 活锁退避序列(秒):另一进程(Obsidian/手动 git/本进程别的 commit thread)短暂
# 持锁。feedback-sink 6.4-6.9 收的 26 条 index.lock 错误全是这种 <600s 活锁,
# 旧代码只清孤儿(>600s)对活锁零重试 → 撞上即报 silent-failure。
_LOCK_CONTENTION_BACKOFFS = (0.3, 0.7, 1.5, 3.0)

# 进程内串行化:gateway 自己连发的 commit thread(schedule + 聚合 + PULSE 镜像)
# 不互抢同一把 .git 锁 —— 自我竞态是这批错误的主要来源之一。
_GIT_OP_LOCK = threading.Lock()


def _index_lock_age(vault_dir: Path) -> float | None:
    """index.lock 存在则返其 age(秒),不存在/读不到返 None。"""
    lock = vault_dir / ".git" / _INDEX_LOCK_NAME
    try:
        if not lock.exists():
            return None
        import time as _time
        return _time.time() - lock.stat().st_mtime
    except Exception:
        return None


def _clear_stale_index_lock(vault_dir: Path) -> bool:
    """A-H13: 清 .git/index.lock 老于 10min 的卡死锁(上次 commit 崩没清)。
    只清孤儿 —— 活锁(<600s)是别的进程在用,删了会破坏对方的 git 操作。
    返 True 表示清掉了,caller 可以重试。
    """
    age = _index_lock_age(vault_dir)
    if age is None or age < _INDEX_LOCK_MAX_AGE_SEC:
        return False
    try:
        (vault_dir / ".git" / _INDEX_LOCK_NAME).unlink()
        log.warning(f"[vault_git] 清掉孤儿 index.lock(age={int(age)}s)")
        return True
    except Exception as e:
        log.warning(f"[vault_git] 清 index.lock 失败: {e}")
        return False


def _run_git_lock_aware(args: list[str], vault_dir: Path, timeout: float) -> tuple[int, str, str]:
    """跑 git,撞 index.lock 时智能重试:
      · 孤儿锁(>600s) → 清掉立即重试
      · 活锁(<600s)   → 退避等持锁进程释放后重试
    退避序列耗尽仍失败 → 返最后一次 (rc, out, err) 交 caller 报 silent-failure。
    非 index.lock 错误不重试(如真 merge 冲突),原样返回。"""
    rc, out, err = _run(args, vault_dir, timeout=timeout)
    if rc == 0 or "index.lock" not in (err or ""):
        return rc, out, err
    import time as _time
    for backoff in _LOCK_CONTENTION_BACKOFFS:
        if not _clear_stale_index_lock(vault_dir):
            # 不是孤儿 → 活锁,等一下让对方释放
            _time.sleep(backoff)
        rc, out, err = _run(args, vault_dir, timeout=timeout)
        if rc == 0 or "index.lock" not in (err or ""):
            return rc, out, err
    return rc, out, err


# 连续失败计数:线程间共享,简单整数 + Lock
_CONSECUTIVE_FAILURES = 0
_CONSECUTIVE_FAILURES_LOCK = threading.Lock()
_CONSECUTIVE_FAILURES_THRESHOLD = 5  # 连续 5 次失败 → 弹通知


def _bump_failure() -> int:
    global _CONSECUTIVE_FAILURES
    with _CONSECUTIVE_FAILURES_LOCK:
        _CONSECUTIVE_FAILURES += 1
        return _CONSECUTIVE_FAILURES


def _reset_failure() -> None:
    global _CONSECUTIVE_FAILURES
    with _CONSECUTIVE_FAILURES_LOCK:
        _CONSECUTIVE_FAILURES = 0


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
    """实际跑 git 的同步函数。在 background thread 里执行。
    A-H13: 连续失败累计 → 阈值 push notification;先尝试清孤儿 index.lock 再重试一次。"""
    try:
        if not _is_repo(vault_dir):
            # 写第一次时 vault 还没 init(用户改 vault 后才启动 gateway 那种边缘)
            ensure_repo(vault_dir)
        # 进程内串行 add+commit:本进程并发的 commit thread 排队,不自相竞锁
        with _GIT_OP_LOCK:
            _try_commit_once(vault_dir, summary, author, paths)
    except Exception as e:
        log.info(f"[vault_git] commit thread crashed: {type(e).__name__}: {e}")
        _report_silent("vault_git_thread_crashed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"author": author, "summary": summary[:60]})
        _on_failure(f"thread crashed: {type(e).__name__}")


def _try_commit_once(vault_dir: Path, summary: str, author: str,
                     paths: list[Path] | None) -> None:
    """跑一遍 add+commit。撞 index.lock 由 _run_git_lock_aware 退避/清孤儿重试,
    退避耗尽仍失败才报 silent-failure。"""
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
    rc, _, err = _run_git_lock_aware(add_args, vault_dir, timeout=15)
    if rc != 0:
        log.info(f"[vault_git] add failed: {err.strip()}")
        _report_silent("vault_git_add_failed", err.strip()[:120],
            context={"author": author, "summary": summary[:60]})
        _on_failure(f"add: {err.strip()[:120]}")
        return
    # 没变化 → skip(git diff --cached --quiet 返 0 表示无变化)
    rc, _, _ = _run(["git", "diff", "--cached", "--quiet"], vault_dir, timeout=10)
    if rc == 0:
        return  # no_changes
    msg = f"{summary} @{author}\n\nauto-commit by gateway at {datetime.now().isoformat(timespec='seconds')}"
    rc, _, err = _run_git_lock_aware(["git", "commit", "-q", "-m", msg], vault_dir, timeout=15)
    if rc != 0:
        log.info(f"[vault_git] commit failed: {err.strip()[:200]}")
        _report_silent("vault_git_commit_failed", err.strip()[:200],
            context={"author": author, "summary": summary[:60]})
        _on_failure(f"commit: {err.strip()[:120]}")
        return
    # 成功 → 失败计数清零
    _reset_failure()


def _on_failure(detail: str) -> None:
    """A-H13: 连续失败累计;到阈值弹用户必看的通知。"""
    n = _bump_failure()
    if n == _CONSECUTIVE_FAILURES_THRESHOLD:  # 只在跨过阈值那次弹,避免重复弹
        _push_broken_notification(detail)
