# PATTERN: api — widget/journal/daily-task/scrapbook LLM tool 实现 extracted from god module (Parallel Change)
# USE WHEN: AI 写侧工具(widgets 增改/journal 插入/打卡/任务图标/scrapbook 落图)相关改动
# COPY THIS: 无 — 本模块是 server.py §6(清册01)的搬迁体,契约在 server re-export
#
# 抽出记录(2026-07-21, 清册01-§6,§9 解锁后第一段):
# - 原址 server.py L716–1128;server.py 保留同名 re-export(Parallel Change expand 阶段)。
# - widgets/journal/task/image/scrapbook 的路径与 I/O 由组装根以具名 provider 注入；
#   datetime 仍按 call-time 取值以保留测试时钟替换，模块自身 helper 直接调用。
# - 三条 LLM 行为疤(模糊匹配层)整段带走:_resolve_task_name 语义全名兜底 /
#   _pick_attachment_url 字段别名容错 / set_daily_task_image 模糊解析 task_name。
# - 跨端:RN services/{tools,supplements,widgets,journal}.ts 对应,契约由 toolSpecs 抓漂移。
import json
import re

from attachment_service import resolve_attachment_url
from image_service_errors import ImageServiceError


_USER_WIDGETS_PATH = None
_WIDGETS_DIR = None
_PRETTY_REL = None
_REPORT_FAILURE = None
_SAFE_WRITE_TEXT = None
_DATETIME = None
_FIND_TODAY_JOURNAL = None
_PATCH_BLOCK = None
_JOURNAL_FOR_DATE = None
_LIST_JOURNAL_FILES = None
_INSERT_BLOCK = None
_APPEND_COMMENT = None
_TOP_SECTION_BOUNDS = None
_GET_PROCESSED_ATTACHMENT = None
_DAILY_TASK_IMAGES_DIR = None
_WATER_CUP_KEY = None
_LOAD_TASK_IMAGE_MAP = None
_SAVE_TASK_IMAGE_MAP = None
_SANITIZE_TASK_FILENAME = None
_SCHEDULE_TEMPLATE_PATH = None
_APPLY_TASK_OP = None
_LOAD_TASK_META_MAP = None
_SAVE_TASK_META_MAP = None
_PLATFORM_ROOT = None
_ATTACHMENTS_DIR = None
_SCRAPBOOK_IMAGES_DIR = None
_SCRAPBOOK_ID = None
_LOAD_SCRAPBOOK = None
_SAVE_SCRAPBOOK = None
_SYNC_TAG_AGGREGATE = None
_DISCLOSE_UNKNOWN_TAGS = None


