"""daily_tasks_routes — APIRouter for /api/daily-tasks/* + /api/water-cup.

Extract Module(ctrl-c-v § 9):把 daily-tasks HTTP 端点从 server.py monolith 抽出。
thin wrapper —— 8 个 handler 搬过来,业务逻辑零变化;helper + 常量由组装根以
具名 provider 注入，测试 patch server.X 仍在 call-time 命中。

**留在 server.py(误移 = 多簇崩,见 P0+ tripwire 测试):**
- io-map `_load/_save_task_image_map` + `_load/_save_task_meta_map`(_audit_vault/_repair_vault
  + cutout 共用 → T11 守)
- `_apply_task_op`(/template/task + /delete + LLM tool_manage 三方共用 → T12/T13 守)
- 全部 daily-task LLM tools(TOOL_IMPL/ActionPolicy 缠绕,chat dispatch 公民 → T9/T13 守)
- server-core:_safe_write_text / find_today_journal / _top_section_bounds / WATER_CUP_KEY
  / DAILY_TASK_IMAGES_DIR / SCHEDULE_TEMPLATE_PATH / datetime(now-faking 测试 patch 点)等

HTTP-only,零直接调用方 → 不 re-export(同 setup_routes)。
characterization 守门:tests/test_daily_tasks_routes.py(16 GREEN-LOCK,§ T7 + P0+ adversarial)。
"""
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["daily-tasks"])

_DATETIME = None
_TIMEDELTA = None
_TODAY_DATE_STR = None
_READ_TASKS = None
_LOAD_IMAGE_MAP = None
_SAVE_IMAGE_MAP = None
_LOAD_META_MAP = None
_SAVE_META_MAP = None
_META_STATE = None
_ENSURE_PROGRESS = None
_WRITABLE_DATES = None
_LOGGER = None
_BUMP_INTAKE = None
_SET_MD_CHECKBOX = None
_FIND_JOURNAL = None
_SCHEDULE_TEMPLATE_PATH = None
_APPLY_TASK_OP = None
_PLATFORM_ROOT = None
_TOP_SECTION_BOUNDS = None
_GET_PROCESSED_ATTACHMENT = None
_TASK_IMAGES_DIR = None
_PRETTY_REL = None
_WATER_CUP_KEY = None


@router.post("/api/template/task")
async def template_task(req: Request):
    """同时维护任务真源与今天日记。"""
    body = await req.json()
    action = body.get("action", "")
    text = (body.get("text") or "").strip()
    old_text = (body.get("old_text") or "").strip()
    if action not in ("add", "edit", "del"):
        raise HTTPException(400, "action must be add | edit | del")

    targets = []
    template_path = _SCHEDULE_TEMPLATE_PATH()
    if template_path.exists():
        targets.append(template_path)
    today_file = _FIND_JOURNAL()
    if today_file:
        targets.append(today_file)
    results = [
        _APPLY_TASK_OP(path, action, text, old_text)
        for path in targets
    ]
    return {"ok": True, "results": results}


def configure_effects(
    *,
    datetime_provider,
    timedelta_provider,
    today_date_str,
    read_tasks,
    load_image_map,
    save_image_map,
    load_meta_map,
    save_meta_map,
    meta_state,
    ensure_progress,
    writable_dates,
    logger,
    bump_intake,
    set_md_checkbox,
    find_journal,
    schedule_template_path,
    apply_task_op,
    platform_root,
    top_section_bounds,
    get_processed_attachment,
    task_images_dir,
    pretty_rel,
    water_cup_key,
) -> None:
    global _DATETIME, _TIMEDELTA, _TODAY_DATE_STR, _READ_TASKS
    global _LOAD_IMAGE_MAP, _SAVE_IMAGE_MAP, _LOAD_META_MAP, _SAVE_META_MAP
    global _META_STATE, _ENSURE_PROGRESS, _WRITABLE_DATES, _LOGGER
    global _BUMP_INTAKE, _SET_MD_CHECKBOX, _FIND_JOURNAL
    global _SCHEDULE_TEMPLATE_PATH, _APPLY_TASK_OP, _PLATFORM_ROOT
    global _TOP_SECTION_BOUNDS, _GET_PROCESSED_ATTACHMENT
    global _TASK_IMAGES_DIR, _PRETTY_REL, _WATER_CUP_KEY
    _DATETIME = datetime_provider
    _TIMEDELTA = timedelta_provider
    _TODAY_DATE_STR = today_date_str
    _READ_TASKS = read_tasks
    _LOAD_IMAGE_MAP = load_image_map
    _SAVE_IMAGE_MAP = save_image_map
    _LOAD_META_MAP = load_meta_map
    _SAVE_META_MAP = save_meta_map
    _META_STATE = meta_state
    _ENSURE_PROGRESS = ensure_progress
    _WRITABLE_DATES = writable_dates
    _LOGGER = logger
    _BUMP_INTAKE = bump_intake
    _SET_MD_CHECKBOX = set_md_checkbox
    _FIND_JOURNAL = find_journal
    _SCHEDULE_TEMPLATE_PATH = schedule_template_path
    _APPLY_TASK_OP = apply_task_op
    _PLATFORM_ROOT = platform_root
    _TOP_SECTION_BOUNDS = top_section_bounds
    _GET_PROCESSED_ATTACHMENT = get_processed_attachment
    _TASK_IMAGES_DIR = task_images_dir
    _PRETTY_REL = pretty_rel
    _WATER_CUP_KEY = water_cup_key

