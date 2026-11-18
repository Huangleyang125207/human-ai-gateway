# PATTERN: util — tag aggregate (标签聚合.md) parse/scan/refresh extracted from god module
# USE WHEN: 标签聚合解析、schedule 扫描、增量 append 逻辑改动
# COPY THIS: 无 — 本模块是 server.py §22(清册01)的搬迁体,契约在 server re-export
#
# 抽出记录(2026-07-21, 清册01-§22 第五刀,Parallel Change expand):
# - 原址 server.py L4297–4373 + L4467–4658(拆前行号,两个不相邻块);server.py 保留
#   同名 re-export,caller(journal_routes 的 lazy `from server import _refresh_tag_aggregate/
#   _parse_tag_aggregate`、server 内 widgets catalog 直用)一字不改。
# - 稳定解析符号留模块本地；路径/锁/写入由组装根以命名 provider 注入。
# - pre-mortem 命中点:test_pc_audit_parity.test_m10_refresh_rmw_under_lock 对
#   inspect.getsource 断言子串 `with _get_vault_md_lock` 且在 `.read_text` 之前 →
#   _refresh_tag_aggregate 内用局部别名保住该子串,别动。
import re
from collections import Counter
from pathlib import Path

import vault_git
from tag_vocabulary import META_LABELS

_JOURNAL_DIR = None
_AGGREGATE_PATH = None
_LOCK_FACTORY = None
_WRITE_TEXT = None
_VAULT_DIR = None
_ON_TAGS_REGISTERED = None


def configure_effects(
    *,
    journal_dir,
    aggregate_path,
    lock_factory,
    write_text,
    vault_dir,
    on_tags_registered=lambda _tags: None,
) -> None:
    global _JOURNAL_DIR, _AGGREGATE_PATH, _LOCK_FACTORY, _WRITE_TEXT, _VAULT_DIR, _ON_TAGS_REGISTERED
    _JOURNAL_DIR = journal_dir
    _AGGREGATE_PATH = aggregate_path
    _LOCK_FACTORY = lock_factory
    _WRITE_TEXT = write_text
    _VAULT_DIR = vault_dir
    _ON_TAGS_REGISTERED = on_tags_registered


# ── 标签聚合.md viewer ───────────────────────────────────────────────
_TAG_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_TAG_DATE_RE = re.compile(r"(\d{2})\.(\d{1,2})\.(\d{1,2})")


def _split_table_cells(line: str):
    """Split a Markdown table row without treating escaped pipes as columns."""
    raw = line.strip().strip("|")
    cells = re.split(r"(?<!\\)\|", raw)
    return [cell.strip().replace(r"\|", "|").replace(r"\\", "\\") for cell in cells]


def _parse_tag_aggregate(text: str):
    """walk lines → [{tag, description, columns, rows}]
    rows: {date_short, iso_date, time, content, sub_tag, link_target}
    """
    sections = []
    cur = None
    table_state = "outside"
    for raw in text.splitlines():
        line = raw.rstrip()
        m = re.match(r"^##\s+#(\S+)\s*$", line)
        if m:
            if cur:
                sections.append(cur)
            cur = {"tag": m.group(1), "description": "", "scope": "", "avoid": "", "columns": [], "rows": []}
            table_state = "outside"
            continue
        if not cur:
            continue
        if line.startswith("|"):
            cells = _split_table_cells(line)
            if table_state == "outside" and cells and cells[0] in ("日期", "Date"):
                cur["columns"] = cells
                table_state = "separator"
                continue
            if table_state == "separator" and cells and all((not c) or set(c) <= set("-: ") for c in cells):
                table_state = "rows"
                continue
            if table_state == "rows" and len(cells) >= 4:
                date_cell, time_cell, link_cell, content_cell = cells[0], cells[1], cells[2], cells[3]
                sub_tag = cells[4] if len(cells) >= 5 else None
                link_text, link_target = link_cell, ""
                m2 = _TAG_LINK_RE.search(link_cell)
                if m2:
                    link_text, link_target = m2.group(1), m2.group(2)
                iso_date = None
                m3 = _TAG_DATE_RE.search(link_target or date_cell)
                if m3:
                    yy, mo, dd = m3.groups()
                    iso_date = f"20{yy}-{int(mo):02d}-{int(dd):02d}"
                cur["rows"].append({
                    "date_short": date_cell,
                    "iso_date": iso_date,
                    "time": time_cell,
                    "link_text": link_text,
                    "link_target": link_target,
                    "content": content_cell,
                    "sub_tag": sub_tag if (sub_tag and sub_tag != "—") else None,
                })
            continue
        if table_state == "rows":
            table_state = "done"
        meta = re.match(r"^>?\s*(说明|适用范围|避免用于)[：:]\s*(.*?)\s*$", line)
        if meta:
            field = next(key for key, label in META_LABELS.items() if label == meta.group(1))
            cur[field] = meta.group(2).strip()
        elif line.strip() and not cur["description"] and not line.startswith(">"):
            # Legacy sections used one unlabelled prose line as the description.
            cur["description"] = line.strip()
    if cur:
        sections.append(cur)
    return sections


