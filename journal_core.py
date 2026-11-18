# PATTERN: util — journal markdown parse + authorship write-primitives extracted from god module
# USE WHEN: 日记 H1/H2 解析、insert/patch/comment 三个写原语、authorship guard 改动
# COPY THIS: 无 — 本模块是 server.py §13(清册01)的搬迁体,契约在 server re-export
#
# 抽出记录(2026-07-22, 清册01-§13,Parallel Change expand):
# - 原址 server.py(拆前行号)L2781–2886 + L4785–5128,两个不相邻块;现址(拆前)
#   L1091–1163(parse core)+ L2374–2389(_get_vault_md_lock/_sha256_text)+
#   L2742–3081(_insert_block.._append_comment_to_block,中间夹 /api/template/task
#   路由 + DAILY_TASKS_SOURCE/SCHEDULE_TEMPLATE_PATH 常量,那两样不属于 §13,留 server.py)。
# - 红线:三个写原语(_insert_block/_patch_block/_append_comment_to_block)+ guard
#   (_check_author)+ sha-lock(_get_vault_md_lock/_sha256_text)函数体逐字节照搬,
#   跨模块引用由组装根以 journal_dir/pretty_rel/write_text/vault_dir 命名 provider 注入。
#   test_authorship.py 直调 server.X(...),已知基线红 test_patch_block_ai_allows_ai_block
#   迁移后必须仍然红同一条 — 这是"一字不动"的证明。
# - 5.29 16:00 联想 entry 被 patch 写舜宇光学吃掉的真事故防御(_patch_block 内)原样带走。
import re
import threading
from pathlib import Path

import vault_git

_JOURNAL_DIR = None
_PRETTY_REL = None
_WRITE_TEXT = None
_VAULT_DIR = None


def configure_effects(*, journal_dir, pretty_rel, write_text, vault_dir) -> None:
    global _JOURNAL_DIR, _PRETTY_REL, _WRITE_TEXT, _VAULT_DIR
    _JOURNAL_DIR = journal_dir
    _PRETTY_REL = pretty_rel
    _WRITE_TEXT = write_text
    _VAULT_DIR = vault_dir


# ── journal parser ───────────────────────────────────────────────────
TIME_H1_RE = re.compile(r'^# (\d{1,2})[：:](\d{2})\s*$')

# PATTERN: util — authorship boundary marker parse
# USE WHEN: any tool that patches existing H2 needs to check who owns it
# COPY THIS: marker syntax is `@user` / `@ai`(行内任何位置都认)
_AUTHOR_RE = re.compile(r"@(user|ai)\b")

def _check_author(h2_line: str) -> str:
    """parse '## #tag title @user' → 'user' / 'ai'。
    无 marker → 'user'(失败安全:旧 entry 默认受保护,AI 不能改)。"""
    m = _AUTHOR_RE.search(h2_line or "")
    return m.group(1) if m else "user"

def find_today_journal(today=None):
    from datetime import datetime
    today = today or datetime.now()
    # filename pattern: 26.5.12(第十天).md  → prefix 26.5.12
    prefix = f"{str(today.year)[-2:]}.{today.month}.{today.day}"
    matches = list(_JOURNAL_DIR().glob(f"{prefix}*.md"))
    return matches[0] if matches else None

def parse_journal(text):
    """parse a 半小时复盘 md into [{time, h2s: [{tags, title, body, commits}]}]
    Empty blocks (no h2 content) filtered.
    Sorted chronologically by time.
    """
    blocks = []
    cur = None
    for line in text.splitlines():
        m = TIME_H1_RE.match(line)
        if m:
            if cur:
                blocks.append(cur)
            cur = {"time": f"{int(m.group(1)):02d}:{m.group(2)}",
                   "h1_raw": f"{int(m.group(1))}：{m.group(2)}",
                   "raw": []}
            continue
        if cur is None:
            continue
        cur["raw"].append(line)
    if cur:
        blocks.append(cur)

    for b in blocks:
        h2s = []
        ch = None
        for line in b["raw"]:
            if line.startswith("## "):
                if ch:
                    h2s.append(ch)
                content = line[3:].strip()
                tags = re.findall(r'#(\S+)', content)
                title = re.sub(r'#\S+\s*', '', content).strip()
                ch = {"tags": tags, "title": title, "body_lines": [], "commits": []}
                continue
            if ch is None:
                continue
            if line.strip() == "---":
                continue  # block separator residue — never part of any h2 body
            if re.match(r'^\s*-\s*#commit', line) or "#commit" in line[:30]:
                ch["commits"].append(line.strip())
            else:
                ch["body_lines"].append(line)
        if ch:
            h2s.append(ch)
        for h in h2s:
            h["body"] = "\n".join(h["body_lines"]).strip()
            del h["body_lines"]
        b["h2"] = h2s
        del b["raw"]

    # 留下:任一 h2 有 tag/title/body/commits 中任意一个。
    # 模板预创建的裸 ## 仍被过滤,但 insert-block 写的 ## #新 (有 tag) 会留下。
    blocks = [b for b in blocks if b["h2"] and any(
        h["tags"] or h["title"] or h["body"] or h["commits"] for h in b["h2"]
    )]
    blocks.sort(key=lambda b: b["time"])
    return blocks


