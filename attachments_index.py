# PATTERN: util — attachments index + curator prompt extracted from god module (Parallel Change)
# USE WHEN: 附件 _index.json 读写 / sha256 去重 / curator system prompt 相关改动
# COPY THIS: 无 — 本模块是 server.py §11(清册01)的搬迁体,契约在 server re-export
#
# 抽出记录(2026-07-21, 清册01-§11 第三刀):
# - 原址 server.py L2567–2727(拆前行号);server.py 保留同名 re-export(Parallel Change
#   expand 阶段),caller(chat_routes/image_routes/pulse_eval/scripts 的 lazy
#   `from server import`)与测试 monkeypatch.setattr(server, "ATTACHMENTS_INDEX", ...) /
#   capture-golden.py 的 `server.X = ...` 直赋 一字不改。
# - 路径、锁、OCR、写入和告警通过窄参数注入；server 保留调用时适配器。
import json
import re
import threading as _threading


_ATTACHMENT_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_ai_visible_attachment(item) -> bool:
    """True only for originals that belong in AI-facing photo history.

    Cutout files remain ordinary local render assets for scrapbook/task UI.  They
    are derived from an original, however, so indexing them as another photo
    doubles the AI's history and search results.
    """
    if not isinstance(item, dict):
        return False
    if item.get("asset_role") == "derived":
        return False
    filename = str(item.get("filename") or item.get("original") or "").lower()
    return not filename.endswith(".cutout.png")


def _usable_vision(value) -> bool:
    """True when a legacy/current vision payload already makes the photo searchable."""
    if not isinstance(value, dict):
        return False
    return any(str(value.get(k) or "").strip() for k in (
        "description", "kind", "brand", "ocr_text", "ocr",
    ))


def _reconcile_existing_attachments(
    *,
    attachments_dir,
    allowed_extensions,
    lock,
    load_index,
    save_index,
    rebuild_prompt,
) -> dict:
    """Register app-owned legacy photos and durably queue missing semantic indexes.

    This is intentionally local-only: it scans the app attachment root, never the
    device photo library, and never calls a model.  The bounded retry worker drains
    ``vision_pending`` separately so an upgrade cannot create an unbounded bill.
    """
    stats = {"discovered": 0, "registered": 0, "updated": 0, "queued": 0}
    allowed = {str(ext).lower().lstrip(".") for ext in allowed_extensions}
    physical = []
    if attachments_dir.exists():
        for day_dir in sorted(attachments_dir.iterdir()):
            if (not day_dir.is_dir() or day_dir.is_symlink()
                    or not _ATTACHMENT_DAY_RE.fullmatch(day_dir.name)):
                continue
            for file in sorted(day_dir.iterdir()):
                ext = file.suffix.lower().lstrip(".")
                if (not file.is_file() or file.is_symlink() or ext not in allowed
                        or file.name.lower().endswith(".cutout.png")):
                    continue
                physical.append((day_dir.name, file.name, file.stat().st_size))
    stats["discovered"] = len(physical)

    with lock:
        loaded_items = load_index()
        items = [item for item in loaded_items if is_ai_visible_attachment(item)]
        by_key = {
            (item.get("date"), item.get("filename")): item
            for item in items if isinstance(item, dict)
        }
        # Remove legacy derived records from the AI index, never their render files.
        dirty = len(items) != len(loaded_items)
        for date, filename, size in physical:
            key = (date, filename)
            item = by_key.get(key)
            existed = item is not None
            if item is None:
                item = {"date": date, "filename": filename}
                items.append(item)
                by_key[key] = item
                stats["registered"] += 1
                dirty = True

            before = dict(item)
            item.setdefault("url", f"/attachments/{date}/{filename}")
            item.setdefault("original", filename)
            item.setdefault("size", size)

            # WebView/RN-era indexes used vision_result.  Normalize it without
            # deleting the legacy field so rollback builds still understand it.
            legacy = item.get("vision_result")
            current = item.get("vision")
            if _usable_vision(legacy) and not _usable_vision(current):
                item["vision"] = dict(legacy)
                current = item["vision"]
            if _usable_vision(current):
                if item.get("vision_pending"):
                    item["vision_pending"] = False
            elif not item.get("vision_pending"):
                item["vision_pending"] = True
                stats["queued"] += 1

            if item != before:
                if existed:
                    stats["updated"] += 1
                dirty = True

        if dirty:
            save_index(items)
            rebuild_prompt()
    return stats