def _register_tag_section(
    text: str,
    tag: str,
    description: str = "",
    with_sub: bool = False,
):
    """Append one registry section without changing existing prose or rows."""
    if re.search(rf"^##\s+#{re.escape(tag)}\s*$", text, re.MULTILINE):
        return None
    parts = [f"## #{tag}\n"]
    if description:
        parts.append(f"\n{description}\n")
    parts.append("\n")
    if with_sub:
        parts.extend((
            "| 日期 | 时间 | 链接 | 内容 | Sub |\n",
            "|------|------|------|------|-----|\n",
        ))
    else:
        parts.extend((
            "| 日期 | 时间 | 链接 | 内容 |\n",
            "|------|------|------|------|\n",
        ))
    parts.append("\n---\n")
    separator = "\n" if not text.endswith("\n") else ""
    if not text.rstrip().endswith("---"):
        separator = separator + "\n---\n\n" if text.strip() else separator
    else:
        separator += "\n"
    return text + separator + "".join(parts)


_SCHEDULE_FILE_RE = re.compile(r"^(\d{2})\.(\d{1,2})\.(\d{1,2})")
_H1_TIME_RE = re.compile(r"^#\s+(\d{1,2})[：:](\d{2})\s*$")
_H2_RE = re.compile(r"^##\s+(.+)$")
_HASH_TAG_RE = re.compile(r"#([A-Za-z0-9_\-/一-鿿]+)")


def _scan_journal_file_for_project_tags(project_tags: set | None, f: Path) -> dict:
    """Extract selected project rows, or discover every parent tag when None."""
    out = {} if project_tags is None else {tag: [] for tag in project_tags}
    m = _SCHEDULE_FILE_RE.match(f.name)
    if not m:
        return out
    yy, mo, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
    iso_date = f"20{yy:02d}-{mo:02d}-{dd:02d}"
    date_short = f"{mo}.{dd}"

    lines = f.read_text(encoding="utf-8").splitlines()

    cur_time = None
    for line in lines:
        m1 = _H1_TIME_RE.match(line)
        if m1:
            cur_time = f"{m1.group(1)}：{m1.group(2)}"
            continue
        m2 = _H2_RE.match(line)
        if not m2 or not cur_time:
            continue
        h2 = m2.group(1).strip()
        tag_tokens = _HASH_TAG_RE.findall(h2)
        if not tag_tokens:
            continue
        title = _HASH_TAG_RE.sub("", h2).strip()
        if not title:
            continue
        for tag_full in tag_tokens:
            if "/" in tag_full:
                parent, child = tag_full.split("/", 1)
                sub = f"/{child}"
            else:
                parent, sub = tag_full, None
            if project_tags is not None and parent not in project_tags:
                continue
            out.setdefault(parent, []).append({
                "iso_date": iso_date,
                "date_short": date_short,
                "time": cur_time,
                "sub_tag": sub,
                "content": title,
                "link_target": f"半小时复盘/{f.name}#{cur_time}",
            })
    return out


def _scan_schedule_for_project_tags(project_tags: set | None) -> dict:
    """Walk 半小时复盘/*.md, 抽 project-tagged H2 entries。
    返:{tag: [{iso_date, date_short, time, sub_tag, content, link_target}, ...]}

    规则:
    - H1 行 `# 13：30` 是当前时间块
    - H2 行 `## #tagA #tagB title` 是一条 entry
      - tag 包括可能的 #parent/child 形式 → roll-up 到 parent section,sub_tag = /child
      - title = H2 去掉所有 #tag token 后剩下的文本
    - 只收 project_tags 命中的;generic tag(#运动 #饮食)等忽略
    """
    out = {} if project_tags is None else {tag: [] for tag in project_tags}
    journal_dir = _JOURNAL_DIR()
    if not journal_dir.exists():
        return out

    for f in sorted(journal_dir.glob("*.md")):
        per_file = _scan_journal_file_for_project_tags(project_tags, f)
        for tag, rows in per_file.items():
            out.setdefault(tag, []).extend(rows)
    return out


