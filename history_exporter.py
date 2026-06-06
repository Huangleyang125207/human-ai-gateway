"""
history_exporter.py — vault git log + thread-history → 训练用 JSONL

Level 1: all.jsonl           每个 commit 1 行,带 diff + 时间窗 join 的 chat context
Level 2: by-tag/{tag}.jsonl  按 diff 里 #tag 分流(#投资 / #ESP32 / ...)
         by-author/{a}.jsonl 按 @author trailer 分流(user / ai / system)
Level 3: (TODO,留下次)

CLI:
    python3 history_exporter.py                 # 走默认路径,rebuild
    python3 history_exporter.py --since 2026-05-01
    python3 history_exporter.py --out /tmp/test

设计:
- 离线 reader,不动 server / 不写 vault
- 全量 rebuild(每天 <100 commits,简单粗暴)
- 时间窗 join:commit ts ± 60s 内的 chat msg = "preceding context"
- 老 chat 没 ts(我们今天才加)→ context_method="tail-fallback" 标记
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid as _uuid
from datetime import datetime, timedelta
from pathlib import Path


# A-H7: 离线 exporter 不 import server 避免拉 FastAPI 栈;复刻最小 atomic write。
# 同一进程内多个 .jsonl 写,tmp 文件名用 uuid 避免撞。
def _atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{_uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(content, encoding=encoding)
    os.replace(str(tmp), str(path))

# ── 路径解析(独立于 server,避免 import 牵扯整个 FastAPI 栈)──────

def _vault_dir() -> Path:
    env = os.environ.get("HUMAN_AI_HOME")
    if env:
        return (Path(env).expanduser().resolve() / "vault")
    # 走跟 server 一样的 vault_config 链
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import vault_config
        return vault_config.resolve_vault_root() / "vault"
    except Exception:
        return Path.home() / ".human-ai" / "vault"


def _app_state_dir() -> Path:
    env = os.environ.get("HUMAN_AI_STATE")
    if env:
        return Path(env).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "HumanAI"
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "HumanAI" if appdata else Path.home() / "AppData" / "Roaming" / "HumanAI"
    xdg = os.environ.get("XDG_DATA_HOME")
    return Path(xdg) / "HumanAI" if xdg else Path.home() / ".local" / "share" / "HumanAI"


DEFAULT_VAULT = _vault_dir()
DEFAULT_APP_STATE = _app_state_dir()
DEFAULT_THREAD_HISTORY = DEFAULT_APP_STATE / "data" / "thread-history.json"
DEFAULT_OUT_DIR = DEFAULT_APP_STATE / "data" / "history-exports"
DEFAULT_OUTCOMES = DEFAULT_APP_STATE / "data" / "outcomes.json"
DEFAULT_PULSE_DIR = DEFAULT_APP_STATE / "pulse-mirror"
DEFAULT_OUTCOMES_PULSE = DEFAULT_APP_STATE / "data" / "outcomes-pulse.json"
# 多 repo:每个 repo 一个 (source_name, path, outcomes_path)。
# source_name 进 jsonl row 的 source 字段,前端 UI 用作 badge 区分。
DEFAULT_REPOS = [
    ("vault", DEFAULT_VAULT, DEFAULT_OUTCOMES),
    ("pulse", DEFAULT_PULSE_DIR, DEFAULT_OUTCOMES_PULSE),
]

# ── git 操作 ──────────────────────────────────────────────────────

_AUTHOR_TRAILER_RE = re.compile(r'@(user|ai|system)\b')
# diff body 里 +号开头行 提到 #tag(中英都接,排除 emoji 串)
_TAG_RE = re.compile(r'#([A-Za-z一-龥][A-Za-z0-9_一-龥/\-]*)')


def _run_git(args: list[str], cwd: Path, timeout: float = 30.0) -> str:
    # quotepath=false 让中文路径不被 \nnn 转义(给 outcome_tracker / 跨模块一致)
    p = subprocess.run(
        ["git", "-C", str(cwd), "-c", "core.quotepath=false"] + args,
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    if p.returncode != 0:
        return ""
    return p.stdout


def _is_repo(vault: Path) -> bool:
    return (vault / ".git").exists()


def list_commits(vault: Path, since: str | None = None) -> list[dict]:
    """返 [{hash, ts_iso, subject}],按时间从老到新。"""
    fmt = "%H%x09%aI%x09%s"
    args = ["log", f"--format={fmt}", "--reverse"]
    if since:
        args += [f"--since={since}"]
    out = _run_git(args, vault)
    rows = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        rows.append({"hash": parts[0], "ts": parts[1], "subject": parts[2]})
    return rows


def commit_detail(vault: Path, h: str) -> dict:
    """返单 commit 的 files + diff body + author 解析。"""
    files_out = _run_git(["diff-tree", "--no-commit-id", "--name-only", "-r", h], vault)
    files = [ln for ln in files_out.splitlines() if ln]
    # full diff(可能很大,后面截到 2k 给 jsonl 用,raw 留全量给 outcome 阶段)
    diff_body = _run_git(["show", "--format=", h], vault, timeout=60)
    return {"files": files, "diff": diff_body}


def parse_author(subject: str, body: str = "") -> str:
    """从 commit msg subject / body 里抠 @author tag,默认 unknown。"""
    for s in (subject, body):
        m = _AUTHOR_TRAILER_RE.search(s)
        if m:
            return m.group(1)
    return "unknown"


def extract_tags_from_diff(diff_body: str) -> list[str]:
    """从 diff 的 + 号行(新增内容)抠 #tag。"""
    tags = set()
    for line in diff_body.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for m in _TAG_RE.finditer(line):
            tags.add(m.group(1))
    return sorted(tags)