def configure_effects(
    *,
    user_widgets_path,
    widgets_dir,
    pretty_rel,
    report_failure,
    safe_write_text,
    datetime_provider,
    find_today_journal,
    patch_block,
    journal_for_date,
    list_journal_files,
    insert_block,
    append_comment,
    top_section_bounds,
    get_processed_attachment,
    daily_task_images_dir,
    water_cup_key,
    load_task_image_map,
    save_task_image_map,
    sanitize_task_filename,
    schedule_template_path,
    apply_task_op,
    load_task_meta_map,
    save_task_meta_map,
    platform_root,
    attachments_dir,
    scrapbook_images_dir,
    scrapbook_id,
    load_scrapbook,
    save_scrapbook,
    sync_tag_aggregate,
    disclose_unknown_tags,
) -> None:
    global _USER_WIDGETS_PATH, _WIDGETS_DIR, _PRETTY_REL, _REPORT_FAILURE
    global _SAFE_WRITE_TEXT, _DATETIME, _FIND_TODAY_JOURNAL, _PATCH_BLOCK
    global _JOURNAL_FOR_DATE, _LIST_JOURNAL_FILES, _INSERT_BLOCK, _APPEND_COMMENT
    global _TOP_SECTION_BOUNDS, _GET_PROCESSED_ATTACHMENT
    global _DAILY_TASK_IMAGES_DIR, _WATER_CUP_KEY
    global _LOAD_TASK_IMAGE_MAP, _SAVE_TASK_IMAGE_MAP, _SANITIZE_TASK_FILENAME
    global _SCHEDULE_TEMPLATE_PATH, _APPLY_TASK_OP
    global _LOAD_TASK_META_MAP, _SAVE_TASK_META_MAP, _PLATFORM_ROOT
    global _ATTACHMENTS_DIR, _SCRAPBOOK_IMAGES_DIR, _SCRAPBOOK_ID
    global _LOAD_SCRAPBOOK, _SAVE_SCRAPBOOK, _SYNC_TAG_AGGREGATE
    global _DISCLOSE_UNKNOWN_TAGS
    _USER_WIDGETS_PATH = user_widgets_path
    _WIDGETS_DIR = widgets_dir
    _PRETTY_REL = pretty_rel
    _REPORT_FAILURE = report_failure
    _SAFE_WRITE_TEXT = safe_write_text
    _DATETIME = datetime_provider
    _FIND_TODAY_JOURNAL = find_today_journal
    _PATCH_BLOCK = patch_block
    _JOURNAL_FOR_DATE = journal_for_date
    _LIST_JOURNAL_FILES = list_journal_files
    _INSERT_BLOCK = insert_block
    _APPEND_COMMENT = append_comment
    _TOP_SECTION_BOUNDS = top_section_bounds
    _GET_PROCESSED_ATTACHMENT = get_processed_attachment
    _DAILY_TASK_IMAGES_DIR = daily_task_images_dir
    _WATER_CUP_KEY = water_cup_key
    _LOAD_TASK_IMAGE_MAP = load_task_image_map
    _SAVE_TASK_IMAGE_MAP = save_task_image_map
    _SANITIZE_TASK_FILENAME = sanitize_task_filename
    _SCHEDULE_TEMPLATE_PATH = schedule_template_path
    _APPLY_TASK_OP = apply_task_op
    _LOAD_TASK_META_MAP = load_task_meta_map
    _SAVE_TASK_META_MAP = save_task_meta_map
    _PLATFORM_ROOT = platform_root
    _ATTACHMENTS_DIR = attachments_dir
    _SCRAPBOOK_IMAGES_DIR = scrapbook_images_dir
    _SCRAPBOOK_ID = scrapbook_id
    _LOAD_SCRAPBOOK = load_scrapbook
    _SAVE_SCRAPBOOK = save_scrapbook
    _SYNC_TAG_AGGREGATE = sync_tag_aggregate
    _DISCLOSE_UNKNOWN_TAGS = disclose_unknown_tags


def _tag_disclosure(tags):
    if not _DISCLOSE_UNKNOWN_TAGS:
        return None
    return _DISCLOSE_UNKNOWN_TAGS(tags)


def tool_list_widgets():
    user_widgets_path = _USER_WIDGETS_PATH()
    user_widgets = json.loads(user_widgets_path.read_text(encoding="utf-8")) if user_widgets_path.exists() else {}
    active = set(user_widgets.get("active", []))
    folders = []
    widgets_dir = _WIDGETS_DIR()
    if widgets_dir.exists():
        for d in sorted(widgets_dir.iterdir()):
            if d.is_dir() and (d / "manifest.json").exists():
                folders.append({"name": d.name, "active": d.name in active})
    return {"widgets": folders, "user_widgets_file": _PRETTY_REL(user_widgets_path)}

def _resolve_date_arg(date_arg: str):
    """统一 date 参数解析 + sanity 校验。
    无 date → today;格式错 / 未来 → error。超过 7 天的 AI 授权由 ActionPolicy
    使用可信 view_date / 用户原文判断，不能在领域层只看模型 args。
    返回 (datetime, error_str)。error_str 空表示通过。
    """
    today = _DATETIME().now()
    if not date_arg:
        return today, ""
    try:
        d = _DATETIME().strptime(date_arg.strip(), "%Y-%m-%d")
    except ValueError:
        return None, f"bad date format: {date_arg!r} (need YYYY-MM-DD)"
    delta_days = (today.date() - d.date()).days
    if delta_days < 0:
        return None, f"date {date_arg} 在未来,拒"
    return d, ""