# ── GET /api/daily-tasks — 清单 + 图 + 剂量/库存 ──────────────────────
@router.get("/api/daily-tasks")
def daily_tasks_catalog(date: str = ""):
    """返指定日 daily-task 清单 + 每个 task 的 image url + meta(剂量/库存)。
    date 缺省 = 今天;date=YYYY-MM-DD 看历史(read-only,不会触发 md 同步)。
    """
    datetime = _DATETIME()
    target = None
    is_today = True
    if date:
        try:
            target = datetime.strptime(date, "%Y-%m-%d")
            is_today = (date == _TODAY_DATE_STR())
        except ValueError:
            raise HTTPException(400, f"bad date: {date}")
    # 读 md(指定日 / 今天)
    tasks = _READ_TASKS(target_date=target)
    image_map = _LOAD_IMAGE_MAP()
    meta_map = _LOAD_META_MAP()
    for t in tasks:
        rel = image_map.get(t["name"])
        t["image_url"] = f"/{rel}" if rel else None
        state = _META_STATE(t["name"], meta_map, target_date=target)
        t.update(state)
        # 只对"今天"做 md 子 box 同步(历史已经 backfill 过,且只读)
        if is_today and state["daily_dose"] > 1:
            try:
                _ENSURE_PROGRESS(t["name"], state["daily_dose"], state["today_intake"])
            except Exception as e:
                _LOGGER().warning(f"ensure md children for '{t['name']}' failed: {e}")
    # is_writable: 今天总可写;过去看 _writable_dates_set(次日 12:00 前补昨天)
    resolved_date = date or _TODAY_DATE_STR()
    is_writable = resolved_date in _WRITABLE_DATES()
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
    datetime = _DATETIME()
    body = await req.json()
    name = (body.get("task_name") or "").strip()
    if not name:
        raise HTTPException(400, "need task_name")

    # 补卡日期解析。缺省 = 今天;有 date 字段就走窗口验证。
    date_arg = (body.get("date") or "").strip()
    for_date = None
    if date_arg:
        if date_arg not in _WRITABLE_DATES():
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
            mm = _LOAD_META_MAP()
            if name not in mm or "daily_dose" not in (mm.get(name) or {}):
                ent = dict(mm.get(name) or {})
                ent["daily_dose"] = init_dose
                mm[name] = ent
                _SAVE_META_MAP(mm)
        except (TypeError, ValueError):
            pass

    if "intake" in body:
        state = _BUMP_INTAKE(name, set_to=int(body["intake"]), for_date=for_date)
    elif "increment" in body:
        state = _BUMP_INTAKE(name, delta=int(body["increment"]), for_date=for_date)
    else:
        # 兼容旧:checked=true → 置满 daily_dose;false → 置 0
        # ★复审 B4:DSML/synth 路径 checked 会是字符串 "false" → bool("false")==True → 反转
        #   (取消勾选反而勾上)。显式判真值。mobile-api.js 同步。
        _ck = body.get("checked")
        checked_flag = (_ck is True) or (str(_ck).strip().lower() == "true")
        meta_map = _LOAD_META_MAP()
        cur = _META_STATE(name, meta_map, target_date=for_date)
        target = cur["daily_dose"] if checked_flag else 0
        state = _BUMP_INTAKE(name, set_to=target, for_date=for_date)

    md_checked = state["today_intake"] >= state["daily_dose"]
    if not _SET_MD_CHECKBOX(name, md_checked, target_date=for_date):
        # md 没找到也不报错 — 可能 task 在 daily-tasks.md 但当日 file 顶部还未刷
        _LOGGER().info(f"check: md row '{name}' not found in {date_arg or 'today'} (meta updated only)")
    # daily_dose>1:同步进度子 box(前 K 个 [x],其余 [ ])
    if state["daily_dose"] > 1:
        try:
            _ENSURE_PROGRESS(name, state["daily_dose"], state["today_intake"],
                             target_date=for_date)
        except Exception as e:
            _LOGGER().warning(f"ensure md children for '{name}' failed: {e}")
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
    body = await req.json()
    name = (body.get("task_name") or "").strip()
    if not name:
        raise HTTPException(400, "need task_name")
    meta_map = _LOAD_META_MAP()
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
    _SAVE_META_MAP(meta_map)
    return {"ok": True, "task_name": name, **_META_STATE(name, meta_map)}


