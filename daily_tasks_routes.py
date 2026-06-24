"""daily_tasks_routes — APIRouter for /api/daily-tasks/* + /api/water-cup.

Extract Module(ctrl-c-v § 9):把 daily-tasks HTTP 端点从 server.py monolith 抽出。
thin wrapper —— 8 个 handler 搬过来,业务逻辑零变化;所有 helper + 常量走 function-body
lazy `from server import` 拉回(避循环,且让测试 patch server.X 仍命中)。

**留在 server.py(误移 = 多簇崩,见 P0+ tripwire 测试):**
- io-map `_load/_save_task_image_map` + `_load/_save_task_meta_map`(_audit_vault/_repair_vault
  + cutout 共用 → T11 守)
- `_apply_task_op`(/template/task + /delete + LLM tool_manage 三方共用 → T12/T13 守)
- 全部 daily-task LLM tools(TOOL_IMPL/TOOL_GROUPS 缠绕,chat dispatch 公民 → T9/T13 守)
- server-core:_safe_write_text / find_today_journal / _top_section_bounds / WATER_CUP_KEY
  / DAILY_TASK_IMAGES_DIR / SCHEDULE_TEMPLATE_PATH / datetime(now-faking 测试 patch 点)等

HTTP-only,零直接调用方 → 不 re-export(同 setup_routes)。
characterization 守门:tests/test_daily_tasks_routes.py(16 GREEN-LOCK,§ T7 + P0+ adversarial)。
"""
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["daily-tasks"])


# ── GET /api/daily-tasks — 清单 + 图 + 剂量/库存 ──────────────────────
@router.get("/api/daily-tasks")
def daily_tasks_catalog(date: str = ""):
    """返指定日 daily-task 清单 + 每个 task 的 image url + meta(剂量/库存)。
    date 缺省 = 今天;date=YYYY-MM-DD 看历史(read-only,不会触发 md 同步)。
    """
    from server import (datetime, _today_date_str, _read_daily_tasks_from_md,
                        _load_task_image_map, _load_task_meta_map, _task_meta_state,
                        _ensure_md_progress_children, _writable_dates_set, log)
    target = None
    is_today = True
    if date:
        try:
            target = datetime.strptime(date, "%Y-%m-%d")
            is_today = (date == _today_date_str())
        except ValueError:
            raise HTTPException(400, f"bad date: {date}")
    # 读 md(指定日 / 今天)
    tasks = _read_daily_tasks_from_md(target_date=target)
    image_map = _load_task_image_map()
    meta_map = _load_task_meta_map()
    for t in tasks:
        rel = image_map.get(t["name"])
        t["image_url"] = f"/{rel}" if rel else None
        state = _task_meta_state(t["name"], meta_map, target_date=target)
        t.update(state)
        # 只对"今天"做 md 子 box 同步(历史已经 backfill 过,且只读)
        if is_today and state["daily_dose"] > 1:
            try:
                _ensure_md_progress_children(t["name"], state["daily_dose"], state["today_intake"])
            except Exception as e:
                log.warning(f"ensure md children for '{t['name']}' failed: {e}")
    # is_writable: 今天总可写;过去看 _writable_dates_set(次日 12:00 前补昨天)
    resolved_date = date or _today_date_str()
    is_writable = resolved_date in _writable_dates_set()
    return {"tasks": tasks, "date": resolved_date, "is_today": is_today,
            "is_writable": is_writable}