def tool_patch_journal_block(args, *, enforce_tag_vocabulary=False):
    target, err = _resolve_date_arg((args.get("date") or "").strip())
    if err:
        return {"error": err}
    f = _FIND_TODAY_JOURNAL(target)
    if not f:
        return {"error": f"no journal file for {target.strftime('%Y-%m-%d')}"}
    if enforce_tag_vocabulary:
        from tag_vocabulary import h2_parent_tags
        disclosure = _tag_disclosure(h2_parent_tags(args.get("new_md") or ""))
        if disclosure:
            return disclosure
    out = _PATCH_BLOCK(f, args["time"], args["new_md"], author="ai",
                       allow_h2_rename=bool(args.get("allow_h2_rename", False)))
    if isinstance(out, dict) and "error" not in out:
        sync_result = _SYNC_TAG_AGGREGATE(f)
        if isinstance(sync_result, dict) and not sync_result.get("ok", True):
            out["aggregate_warning"] = sync_result.get("error", "标签索引同步失败，可稍后重建")
    return out

def tool_read_today_schedule(args):
    return _JOURNAL_FOR_DATE(args.get("date"))

def tool_list_recent_days(args):
    n = int(args.get("n") or 7)
    days = _LIST_JOURNAL_FILES()
    return {"days": days[-n:][::-1]}  # 倒序,最新在前

def tool_insert_journal_block(args, *, enforce_tag_vocabulary=False):
    time_str = (args.get("time") or "").strip()
    tag = (args.get("tag") or "").strip()
    title = (args.get("title") or "").strip()
    body = (args.get("body") or "").strip()
    # 参数卫生(对齐 RN adaptToolArgs,7.21 真机实锤:模型传 tag:"#算法"、title:"...@user"):
    # spec 明言 tag 不含 #;@user/@ai 是系统署名,写进 title/tag 会伪造 authorship。PC 是 oracle,两端行为必须一致。
    # 边界用 (?![A-Za-z0-9_]) 而非 \b:Python \b 把汉字算词字符,"中间@user嵌套的"
    # 这种中文紧贴场景不会剥;JS \b 只认 ASCII → RN 剥。反伪造语义下"剥"才对,
    # 且 RN 行为 7.21 真机验证过 —— PC 向 JS 语义靠齐(7.23 对拍抓的跨语言分叉)。
    _SIG = r"@(user|ai)(?![A-Za-z0-9_])"
    if tag:
        tag = re.sub(r"^#+", "", tag)
        tag = re.sub(_SIG, "", tag).strip()
    if title:
        title = re.sub(_SIG, "", title).strip()
    # 兜底:没指定 time 用当前半小时
    if not time_str:
        now = _DATETIME().now()
        time_str = f"{now.hour}:{0 if now.minute < 30 else 30:02d}"
    target, err = _resolve_date_arg((args.get("date") or "").strip())
    if err:
        return {"error": err}
    f = _FIND_TODAY_JOURNAL(target)
    if not f:
        return {"error": f"no journal file for {target.strftime('%Y-%m-%d')}"}
    if enforce_tag_vocabulary:
        disclosure = _tag_disclosure([tag])
        if disclosure:
            return disclosure
    out = _INSERT_BLOCK(f, time_str, tag=tag, title=title, author="ai", body=body)
    if isinstance(out, dict) and out.get("ok"):
        sync_result = _SYNC_TAG_AGGREGATE(f)
        if isinstance(sync_result, dict) and not sync_result.get("ok", True):
            out["aggregate_warning"] = sync_result.get("error", "标签索引同步失败，可稍后重建")
    # 钉子(兜旧习惯):标题-only 条目违反日记协议,在 tool result 里压模型立刻补正文
    if isinstance(out, dict) and out.get("ok") and not body:
        out["warning"] = ("⚠ 只写了标题没写正文,违反日记协议(每条 entry 必须有"
                          "result + significance 的散文)。请立即用 patch_journal_block 补上正文。")
    return out


def tool_append_journal_comment(args):
    """append-only AI 评论:在指定时间块 body 末尾 append 一段,**不动原 H2 / 原 body**。
    撞 @user 块时 patch_journal_block 会拒绝 → 用这个工具留评论"穿线/回看/AI 注"。"""
    time_str = (args.get("time") or "").strip()
    comment = (args.get("comment_md") or "").strip()
    if not time_str:
        return {"error": "need time HH:MM"}
    if not comment:
        return {"error": "need comment_md"}
    target, err = _resolve_date_arg((args.get("date") or "").strip())
    if err:
        return {"error": err}
    f = _FIND_TODAY_JOURNAL(target)
    if not f:
        return {"error": f"no journal file for {target.strftime('%Y-%m-%d')}"}
    return _APPEND_COMMENT(f, time_str, comment)


