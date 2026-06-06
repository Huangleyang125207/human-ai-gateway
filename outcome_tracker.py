"""
outcome_tracker.py — 给每个 commit 打"稳了多久 / 被怎么改"标注

为啥:DPO 数据的灵魂是 (写了什么, 用户保留 vs 修改 vs 撤回)。
git 自己有,但要 walker + per-commit 计算。

每个 commit C 的 outcome:
  - touched_files: C 改了哪些 file
  - later_touches: 之后有哪些 commit 又改了这些 file
  - outcome_class: stable | modified
  - modified_after_seconds: C 落后多久第一次被改(若 stable 则 null)
  - age_seconds: C 到现在多久
  - last_computed: 标记什么时候算的(数据新鲜度)

存:APP_STATE_DIR/data/outcomes.json — 全量 JSON 单文件,scale 5 年 ~2000 commits 不卡。

CLI:
    python3 outcome_tracker.py                   # rebuild outcomes.json
    python3 outcome_tracker.py --vault X         # 指定 vault
    python3 outcome_tracker.py --since 2026-05-01
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# ── 路径解析(跟 history_exporter 对齐)──────────────────────────

def _vault_dir() -> Path:
    env = os.environ.get("HUMAN_AI_HOME")
    if env:
        return Path(env).expanduser().resolve() / "vault"
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
DEFAULT_OUTCOMES = _app_state_dir() / "data" / "outcomes.json"


# ── git ──────────────────────────────────────────────────────────

def _run_git(args: list[str], cwd: Path, timeout: float = 30.0) -> str:
    # quotepath=false 让中文路径不被 \nnn 转义;否则下游 file_history 查不到
    p = subprocess.run(
        ["git", "-C", str(cwd), "-c", "core.quotepath=false"] + args,
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    return p.stdout if p.returncode == 0 else ""


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


# ── 主计算 ────────────────────────────────────────────────────────

def file_history(vault: Path, file_path: str) -> list[tuple[str, str]]:
    """返该 file 的所有 commit(从老到新):[(hash, iso_ts), ...]。"""
    out = _run_git(["log", "--format=%H%x09%aI", "--reverse", "--", file_path], vault)
    rows = []
    for line in out.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            rows.append((parts[0], parts[1]))
    return rows


def commit_files(vault: Path, commit_hash: str) -> list[str]:
    out = _run_git(["diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash], vault)
    return [ln for ln in out.splitlines() if ln]


def compute_outcome(vault: Path, commit_hash: str, ts: str,
                    now: datetime | None = None) -> dict:
    """单 commit 的 outcome。
    now: 给测试注入"假装现在是什么时候"。生产传 None → datetime.now(UTC)。
    """
    if now is None:
        now = datetime.now(timezone.utc)

    commit_dt = _parse_iso(ts)
    age_seconds = int((now - commit_dt).total_seconds()) if commit_dt else None

    files = commit_files(vault, commit_hash)
    # 对每个 file:看后续有没有 commit 又改它
    later_touches: list[dict] = []
    earliest_later_seconds: int | None = None
    for f in files:
        hist = file_history(vault, f)
        # 找到自己的位置
        my_idx = None
        for i, (h, _) in enumerate(hist):
            if h == commit_hash:
                my_idx = i
                break
        if my_idx is None:
            continue
        for h, h_ts in hist[my_idx + 1:]:
            later_touches.append({"file": f, "commit": h, "ts": h_ts})
            ht = _parse_iso(h_ts)
            if ht and commit_dt:
                delta = int((ht - commit_dt).total_seconds())
                if earliest_later_seconds is None or delta < earliest_later_seconds:
                    earliest_later_seconds = delta

    outcome_class = "stable" if not later_touches else "modified"

    return {
        "commit": commit_hash,
        "ts": ts,
        "files_touched": files,
        "outcome_class": outcome_class,
        "later_touch_count": len(later_touches),
        "later_touches": later_touches[:20],  # cap 防 JSON 爆;真要全用 git 自己查
        "modified_after_seconds": earliest_later_seconds,
        "age_seconds": age_seconds,
        "last_computed": now.isoformat(),
    }


# ── 全量 rebuild ─────────────────────────────────────────────────

def list_all_commits(vault: Path, since: str | None = None) -> list[tuple[str, str]]:
    args = ["log", "--format=%H%x09%aI", "--reverse"]
    if since:
        args += [f"--since={since}"]
    out = _run_git(args, vault)
    rows = []
    for line in out.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            rows.append((parts[0], parts[1]))
    return rows


def compute_all(vault: Path, since: str | None = None,
                now: datetime | None = None) -> dict:
    """对 vault 里所有 commit 算 outcome,返 dict 以 hash 为 key。"""
    if now is None:
        now = datetime.now(timezone.utc)
    outcomes = {}
    for h, ts in list_all_commits(vault, since=since):
        outcomes[h] = compute_outcome(vault, h, ts, now=now)
    return {
        "computed_at": now.isoformat(),
        "vault": str(vault),
        "count": len(outcomes),
        "outcomes": outcomes,
    }


def save_outcomes(data: dict, path: Path = DEFAULT_OUTCOMES) -> None:
    # A-H8: atomic + rotate;outcomes 指针损坏 = 训练 DPO 数据全没了
    import os as _os
    import uuid as _uuid
    path.parent.mkdir(parents=True, exist_ok=True)
    # 5-rotate backup
    try:
        if path.exists():
            for i in range(5, 1, -1):
                src = path.with_name(f"{path.name}.bak.{i-1}")
                if src.exists():
                    src.rename(path.with_name(f"{path.name}.bak.{i}"))
            path.with_name(f"{path.name}.bak.1").write_bytes(path.read_bytes())
    except Exception:
        pass  # 备份失败不阻塞主写
    tmp = path.with_name(f"{path.name}.{_os.getpid()}.{_uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _os.replace(str(tmp), str(path))


def load_outcomes(path: Path = DEFAULT_OUTCOMES) -> dict:
    if not path.exists():
        return {"computed_at": None, "count": 0, "outcomes": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        # A-H8: 不再静默 — 至少 stderr 让 caller / cron 看到
        import sys as _sys
        _sys.stderr.write(
            f"[outcome_tracker] WARN: failed to parse {path}: {type(e).__name__}: {e}\n"
        )
        # 尝试 bak.1 回滚
        bak = path.with_name(f"{path.name}.bak.1")
        if bak.exists():
            try:
                return json.loads(bak.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"computed_at": None, "count": 0, "outcomes": {}}


# ── CLI ──────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="annotate each vault commit with outcome (stable/modified)")
    ap.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUTCOMES)
    ap.add_argument("--since", type=str, default=None)
    args = ap.parse_args()

    if not (args.vault / ".git").exists():
        print(json.dumps({"error": f"not a git repo: {args.vault}"}, ensure_ascii=False))
        sys.exit(2)
    data = compute_all(args.vault, since=args.since)
    save_outcomes(data, args.out)
    # 输出摘要
    classes = {}
    for o in data["outcomes"].values():
        classes[o["outcome_class"]] = classes.get(o["outcome_class"], 0) + 1
    print(json.dumps({
        "count": data["count"],
        "out": str(args.out),
        "classes": classes,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