def _row_signature(tag: str, row: dict) -> tuple:
    return (
        tag,
        row.get("iso_date"),
        row.get("time"),
        row.get("sub_tag"),
        row.get("content"),
        row.get("link_target"),
    )


def _row_counter(sections) -> Counter:
    return Counter(
        _row_signature(section["tag"], row)
        for section in sections
        for row in section["rows"]
    )


def _refresh_tag_aggregate() -> dict:
    """Rebuild all derived rows from journal truth while preserving section prose."""
    # 局部别名:test_pc_audit_parity M10 用 inspect.getsource 断言
    # `with _get_vault_md_lock` 子串在 `.read_text` 之前 — 别名保住子串,勿改成 S. 前缀
    _get_vault_md_lock = _LOCK_FACTORY()
    TAG_AGGREGATE_PATH = _AGGREGATE_PATH()
    # ★ 7.10 审计 M10:read→compute→write 整段进锁(对齐 _patch_block),读在锁内 →
    #   与并发 register/另一个 refresh 交错时不再各读同一 base、后写覆盖前写丢行。
    with _get_vault_md_lock(str(TAG_AGGREGATE_PATH)):
        original = (
            TAG_AGGREGATE_PATH.read_text(encoding="utf-8")
            if TAG_AGGREGATE_PATH.exists()
            else "# 标签聚合\n"
        )

        try:
            discovered_rows = _scan_schedule_for_project_tags(None)
        except Exception as exc:
            return {
                "error": f"日记读取失败，保留原标签索引: {type(exc).__name__}: {exc}",
                "added": 0,
            }

        text = original
        existing_tags = {s["tag"] for s in _parse_tag_aggregate(text)}
        registered = sorted(set(discovered_rows) - existing_tags)
        for tag in registered:
            text = _register_tag_section(text, tag, with_sub=True)
        project_tags = existing_tags | set(registered)
        if not project_tags:
            return {
                "added": 0, "removed": 0, "registered": [],
                "per_tag": {}, "scanned": 0,
            }
        scanned = {tag: discovered_rows.get(tag, []) for tag in project_tags}

        new_text = _reconcile_rows_in_aggregate(text, scanned)
        old_counter = _row_counter(_parse_tag_aggregate(original))
        new_counter = _row_counter(_parse_tag_aggregate(new_text))
        total_added = sum((new_counter - old_counter).values())
        total_removed = sum((old_counter - new_counter).values())
        per_tag_added = Counter()
        for signature, count in (new_counter - old_counter).items():
            per_tag_added[signature[0]] += count
        if not TAG_AGGREGATE_PATH.exists() or new_text != original:
            _WRITE_TEXT()(TAG_AGGREGATE_PATH, new_text, rotate=True)
            vault_git.commit_after_write(
                _VAULT_DIR(),
                f"aggregate reconcile +{total_added} -{total_removed} register={len(registered)}",
                author="system",
                paths=[TAG_AGGREGATE_PATH],
            )

    pending_metadata = [
        section["tag"] for section in _parse_tag_aggregate(new_text)
        if not section.get("description") or not section.get("scope")
    ]
    if pending_metadata:
        _ON_TAGS_REGISTERED(pending_metadata)
    return {
        "added": total_added,
        "removed": total_removed,
        "registered": registered,
        "per_tag": dict(per_tag_added),
        "scanned": sum(len(v) for v in scanned.values()),
    }


def _format_row(row: dict, with_sub: bool) -> str:
    """单行 markdown table 行(链接锚点保留全角冒号)。"""
    yy = str(row["iso_date"])[2:4]
    link = f"[{yy}.{row['date_short']}#{row['time']}]({row['link_target']})"
    content = str(row["content"]).replace("\\", "\\\\").replace("|", r"\|")
    base = f"| {row['date_short']} | {row['time']} | {link} | {content} |"
    if with_sub:
        base += f" {row['sub_tag'] or '—'} |"
    return base


def _parse_table_row(line: str):
    sections = _parse_tag_aggregate(
        "## #_\n| 日期 | 时间 | 链接 | 内容 | Sub |\n"
        "|---|---|---|---|---|\n" + line
    )
    if sections and sections[0]["rows"]:
        return sections[0]["rows"][0]
    return None


