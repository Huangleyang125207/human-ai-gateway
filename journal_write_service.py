# PATTERN: service — journal HTTP writes over existing authorship primitives
# USE WHEN: changing new-day/insert/delete/patch orchestration
# COPY THIS: inject journal lookup and protected write primitives

import re


class JournalWriteError(Exception):
    def __init__(self, status_code: int, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class JournalWriteRejected(Exception):
    def __init__(self, payload: dict):
        self.payload = payload
        super().__init__(str(payload))


class JournalWriteService:
    def __init__(
        self,
        *,
        datetime_type,
        new_day_create,
        find_journal,
        insert_block,
        patch_block,
        write_text,
        pretty_rel,
        time_h1_re,
        sync_tag_aggregate,
    ):
        self.datetime_type = datetime_type
        self.new_day_create = new_day_create
        self.find_journal = find_journal
        self.insert_block = insert_block
        self.patch_block = patch_block
        self.write_text = write_text
        self.pretty_rel = pretty_rel
        self.time_h1_re = time_h1_re
        self.sync_tag_aggregate = sync_tag_aggregate

    def _sync_aggregate(self, path, result: dict):
        sync_result = self.sync_tag_aggregate(path)
        if isinstance(sync_result, dict) and not sync_result.get("ok", True):
            result["aggregate_warning"] = sync_result.get(
                "error", "标签索引同步失败，可稍后重建"
            )

    def new_day(self, date_arg: str = ""):
        target = date_arg.strip() or self.datetime_type.now().strftime(
            "%Y-%m-%d"
        )
        return self.new_day_create(target)

    def _find(self, date_arg: str, missing_detail: str):
        if date_arg:
            try:
                target = self.datetime_type.strptime(date_arg, "%Y-%m-%d")
            except ValueError as e:
                raise JournalWriteError(
                    400,
                    f"bad date: {date_arg}",
                ) from e
            path = self.find_journal(target)
        else:
            path = self.find_journal()
        if not path:
            raise JournalWriteError(404, missing_detail)
        return path

    def insert(self, body: dict):
        date_arg = (body.get("date") or "").strip()
        time_str = (body.get("time") or "").strip()
        tag = (body.get("tag") or "").strip().lstrip("#")
        title = (body.get("title") or "").strip()
        if not time_str:
            raise JournalWriteError(400, "need 'time'")
        path = self._find(
            date_arg,
            "no journal file for that date",
        )
        result = self.insert_block(
            path,
            time_str,
            tag=tag,
            title=title,
            author="user",
            body=(body.get("body") or "").strip(),
        )
        if "error" in result:
            raise JournalWriteRejected(result)
        self._sync_aggregate(path, result)
        return result

    def delete(self, body: dict):
        time_label = (body.get("time") or "").strip()
        date_arg = (body.get("date") or "").strip()
        if not time_label:
            raise JournalWriteError(400, "need 'time'")
        path = self._find(date_arg, "no journal file")
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        hour, minute = time_label.replace("：", ":").split(":")
        block_re = re.compile(
            rf"^# {int(hour)}[：:]{int(minute):02d}\s*$"
        )
        start = next(
            (index for index, line in enumerate(lines) if block_re.match(line)),
            None,
        )
        if start is None:
            raise JournalWriteError(
                404,
                f"time block {time_label} not found",
            )
        end = len(lines)
        for index in range(start + 1, len(lines)):
            if (
                self.time_h1_re.match(lines[index])
                or lines[index].strip() == "---"
            ):
                end = index
                break
        new_lines = lines[:start + 1] + ["", "##", ""] + lines[end:]
        self.write_text(
            path,
            "\n".join(new_lines) + ("\n" if text.endswith("\n") else ""),
            rotate=True,
        )
        result = {
            "ok": True,
            "cleared": time_label,
            "file": self.pretty_rel(path),
        }
        self._sync_aggregate(path, result)
        return result

    def patch(self, body: dict):
        time_label = body.get("time")
        new_block_md = body.get("new_md")
        date_arg = (body.get("date") or "").strip()
        if not time_label or new_block_md is None:
            raise JournalWriteError(400, "need {time, new_md}")
        path = self._find(
            date_arg,
            f"no journal file for {date_arg or 'today'}",
        )
        result = self.patch_block(
            path,
            time_label,
            new_block_md,
            author="user",
        )
        if "error" not in result:
            self._sync_aggregate(path, result)
        return result