# ── POST /api/daily-tasks/check — 打卡 ───────────────────────────────
@router.post("/api/daily-tasks/check")
async def daily_task_check(req: Request):
    """打卡。三种 body 形式:
      {task_name, checked: bool}  → 兼容旧用法。true=置满 daily_dose,false=置 0。
      {task_name, increment: ±1}  → 当前 intake ±1。
      {task_name, intake: N}      → 直接置数。
    可选 date=YYYY-MM-DD:补卡昨天(仅 _writable_dates_set 允许的日期 — 次日 12:00 前补昨天)。
    md 的 - [x] / - [ ] 自动跟随 (intake >= daily_dose 才 [x])。
    返回:{ok, task_name, checked, ...meta_state}
    """
    from server import (datetime, _writable_dates_set, _load_task_meta_map,
                        _save_task_meta_map, _bump_intake, _task_meta_state,
                        _set_md_checkbox, _ensure_md_progress_children, log)
    body = await req.json()
    name = (body.get("task_name") or "").strip()
    if not name:
        raise HTTPException(400, "need task_name")

    # 补卡日期解析。缺省 = 今天;有 date 字段就走窗口验证。
    date_arg = (body.get("date") or "").strip()
    for_date = None
    if date_arg:
        if date_arg not in _writable_dates_set():
            raise HTTPException(400,
                f"date {date_arg} 不在补卡窗口内(只能补今天 / 昨天 12:00 前)")
        try:
            for_date = datetime.strptime(date_arg, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, f"bad date: {date_arg}")

    # 可选:首次记录该 task 时用 caller 给的 daily_dose 初始化(没设过的话)。
    # 水杯特别需要 — 前端 CUPS_TOTAL=8,但 fresh meta 没这个 task,默认 dose=1
    # 会把 intake=4 clamp 到 1。caller 传 daily_dose 表"我知道这个 task 的剂量"。
    init_dose = body.get("daily_dose")
    if init_dose is not None:
        try:
            init_dose = max(1, int(init_dose))
            mm = _load_task_meta_map()
            if name not in mm or "daily_dose" not in (mm.get(name) or {}):
                ent = dict(mm.get(name) or {})
                ent["daily_dose"] = init_dose
                mm[name] = ent
                _save_task_meta_map(mm)
        except (TypeError, ValueError):
            pass

    if "intake" in body:
        state = _bump_intake(name, set_to=int(body["intake"]), for_date=for_date)
    elif "increment" in body:
        state = _bump_intake(name, delta=int(body["increment"]), for_date=for_date)
    else:
        # 兼容旧:checked=true → 置满 daily_dose;false → 置 0
        checked_flag = bool(body.get("checked"))
        meta_map = _load_task_meta_map()
        cur = _task_meta_state(name, meta_map, target_date=for_date)
        target = cur["daily_dose"] if checked_flag else 0
        state = _bump_intake(name, set_to=target, for_date=for_date)

    md_checked = state["today_intake"] >= state["daily_dose"]
    if not _set_md_checkbox(name, md_checked, target_date=for_date):
        # md 没找到也不报错 — 可能 task 在 daily-tasks.md 但当日 file 顶部还未刷
        log.info(f"check: md row '{name}' not found in {date_arg or 'today'} (meta updated only)")
    # daily_dose>1:同步进度子 box(前 K 个 [x],其余 [ ])
    if state["daily_dose"] > 1:
        try:
            _ensure_md_progress_children(name, state["daily_dose"], state["today_intake"],
                                          target_date=for_date)
        except Exception as e:
            log.warning(f"ensure md children for '{name}' failed: {e}")
    return {
        "ok": True,
        "task_name": name,
        "checked": md_checked,
        **state,
    }


# ── POST /api/daily-tasks/meta — 改剂量/库存 ─────────────────────────
@router.post("/api/daily-tasks/meta")
async def daily_task_meta_update(req: Request):
    """改 task 的 total_pills / daily_dose。body: {task_name, total_pills?, daily_dose?}"""
    from server import _load_task_meta_map, _save_task_meta_map, _task_meta_state
    body = await req.json()
    name = (body.get("task_name") or "").strip()
    if not name:
        raise HTTPException(400, "need task_name")
    meta_map = _load_task_meta_map()
    entry = dict(meta_map.get(name) or {})
    if "total_pills" in body:
        v = body["total_pills"]
        if v in (None, "", 0):
            entry.pop("total_pills", None)
        else:
            try:
                entry["total_pills"] = max(1, int(v))
            except (TypeError, ValueError):
                raise HTTPException(400, "total_pills must be int")
    if "daily_dose" in body:
        try:
            d = int(body["daily_dose"])
        except (TypeError, ValueError):
            raise HTTPException(400, "daily_dose must be int")
        entry["daily_dose"] = max(1, d)
    meta_map[name] = entry
    _save_task_meta_map(meta_map)
    return {"ok": True, "task_name": name, **_task_meta_state(name, meta_map)}


# ── POST /api/daily-tasks/backfill-progress — 历史子 box 回填 ─────────
@router.post("/api/daily-tasks/backfill-progress")
def daily_task_backfill_progress():
    """扫所有 task 的 intake_log,把每一天对应的 md 顶部段也展成 N 个进度子 box。
    幂等可重跑。只动 daily_dose > 1 的 task。
    """
    from server import (_load_task_meta_map, datetime, find_today_journal,
                        _ensure_md_progress_children, log)
    meta_map = _load_task_meta_map()
    touched = []
    skipped_no_file = []
    for name, entry in meta_map.items():
        entry = entry or {}
        daily_dose = int(entry.get("daily_dose") or 1)
        if daily_dose < 2:
            continue
        intake_log = entry.get("intake_log") or {}
        for date_str, intake in intake_log.items():
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d")
            except Exception:
                continue
            day_f = find_today_journal(d)
            if not day_f:
                skipped_no_file.append({"task": name, "date": date_str})
                continue
            try:
                changed = _ensure_md_progress_children(name, daily_dose, int(intake or 0), target_date=d)
                if changed:
                    touched.append({"task": name, "date": date_str, "intake": int(intake or 0), "dose": daily_dose})
            except Exception as e:
                log.warning(f"backfill {name} {date_str}: {e}")
    return {"ok": True, "touched": touched, "touched_count": len(touched), "skipped_no_file": skipped_no_file}


