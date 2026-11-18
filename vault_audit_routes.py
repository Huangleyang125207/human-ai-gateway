# PATTERN: routes — vault structural audit/self-heal + git commit history extracted from god module
# USE WHEN: /api/vault/audit|repair 或 /api/history/* 端点、image/meta 映射自愈逻辑改动
# COPY THIS: 无 — 本模块是 server.py §15(清册01)的搬迁体,契约在 server re-export
#
# 抽出记录(2026-07-22, 清册01-§15,Parallel Change expand):
# - 原址 server.py "vault audit + self-heal" 段(_audit_vault/_repair_vault)+
#   "history API" 段(_active_repos/history_stats/history_recent/history_commit/
#   history_rebuild),函数体逐字节照搬。
# - image/meta I/O 与所有路径/解析函数由组装根以命名 provider 注入，
#   保留 tests 的 call-time patch 语义。
# - 2 端点(vault_audit_get/vault_repair)+ 4 history 端点上 APIRouter(HTTP 路径
#   不变),同 consent_routes.py 先例。
# - vault_git.py 反向 lazy 拉 _report_silent_failure/_push_notification,本段不涉及
#   （那两个函数留在 server 权威命名空间 / §20 段，vault_git 的 lazy import 零改动）。
import re as _re

from fastapi import APIRouter

import history_exporter as _he
import outcome_tracker as _ot

router = APIRouter(tags=["vault-audit", "history"])

_LOAD_IMAGE_MAP = None
_SAVE_IMAGE_MAP = None
_LOAD_META_MAP = None
_TASK_IMAGES_DIR = None
_PLATFORM_ROOT = None
_PRETTY_REL = None
_TEMPLATE_PATH = None
_FIND_JOURNAL = None
_TOP_SECTION_BOUNDS = None
_AGGREGATE_PATH = None
_PARSE_AGGREGATE = None
_VAULT_DIR = None
_APP_STATE_DIR = None
_DATA_DIR = None


def configure_effects(
    *,
    load_image_map,
    save_image_map,
    load_meta_map,
    task_images_dir,
    platform_root,
    pretty_rel,
    template_path,
    find_journal,
    top_section_bounds,
    aggregate_path,
    parse_aggregate,
    vault_dir,
    app_state_dir,
    data_dir,
) -> None:
    global _LOAD_IMAGE_MAP, _SAVE_IMAGE_MAP, _LOAD_META_MAP
    global _TASK_IMAGES_DIR, _PLATFORM_ROOT, _PRETTY_REL, _TEMPLATE_PATH
    global _FIND_JOURNAL, _TOP_SECTION_BOUNDS, _AGGREGATE_PATH
    global _PARSE_AGGREGATE, _VAULT_DIR, _APP_STATE_DIR, _DATA_DIR
    _LOAD_IMAGE_MAP = load_image_map
    _SAVE_IMAGE_MAP = save_image_map
    _LOAD_META_MAP = load_meta_map
    _TASK_IMAGES_DIR = task_images_dir
    _PLATFORM_ROOT = platform_root
    _PRETTY_REL = pretty_rel
    _TEMPLATE_PATH = template_path
    _FIND_JOURNAL = find_journal
    _TOP_SECTION_BOUNDS = top_section_bounds
    _AGGREGATE_PATH = aggregate_path
    _PARSE_AGGREGATE = parse_aggregate
    _VAULT_DIR = vault_dir
    _APP_STATE_DIR = app_state_dir
    _DATA_DIR = data_dir