def _list_today_tasks():
    """读今天 md 顶部 - [ ] 行,返完整任务名列表 + 文件 + lines + bounds。
    供 _resolve_task_name 和 tool_check_daily_task 共用。"""
    f = _FIND_TODAY_JOURNAL()
    if not f:
        return None, None, None, None, "no today journal"
    text = f.read_text(encoding="utf-8")
    bounds = _TOP_SECTION_BOUNDS(text)
    if not bounds:
        return f, text, None, None, "no top section"
    lines = text.splitlines()
    tasks = []
    for i in range(bounds[0], bounds[1]):
        m = re.match(r"^(-\s*\[)([ x])(\]\s*)(.+)", lines[i])
        if m:
            tasks.append(m.group(4).strip())
    return f, text, lines, tasks, None

def _resolve_task_name(name):
    """模糊解析 daily-task 名 → 完整规范名。
    AI 实测倾向用'语义全名'省 suffix(如'维生素（某品牌）' 漏'，60粒装'),
    严格匹配会全失败。这里兜:子串包含(任一方向)唯一命中 → 用全名。多/无 → 报错带候选。
    返 (full_name, None) 或 (None, error_dict)。"""
    name = (name or "").strip()
    if not name:
        return None, {"error": "need task_name"}
    _, _, _, tasks, err = _list_today_tasks()
    if err:
        return None, {"error": err}
    if not tasks:
        return None, {"error": "no tasks in today's checklist"}
    # 1) 精确
    for t in tasks:
        if t == name:
            return t, None
    # 2) 子串(name in task 或 task in name) — 唯一命中算解析成功
    matches = [t for t in tasks if (name in t) or (t in name)]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, {"error": f"task '{name}' 模糊匹配多条,请用更精确名",
                      "candidates": matches}
    # 3) 归一化(去掉中英括号内容 + 去空格 + 小写)再比 —— 兜 AI 漏 suffix
    #    例:"维生素（某品牌）" vs "维生素（某品牌，60粒装）"
    #    步2 不命中(`）` vs `，` 卡),步3 归一化后两边都是"维生素某品牌" → 命中
    def _norm(s):
        return re.sub(r"[\(（][^\)）]*[\)）]", "", s or "").lower().replace(" ", "").strip()
    nn = _norm(name)
    if nn:
        nmatches = [t for t in tasks if _norm(t) == nn or nn in _norm(t) or _norm(t) in nn]
        if len(nmatches) == 1:
            return nmatches[0], None
        if len(nmatches) > 1:
            return None, {"error": f"task '{name}' 归一化后多条,请用更精确名",
                          "candidates": nmatches}
    return None, {"error": f"task '{name}' 不在今天的清单里", "candidates": tasks}


def tool_check_daily_task(args):
    """打卡。task_name 支持模糊匹配——传短名/缺 suffix 也能定位到全名行。"""
    full, err = _resolve_task_name(args.get("task_name"))
    if err:
        return err
    checked = bool(args.get("checked"))
    f, text, lines, _, lerr = _list_today_tasks()
    if lerr:
        return {"error": lerr}
    box = "x" if checked else " "
    for i in range(*_TOP_SECTION_BOUNDS(text)):
        m = re.match(r"^(-\s*\[)([ x])(\]\s*)(.+)", lines[i])
        if m and m.group(4).strip() == full:
            lines[i] = f"{m.group(1)}{box}{m.group(3)}{m.group(4)}"
            new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
            _SAFE_WRITE_TEXT(f, new_text, rotate=True)
            return {"ok": True, "task_name": full, "checked": checked,
                    **({"resolved_from": args.get("task_name")} if args.get("task_name") != full else {})}
    return {"error": f"task '{full}' 解析后仍未找到对应行(罕见,可能 md 顶部刚改动)"}


def _pick_attachment_url(args):
    """容错:模型偶尔把 attachment_url 写成 image_path/url/image_url/path/attachment
    (5.27 实测 deepseek 用了 image_path → 整个 set_daily_task_image 失败)。都认,挑第一个非空。"""
    for k in ("attachment_url", "image_path", "image_url", "url", "attachment", "path"):
        v = args.get(k)
        if v and str(v).strip():
            return str(v).strip()
    return ""


