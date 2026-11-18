# PATTERN: util — daily-task io-map (meta) + MD 进度双向同步,从 god module 抽出
# USE WHEN: daily-task 打卡状态(剂量/库存/intake_log)读写、MD checkbox/进度子行同步改动
# COPY THIS: 无 — 本模块是 server.py §14(清册01)的搬迁体,契约在 server re-export
#
# 抽出记录(2026-07-22, 清册01-§14,Parallel Change expand):
# - 原址 server.py(拆前 §13 记录之后行号)L1357–1612(_sanitize_task_filename..WATER_CUP_KEY,
#   中间夹着的 _load_task_image_map/_save_task_image_map/_save_task_meta_map/_today_date_str/
#   _writable_dates_set 不属于§14 anchor list,原样留 server.py,分段 cut)。
# - 跨模块引用由组装根以 8 个命名 provider 注入，保留 call-time patch 语义。
#   T10 tripwire(tests/test_daily_tasks_routes.py)monkeypatch.setattr(server,
#   "_report_silent_failure", ...) 依赖这条 call-time resolve,顶层 import 会漏接。
# - _load_task_meta_map / _save_task_meta_map / _load_task_image_map / _save_task_image_map
#   四个 io-map helper 中，只有 _load_task_meta_map 属§14；其余三个 T11 tripwire 明确要求
#   与 _audit_vault/_repair_vault 共享同一权威定义 → 原样留 server.py，本模块经 S 调用。
import json
import re

_META_PATH = None
_REPORT_FAILURE = None
_SAVE_META = None
_TODAY_DATE = None
_FIND_JOURNAL = None
_TEMPLATE_PATH = None
_TOP_SECTION_BOUNDS = None
_WRITE_TEXT = None


def configure_effects(
    *,
    meta_path,
    report_failure,
    save_meta,
    today_date,
    find_journal,
    template_path,
    top_section_bounds,
    write_text,
) -> None:
    global _META_PATH, _REPORT_FAILURE, _SAVE_META, _TODAY_DATE
    global _FIND_JOURNAL, _TEMPLATE_PATH, _TOP_SECTION_BOUNDS, _WRITE_TEXT
    _META_PATH = meta_path
    _REPORT_FAILURE = report_failure
    _SAVE_META = save_meta
    _TODAY_DATE = today_date
    _FIND_JOURNAL = find_journal
    _TEMPLATE_PATH = template_path
    _TOP_SECTION_BOUNDS = top_section_bounds
    _WRITE_TEXT = write_text


def _sanitize_task_filename(name: str) -> str:
    """task name → 文件名安全的 stem。'维生素（每日）' → '维生素_每日_'"""
    safe = re.sub(r"[^\w一-鿿]+", "_", name).strip("_")
    return safe or "task"