# ── POST /api/daily-tasks/delete — 删补剂(md 双写 + image + meta)─────
@router.post("/api/daily-tasks/delete")
async def daily_task_delete(req: Request):
    """删除一个补剂:从 daily-tasks.md + 今天 md + image map + meta map 全部清掉。
    body: {task_name}
    """
    from server import (SCHEDULE_TEMPLATE_PATH, find_today_journal, _apply_task_op,
                        _load_task_image_map, _save_task_image_map, _load_task_meta_map,
                        _save_task_meta_map, PLATFORM_ROOT, log)
    body = await req.json()
    name = (body.get("task_name") or "").strip()
    if not name:
        raise HTTPException(400, "need task_name")

    # 1. 从 md 真相源 + 今天文件删行
    targets = []
    if SCHEDULE_TEMPLATE_PATH.exists():
        targets.append(SCHEDULE_TEMPLATE_PATH)
    today_f = find_today_journal()
    if today_f:
        targets.append(today_f)
    md_results = [_apply_task_op(f, "del", "", name) for f in targets]

    # 2. 删图 + image map
    image_map = _load_task_image_map()
    rel = image_map.pop(name, None)
    if rel:
        try:
            (PLATFORM_ROOT / rel).unlink(missing_ok=True)
        except Exception as e:
            log.warning(f"delete image {rel} failed: {e}")
        _save_task_image_map(image_map)

    # 3. 删 meta
    meta_map = _load_task_meta_map()
    if name in meta_map:
        meta_map.pop(name, None)
        _save_task_meta_map(meta_map)

    return {"ok": True, "task_name": name, "md_results": md_results, "image_removed": bool(rel)}


# ── GET /api/daily-tasks/history — 最近 N 天 check 状态 ───────────────
@router.get("/api/daily-tasks/history")
def daily_task_history(name: str, days: int = 14):
    """返回 task 在最近 N 天的 check 状态。给大图 modal 显示历史 streak 用。"""
    from server import datetime, timedelta, find_today_journal, _top_section_bounds
    import re
    if not name:
        raise HTTPException(400, "need name query param")
    days = max(1, min(int(days), 60))
    today = datetime.now()
    out = []
    for i in range(days):
        d = today - timedelta(days=i)
        f = find_today_journal(d)
        entry = {"date": d.strftime("%Y-%m-%d"), "checked": None}
        if f:
            try:
                text = f.read_text(encoding="utf-8")
                bounds = _top_section_bounds(text)
                if bounds:
                    lines = text.splitlines()
                    for ln in lines[bounds[0]:bounds[1]]:
                        m = re.match(r"^-\s*\[([ x])\]\s*(.+)", ln)
                        if m and m.group(2).strip() == name:
                            entry["checked"] = (m.group(1) == "x")
                            break
            except Exception:
                pass
        out.append(entry)
    return {"name": name, "days": list(reversed(out))}  # 最早→最新


# ── GET /api/water-cup — 当前水杯图 ──────────────────────────────────
@router.get("/api/water-cup")
def water_cup_get():
    """返当前水杯图 url(若设过)。"""
    from server import _load_task_image_map, WATER_CUP_KEY
    rel = _load_task_image_map().get(WATER_CUP_KEY)
    return {"image_url": f"/{rel}" if rel else None}


# ── POST /api/water-cup — 设水杯图(复用 cutout 流)──────────────────
@router.post("/api/water-cup")
async def water_cup_set(req: Request):
    """设水杯图。body: {attachment_url}。复用 cutout 流。"""
    from server import (_get_or_create_processed_attachment, DAILY_TASK_IMAGES_DIR,
                        _pretty_rel, _load_task_image_map, _save_task_image_map, WATER_CUP_KEY)
    body = await req.json()
    url = (body.get("attachment_url") or "").strip()
    if not url:
        raise HTTPException(400, "need attachment_url")
    processed, err = _get_or_create_processed_attachment(url)
    if err:
        raise HTTPException(400, err)
    DAILY_TASK_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    out = DAILY_TASK_IMAGES_DIR / "_water_cup.png"
    out.write_bytes(processed.read_bytes())
    rel = _pretty_rel(out)
    image_map = _load_task_image_map()
    image_map[WATER_CUP_KEY] = rel
    _save_task_image_map(image_map)
    return {"ok": True, "image_url": f"/{rel}"}