# vault md (schedule + tag-aggregate) write 路径用,防 Obsidian 并发编辑被静默覆盖
# 跟 _EVOLVE_LOCKS 分开:一个保护 schema migration(LLM 重写真源),
# 一个保护 patch/insert/comment(块级编辑)。
_VAULT_MD_LOCKS: dict[str, threading.Lock] = {}
_VAULT_MD_LOCKS_GUARD = threading.Lock()


def _get_vault_md_lock(path_str: str) -> threading.Lock:
    with _VAULT_MD_LOCKS_GUARD:
        lk = _VAULT_MD_LOCKS.get(path_str)
        if lk is None:
            lk = threading.Lock()
            _VAULT_MD_LOCKS[path_str] = lk
        return lk


def _sha256_text(s: str) -> str:
    import hashlib as _hl
    return _hl.sha256(s.encode("utf-8")).hexdigest()


def _insert_block(f: Path, time_str: str, tag: str = "", title: str = "", author: str = "ai", body: str = "") -> dict:
    """加新条目。
    - 块不存在 → 新建 H1 + 一个 ## #tag title 的 H2
    - 块已存在 → append 新的 H2 到该块下(同时间多条目)
    tag/title 都可空,空时落 "## #新" 占位让 parser 不过滤(模板裸 ## 会被过滤)
    body = H2 下的散文正文(§ H5 result + significance)。标题-only 条目违反日记
    协议,tool schema 把 body 设 required;这里仍兼容空(老调用路径/前端)。
    Time can be HH:MM (half-width) or HH：MM (full-width). Stored as full-width.

    author='ai' (默认) 或 'user',新 H2 末尾 stamp @{author}。owner 决定后续 patch
    权限(详 _patch_block authorship boundary)。
    """
    m = re.fullmatch(r'\s*(\d{1,2})\s*[：:]\s*(\d{2})\s*', time_str)
    if not m:
        return {"error": "时间格式必须是 HH:MM,例如 9:15 或 16:42"}
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return {"error": f"时间超范围 (要 0:00 - 23:59)"}
    new_min = hh * 60 + mm

    text = f.read_text(encoding="utf-8")
    baseline_sha = _sha256_text(text)
    lines = text.splitlines()

    # 拼新 H2: tag 优先,兜底 #新;末尾 stamp @author 给 authorship boundary 用
    tag_clean = tag.strip().lstrip("#") or "新"
    h2_line = f"## #{tag_clean}" + (f" {title.strip()}" if title.strip() else "") + f" @{author}"
    # H2 + 正文一体落盘:body 空时 entry 只有标题行(老路径兼容,tool 层会提醒补写)
    body_lines = [ln.rstrip() for ln in (body or "").strip().splitlines()]
    entry_lines = [h2_line] + ([""] + body_lines if body_lines else [])

    # 找现有同时间块 + 找按时序插入位置
    existing_h1_idx = None
    insert_idx = None
    for i, ln in enumerate(lines):
        m1 = TIME_H1_RE.match(ln)
        if m1:
            em = int(m1.group(1)) * 60 + int(m1.group(2))
            if em == new_min:
                existing_h1_idx = i
                break
            if em > new_min and insert_idx is None:
                insert_idx = i

    if existing_h1_idx is not None:
        # 块已存在 → APPEND 新 H2 到块尾(每段 tag+title 是独立叙事,UI 层做时间去重显示)
        end_idx = len(lines)
        for j in range(existing_h1_idx + 1, len(lines)):
            if TIME_H1_RE.match(lines[j]):
                end_idx = j
                break
        # 倒查到非 --- 非空的真实块尾
        body_end = end_idx
        while body_end > existing_h1_idx + 1 and (not lines[body_end - 1].strip() or lines[body_end - 1].strip() == "---"):
            body_end -= 1
        # 若块只有占位 `##` 一行,直接替换它(否则 append)
        only_placeholder = False
        if body_end == existing_h1_idx + 2 and lines[existing_h1_idx + 1].strip() == "##":
            lines[existing_h1_idx + 1:existing_h1_idx + 2] = entry_lines
            only_placeholder = True
        elif body_end > existing_h1_idx + 1:
            # 检查 placeholder ## 在范围内
            for j in range(existing_h1_idx + 1, body_end):
                if lines[j].strip() == "##":
                    lines[j:j + 1] = entry_lines
                    only_placeholder = True
                    break
        if not only_placeholder:
            lines = lines[:body_end] + ["", *entry_lines, ""] + lines[body_end:]

        new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        with _get_vault_md_lock(str(f)):
            actual = f.read_text(encoding="utf-8")
            if _sha256_text(actual) != baseline_sha:
                return {"error": f"vault md `{f.name}` 在 insert 期间被外部修改,拒绝覆盖。",
                        "conflict": True, "file": _PRETTY_REL()(f)}
            _WRITE_TEXT()(f, new_text, rotate=True)
        vault_git.commit_after_write(_VAULT_DIR(), f"insert {f.stem} {hh}:{mm:02d} #{tag_clean}", author=author, paths=[f])
        return {"ok": True, "appended_to_existing": True, "h2": h2_line,
                "file": _PRETTY_REL()(f)}

    new_h1 = f"# {hh}：{mm:02d}"
    if insert_idx is not None:
        new_block = [new_h1, "", *entry_lines, "", "---", ""]
        new_lines = lines[:insert_idx] + new_block + lines[insert_idx:]
    else:
        new_lines = lines + ["", "---", "", new_h1, "", *entry_lines]

    new_text = "\n".join(new_lines) + ("\n" if text.endswith("\n") else "")
    with _get_vault_md_lock(str(f)):
        actual = f.read_text(encoding="utf-8")
        if _sha256_text(actual) != baseline_sha:
            return {"error": f"vault md `{f.name}` 在 insert 期间被外部修改,拒绝覆盖。",
                    "conflict": True, "file": _PRETTY_REL()(f)}
        _WRITE_TEXT()(f, new_text, rotate=True)
    vault_git.commit_after_write(_VAULT_DIR(), f"insert {f.stem} {hh}:{mm:02d} #{tag_clean}", author=author, paths=[f])
    return {"ok": True, "inserted": new_h1, "file": _PRETTY_REL()(f)}