def tool_set_water_cup_image(args):
    url = _pick_attachment_url(args)
    if not url:
        return {"error": "need attachment_url"}
    processed, err = _GET_PROCESSED_ATTACHMENT(url)
    if err:
        return {"error": err}
    daily_task_images_dir = _DAILY_TASK_IMAGES_DIR()
    daily_task_images_dir.mkdir(parents=True, exist_ok=True)
    out = daily_task_images_dir / "_water_cup.png"
    out.write_bytes(processed.read_bytes())
    rel = _PRETTY_REL(out)
    image_map = _LOAD_TASK_IMAGE_MAP()
    image_map[_WATER_CUP_KEY()] = rel
    _SAVE_TASK_IMAGE_MAP(image_map)
    return {"ok": True, "image_url": f"/{rel}"}


def tool_set_daily_task_image(args):
    url = _pick_attachment_url(args)
    if not url:
        return {"error": "need attachment_url (or image_path/url alias)"}
    # 模糊解析 task_name → 全名;否则 image_map 键跟任务行对不上,图标不显示(5.28 实测的坑)
    full, name_err = _resolve_task_name(args.get("task_name"))
    if name_err:
        return name_err
    processed, err = _GET_PROCESSED_ATTACHMENT(url)
    if err:
        return {"error": err}
    daily_task_images_dir = _DAILY_TASK_IMAGES_DIR()
    daily_task_images_dir.mkdir(parents=True, exist_ok=True)
    stem = _SANITIZE_TASK_FILENAME(full)
    out = daily_task_images_dir / f"{stem}.png"
    out.write_bytes(processed.read_bytes())
    rel = _PRETTY_REL(out)
    image_map = _LOAD_TASK_IMAGE_MAP()
    image_map[full] = rel
    _SAVE_TASK_IMAGE_MAP(image_map)
    return {"ok": True, "task_name": full, "image_url": f"/{rel}",
            **({"resolved_from": args.get("task_name")} if args.get("task_name") != full else {})}


def tool_manage_daily_task(args):
    action = args.get("action")
    if action not in ("add", "edit", "del"):
        return {"error": "action must be add|edit|del"}
    text = (args.get("text") or "").strip()
    old_text = (args.get("old_text") or "").strip()
    targets = []
    schedule_template_path = _SCHEDULE_TEMPLATE_PATH()
    if schedule_template_path.exists():
        targets.append(schedule_template_path)
    today_f = _FIND_TODAY_JOURNAL()
    if today_f:
        targets.append(today_f)
    md_results = [_APPLY_TASK_OP(f, action, text, old_text) for f in targets]

    # rename safety:edit / del 时把 meta + image map 的 key 一并迁移 / 清掉
    # 否则旧 key 变孤儿:intake history、图片、库存全失联
    side_effects = {}
    if action == "edit" and old_text and text and old_text != text and any(r.get("ok") for r in md_results):
        side_effects = _migrate_task_keys(old_text, text)
    elif action == "del" and old_text and any(r.get("ok") for r in md_results):
        side_effects = _purge_task_keys(old_text)

    return {"ok": True, "results": md_results, "side_effects": side_effects}


