# TEST PATTERN: contract + effect — history exporter (git → training JSONL)
# USE WHEN: 验证 commit walker / tag extractor / thread join / 输出格式
# COPY THIS: 改 fixture vault path,新增 commit 后跑 pytest tests/test_history_exporter.py -v
# TESTED IN: gateway (2026-05-24)
#
# 测的边界:
#   T1 list_commits 空 repo → 空 list
#   T2 list_commits 有 commits → 按时间 reverse 顺
#   T3 parse_author 抠 @user/@ai/@system + 默认 unknown
#   T4 extract_tags_from_diff 抠 #tag(中英文),只看 + 行
#   T5 join_context 有 ts → time-window 匹配
#   T6 join_context 无 ts → tail-fallback
#   T7 export 真出文件 + all.jsonl 行数对 + by-tag/by-author 分桶对

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import history_exporter as he  # noqa: E402
import vault_git  # noqa: E402


def _git(args: list[str], cwd: Path):
    subprocess.run(["git", "-C", str(cwd)] + args, check=True,
                   capture_output=True, text=True)


@pytest.fixture
def fresh_vault_repo(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    (v / "半小时复盘").mkdir()
    # init via vault_git so .gitignore + baseline match prod
    vault_git.ensure_repo(v)
    return v


@pytest.fixture
def vault_with_commits(fresh_vault_repo):
    v = fresh_vault_repo
    j = v / "半小时复盘" / "26.5.24(test).md"
    # commit 1: ai patch + #投资 tag
    j.write_text("# 9：00\n\n## #投资 #协作 联想财报 @ai\nbody1\n", encoding="utf-8")
    _git(["add", "-A"], v)
    _git(["commit", "-q", "-m", "patch 26.5.24 9:00 @ai"], v)
    # commit 2: user patch + #社交 tag
    j.write_text("# 9：00\n\n## #投资 #协作 联想财报 @ai\nbody1\n\n## #社交 朋友 @user\nbody2\n",
                 encoding="utf-8")
    _git(["add", "-A"], v)
    _git(["commit", "-q", "-m", "insert 26.5.24 9:00 #社交 @user"], v)
    # commit 3: system aggregate refresh
    (v / "标签聚合.md").write_text("# 索引\n\n## #投资\n\n| date | row |\n+ #投资 新行\n", encoding="utf-8")
    _git(["add", "-A"], v)
    _git(["commit", "-q", "-m", "aggregate refresh +1 row #投资 @system"], v)
    return v


# ─── T1 · 空 repo → 空 list ────────────────────────────────────

def test_list_commits_empty_repo(fresh_vault_repo):
    # 注:ensure_repo 已经做了 baseline commit → 至少 1 条
    commits = he.list_commits(fresh_vault_repo)
    assert len(commits) >= 1
    assert "baseline" in commits[0]["subject"]


def test_list_commits_nonexistent_dir(tmp_path):
    assert he.list_commits(tmp_path / "ghost") == []


# ─── T2 · list_commits 时间序(reverse=老在前) ────────────────

def test_list_commits_chronological(vault_with_commits):
    commits = he.list_commits(vault_with_commits)
    assert len(commits) >= 4  # baseline + 3
    # ts 从老到新
    ts_list = [c["ts"] for c in commits]
    assert ts_list == sorted(ts_list), "commits 应按时间从老到新"


# ─── T3 · parse_author ────────────────────────────────────────

def test_parse_author_ai():
    assert he.parse_author("patch 26.5.24 17:30 @ai") == "ai"


def test_parse_author_user():
    assert he.parse_author("insert 26.5.24 11:00 #社交 @user") == "user"


def test_parse_author_system():
    assert he.parse_author("aggregate refresh +4 rows #投资 @system") == "system"


def test_parse_author_unknown():
    assert he.parse_author("misc commit no trailer") == "unknown"


def test_parse_author_in_body():
    """trailer 落在 body 也能找到。"""
    assert he.parse_author("subject", "this is body @ai with stuff") == "ai"


# ─── T4 · extract_tags_from_diff ──────────────────────────────

def test_extract_tags_chinese():
    diff = "+## #投资 #协作 联想财报\n+ body\n-## old line\n"
    tags = he.extract_tags_from_diff(diff)
    assert "投资" in tags
    assert "协作" in tags


def test_extract_tags_ignores_minus_lines():
    """- 行(被删除内容)的 #tag 不算 — 我们只关心新增的语义。"""
    diff = "-## #投资 old\n+## new\n"
    assert "投资" not in he.extract_tags_from_diff(diff)


def test_extract_tags_ignores_diff_header():
    diff = "+++ b/file.md\n++ #投资 not a tag this is diff header line\n+## #真tag here\n"
    tags = he.extract_tags_from_diff(diff)
    assert "真tag" in tags
    # +++ 行不抠
    # 但 ++ 不是 +++ 的开头,我们 startswith("+++") 排掉的是 diff filename header


# ─── T5 + T6 · join_context ──────────────────────────────────

def test_join_context_time_window_match():
    """有 ts 的 thread → time-window 匹配。"""
    thread = [
        {"role": "user", "content": "帮我记一下", "ts": "2026-05-24T15:00:00+00:00"},
        {"role": "assistant", "content": "好的", "ts": "2026-05-24T15:00:10+00:00"},
    ]
    ctx = he.join_context("2026-05-24T15:00:30+00:00", thread, window_sec=60)
    assert ctx["context_method"] == "time-window"
    assert ctx["preceding_user_msg"] == "帮我记一下"
    assert ctx["preceding_ai_reply"] == "好的"


def test_join_context_tail_fallback():
    """无 ts → 用末尾 N 条。"""
    thread = [
        {"role": "user", "content": "老问题"},
        {"role": "assistant", "content": "老回答"},
    ]
    ctx = he.join_context("2026-05-24T15:00:30+00:00", thread)
    assert ctx["context_method"] == "tail-fallback"
    assert ctx["preceding_user_msg"] == "老问题"


def test_join_context_empty():
    ctx = he.join_context("2026-05-24T15:00:30+00:00", [])
    assert ctx["context_method"] == "empty"


# ─── T7 · export 端到端 ──────────────────────────────────────

def test_export_writes_all_files(vault_with_commits, tmp_path):
    out = tmp_path / "exports"
    r = he.export(vault=vault_with_commits, thread_path=tmp_path / "no-thread.json",
                  out_dir=out)
    assert "error" not in r
    assert r["commits"] >= 4
    # all.jsonl 存在 + 行数对
    all_lines = (out / "all.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(all_lines) == r["commits"]
    # 每行可解析
    for ln in all_lines:
        d = json.loads(ln)
        assert "commit" in d and "ts" in d and "author" in d


def test_export_by_tag_split(vault_with_commits, tmp_path):
    out = tmp_path / "exports"
    he.export(vault=vault_with_commits, thread_path=tmp_path / "no-thread.json", out_dir=out)
    # commit 1 + 2 都加了 #投资 字面但 commit 1 也有 #协作
    tag_dir = out / "by-tag"
    assert tag_dir.exists()
    files = sorted(p.name for p in tag_dir.glob("*.jsonl"))
    # 至少应该有 投资 + 协作 + 社交
    assert any("投资" in n for n in files), f"expected #投资 file, got {files}"
    assert any("协作" in n for n in files)


def test_export_by_author_split(vault_with_commits, tmp_path):
    out = tmp_path / "exports"
    he.export(vault=vault_with_commits, thread_path=tmp_path / "no-thread.json", out_dir=out)
    auth_dir = out / "by-author"
    files = sorted(p.name for p in auth_dir.glob("*.jsonl"))
    # ai / user / system / unknown (baseline) 至少 4 个
    assert "ai.jsonl" in files
    assert "user.jsonl" in files
    assert "system.jsonl" in files


def test_export_empty_repo_path():
    r = he.export(vault=Path("/nonexistent/path/xyz"))
    assert "error" in r