def _top_section_bounds(text: str):
    """找模板/日记顶部 section 的范围(从开头到第一个 `---`)。返回 (start_line, end_line_exclusive)。"""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() == "---":
            return (0, i)
    return None


def _apply_task_op(f: Path, action: str, text: str, old_text: str) -> dict:
    raw = f.read_text(encoding="utf-8")
    lines = raw.splitlines()
    bounds = _top_section_bounds(raw)
    if bounds is None:
        return {"file": _PRETTY_REL()(f), "error": "找不到顶部 section (缺 --- 分割)"}
    start, end = bounds  # [start, end)

    # 顶层 task only — 不动 daily_dose>1 task 下挂的进度子 box
    def _is_top_task_line(s: str) -> bool:
        return s.startswith("- [")

    if action == "add":
        # 找最后一个顶层 '- [' 行,在它后面加;否则在 end 前加
        insert_after = end
        for j in range(end - 1, start - 1, -1):
            if _is_top_task_line(lines[j]):
                # 跳过该顶层项的子 box,新行插在子 box 之后
                k = j + 1
                while k < end and re.match(r"^\s+-\s*\[[ x]\]", lines[k]):
                    k += 1
                insert_after = k
                break
        new_line = f"- [ ] {text}"
        new_lines = lines[:insert_after] + [new_line] + lines[insert_after:]
    elif action == "edit":
        target_idx = None
        for j in range(start, end):
            if old_text and old_text in lines[j] and _is_top_task_line(lines[j]):
                target_idx = j
                break
        if target_idx is None:
            return {"file": str(f), "error": f"找不到含 '{old_text}' 的任务项"}
        # 保留 checkbox 状态前缀,替换文本部分
        checkbox_match = re.match(r'^(-\s*\[[ x]\]\s*)(.*)', lines[target_idx])
        if checkbox_match:
            lines[target_idx] = checkbox_match.group(1) + text
        else:
            lines[target_idx] = f"- [ ] {text}"
        new_lines = lines
    else:  # del
        target_idx = None
        for j in range(start, end):
            if old_text and old_text in lines[j] and _is_top_task_line(lines[j]):
                target_idx = j
                break
        if target_idx is None:
            return {"file": str(f), "error": f"找不到含 '{old_text}' 的任务项"}
        # 删父行 + 紧随的进度子 box(若有)
        end_idx = target_idx + 1
        while end_idx < end and re.match(r"^\s+-\s*\[[ x]\]", lines[end_idx]):
            end_idx += 1
        new_lines = lines[:target_idx] + lines[end_idx:]

    new_text = "\n".join(new_lines) + ("\n" if raw.endswith("\n") else "")
    _WRITE_TEXT()(f, new_text, rotate=True)
    try:
        rel = _PRETTY_REL()(f)
    except Exception:
        rel = str(f)
    return {"file": rel, "ok": True}