# ── vault audit + self-heal(防用户/AI 整理文件后映射失联)─────────────
def _audit_vault() -> dict:
    """扫所有"path-based 映射"是否还能落到真文件。
    返报告:{image_orphans, image_recoverable, meta_orphans, aggregate_broken_links}
    - image_orphans:image map 里 path 不存在 且 没找到同名 fallback → 真断
    - image_recoverable:path 不存在但 daily-task-images/ 内能找到同名文件 → 可自愈
    - meta_orphans:meta 有这个 task,但当前 daily-tasks.md + today.md 都没这一行
    - aggregate_broken_links:聚合页 row 的 link_target 找不到对应文件
    """
    from datetime import datetime
    from pathlib import Path

    report = {
        "image_orphans": [],
        "image_recoverable": [],
        "meta_orphans": [],
        "aggregate_broken_links": [],
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }

    # 1. images
    try:
        img_map = _LOAD_IMAGE_MAP()
    except Exception:
        img_map = {}
    # 预扫描 daily-task-images 目录下所有 png(递归),建 basename → path 索引
    name_index = {}
    task_images_dir = _TASK_IMAGES_DIR()
    if task_images_dir.exists():
        for p in task_images_dir.rglob("*.png"):
            name_index.setdefault(p.name, []).append(p)
    for key, rel in img_map.items():
        target = _PLATFORM_ROOT() / rel
        if target.exists():
            continue
        # 尝试用 basename 找
        basename = Path(rel).name
        cands = name_index.get(basename, [])
        if cands:
            new_rel = _PRETTY_REL()(cands[0])
            report["image_recoverable"].append({
                "task": key, "old_path": rel, "new_path": new_rel,
            })
        else:
            report["image_orphans"].append({"task": key, "path": rel})

    # 2. meta orphans:每个 meta key 必须能在当前活跃的 daily-task 列表里找到
    try:
        meta = _LOAD_META_MAP()
    except Exception:
        meta = {}
    active_names = set()
    for src in (_TEMPLATE_PATH(), _FIND_JOURNAL()):
        if not src or not src.exists():
            continue
        try:
            text = src.read_text(encoding="utf-8")
            bounds = _TOP_SECTION_BOUNDS(text)
            if not bounds:
                continue
            for line in text.splitlines()[bounds[0]:bounds[1]]:
                m = _re.match(r"^-\s*\[[ x]\]\s*(.+)", line)
                if m:
                    active_names.add(m.group(1).strip())
        except Exception:
            pass
    for key in meta:
        if key not in active_names:
            report["meta_orphans"].append({"task": key, "intake_log_days": len((meta[key] or {}).get("intake_log") or {})})

    # 3. 聚合页 row link 是否 404
    # 注意:markdown `[text](url)` 里 url 含未转义 `)` 会被截断 → link_target
    # 提前结束(如 `26.5.7(第五天` 没 .md)。fallback 重构:尝试 `path).md`。
    try:
        aggregate_path = _AGGREGATE_PATH()
        if aggregate_path.exists():
            text = aggregate_path.read_text(encoding="utf-8")
            for sec in _PARSE_AGGREGATE(text):
                for row in sec["rows"]:
                    link = row.get("link_target") or ""
                    if not link:
                        continue
                    path_part = link.split("#")[0]
                    if not path_part:
                        continue
                    vault_dir = _VAULT_DIR()
                    target = vault_dir / path_part
                    if target.exists():
                        continue
                    # fallback:截断 `).md` 重构
                    if not path_part.endswith(".md"):
                        alt = vault_dir / (path_part + ").md")
                        if alt.exists():
                            continue
                    report["aggregate_broken_links"].append({
                        "tag": sec["tag"], "row_date": row.get("date_short"),
                        "row_time": row.get("time"), "link": link,
                    })
    except Exception:
        pass

    # total_drift 只算"真断"项:image_recoverable / image_orphans / meta_orphans。
    # aggregate_broken_links 报告但不计入(多半是 markdown 链接括号截断,iso_date
    # 解析仍正常,不影响 navigation)
    report["total_drift"] = (
        len(report["image_orphans"])
        + len(report["image_recoverable"])
        + len(report["meta_orphans"])
    )
    report["aggregate_broken_count"] = len(report["aggregate_broken_links"])
    return report


def _repair_vault() -> dict:
    """安全自动修:只动 image_recoverable(改 image map 指到新 path)。
    meta_orphans / aggregate_broken_links 留报告给用户决断,不自动碰。
    """
    report = _audit_vault()
    fixed_images = 0
    if report["image_recoverable"]:
        img_map = _LOAD_IMAGE_MAP()
        for item in report["image_recoverable"]:
            img_map[item["task"]] = item["new_path"]
            fixed_images += 1
        _SAVE_IMAGE_MAP(img_map)
    return {"fixed_images": fixed_images, "remaining": _audit_vault()}


@router.get("/api/vault/audit")
def vault_audit_get():
    return _audit_vault()


@router.post("/api/vault/repair")
def vault_repair():
    return _repair_vault()


# ── history API(给 history.html 前端用)──────────────────────────
# 数据源:vault git log + outcomes.json + thread-history.json,通过 history_exporter
# / outcome_tracker 计算。endpoint 永远现算(scale 小,不缓存)。
def _active_repos():
    """返当前可用 repo 列表 [(source, path, outcomes_path), ...]。"""
    app_state_dir = _APP_STATE_DIR()
    vault_dir = _VAULT_DIR()
    data_dir = _DATA_DIR()
    pulse_dir = app_state_dir / "pulse-mirror"
    out = []
    if (vault_dir / ".git").exists():
        out.append(("vault", vault_dir, data_dir / "outcomes.json"))
    if pulse_dir.exists() and (pulse_dir / ".git").exists():
        out.append(("pulse", pulse_dir, data_dir / "outcomes-pulse.json"))
    return out


