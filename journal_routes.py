"""journal_routes — APIRouter for /api/journal/* + /api/tag-aggregate/*.

Extract Module(ctrl-c-v § 9):journal 读/写 + tag-aggregate 10 endpoint 从 server.py 抽出。
核心簇拆分 target 4(移动 parity 价值最高:mobile 真迁 /api/journal/*)。

**关键 de-risk —— 危险 helper 全留 server.py 不动:**
- _patch_block / _insert_block / _append_comment_to_block / _check_author
  (authorship 边界 = AI 不能覆盖 @user 块 + sha256 baseline+lock + H2-mismatch guard)
- parse_journal / _journal_for_date / _list_journal_files / _new_day_create / _get_day_one
- _refresh_tag_aggregate / _parse_tag_aggregate
- find_today_journal / TIME_H1_RE / _safe_write_text / vault_git / 路径常量
这些被 LLM tools(tool_patch_journal_block 等,在 server TOOL_DISPATCH)+ test_authorship/
test_patch_h2_rename/test_insert_block_body 直接调,留 server → 零迁移、authorship 核心一字不动。

本模块只搬 *thin handler*:解析 request → 调 helper → 返回。全走 function-body lazy
`from server import`(date 路由经 find_today_journal 读 server.JOURNAL_DIR,测试 patch 仍命中)。
HTTP-only,零直接调用方 → 不 re-export。
characterization:tests/test_journal_routes.py(15,handler 契约)+ helper 层 3 个现有测试。
"""
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["journal"])


# ── GET /api/journal/today ───────────────────────────────────────────
@router.get("/api/journal/today")
def journal_today(date: str = None):
    from server import _journal_for_date
    return _journal_for_date(date)


# ── GET /api/journal/days ────────────────────────────────────────────
@router.get("/api/journal/days")
def journal_days():
    from server import _list_journal_files
    return {"days": _list_journal_files()}


# ── POST /api/journal/new-day ────────────────────────────────────────
@router.post("/api/journal/new-day")
async def journal_new_day(req: Request):
    """生成今天(或指定日期)的 schedule 骨架文件。Python 内联,不依赖 bash 脚本。
    body 可选 {"date": "YYYY-MM-DD"};不传 = 今天。
    返 {ok, created, file, message}。已存在 created=False 仍 ok=True(幂等)。
    """
    from server import datetime, _new_day_create
    body = {}
    try:
        body = await req.json()
    except Exception:
        pass
    date_arg = (body or {}).get("date", "").strip() or datetime.now().strftime("%Y-%m-%d")
    return _new_day_create(date_arg)


# ── GET /api/journal/tag-stats ───────────────────────────────────────
@router.get("/api/journal/tag-stats")
def journal_tag_stats(limit: int = 5):
    """统计 vault/半小时复盘/ 下所有 md 的 H2 行 #tag 出现次数,返 top N。
    没用过任何 tag(新装用户) → 兜底返 5 个默认 tag,带 default=True 标记。
    """
    from server import JOURNAL_DIR
    DEFAULT_TAGS = ["工作", "饮食", "运动", "探索", "投资"]
    counts = {}
    if JOURNAL_DIR.exists():
        for f in JOURNAL_DIR.glob("*.md"):
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            for line in text.splitlines():
                if line.startswith("## "):
                    for t in re.findall(r"#(\S+)", line[3:]):
                        counts[t] = counts.get(t, 0) + 1
    top = sorted(counts.items(), key=lambda x: -x[1])[:max(1, limit)]
    if not top:
        return {"tags": [{"tag": t, "count": 0, "default": True} for t in DEFAULT_TAGS]}
    return {"tags": [{"tag": t, "count": c} for t, c in top]}