def _patch_block(f: Path, time_label: str, new_md: str, author: str = "ai",
                 allow_h2_rename: bool = False) -> dict:
    """Replace the body between `# {time}` and the next `# H1` or `---` boundary.
    new_md should NOT include the H1 line itself — only what comes after it.

    author='ai' (默认,最严格) — 撞 @user 块拒绝。author='user' 可改任何块。
    @marker 解析:看时间块内第一个 H2 行的 @user/@ai。无 marker → @user(失败安全)。
    allow_h2_rename=True:跳过 H2 不匹配的拒,让 AI 显式 rename H2。仅在
    用户明示要改标题时由 tool caller 传。
    """
    text = f.read_text(encoding="utf-8")
    baseline_sha = _sha256_text(text)
    lines = text.splitlines()
    h, m = time_label.split(":")
    # match either "# 18：30" (full-width) or "# 18:30" (half-width)
    re_h1 = re.compile(rf'^# {int(h)}[：:]{m}\s*$')

    start = None
    for i, ln in enumerate(lines):
        if re_h1.match(ln):
            start = i
            break
    if start is None:
        existing = [f"{int(m1.group(1))}:{m1.group(2)}" for ln in lines if (m1 := TIME_H1_RE.match(ln))]
        return {"error": f"time block # {time_label} not found in {f.name}; "
                          f"合法值是文件里已存在的半小时块,当前有: {existing}。"
                          f"想新建块请用 insert_journal_block(会自动建块),这个工具只能改已存在的块。"}

    # find end: next # H1 (any time) OR `---` line, whichever comes first AFTER content
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if TIME_H1_RE.match(lines[j]) or lines[j].strip() == "---":
            end = j
            break

    # authorship boundary:扫块内首条 H2,看 owner。AI 调不能改 @user 块。
    if author != "user":
        for k in range(start + 1, end):
            if lines[k].startswith("## "):
                owner = _check_author(lines[k])
                if owner == "user":
                    return {"error": f"block @ {time_label} 是 @user 所有,AI 不能 patch。"
                                     f"想加评论用 append_journal_comment;想新加 entry 用 insert_journal_block。"}
                break  # 只看第一个 H2

    # AI 误用 patch 当 insert 的反向防御 — 对比现存第一条 H2 vs new_md 第一条 H2:
    # 完整行(除 @marker 之外)不一致 → AI 大概率是想"加新 entry"误用 patch,
    # 会把原 entry 整段吃掉。拒。
    # 5.29 16:00 联想 entry 被 patch 写舜宇光学吃掉的真事故 = 这条 guard 没有的恶果。
    # 注意:同 tag 同 title 但不同 body 是合法 patch(典型用例:补充 / 改散文措辞)。
    if author != "user":
        existing_first_h2 = None
        for k in range(start + 1, end):
            if lines[k].startswith("## "):
                existing_first_h2 = lines[k]
                break
        new_first_h2 = None
        for ln in new_md.splitlines():
            if ln.startswith("## "):
                new_first_h2 = ln
                break

        def _strip_author(h2):
            # 去掉末尾 @ai / @user / @<handle> 让对比看 tag + title
            return re.sub(r"\s*@\S+\s*$", "", h2 or "").strip()

        if (existing_first_h2 and new_first_h2
                and existing_first_h2.strip() != "##"
                and _strip_author(existing_first_h2) != _strip_author(new_first_h2)
                and not allow_h2_rename):
            return {"error":
                f"block @ {time_label} 已有 H2:`{existing_first_h2.strip()}`。"
                f"你的 new_md 第一个 H2 是:`{new_first_h2.strip()}` — 不一样。"
                f"patch_journal_block 会**整段替换**,原 H2 + body 会被吃掉。"
                f"如果想给块加新 H2 → 用 insert_journal_block(append,不覆盖)。"
                f"如果用户明示要改这个 entry 的标题 → 重传带 allow_h2_rename=true。"
                f"如果真要替换 = 放弃原 entry(数据丢失),先 read_today_schedule 确认要丢什么,"
                f"再在 new_md 里同时写原 H2 段 + 新 H2 段。"
            }

    new_lines = lines[:start + 1] + [""] + new_md.rstrip().splitlines() + [""] + lines[end:]
    new_content = "\n".join(new_lines) + ("\n" if text.endswith("\n") else "")
    # 锁内重读 + sha256 比对,防 Obsidian 并发编辑被静默覆盖(C5)
    with _get_vault_md_lock(str(f)):
        actual = f.read_text(encoding="utf-8")
        if _sha256_text(actual) != baseline_sha:
            return {"error": f"vault md `{f.name}` 在 patch 期间被外部修改(Obsidian?),"
                             f"拒绝覆盖。请前端 force-reload 后让用户重提交。",
                    "conflict": True, "file": _PRETTY_REL()(f)}
        _WRITE_TEXT()(f, new_content, rotate=True)
    vault_git.commit_after_write(_VAULT_DIR(), f"patch {f.stem} {time_label}", author=author, paths=[f])
    return {"patched": time_label, "file": _PRETTY_REL()(f)}