@router.get("/api/history/stats")
def history_stats():
    """count + by_author + by_class + by_day(最近 30 天)+ by_source。"""
    from collections import Counter
    repos = _active_repos()
    if not repos:
        return {"error": "no git repos available"}
    by_author, by_class, by_day, by_source = Counter(), Counter(), Counter(), Counter()
    total = 0
    outcomes_computed_any = False
    for src, vpath, opath in repos:
        commits = _he.list_commits(vpath)
        outcomes_map = _ot.load_outcomes(opath).get("outcomes", {})
        if outcomes_map:
            outcomes_computed_any = True
        for c in commits:
            total += 1
            by_source[src] += 1
            by_author[_he.parse_author(c["subject"])] += 1
            by_day[c["ts"][:10]] += 1
            o = outcomes_map.get(c["hash"])
            if o:
                by_class[o.get("outcome_class") or "unknown"] += 1
    return {
        "total": total,
        "by_source": dict(by_source),
        "by_author": dict(by_author),
        "by_class": dict(by_class),
        "by_day": dict(sorted(by_day.items())[-30:]),
        "outcomes_computed": outcomes_computed_any,
    }


@router.get("/api/history/recent")
def history_recent(limit: int = 50):
    """最近 N commits brief。跨 repo 按 ts 排序,前端列表用。"""
    repos = _active_repos()
    if not repos:
        return {"error": "no git repos available"}
    all_brief = []
    for src, vpath, opath in repos:
        commits = _he.list_commits(vpath)
        outcomes_map = _ot.load_outcomes(opath).get("outcomes", {})
        for c in commits:
            o = outcomes_map.get(c["hash"], {})
            all_brief.append({
                "commit": c["hash"][:12],
                "full_hash": c["hash"],
                "source": src,
                "ts": c["ts"],
                "author": _he.parse_author(c["subject"]),
                "action": _he.strip_action_trailer(c["subject"]),
                "outcome_class": o.get("outcome_class"),
                "later_touch_count": o.get("later_touch_count", 0),
            })
    # ts 倒序(新在前)
    all_brief.sort(key=lambda r: r["ts"] or "", reverse=True)
    return {"commits": all_brief[: max(1, min(limit, 500))], "limit": limit}


@router.get("/api/history/commit/{commit_hash}")
def history_commit(commit_hash: str):
    """单 commit 完整(跨 repo 查找)。"""
    repos = _active_repos()
    if not repos:
        return {"error": "no git repos available"}
    for src, vpath, opath in repos:
        detail = _he.commit_detail(vpath, commit_hash)
        if detail["files"] or detail["diff"]:
            info = _he._run_git(["log", "-1", "--format=%aI%x09%s", commit_hash], vpath)
            parts = info.strip().split("\t", 1)
            ts = parts[0] if parts else ""
            subject = parts[1] if len(parts) > 1 else ""
            thread = _he.load_thread(_he.DEFAULT_THREAD_HISTORY)
            outcomes_map = _ot.load_outcomes(opath).get("outcomes", {})
            return _he.commit_to_row(vpath, {"hash": commit_hash, "ts": ts, "subject": subject},
                                     thread, outcomes=outcomes_map, source=src)
    return {"error": f"commit not found in any repo: {commit_hash}"}


@router.post("/api/history/rebuild")
def history_rebuild():
    """重新跑 outcome_tracker(每个 repo 各一份)+ history_exporter(multi-repo)。"""
    repos = []
    app_state_dir = _APP_STATE_DIR()
    vault_dir = _VAULT_DIR()
    data_dir = _DATA_DIR()
    pulse_dir = app_state_dir / "pulse-mirror"
    if (vault_dir / ".git").exists():
        repos.append(("vault", vault_dir, data_dir / "outcomes.json"))
    if pulse_dir.exists() and (pulse_dir / ".git").exists():
        repos.append(("pulse", pulse_dir, data_dir / "outcomes-pulse.json"))
    if not repos:
        return {"error": "no git repos found (run /api/pulse/refresh-mirror first?)"}

    outcome_counts = {}
    for src, vpath, opath in repos:
        data = _ot.compute_all(vpath)
        _ot.save_outcomes(data, opath)
        outcome_counts[src] = data["count"]

    r = _he.export(repos=repos)
    return {"outcomes_counts": outcome_counts, "export": r}
