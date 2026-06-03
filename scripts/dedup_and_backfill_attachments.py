#!/usr/bin/env python3
"""
扫 attachments 索引,做三件事:

  1. hash backfill — 给没有 hash 字段的 record 算 sha256
  2. dedup — 同 hash 多 record 合并:保留最早的,其余进 dupes/ audit trail
  3. vision backfill — vision.description 空的现场跑一次 qwen-vl,回写索引

默认 --dry-run,只打印计划不动数据。--apply 才写。
"""

from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# server 必须先 import 才能拿 _qwen_classify_image / ATTACHMENTS_DIR 这些
import server  # noqa: E402


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def step1_hash_backfill(arr, apply: bool):
    """无论 dry-run/apply 都计算 hash 写进 in-memory record,这样后续 step 能看到 dedup 计划。
    只有 apply 时才会通过 _save_attachments_index 真持久化。
    """
    print("\n── Step 1 · hash backfill ─────────────────")
    todo = []
    for x in arr:
        if x.get("hash"):
            continue
        p = server.ATTACHMENTS_DIR / x["date"] / x["filename"]
        if not p.exists():
            print(f"  miss: {x['date']}/{x['filename']} (file 丢)")
            continue
        todo.append((x, p))
    print(f"  待补 hash: {len(todo)} 条")
    for x, p in todo:
        x["hash"] = sha256_file(p)
    print(f"  ✓ 算完(in-memory{'+保存' if apply else ',未保存'})")


def step2_dedup(arr, apply: bool, purge_files: bool):
    """同 hash 多 record 合并:留最早,其他从 index 去掉。

    默认 **不动物理文件** — 老 chat / journal 已经 cite 了 dropped 的 url,文件留着
    保证历史不 404。--purge-files 才把多余的搬进 _dupes/。
    """
    print("\n── Step 2 · dedup by hash ─────────────────")
    by_hash: dict[str, list] = {}
    for x in arr:
        h = x.get("hash")
        if not h:
            continue
        by_hash.setdefault(h, []).append(x)

    groups = [(h, xs) for h, xs in by_hash.items() if len(xs) > 1]
    print(f"  重复组: {len(groups)} 组")
    to_remove = []
    keep_url_remap: dict[str, str] = {}
    for h, xs in groups:
        def sort_key(x):
            return (x.get("date", ""), x.get("filename", ""))
        xs_sorted = sorted(xs, key=sort_key)
        keep = xs_sorted[0]
        drops = xs_sorted[1:]
        # description 合并:取最长版本
        best_desc = max(
            (((y.get("vision") or {}).get("description") or "") for y in xs_sorted),
            key=len,
        )
        if best_desc and not (keep.get("vision") or {}).get("description"):
            keep.setdefault("vision", {})
            keep["vision"]["description"] = best_desc
        keep_desc = ((keep.get("vision") or {}).get("description") or "")[:40]
        print(f"  [{h[:8]}] 留 {keep['date']}/{keep['filename']}  '{keep_desc}'")
        for d in drops:
            d_desc = ((d.get("vision") or {}).get("description") or "")[:40]
            print(f"           扔 {d['date']}/{d['filename']}  '{d_desc}'")
            to_remove.append(d)
            keep_url_remap[d.get("url", "")] = keep.get("url", "")

    if not apply:
        archive_note = "归档物理" if purge_files else "文件留着"
        print(f"  (dry-run: 会从 index 去 {len(to_remove)} 条,{archive_note})")
        return [], {}

    # apply: index 缩容
    for x in to_remove:
        arr.remove(x)

    if purge_files:
        dupes_dir = server.ATTACHMENTS_DIR / "_dupes"
        dupes_dir.mkdir(parents=True, exist_ok=True)
        moved = 0
        for old_url in keep_url_remap:
            import re as _re
            m = _re.match(r"^/attachments/([^/]+)/([^/]+)$", old_url or "")
            if not m:
                continue
            src = server.ATTACHMENTS_DIR / m.group(1) / m.group(2)
            if src.exists():
                dst = dupes_dir / f"{m.group(1)}_{m.group(2)}"
                shutil.move(str(src), str(dst))
                moved += 1
        print(f"  ✓ index 缩 {len(to_remove)} 条,物理文件 {moved} 个搬到 _dupes/")
    else:
        print(f"  ✓ index 缩 {len(to_remove)} 条(物理文件留着,老 url 仍可访问)")
    return to_remove, keep_url_remap


def step3_vision_backfill(arr, apply: bool, only_count: int | None = None):
    print("\n── Step 3 · vision backfill ───────────────")
    todo = []
    for x in arr:
        if (x.get("vision") or {}).get("description"):
            continue
        p = server.ATTACHMENTS_DIR / x["date"] / x["filename"]
        if not p.exists():
            continue
        todo.append((x, p))
    print(f"  待跑 vision: {len(todo)} 条")
    if only_count is not None:
        todo = todo[:only_count]
        print(f"  (限 {only_count} 条本轮跑)")
    if not apply or not todo:
        return
    ok, fail = 0, 0
    for i, (x, p) in enumerate(todo, 1):
        try:
            res = server._qwen_classify_image(p)
            if isinstance(res, dict) and not res.get("error"):
                x["vision"] = res
                ok += 1
                desc = (res.get("description") or "")[:50]
                print(f"  [{i}/{len(todo)}] ✓ {x['filename']}: {desc}")
            else:
                fail += 1
                print(f"  [{i}/{len(todo)}] ✗ {x['filename']}: {res}")
        except Exception as e:
            fail += 1
            print(f"  [{i}/{len(todo)}] ✗ {x['filename']}: {type(e).__name__} {e}")
        time.sleep(0.3)  # 别撞 rate limit
    print(f"  ✓ 跑完 ok={ok} fail={fail}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真改;默认 dry-run")
    ap.add_argument("--skip-vision", action="store_true", help="跳过 vision 回填(省钱测)")
    ap.add_argument("--vision-limit", type=int, default=None, help="本轮 vision 跑多少条上限")
    ap.add_argument("--purge-files", action="store_true",
                    help="dedup 时把重复物理文件搬进 _dupes/(默认留着保历史引用可用)")
    args = ap.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"== {mode} ==  index: {server.ATTACHMENTS_INDEX}")
    arr = server._load_attachments_index()
    print(f"baseline: {len(arr)} records")

    step1_hash_backfill(arr, apply=args.apply)
    step2_dedup(arr, apply=args.apply, purge_files=args.purge_files)
    if not args.skip_vision:
        step3_vision_backfill(arr, apply=args.apply, only_count=args.vision_limit)

    if args.apply:
        server._save_attachments_index(arr)
        print(f"\n✓ index saved: {len(arr)} records")
    else:
        print("\n(dry-run 没改任何东西。--apply 真改。)")


if __name__ == "__main__":
    main()