# PATTERN: util — append-only journal comment (authorship boundary 安全旁路)
# USE WHEN: AI 想给 @user 块留评论但不能动原文 — append 到 body 末尾
# COPY THIS: 改 prefix 标记(默认 *AI:* 给 user 看出来是 AI 加的)
def _append_comment_to_block(f: Path, time_label: str, comment_md: str) -> dict:
    """在指定时间块 body 末尾 append 一段 comment。**不修改原 H2 / 原 body**。
    给 @user 块写"穿线 / 回看 / AI 注"用 — _patch_block 拒绝 @user 时的合法替代路径。
    """
    text = f.read_text(encoding="utf-8")
    baseline_sha = _sha256_text(text)
    lines = text.splitlines()
    h, m = time_label.split(":")
    re_h1 = re.compile(rf'^# {int(h)}[：:]{m}\s*$')

    start = None
    for i, ln in enumerate(lines):
        if re_h1.match(ln):
            start = i
            break
    if start is None:
        existing = [f"{int(m1.group(1))}:{m1.group(2)}" for ln in lines if (m1 := TIME_H1_RE.match(ln))]
        return {"error": f"time block # {time_label} not found in {f.name}; "
                          f"合法值是文件里已存在的半小时块,当前有: {existing}。"
                          f"想新建块请用 insert_journal_block(会自动建块),这个工具只能改已存在的块。"}

    # 找块结束:next H1 / `---`
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if TIME_H1_RE.match(lines[j]) or lines[j].strip() == "---":
            end = j
            break

    # 在 end 之前插入 comment(保留原 body)。前留个空行让 markdown 段落分开。
    comment_lines = comment_md.rstrip().splitlines()
    new_lines = lines[:end] + [""] + comment_lines + [""] + lines[end:]
    new_content = "\n".join(new_lines) + ("\n" if text.endswith("\n") else "")
    # 锁内重读 + sha256 比对,防 Obsidian 并发编辑被静默覆盖(C5)
    with _get_vault_md_lock(str(f)):
        actual = f.read_text(encoding="utf-8")
        if _sha256_text(actual) != baseline_sha:
            return {"error": f"vault md `{f.name}` 在 append-comment 期间被外部修改,"
                             f"拒绝覆盖。请刷新后重试。",
                    "conflict": True, "file": _PRETTY_REL()(f)}
        _WRITE_TEXT()(f, new_content, rotate=True)
    vault_git.commit_after_write(_VAULT_DIR(), f"append-comment {f.stem} {time_label}", author="ai", paths=[f])
    return {"appended": time_label, "file": _PRETTY_REL()(f)}