def _load_attachments_index(*, index_path, report_failure) -> list:
    if not index_path.exists():
        return []
    try:
        return json.loads(index_path.read_text(encoding="utf-8"))
    except Exception as e:
        report_failure("attachments_index_parse_failed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"file_size_kb": index_path.stat().st_size // 1024})
        return []


def _save_attachments_index(arr: list, *, index_path, write_text):
    # A-H1: atomic + rotate;BackgroundTasks 跟 _index_upsert 是已知并发路径
    write_text(
        index_path,
        json.dumps(arr, indent=2, ensure_ascii=False),
        rotate=True,
    )


# ── Curator system prompt 重建 ──────────────────────────────────────
# 月分块 + 老月在前 = DeepSeek implicit prefix cache 友好。
# 加 1 张新图只 invalidate 当月段以后(几乎全部历史月份 hit)。
# 行格式 CSV-like 压缩(~30 token/张 vs JSON ~100):date|stem|kind|desc

def _format_curator_line(x: dict) -> str:
    date = x.get("date", "")
    fn = x.get("filename", "")
    stem = fn.rsplit(".", 1)[0] if "." in fn else fn
    v = x.get("vision") or {}
    kind = (v.get("kind", "") or "?").replace("|", " ")
    desc = (v.get("description", "") or "").replace("\n", " ").replace("|", " ")[:80]
    # 没 vision 时 ocr 兜 — curator 找截图里的字也需要
    if not desc:
        ocr = (x.get("ocr_text", "") or "").replace("\n", " ").replace("|", " ")[:40]
        if ocr:
            desc = f"ocr:{ocr}"
    return f"{date}|{stem}|{kind}|{desc}"


def _rebuild_curator_system_prompt(
    *,
    load_index,
    format_line,
    prompt_path,
    write_text,
    report_failure,
):
    """读全部索引 → 按 YYYY-MM 分块 (老月在前) → 写 frozen system prompt 文件。
    在 _index_upsert 里调一次 (upload / vision 完成时)。chat 时只读文件,不重建。
    """
    arr = [item for item in load_index() if is_ai_visible_attachment(item)]
    by_month: dict = {}
    for x in arr:
        m = (x.get("date", "") or "")[:7]
        if not m:
            continue
        by_month.setdefault(m, []).append(x)

    lines = [
        "你是相册管理员 (curator)。下面是用户全部照片元数据,每行格式:",
        "date | filename_stem | kind | description",
        "",
        "任务: 用户问什么,你只返匹配的 stem 列表,date 拼接成 'YYYY-MM-DD/stem'。",
        '严格 JSON: {"matches":["2026-05-16/115227-6002ea", ...],"total":N,"note":""}',
        "结果 > 15 时按时间倒序截到 15,note 写 'truncated, total=N'。无匹配返 matches=[]。",
        "不解释。不复述描述。不评论。**仅 JSON**。",
        "",
        "跨 terminology 推理: 用户可能用自起的昵称指宠物/物品(比如把自家狗叫'豆豆'),'狗'='豆豆'这类等价要从 description 推出来。",
        "",
    ]
    for month in sorted(by_month.keys()):  # 老在前 = cache 友好
        photos = sorted(by_month[month], key=lambda x: (x.get("date", ""), x.get("filename", "")))
        lines.append(f"--- {month} ({len(photos)} 张) ---")
        for x in photos:
            lines.append(format_line(x))
        lines.append("")
    txt = "\n".join(lines)
    try:
        # A-H1: curator prompt 可重建,rotate=False(节省 IO)
        write_text(prompt_path, txt, rotate=False)
    except Exception as e:
        report_failure("curator_system_rebuild_failed",
            f"{type(e).__name__}: {str(e)[:120]}",
            context={"entries": len(arr)})


# Lock + upsert 化解 race:后台 OCR task 和 chat 触发的 vision call 都要写索引,
# 各自 load → mutate → save 会互相覆盖(后写的赢)— 现象:OCR 覆盖了 vision,
# 或反过来。upsert 只 merge 显式传的字段,不动其他;lock 串行化 read-modify-write。
_attachments_index_lock = _threading.Lock()


def _find_by_hash(sha256_hex: str, *, load_index):
    """同字节 upload 去重的关键:扫 index 查 hash。命中返既有 record,没命中返 None。
    O(N) 扫;index 体量 < 几百条,无需建额外索引。
    """
    if not sha256_hex:
        return None
    for x in load_index():
        if is_ai_visible_attachment(x) and x.get("hash") == sha256_hex:
            return x
    return None


def _index_upsert(
    date: str,
    filename: str,
    *,
    lock,
    load_index,
    save_index,
    rebuild_prompt,
    **fields,
):
    """Find-or-create by (date, filename),只 merge 传进来的字段;不动其余。
    在 lock 下做完整 read-modify-write 防并发覆盖。
    """
    with lock:
        arr = load_index()
        idx = next((i for i, x in enumerate(arr)
                    if x.get("date") == date and x.get("filename") == filename), -1)
        if idx < 0:
            arr.append({"date": date, "filename": filename, **fields})
        else:
            arr[idx].update(fields)
        save_index(arr)
        # 同步刷新 curator system prompt — 几 ms 字符串拼接,值得为 cache 友好换
        rebuild_prompt()


def _index_attachment(
    date: str,
    filename: str,
    original: str,
    size: int,
    sha256_hex: str = "",
    *,
    attachments_dir,
    ocr_text,
    logger,
    upsert,
):
    """后台跑 OCR + 写索引。失败也不抛(索引降级)。
    vision 分类不在这里跑(成本考虑):upload 即跑 vision 对"上传多但不讨论"
    场景白花钱。lazy 策略 — chat 时 _refs_to_vision_hints 现场 sync call 一次
    + 回写索引,后续命中 cache。
    sha256_hex 由 upload 入口算好传进来,用于后续 _find_by_hash 同字节去重。
    """
    f = attachments_dir / date / filename
    try:
        ocr_result = ocr_text(f)
    except Exception as e:
        logger.warning(f"index OCR failed for {filename}: {e}")
        ocr_result = ""
    fields = {
        "original": original,
        "size": size,
        "ocr_text": ocr_result[:2000],
        "url": f"/attachments/{date}/{filename}",
    }
    if sha256_hex:
        fields["hash"] = sha256_hex
    # upsert 而非 append:若 vision call 先到、已建好 entry,这里只补 OCR / 元数据,
    # 不动已有的 vision 字段(原来 append + skip-if-exists 的逻辑碰上 race 会丢 vision)
    upsert(date, filename, **fields)