# ── POST /api/journal/insert-block ───────────────────────────────────
@router.post("/api/journal/insert-block")
async def journal_insert_block(req: Request):
    """加新条目到今天(或指定日期)的 md 中。
    body: {date?, time: HH:MM, tag?: "工作", title?: "...", body?: "正文 md"}
    - 时间块不存在 → 新建
    - 已存在 → append 一个新 H2 到该块下(支持同时间多条目)
    body 直通 _insert_block(paper 版 composer「回一句」真落 md 走这里)。
    """
    from server import datetime, find_today_journal, _insert_block
    body = await req.json()
    date_arg = (body.get("date") or "").strip()
    time_str = (body.get("time") or "").strip()
    tag = (body.get("tag") or "").strip().lstrip("#")
    title = (body.get("title") or "").strip()
    if not time_str:
        raise HTTPException(400, "need 'time'")

    if date_arg:
        try:
            target = datetime.strptime(date_arg, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, f"bad date: {date_arg}")
        f = find_today_journal(target)
    else:
        f = find_today_journal()
    if not f:
        raise HTTPException(404, "no journal file for that date")

    # HTTP endpoint = user 自己点 UI 加 entry → 标 @user(authorship boundary 用)
    body_md = (body.get("body") or "").strip()
    result = _insert_block(f, time_str, tag=tag, title=title, author="user", body=body_md)
    if "error" in result:
        return JSONResponse(status_code=400, content=result)
    return result


# ── POST /api/journal/delete-block ───────────────────────────────────
@router.post("/api/journal/delete-block")
async def journal_delete_block(req: Request):
    """删除某个时间块的全部内容(回到 `## ` 占位状态)。
    body: {time, date?}
    """
    from server import datetime, find_today_journal, TIME_H1_RE, _safe_write_text, _pretty_rel
    body = await req.json()
    time_label = (body.get("time") or "").strip()
    date_arg = (body.get("date") or "").strip()
    if not time_label:
        raise HTTPException(400, "need 'time'")
    if date_arg:
        try:
            target = datetime.strptime(date_arg, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, f"bad date: {date_arg}")
        f = find_today_journal(target)
    else:
        f = find_today_journal()
    if not f:
        raise HTTPException(404, "no journal file")
    text = f.read_text(encoding="utf-8")
    lines = text.splitlines()
    h, m = time_label.replace("：", ":").split(":")
    re_h1 = re.compile(rf'^# {int(h)}[：:]{int(m):02d}\s*$')
    start = None
    for i, ln in enumerate(lines):
        if re_h1.match(ln):
            start = i
            break
    if start is None:
        raise HTTPException(404, f"time block {time_label} not found")
    # 找下一个 H1 或 ---
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if TIME_H1_RE.match(lines[j]) or lines[j].strip() == "---":
            end = j
            break
    # 替换为占位 `##` + 一个空行
    new_lines = lines[:start + 1] + ["", "##", ""] + lines[end:]
    _safe_write_text(f, "\n".join(new_lines) + ("\n" if text.endswith("\n") else ""), rotate=True)
    return {"ok": True, "cleared": time_label, "file": _pretty_rel(f)}


# ── POST /api/journal/patch ──────────────────────────────────────────
@router.post("/api/journal/patch")
async def journal_patch(req: Request):
    from server import datetime, find_today_journal, _patch_block
    body = await req.json()
    time_label = body.get("time")          # e.g. "18:30"
    new_block_md = body.get("new_md")      # full replacement of that block (between # H1 and next ---)
    date_arg = (body.get("date") or "").strip()
    if not time_label or new_block_md is None:
        raise HTTPException(400, "need {time, new_md}")
    # 关键:用 body.date 决定写哪天的 md;不传 date 才 fallback 今天
    # 之前 hardcode find_today_journal() → 用户在历史日期视图编辑,内容打到今天 md / 找不到块 404
    if date_arg:
        try:
            target = datetime.strptime(date_arg, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, f"bad date: {date_arg}")
        f = find_today_journal(target)
    else:
        f = find_today_journal()
    if not f:
        raise HTTPException(404, f"no journal file for {date_arg or 'today'}")
    # HTTP endpoint = user 自己改 UI → author='user' 可改任何块(含 @ai)
    return _patch_block(f, time_label, new_block_md, author="user")


