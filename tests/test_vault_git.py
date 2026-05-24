# TEST PATTERN: contract + effect — vault auto-commit
# USE WHEN: vault 写后要保版本史,验证 init / commit / 失败容忍
# COPY THIS: 改 fixture path,跑 pytest tests/test_vault_git.py -v
# TESTED IN: gateway (2026-05-24)
#
# 测的边界:
#   T1 ensure_repo on fresh dir → init success
#   T2 ensure_repo idempotent → 已 init 的 dir 不重 init
#   T3 commit_after_write → 文件写 → commit 出现在 git log
#   T4 commit_after_write on no-changes → 不创空 commit
#   T5 commit_after_write 在非 git 环境 → silently no-op,不抛
#   T6 .gitignore 自动落

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import vault_git  # noqa: E402


def _git_log_oneline(repo: Path) -> list[str]:
    """Return git log output as list of "hash subject" lines."""
    p = subprocess.run(
        ["git", "log", "--oneline"], cwd=str(repo),
        capture_output=True, text=True, check=False,
    )
    return [ln for ln in p.stdout.splitlines() if ln.strip()]


def _wait_for_commit(repo: Path, expected_count: int, timeout: float = 3.0) -> bool:
    """commit 是后台 thread 跑的,等到 log count 达到 expected 或超时。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if len(_git_log_oneline(repo)) >= expected_count:
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def fresh_vault(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    (v / "半小时复盘").mkdir()
    (v / "半小时复盘" / "26.5.24.md").write_text("# 9：00\n\n##\n", encoding="utf-8")
    return v


# ─── T1 · ensure_repo on fresh dir → init success ───────────────────

def test_ensure_repo_inits_fresh_dir(fresh_vault):
    if not vault_git._git_available():
        pytest.skip("git not on PATH")
    status = vault_git.ensure_repo(fresh_vault)
    assert status == "ready", f"expected ready, got {status}"
    assert (fresh_vault / ".git").exists()
    assert (fresh_vault / ".gitignore").exists()
    # baseline commit 应该存在
    assert len(_git_log_oneline(fresh_vault)) >= 1


# ─── T2 · ensure_repo idempotent ────────────────────────────────────

def test_ensure_repo_idempotent(fresh_vault):
    if not vault_git._git_available():
        pytest.skip("git not on PATH")
    vault_git.ensure_repo(fresh_vault)
    before = _git_log_oneline(fresh_vault)
    status = vault_git.ensure_repo(fresh_vault)
    assert status == "existing"
    after = _git_log_oneline(fresh_vault)
    assert before == after, "second ensure_repo must not create new commits"


# ─── T3 · commit_after_write → 真出现在 log 里 ───────────────────────

def test_commit_after_write_creates_commit(fresh_vault):
    if not vault_git._git_available():
        pytest.skip("git not on PATH")
    vault_git.ensure_repo(fresh_vault)
    initial = _git_log_oneline(fresh_vault)
    # 改文件
    f = fresh_vault / "半小时复盘" / "26.5.24.md"
    f.write_text("# 9：00\n\n## #思考 something @ai\nbody\n", encoding="utf-8")
    vault_git.commit_after_write(fresh_vault, "patch 26.5.24 9:00", author="ai", paths=[f])
    assert _wait_for_commit(fresh_vault, len(initial) + 1), \
        f"expected commit didn't land; log: {_git_log_oneline(fresh_vault)}"
    latest = _git_log_oneline(fresh_vault)[0]
    assert "patch 26.5.24 9:00" in latest
    assert "@ai" in latest


# ─── T4 · no-changes → 不创空 commit ─────────────────────────────────

def test_commit_no_changes_skipped(fresh_vault):
    if not vault_git._git_available():
        pytest.skip("git not on PATH")
    vault_git.ensure_repo(fresh_vault)
    before = _git_log_oneline(fresh_vault)
    # 不改任何文件,直接 commit
    vault_git.commit_after_write(fresh_vault, "noop", author="ai")
    time.sleep(0.5)  # 给后台 thread 跑一下
    after = _git_log_oneline(fresh_vault)
    assert before == after, "empty commit should be skipped"


# ─── T5 · 非 git 环境 → 静默 no-op,不抛 ──────────────────────────────

def test_commit_in_nonexistent_dir_does_not_throw(tmp_path):
    nonexistent = tmp_path / "ghost"
    # 不创建,直接调
    vault_git.commit_after_write(nonexistent, "test", author="ai")
    # 不抛就成 — sleep 给 thread 跑(虽然其实第一行就 return 了)
    time.sleep(0.2)


def test_ensure_repo_on_nonexistent_returns_no_vault(tmp_path):
    nonexistent = tmp_path / "ghost"
    assert vault_git.ensure_repo(nonexistent) == "no_vault"


# ─── T6 · .gitignore 内容合理 ────────────────────────────────────────

def test_gitignore_excludes_pulse_and_attachments(fresh_vault):
    if not vault_git._git_available():
        pytest.skip("git not on PATH")
    vault_git.ensure_repo(fresh_vault)
    gi = (fresh_vault / ".gitignore").read_text(encoding="utf-8")
    assert "PULSE/" in gi, "PULSE/ must be ignored (it's a mirror)"
    assert "attachments/" in gi, "attachments/ must be ignored (legacy location)"
    assert ".DS_Store" in gi
