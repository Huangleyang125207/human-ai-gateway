# TEST PATTERN: contract + effect — git outcome computation
# USE WHEN: 验证 stable / modified 分类 + age + first-modify delay
# COPY THIS: 改 fixture 加新 commit pattern,跑 pytest tests/test_outcome_tracker.py -v
# TESTED IN: gateway (2026-05-24)
#
# 测的边界:
#   T1 单 commit 无后续 → stable
#   T2 commit 后又改同 file → modified
#   T3 commit 后改别的 file → 当 commit 仍 stable
#   T4 modified_after_seconds 计算正确
#   T5 compute_all rebuilds all commits
#   T6 save/load roundtrip

import json
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import outcome_tracker as ot  # noqa: E402
import vault_git  # noqa: E402


def _git(args, cwd):
    subprocess.run(["git", "-C", str(cwd)] + args, check=True,
                   capture_output=True, text=True)


def _head_hash(repo: Path) -> str:
    p = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                       capture_output=True, text=True, check=True)
    return p.stdout.strip()


def _head_ts(repo: Path) -> str:
    p = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%aI"],
                       capture_output=True, text=True, check=True)
    return p.stdout.strip()


@pytest.fixture
def vault_with_stable_commit(tmp_path):
    """Vault 含一个 commit,后续没被改 → stable."""
    v = tmp_path / "vault"
    v.mkdir()
    (v / "半小时复盘").mkdir()
    vault_git.ensure_repo(v)
    j = v / "半小时复盘" / "a.md"
    j.write_text("# 9：00\nbody a\n", encoding="utf-8")
    _git(["add", "-A"], v)
    _git(["commit", "-q", "-m", "patch a @ai"], v)
    h = _head_hash(v)
    return v, h


@pytest.fixture
def vault_with_modified_commit(tmp_path):
    """Vault 含 commit C,后又 commit 改同 file → modified."""
    v = tmp_path / "vault"
    v.mkdir()
    (v / "半小时复盘").mkdir()
    vault_git.ensure_repo(v)
    j = v / "半小时复盘" / "a.md"
    j.write_text("# 9：00\nbody v1\n", encoding="utf-8")
    _git(["add", "-A"], v)
    _git(["commit", "-q", "-m", "patch a v1 @ai"], v)
    h1 = _head_hash(v)
    time.sleep(1.1)  # 确保 ts 不同(秒级精度)
    j.write_text("# 9：00\nbody v2 modified\n", encoding="utf-8")
    _git(["add", "-A"], v)
    _git(["commit", "-q", "-m", "patch a v2 @user"], v)
    return v, h1


# ─── T1 · 无后续 → stable ────────────────────────────────────────

def test_stable_when_no_later_commits(vault_with_stable_commit):
    v, h = vault_with_stable_commit
    ts = _head_ts(v)
    o = ot.compute_outcome(v, h, ts)
    assert o["outcome_class"] == "stable"
    assert o["later_touch_count"] == 0
    assert o["modified_after_seconds"] is None


# ─── T2 · 后续改同 file → modified ───────────────────────────────

def test_modified_when_later_commit_touches_same_file(vault_with_modified_commit):
    v, h1 = vault_with_modified_commit
    # 拿到 commit 1 的 ts
    p = subprocess.run(["git", "-C", str(v), "log", "-1", "--format=%aI", h1],
                       capture_output=True, text=True, check=True)
    ts = p.stdout.strip()
    o = ot.compute_outcome(v, h1, ts)
    assert o["outcome_class"] == "modified"
    assert o["later_touch_count"] >= 1


# ─── T3 · 后续改别的 file → 当 commit 仍 stable ──────────────────

def test_stable_when_later_commits_touch_other_files(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    vault_git.ensure_repo(v)
    (v / "a.md").write_text("a\n", encoding="utf-8")
    _git(["add", "-A"], v)
    _git(["commit", "-q", "-m", "add a @ai"], v)
    h_a = _head_hash(v)
    ts_a = _head_ts(v)
    time.sleep(1.1)
    (v / "b.md").write_text("b\n", encoding="utf-8")
    _git(["add", "-A"], v)
    _git(["commit", "-q", "-m", "add b @ai"], v)
    o = ot.compute_outcome(v, h_a, ts_a)
    assert o["outcome_class"] == "stable", "改 b.md 不应该影响 a 的 outcome"


# ─── T4 · modified_after_seconds 计算 ────────────────────────────

def test_modified_after_seconds_positive(vault_with_modified_commit):
    v, h1 = vault_with_modified_commit
    p = subprocess.run(["git", "-C", str(v), "log", "-1", "--format=%aI", h1],
                       capture_output=True, text=True, check=True)
    ts = p.stdout.strip()
    o = ot.compute_outcome(v, h1, ts)
    assert o["modified_after_seconds"] is not None
    assert o["modified_after_seconds"] >= 1, "至少 1 秒(fixture sleep 1.1)"


# ─── T5 · compute_all 全量 rebuild ───────────────────────────────

def test_compute_all_covers_all_commits(vault_with_modified_commit):
    v, h1 = vault_with_modified_commit
    data = ot.compute_all(v)
    assert data["count"] >= 3  # baseline + 2
    assert h1 in data["outcomes"]
    # baseline commit 自己也 stable(没人后改 .gitignore)
    classes = {o["outcome_class"] for o in data["outcomes"].values()}
    assert "stable" in classes
    assert "modified" in classes


# ─── T6 · save/load roundtrip ────────────────────────────────────

def test_save_load_roundtrip(tmp_path, vault_with_stable_commit):
    v, _ = vault_with_stable_commit
    data = ot.compute_all(v)
    out = tmp_path / "outcomes.json"
    ot.save_outcomes(data, out)
    loaded = ot.load_outcomes(out)
    assert loaded["count"] == data["count"]
    assert set(loaded["outcomes"].keys()) == set(data["outcomes"].keys())


def test_load_missing_file_returns_empty(tmp_path):
    loaded = ot.load_outcomes(tmp_path / "nope.json")
    assert loaded["count"] == 0
    assert loaded["outcomes"] == {}