# ── POST /api/tag-aggregate/register ─────────────────────────────────
@router.post("/api/tag-aggregate/register")
async def tag_aggregate_register(req: Request):
    """注册新 project tag — 在 标签聚合.md 末尾追加 `## #tagname` section,
    带空表头。注册后调用方应自动 trigger refresh 把 schedule 里已有的
    匹配 entry 吸进来。

    body: {tag: str (不带 #), description?: str, with_sub?: bool}
    """
    from server import TAG_AGGREGATE_PATH, _safe_write_text, vault_git, VAULT_DIR
    body = await req.json()
    tag = (body.get("tag") or "").strip().lstrip("#").strip()
    description = (body.get("description") or "").strip()
    with_sub = bool(body.get("with_sub"))

    if not tag:
        return {"ok": False, "error": "tag 名不能为空"}
    if not re.match(r"^[\w\-一-鿿/]+$", tag):
        return {"ok": False, "error": f"tag 只能用字母/数字/下划线/连字符/中文,得到:{tag}"}
    if "/" in tag:
        return {"ok": False, "error": "注册 parent tag(不带 /sub);sub-tag 自动 roll-up"}

    if not TAG_AGGREGATE_PATH.exists():
        return {"ok": False, "error": "标签聚合.md 不存在"}

    text = TAG_AGGREGATE_PATH.read_text(encoding="utf-8")
    # 已注册?
    if re.search(rf"^##\s+#{re.escape(tag)}\s*$", text, re.MULTILINE):
        return {"ok": False, "error": f"#{tag} 已经注册过了"}

    # 拼新 section
    parts = [f"## #{tag}\n"]
    if description:
        parts.append(f"\n{description}\n")
    parts.append("\n")
    if with_sub:
        parts.append("| 日期 | 时间 | 链接 | 内容 | Sub |\n")
        parts.append("|------|------|------|------|-----|\n")
    else:
        parts.append("| 日期 | 时间 | 链接 | 内容 |\n")
        parts.append("|------|------|------|------|\n")
    parts.append("\n---\n")
    section = "".join(parts)

    # append 到文件末尾(确保前面有 \n 隔开)
    sep = "\n" if not text.endswith("\n") else ""
    if not text.rstrip().endswith("---"):
        # 保证段间有 --- 分隔(跟现有约定一致)
        sep = sep + "\n---\n\n" if text.strip() else sep
    else:
        sep += "\n"
    new_text = text + sep + section
    _safe_write_text(TAG_AGGREGATE_PATH, new_text, rotate=True)
    vault_git.commit_after_write(VAULT_DIR, f"aggregate register #{tag}",
                                 author="system", paths=[TAG_AGGREGATE_PATH])

    return {"ok": True, "tag": tag, "with_sub": with_sub}


# ── POST /api/tag-aggregate/refresh ──────────────────────────────────
@router.post("/api/tag-aggregate/refresh")
def tag_aggregate_refresh():
    """扫 schedule files → diff 现有 标签聚合.md → append 缺失行。
    只 append,不 delete,不动 description。"""
    from server import _refresh_tag_aggregate, log
    try:
        result = _refresh_tag_aggregate()
        return {"ok": True, **result}
    except Exception as e:
        log.exception("tag aggregate refresh failed")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ── GET /api/tag-aggregate ───────────────────────────────────────────
@router.get("/api/tag-aggregate")
def tag_aggregate():
    """解析 数据库/valut/标签聚合.md, 返回按 tag 分组的 rows。
    每 row 含 iso_date,前端点击 → window.gateway.journal.goto(iso_date)。
    """
    from server import TAG_AGGREGATE_PATH, _parse_tag_aggregate
    if not TAG_AGGREGATE_PATH.exists():
        return {"sections": [], "warning": f"not found: {TAG_AGGREGATE_PATH}"}
    text = TAG_AGGREGATE_PATH.read_text(encoding="utf-8")
    return {"sections": _parse_tag_aggregate(text)}