def _reconcile_rows_in_aggregate(
    text: str,
    replacement_rows: dict,
    replace_dates=None,
) -> str:
    """Replace derived table rows; retain registered sections and prose verbatim."""
    lines = text.splitlines()
    section_starts = [i for i, line in enumerate(lines) if re.match(r"^##\s+#(\S+)\s*$", line)]
    if not section_starts:
        return text
    section_starts.append(len(lines))
    out = lines[:section_starts[0]]

    for pos in range(len(section_starts) - 1):
        start, end = section_starts[pos], section_starts[pos + 1]
        section = lines[start:end]
        tag = re.match(r"^##\s+#(\S+)\s*$", section[0]).group(1)
        header_idx = next((
            i for i, line in enumerate(section)
            if line.startswith("|") and _split_table_cells(line)[0] in ("日期", "Date")
        ), None)
        if header_idx is None or header_idx + 1 >= len(section):
            out.extend(section)
            continue
        separator_idx = header_idx + 1
        separator_cells = _split_table_cells(section[separator_idx]) if section[separator_idx].startswith("|") else []
        if not separator_cells or not all((not c) or set(c) <= set("-: ") for c in separator_cells):
            out.extend(section)
            continue
        data_indexes = []
        index = separator_idx + 1
        while index < len(section) and section[index].startswith("|"):
            data_indexes.append(index)
            index += 1
        data_index_set = set(data_indexes)
        with_sub = section[header_idx].count("|") >= 6
        combined = []
        for index in data_indexes:
            raw = section[index]
            parsed = _parse_table_row(raw)
            if replace_dates is None or (parsed and parsed.get("iso_date") in replace_dates):
                continue
            key = (
                parsed.get("iso_date") if parsed else "9999-99-99",
                parsed.get("time") if parsed else "99：99",
            )
            combined.append((key, raw))
        for row in replacement_rows.get(tag, []):
            if replace_dates is not None and row.get("iso_date") not in replace_dates:
                continue
            combined.append(((row["iso_date"], row["time"]), _format_row(row, with_sub)))
        combined.sort(key=lambda item: item[0])

        for index, line in enumerate(section):
            if index in data_index_set:
                continue
            out.append(line)
            if index == separator_idx:
                out.extend(raw for _key, raw in combined)

    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def _sync_tag_aggregate_for_file(journal_path: Path) -> dict:
    """Reconcile one changed journal date without blocking the journal truth write."""
    try:
        match = _SCHEDULE_FILE_RE.match(journal_path.name)
        aggregate_path = _AGGREGATE_PATH()
        if not match:
            return {"ok": True, "changed": False}
        iso_date = f"20{int(match.group(1)):02d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        lock_factory = _LOCK_FACTORY()
        with lock_factory(str(aggregate_path)):
            original = (
                aggregate_path.read_text(encoding="utf-8")
                if aggregate_path.exists()
                else "# 标签聚合\n"
            )
            discovered_rows = {}
            for candidate in sorted(journal_path.parent.glob("*.md")):
                candidate_match = _SCHEDULE_FILE_RE.match(candidate.name)
                if not candidate_match:
                    continue
                candidate_iso = (
                    f"20{int(candidate_match.group(1)):02d}-"
                    f"{int(candidate_match.group(2)):02d}-{int(candidate_match.group(3)):02d}"
                )
                if candidate_iso != iso_date:
                    continue
                per_file = _scan_journal_file_for_project_tags(None, candidate)
                for tag, found in per_file.items():
                    discovered_rows.setdefault(tag, []).extend(found)
            text = original
            existing_tags = {section["tag"] for section in _parse_tag_aggregate(text)}
            registered = sorted(set(discovered_rows) - existing_tags)
            for tag in registered:
                text = _register_tag_section(text, tag, with_sub=True)
            project_tags = existing_tags | set(registered)
            if not project_tags:
                return {"ok": True, "changed": False, "registered": []}
            rows = {tag: discovered_rows.get(tag, []) for tag in project_tags}
            new_text = _reconcile_rows_in_aggregate(text, rows, {iso_date})
            if aggregate_path.exists() and new_text == original:
                return {"ok": True, "changed": False, "registered": registered}
            _WRITE_TEXT()(aggregate_path, new_text, rotate=True)
            vault_git.commit_after_write(
                _VAULT_DIR(),
                f"aggregate sync {iso_date} register={len(registered)}",
                author="system",
                paths=[aggregate_path],
            )
        if registered:
            _ON_TAGS_REGISTERED(registered)
        return {"ok": True, "changed": True, "registered": registered}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
