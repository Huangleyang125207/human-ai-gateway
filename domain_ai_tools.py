"""Semantic AI tools over existing journal, care, aggregate and scrapbook domains."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path


class DomainAITools:
    def __init__(self, *, tag_service, find_journal, top_section_bounds, load_task_meta,
                 load_task_images, load_scrapbook, save_scrapbook, write_text,
                 sync_tag_aggregate, app_state_dir, pretty_rel):
        self.tag_service = tag_service
        self.find_journal = find_journal
        self.top_section_bounds = top_section_bounds
        self.load_task_meta = load_task_meta
        self.load_task_images = load_task_images
        self.load_scrapbook = load_scrapbook
        self.save_scrapbook = save_scrapbook
        self.write_text = write_text
        self.sync_tag_aggregate = sync_tag_aggregate
        self.mood_path = Path(app_state_dir) / "moods.json"
        self.pretty_rel = pretty_rel

    @staticmethod
    def _date(raw):
        value = (raw or datetime.now().strftime("%Y-%m-%d")).strip()
        datetime.strptime(value, "%Y-%m-%d")
        return value

    def manage_tag_aggregate(self, args):
        action = str(args.get("action") or "").lower()
        if action == "list":
            return {"ok": True, **self.tag_service().get()}
        if action == "refresh":
            return self.tag_service().refresh()
        if action == "register":
            result = self.tag_service().register(args)
            if not result.get("ok"):
                return result
            refreshed = self.tag_service().refresh()
            return {**result, "refresh": refreshed}
        return {"ok": False, "error": "action must be list|register|refresh"}

    def get_daily_care_state(self, args):
        try:
            date = self._date(args.get("date"))
        except ValueError:
            return {"ok": False, "error": "date must be YYYY-MM-DD"}
        days = max(1, min(int(args.get("history_days") or 14), 30))
        path = self.find_journal(datetime.strptime(date, "%Y-%m-%d"))
        if not path:
            return {"ok": True, "date": date, "tasks": [], "water": 0, "history": {}}
        text = path.read_text(encoding="utf-8")
        bounds = self.top_section_bounds(text)
        tasks, water = [], 0
        meta, images = self.load_task_meta(), self.load_task_images()
        if bounds:
            for line in text.splitlines()[bounds[0]:bounds[1]]:
                task = re.match(r"^-\s*\[([ xX])\]\s*(.+)$", line)
                cup = re.match(r"^\s*-\s*\[([ xX])\]\s*第\s*\d+\s*杯", line)
                if cup:
                    water += cup.group(1).lower() == "x"
                elif task and task.group(2).strip() != "喝水":
                    name = task.group(2).strip()
                    tasks.append({"name": name, "checked": task.group(1).lower() == "x",
                                  "meta": meta.get(name, {}), "image": images.get(name)})
        history = {}
        end = datetime.strptime(date, "%Y-%m-%d")
        for task in tasks:
            rows = []
            for offset in range(days - 1, -1, -1):
                day = end - timedelta(days=offset)
                journal = self.find_journal(day)
                checked = None
                if journal:
                    match = re.search(rf"^-\s*\[([ xX])\]\s*{re.escape(task['name'])}\s*$", journal.read_text(encoding="utf-8"), re.M)
                    checked = None if match is None else match.group(1).lower() == "x"
                rows.append({"date": day.strftime("%Y-%m-%d"), "checked": checked})
            history[task["name"]] = rows
        return {"ok": True, "date": date, "tasks": tasks, "water": water, "history": history,
                "water_image": images.get("__water_cup__")}

    def manage_scrapbook(self, args):
        action, date = str(args.get("action") or "").lower(), str(args.get("date") or "")
        if not date:
            return {"ok": False, "error": "need date"}
        items = self.load_scrapbook(date)
        if action == "list":
            return {"ok": True, "date": date, "items": items}
        item_id = str(args.get("id") or "")
        index = next((i for i, item in enumerate(items) if str(item.get("id")) == item_id), -1)
        if index < 0:
            return {"ok": False, "error": f"sticker not found: {item_id}"}
        if action == "remove":
            removed = items.pop(index)
            self.save_scrapbook(date, items)
            return {"ok": True, "removed": removed.get("id")}
        if action == "update":
            patch = args.get("patch") or {}
            allowed = {"anchor_time", "x_pct", "y_px", "size_pct", "rotation", "z"}
            items[index].update({key: value for key, value in patch.items() if key in allowed})
            if "y_px" in patch:
                items[index]["auto_y"] = False
            self.save_scrapbook(date, items)
            return {"ok": True, "item": items[index]}
        return {"ok": False, "error": "action must be list|update|remove"}

    def delete_journal_entry(self, args):
        try:
            date = self._date(args.get("date"))
            index = int(args.get("entry_index"))
        except (ValueError, TypeError):
            return {"ok": False, "error": "invalid date or entry_index"}
        time = str(args.get("time") or "").replace("：", ":")
        if not re.match(r"^\d{1,2}:\d{2}$", time):
            return {"ok": False, "error": "time must be HH:MM"}
        path = self.find_journal(datetime.strptime(date, "%Y-%m-%d"))
        if not path:
            return {"ok": False, "error": "journal not found"}
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        target = re.compile(rf"^#\s*{int(time.split(':')[0])}[：:]{int(time.split(':')[1]):02d}\s*$")
        start = next((i for i, line in enumerate(lines) if target.match(line)), -1)
        if start < 0:
            return {"ok": False, "error": "time block not found"}
        end = next((i for i in range(start + 1, len(lines)) if re.match(r"^#\s*\d{1,2}[：:]\d{2}\s*$", lines[i]) or lines[i].strip() == "---"), len(lines))
        starts = [i for i in range(start + 1, end) if lines[i].startswith("## ")]
        if index < 0 or index >= len(starts):
            return {"ok": False, "error": "entry_index out of range", "entry_count": len(starts)}
        seg_start = starts[index]
        seg_end = starts[index + 1] if index + 1 < len(starts) else end
        remaining = lines[:seg_start] + lines[seg_end:]
        if len(starts) == 1:
            remaining = lines[:start + 1] + ["", "##", ""] + lines[end:]
        new_text = "\n".join(remaining) + ("\n" if text.endswith("\n") else "")
        self.write_text(path, new_text, rotate=True)
        result = {"ok": True, "date": date, "time": time, "entry_index": index, "file": self.pretty_rel(path)}
        sync = self.sync_tag_aggregate(path)
        if isinstance(sync, dict) and not sync.get("ok", True):
            result["aggregate_warning"] = sync.get("error", "aggregate sync failed")
        return result

    def manage_mood(self, args):
        try:
            date = self._date(args.get("date"))
        except ValueError:
            return {"ok": False, "error": "date must be YYYY-MM-DD"}
        data = {}
        if self.mood_path.exists():
            try:
                data = json.loads(self.mood_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                data = {}
        action = str(args.get("action") or "").lower()
        if action == "get":
            return {"ok": True, "date": date, "value": data.get(date)}
        if action == "clear":
            data.pop(date, None)
        elif action == "set":
            value = str(args.get("value") or "").strip()
            if not value:
                return {"ok": False, "error": "need value"}
            data[date] = value
        else:
            return {"ok": False, "error": "action must be get|set|clear"}
        self.mood_path.parent.mkdir(parents=True, exist_ok=True)
        self.write_text(self.mood_path, json.dumps(data, ensure_ascii=False, indent=2), rotate=True)
        return {"ok": True, "date": date, "value": data.get(date)}