def strip_action_trailer(subject: str) -> str:
    """commit subject 去掉末尾的 @author 部分,留干净 action 描述。"""
    return _AUTHOR_TRAILER_RE.sub("", subject).strip()


# ── chat thread join ─────────────────────────────────────────────

def load_thread(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        # python 3.9 fromisoformat 不接 'Z',要替
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def join_context(commit_ts: str, thread: list[dict], window_sec: int = 60) -> dict:
    """commit ts ± window 内的 chat msg = preceding context。
    返 {preceding_user_msg, preceding_ai_reply, context_method}。
    """
    commit_dt = _parse_iso(commit_ts)
    if not commit_dt:
        return {"preceding_user_msg": None, "preceding_ai_reply": None, "context_method": "no-ts"}

    # 时间窗内的所有 msg(优先时间窗)
    pre_user, pre_ai = None, None
    timed_msgs = [m for m in thread if m.get("ts") and _parse_iso(m["ts"])]
    if timed_msgs:
        cutoff_after = commit_dt + timedelta(seconds=window_sec)
        cutoff_before = commit_dt - timedelta(seconds=window_sec * 10)  # 给 thinking 留宽窗
        # 从老到新过一遍,找窗口内最后一对 user→ai
        for m in timed_msgs:
            mt = _parse_iso(m["ts"])
            if mt is None or mt > cutoff_after:
                continue
            if mt < cutoff_before:
                continue
            if m.get("role") == "user":
                pre_user = (m.get("content") or "")[:500]
                pre_ai = None  # 重置 — 用户又问了
            elif m.get("role") == "assistant" and pre_user is not None and pre_ai is None:
                pre_ai = (m.get("content") or "")[:500]
        if pre_user is not None:
            return {"preceding_user_msg": pre_user, "preceding_ai_reply": pre_ai,
                    "context_method": "time-window"}

    # fallback:thread 末尾 2 条(用户在做这个 commit 前最后说的)
    if thread:
        recent = thread[-3:]  # 最近 3 条找一对 user→ai
        for m in reversed(recent):
            if m.get("role") == "assistant" and pre_ai is None:
                pre_ai = (m.get("content") or "")[:500]
            elif m.get("role") == "user" and pre_user is None:
                pre_user = (m.get("content") or "")[:500]
            if pre_user and pre_ai:
                break
        if pre_user:
            return {"preceding_user_msg": pre_user, "preceding_ai_reply": pre_ai,
                    "context_method": "tail-fallback"}

    return {"preceding_user_msg": None, "preceding_ai_reply": None, "context_method": "empty"}


# ── 主导出流程 ────────────────────────────────────────────────────

DIFF_CAP = 4000  # jsonl 单行 diff 截到 4k,full diff 想要再去 git show


def commit_to_row(vault: Path, commit: dict, thread: list[dict],
                  outcomes: dict | None = None, source: str = "vault") -> dict:
    detail = commit_detail(vault, commit["hash"])
    author = parse_author(commit["subject"])
    tags = extract_tags_from_diff(detail["diff"])
    diff_short = detail["diff"]
    truncated = len(diff_short) > DIFF_CAP
    if truncated:
        diff_short = diff_short[:DIFF_CAP] + f"\n…(truncated, {len(detail['diff']) - DIFF_CAP} more chars)"

    row = {
        "commit": commit["hash"],
        "source": source,  # "vault" | "pulse" — 前端 badge 用
        "ts": commit["ts"],
        "author": author,
        "action": strip_action_trailer(commit["subject"]),
        "files": detail["files"],
        "tags": tags,
        "diff_truncated": truncated,
        "diff": diff_short,
        "context": join_context(commit["ts"], thread),
    }
    # 集成 Z outcome:有 outcome 就贴上,没就空
    if outcomes:
        o = outcomes.get(commit["hash"])
        if o:
            row["outcome"] = {
                "class": o.get("outcome_class"),
                "later_touch_count": o.get("later_touch_count"),
                "modified_after_seconds": o.get("modified_after_seconds"),
                "age_seconds": o.get("age_seconds"),
            }
    return row


def export(vault: Path = DEFAULT_VAULT,
           thread_path: Path = DEFAULT_THREAD_HISTORY,
           out_dir: Path = DEFAULT_OUT_DIR,
           since: str | None = None,
           outcomes_path: Path = DEFAULT_OUTCOMES,
           repos: list | None = None) -> dict:
    """主入口。返 {commits, tags, authors, sources, out_dir} 统计。

    repos: list[(source_name, vault_path, outcomes_path)] — 多 repo 时用。
           默认 None → 仅扫单 vault(向后兼容)。传 DEFAULT_REPOS 扫 vault + pulse。
    """
    # 兼容路径:若没传 repos 用单 vault 模式
    if repos is None:
        repos = [("vault", vault, outcomes_path)]

    # 任一 repo 不可用就 skip 该 repo,但其他 repo 继续
    usable_repos = []
    for src_name, vpath, opath in repos:
        if not vpath.exists() or not _is_repo(vpath):
            continue
        usable_repos.append((src_name, vpath, opath))
    if not usable_repos:
        return {"error": f"no usable git repos in {[str(r[1]) for r in repos]}"}

    thread = load_thread(thread_path)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "by-tag").mkdir(exist_ok=True)
    (out_dir / "by-author").mkdir(exist_ok=True)
    (out_dir / "by-source").mkdir(exist_ok=True)  # 新:按 source 分桶,training 时 filter 用

    all_path = out_dir / "all.jsonl"
    by_tag_handles: dict[str, list[str]] = {}
    by_author_handles: dict[str, list[str]] = {}
    by_source_handles: dict[str, list[str]] = {}

    all_rows = []
    per_source_count = {}
    for src_name, vpath, opath in usable_repos:
        commits = list_commits(vpath, since=since)
        outcomes_map = {}
        if opath and opath.exists():
            try:
                outcomes_map = json.loads(opath.read_text(encoding="utf-8")).get("outcomes", {})
            except Exception as e:
                # A-H8: 不再静默吞 — 训练语料丢 outcome 是高代价静默退化
                sys.stderr.write(
                    f"[history_exporter] WARN: failed to load outcomes "
                    f"from {opath}: {type(e).__name__}: {e}\n"
                )
                outcomes_map = {}
        per_source_count[src_name] = len(commits)
        for c in commits:
            row = commit_to_row(vpath, c, thread, outcomes=outcomes_map, source=src_name)
            all_rows.append(row)
            line = json.dumps(row, ensure_ascii=False)
            by_source_handles.setdefault(src_name, []).append(line)
            # baseline / bulk-import 不进 tag/author 索引(避免污染)
            is_bulk = row["action"].startswith("baseline:") or len(row["tags"]) > 20
            if is_bulk:
                continue
            for tag in row["tags"]:
                by_tag_handles.setdefault(tag, []).append(line)
            by_author_handles.setdefault(row["author"], []).append(line)

    # 按 ts 排序所有 rows(跨 repo 时间线交织)
    all_rows.sort(key=lambda r: r.get("ts") or "")
    _atomic_write_text(
        all_path,
        "\n".join(json.dumps(r, ensure_ascii=False) for r in all_rows) + "\n",
    )
    for tag, lines in by_tag_handles.items():
        # sub-tag `配置系统/ctrl-c-v` 不能直接当 filename — 把 / 替成 _
        safe_name = tag.replace("/", "_").replace("\\", "_") or "_empty"
        _atomic_write_text(
            out_dir / "by-tag" / f"{safe_name}.jsonl",
            "\n".join(lines) + "\n",
        )
    for author, lines in by_author_handles.items():
        _atomic_write_text(out_dir / "by-author" / f"{author}.jsonl", "\n".join(lines) + "\n")
    for src, lines in by_source_handles.items():
        _atomic_write_text(out_dir / "by-source" / f"{src}.jsonl", "\n".join(lines) + "\n")

    return {
        "commits": len(all_rows),
        "per_source": per_source_count,
        "tags": sorted(by_tag_handles.keys()),
        "authors": sorted(by_author_handles.keys()),
        "sources": sorted(by_source_handles.keys()),
        "out_dir": str(out_dir),
        "thread_msgs": len(thread),
    }


# ── CLI ──────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="export vault git history + chat for LLM post-training")
    ap.add_argument("--vault", type=Path, default=DEFAULT_VAULT, help="vault dir(默认从 vault_config / env 解析)")
    ap.add_argument("--thread", type=Path, default=DEFAULT_THREAD_HISTORY, help="thread-history.json 路径")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="输出 jsonl 目录")
    ap.add_argument("--since", type=str, default=None, help='git log --since,例 "2026-05-01"')
    args = ap.parse_args()

    r = export(vault=args.vault, thread_path=args.thread, out_dir=args.out, since=args.since)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    if r.get("error"):
        sys.exit(2)


if __name__ == "__main__":
    main()