# ── POST /api/daily-tasks/backfill-progress — 历史子 box 回填 ─────────
@router.post("/api/daily-tasks/backfill-progress")
def daily_task_backfill_progress():
    """扫所有 task 的 intake_log,把每一天对应的 md 顶部段也展成 N 个进度子 box。
    幂等可重跑。只动 daily_dose > 1 的 task。
    """
    datetime = _DATETIME()
    meta_map = _LOAD_META_MAP()
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
            day_f = _FIND_JOURNAL(d)
            if not day_f:
                skipped_no_file.append({"task": name, "date": date_str})
                continue
            try:
                changed = _ENSURE_PROGRESS(
                    name, daily_dose, int(intake or 0), target_date=d
                )
                if changed:
                    touched.append({"task": name, "date": date_str, "intake": int(intake or 0), "dose": daily_dose})
            except Exception as e:
                _LOGGER().warning(f"backfill {name} {date_str}: {e}")
    return {"ok": True, "touched": touched, "touched_count": len(touched), "skipped_no_file": skipped_no_file}


# ── POST /api/daily-tasks/delete — 删补剂(md 双写 + image + meta)─────
@router.post("/api/daily-tasks/delete")
async def daily_task_delete(req: Request):
    """删除一个补剂:从 daily-tasks.md + 今天 md + image map + meta map 全部清掉。
    body: {task_name}
    """
    body = await req.json()
    name = (body.get("task_name") or "").strip()
    if not name:
        raise HTTPException(400, "need task_name")

    # 1. 从 md 真相源 + 今天文件删行
    targets = []
    schedule_template_path = _SCHEDULE_TEMPLATE_PATH()
    if schedule_template_path.exists():
        targets.append(schedule_template_path)
    today_f = _FIND_JOURNAL()
    if today_f:
        targets.append(today_f)
    md_results = [_APPLY_TASK_OP(f, "del", "", name) for f in targets]

    # 2. 删图 + image map
    image_map = _LOAD_IMAGE_MAP()
    rel = image_map.pop(name, None)
    if rel:
        try:
            (_PLATFORM_ROOT() / rel).unlink(missing_ok=True)
        except Exception as e:
            _LOGGER().warning(f"delete image {rel} failed: {e}")
        _SAVE_IMAGE_MAP(image_map)

    # 3. 删 meta
    meta_map = _LOAD_META_MAP()
    if name in meta_map:
        meta_map.pop(name, None)
        _SAVE_META_MAP(meta_map)

    return {"ok": True, "task_name": name, "md_results": md_results, "image_removed": bool(rel)}


# ── GET /api/daily-tasks/history — 最近 N 天 check 状态 ───────────────
@router.get("/api/daily-tasks/history")
def daily_task_history(name: str, days: int = 14):
    """返回 task 在最近 N 天的 check 状态。给大图 modal 显示历史 streak 用。"""
    import re
    if not name:
        raise HTTPException(400, "need name query param")
    days = max(1, min(int(days), 60))
    datetime = _DATETIME()
    timedelta = _TIMEDELTA()
    today = datetime.now()
    out = []
    for i in range(days):
        d = today - timedelta(days=i)
        f = _FIND_JOURNAL(d)
        entry = {"date": d.strftime("%Y-%m-%d"), "checked": None}
        if f:
            try:
                text = f.read_text(encoding="utf-8")
                bounds = _TOP_SECTION_BOUNDS(text)
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
    rel = _LOAD_IMAGE_MAP().get(_WATER_CUP_KEY())
    return {"image_url": f"/{rel}" if rel else None}


# ── POST /api/water-cup — 设水杯图(复用 cutout 流)──────────────────
@router.post("/api/water-cup")
async def water_cup_set(req: Request):
    """设水杯图。body: {attachment_url}。复用 cutout 流。"""
    body = await req.json()
    url = (body.get("attachment_url") or "").strip()
    if not url:
        raise HTTPException(400, "need attachment_url")
    processed, err = _GET_PROCESSED_ATTACHMENT(url)
    if err:
        raise HTTPException(400, err)
    task_images_dir = _TASK_IMAGES_DIR()
    task_images_dir.mkdir(parents=True, exist_ok=True)
    out = task_images_dir / "_water_cup.png"
    out.write_bytes(processed.read_bytes())
    rel = _PRETTY_REL(out)
    image_map = _LOAD_IMAGE_MAP()
    image_map[_WATER_CUP_KEY()] = rel
    _SAVE_IMAGE_MAP(image_map)
    return {"ok": True, "image_url": f"/{rel}"}