def _load_task_meta_map() -> dict:
    meta_path = _META_PATH()
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as e:
        # P0:同上 — intake_log 不可再生数据,parse 失败要响铃
        _REPORT_FAILURE("task_meta_map_parse_failed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"file_size_kb": meta_path.stat().st_size // 1024 if meta_path.exists() else 0})
        return {}


def _task_meta_state(name: str, meta_map: dict, target_date=None) -> dict:
    """单 task 的剂量/库存状态。无 meta 返默认。
    target_date=None → 今天 intake;target_date=datetime → 该日 intake。
    """
    m = meta_map.get(name) or {}
    total_pills = m.get("total_pills")  # int | None
    daily_dose = int(m.get("daily_dose") or 1)
    if daily_dose < 1:
        daily_dose = 1
    intake_log = m.get("intake_log") or {}
    date_key = (target_date.strftime("%Y-%m-%d") if target_date is not None
                else _TODAY_DATE())
    today_intake = int(intake_log.get(date_key, 0) or 0)
    consumed = sum(int(v or 0) for v in intake_log.values())
    remaining = (total_pills - consumed) if isinstance(total_pills, int) else None
    return {
        "total_pills": total_pills,
        "daily_dose": daily_dose,
        "today_intake": today_intake,
        "remaining": remaining,
    }


def _bump_intake(name: str, delta: int = 1, set_to=None, for_date=None) -> dict:
    """改 intake_log[date_key]。delta 累加,set_to 直接置数(优先 set_to)。
    for_date=None → 今天;datetime → 该日。补卡窗口管控在 caller(_writable_dates_set)。
    返回该日的 meta state。
    """
    meta_map = _load_task_meta_map()
    entry = dict(meta_map.get(name) or {})
    daily_dose = int(entry.get("daily_dose") or 1)
    if daily_dose < 1:
        daily_dose = 1
    intake_log = dict(entry.get("intake_log") or {})
    date_key = (for_date.strftime("%Y-%m-%d") if for_date is not None
                else _TODAY_DATE())
    cur = int(intake_log.get(date_key, 0) or 0)
    if set_to is not None:
        new = max(0, int(set_to))
    else:
        new = cur + int(delta)
    new = max(0, min(new, daily_dose))
    if new == 0:
        intake_log.pop(date_key, None)
    else:
        intake_log[date_key] = new
    entry["daily_dose"] = daily_dose
    entry["intake_log"] = intake_log
    meta_map[name] = entry
    _SAVE_META(meta_map)
    return _task_meta_state(name, meta_map, target_date=for_date)


def _read_daily_tasks_from_md(target_date=None) -> list:
    """从指定日 md 顶部读 daily task 清单 (- [ ] xxx 行,任意 checkbox 状态)。
    target_date=None → 今天(没今天 fallback 模板)。
    target_date=datetime → 该日;没文件返 []。
    返 [{name, checked}, ...]
    """
    if target_date is not None:
        f = _FIND_JOURNAL(target_date)
        if not f:
            return []
        text = f.read_text(encoding="utf-8")
    else:
        f = _FIND_JOURNAL()
        if not f:
            template_path = _TEMPLATE_PATH()
            tpl = template_path if template_path.exists() else None
            if not tpl:
                return []
            text = tpl.read_text(encoding="utf-8")
        else:
            text = f.read_text(encoding="utf-8")
    bounds = _TOP_SECTION_BOUNDS(text)
    if bounds is None:
        return []
    start, end = bounds
    out = []
    for line in text.splitlines()[start:end]:
        # 只取顶层(无缩进)task。daily_dose>1 的 task 下挂的子 box 是进度刻度,不算独立 task。
        m = re.match(r"^-\s*\[([ x])\]\s*(.+)", line)
        if m:
            out.append({"name": m.group(2).strip(), "checked": m.group(1) == "x"})
    return out


def _ensure_md_progress_children(name: str, daily_dose: int, today_intake: int,
                                  target_date=None) -> bool:
    """daily_dose > 1 的 task,把 md 顶部该行下面挂 N 个进度子 box,前 today_intake 个 [x],其余 [ ]。
    幂等。
    target_date=None(默认):同时刷模板源 + 今天文件。
    target_date=datetime:只刷该日期对应的 md(用于历史回填,不动模板)。
    daily_dose <= 1 不做(单行就够,展开反而碍眼)。
    """
    if daily_dose < 2:
        return False
    changed = False
    targets = []
    if target_date is None:
        template_path = _TEMPLATE_PATH()
        if template_path.exists():
            targets.append(template_path)
        today_f = _FIND_JOURNAL()
        if today_f and today_f not in targets:
            targets.append(today_f)
    else:
        day_f = _FIND_JOURNAL(target_date)
        if day_f:
            targets.append(day_f)
    for f in targets:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        bounds = _TOP_SECTION_BOUNDS(text)
        if not bounds:
            continue
        lines = text.splitlines()
        start, end = bounds
        # 找父行(顶层 only)
        parent_idx = None
        for i in range(start, end):
            m = re.match(r"^(-\s*\[)([ x])(\]\s*)(.+)$", lines[i])
            if m and m.group(4).strip() == name:
                parent_idx = i
                parent_m = m
                break
        if parent_idx is None:
            continue
        # 数已挂的子 box(紧随父行的缩进 - [ ] 行)
        child_end = parent_idx + 1
        while child_end < end and re.match(r"^\s+-\s*\[[ x]\]", lines[child_end]):
            child_end += 1
        # 目标:N 个子 box,前 K 个 [x],其余 [ ];父行根据"是否全勾"翻
        clamp_intake = max(0, min(today_intake, daily_dose))
        desired_children = [
            f"  - [{'x' if k <= clamp_intake else ' '}] {k}"
            for k in range(1, daily_dose + 1)
        ]
        parent_box = "x" if clamp_intake >= daily_dose else " "
        new_parent = f"{parent_m.group(1)}{parent_box}{parent_m.group(3)}{parent_m.group(4)}"
        existing_children = lines[parent_idx + 1:child_end]
        if lines[parent_idx] == new_parent and existing_children == desired_children:
            continue  # 已经 in sync
        new_lines = (
            lines[:parent_idx]
            + [new_parent]
            + desired_children
            + lines[child_end:]
        )
        _WRITE_TEXT(
            f,
            "\n".join(new_lines) + ("\n" if text.endswith("\n") else ""),
            rotate=True,
        )
        changed = True
    return changed


def _set_md_checkbox(name: str, checked: bool, target_date=None) -> bool:
    """改 md 顶部 - [ ] / - [x]。找到返 True;没找到 False(不抛)。
    target_date=None → 今天;datetime → 该日(补卡用)。"""
    f = _FIND_JOURNAL(target_date) if target_date is not None else _FIND_JOURNAL()
    if not f:
        return False
    text = f.read_text(encoding="utf-8")
    bounds = _TOP_SECTION_BOUNDS(text)
    if not bounds:
        return False
    lines = text.splitlines()
    start, end = bounds
    box = "x" if checked else " "
    for i in range(start, end):
        m = re.match(r"(\s*-\s*\[)([ x])(\]\s*)(.+)", lines[i])
        if m and m.group(4).strip() == name:
            if m.group(2) == box:
                return True  # 已经是这个状态,no-op
            lines[i] = f"{m.group(1)}{box}{m.group(3)}{m.group(4)}"
            new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
            _WRITE_TEXT(f, new_text, rotate=True)
            return True
    return False


# ── water cup image (8 杯水的个人化照片,跟 daily-task 共用 cutout 流) ──
WATER_CUP_KEY = "__water_cup__"  # 在 daily-task-images.json 里的保留 key