def _migrate_task_keys(old_name: str, new_name: str) -> dict:
    """edit 时把 daily-task-meta + daily-task-images 的 key 从 old 改 new。
    幂等:new key 已存在就保留 new、不覆盖。返做了什么。
    """
    out = {"meta_migrated": False, "image_migrated": False}
    try:
        meta = _LOAD_TASK_META_MAP()
        if old_name in meta and new_name not in meta:
            meta[new_name] = meta.pop(old_name)
            _SAVE_TASK_META_MAP(meta)
            out["meta_migrated"] = True
    except Exception as e:
        out["meta_error"] = str(e)
        # 改名后 intake_log 历史变孤儿,UI 看不出问题但数据断 — 必须响铃
        _REPORT_FAILURE("task_rename_meta_migrate_failed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"old": old_name[:40], "new": new_name[:40]})
    try:
        img_map = _LOAD_TASK_IMAGE_MAP()
        if old_name in img_map and new_name not in img_map:
            img_map[new_name] = img_map.pop(old_name)
            _SAVE_TASK_IMAGE_MAP(img_map)
            out["image_migrated"] = True
    except Exception as e:
        out["image_error"] = str(e)
        _REPORT_FAILURE("task_rename_image_migrate_failed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"old": old_name[:40], "new": new_name[:40]})
    return out


def _purge_task_keys(name: str) -> dict:
    """del 时清理 daily-task-meta + daily-task-images 的对应 key + 删图文件。
    跟现有 daily-tasks/delete 端点逻辑保持一致(单一真相)。
    """
    out = {"meta_purged": False, "image_purged": False, "image_file_removed": False}
    try:
        meta = _LOAD_TASK_META_MAP()
        if name in meta:
            del meta[name]
            _SAVE_TASK_META_MAP(meta)
            out["meta_purged"] = True
    except Exception as e:
        out["meta_error"] = str(e)
        _REPORT_FAILURE("task_delete_meta_purge_failed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"name": name[:40]})
    try:
        img_map = _LOAD_TASK_IMAGE_MAP()
        if name in img_map:
            rel = img_map.pop(name)
            _SAVE_TASK_IMAGE_MAP(img_map)
            out["image_purged"] = True
            try:
                p = _PLATFORM_ROOT() / rel
                if p.exists():
                    p.unlink()
                    out["image_file_removed"] = True
            except Exception:
                pass
    except Exception as e:
        out["image_error"] = str(e)
        _REPORT_FAILURE("task_delete_image_purge_failed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"name": name[:40]})
    return out


def tool_place_scrapbook_image(args):
    """AI 把照片 absolute 浮在 .page 之上(v3 自由位置)。失败返 {error}。"""
    import random
    url = _pick_attachment_url(args)
    date = (args.get("date") or "").strip()
    anchor_time = (args.get("anchor_time") or "").strip()
    # 新 schema:x_pct / y_px。容忍 legacy align/position 字段,转换。
    x_pct = args.get("x_pct")
    y_px = args.get("y_px")
    if x_pct is None:
        legacy_align = args.get("align") or args.get("position")
        x_pct = 3 if legacy_align == "left" else 75
    # auto_y 表示"AI 没指定纵坐标 → 由客户端按 anchor_time 算到对应 entry 旁边"。
    # 之前默认 y_px=0 + 注释说"前端会重算",但前端 applyPos 老老实实读 0,图就贴
    # 到了页面顶。补 auto_y 字段让 scrapbook.js 触发 computeYFromAnchor。
    auto_y = (y_px is None)
    if y_px is None:
        y_px = 0
    x_pct = max(0, min(95, float(x_pct)))
    y_px = max(0, float(y_px))
    do_cutout = args.get("cutout", True)
    rot = args.get("rotation")
    if rot is None:
        rot = round(random.uniform(-4, 4), 1)
    if not url or not date or not anchor_time:
        return {"error": "need attachment_url + date + anchor_time"}
    try:
        src_file = resolve_attachment_url(_ATTACHMENTS_DIR(), url)
    except ImageServiceError as exc:
        return {"error": exc.detail}

    scrapbook_images_dir = _SCRAPBOOK_IMAGES_DIR()
    scrapbook_images_dir.mkdir(parents=True, exist_ok=True)
    out_stem = f"{date}_{_SCRAPBOOK_ID()}"
    if do_cutout:
        # 把用户意图传下去 — 函数内部还会再 fallback 一次(无 key 直接返原图),
        # 这里 do_cutout=True 表"用户希望抠",有 key 才真抠,没 key 静默原图。
        processed, err = _GET_PROCESSED_ATTACHMENT(url, cutout=True)
        if err:
            return {"error": err + " (要不要 cutout=false 重试?)"}
        out_file = scrapbook_images_dir / f"{out_stem}.png"
        out_file.write_bytes(processed.read_bytes())
    else:
        ext = src_file.suffix or ".png"
        out_file = scrapbook_images_dir / f"{out_stem}{ext}"
        out_file.write_bytes(src_file.read_bytes())

    rel = "/" + _PRETTY_REL(out_file)

    items = _LOAD_SCRAPBOOK(date)
    item = {
        "id": _SCRAPBOOK_ID(),
        "src": rel,
        "cutout": bool(do_cutout),   # 渲染端据此去/留相框(抠图主体不套拍立得框)
        "anchor_time": anchor_time,
        "x_pct": x_pct,
        "y_px": y_px,
        "w": 220,
        "h": 220,
        "rotation": float(rot),
        "auto_y": auto_y,  # True → 客户端 render 时按 anchor_time 算 y;用户拖完后 upsert 会清掉
    }
    items.append(item)
    _SAVE_SCRAPBOOK(date, items)
    return {"ok": True, "item": item, "image_url": rel}
