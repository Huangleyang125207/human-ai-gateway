# PATTERN: service — tag aggregate register/refresh/read with explicit effects
# USE WHEN: changing tag registry persistence or vault Git audit behavior
# COPY THIS: inject path, lock, writer, parser, refresher, and commit effect

import re
from pathlib import Path

from tag_aggregate import _register_tag_section


class TagAggregateService:
    def __init__(
        self,
        *,
        path,
        vault_dir,
        lock_factory,
        write_text,
        commit_after_write,
        refresh_aggregate,
        parse_aggregate,
        logger,
        on_tags_registered=lambda _tags: None,
    ):
        self.path = Path(path)
        self.vault_dir = Path(vault_dir)
        self.lock_factory = lock_factory
        self.write_text = write_text
        self.commit_after_write = commit_after_write
        self.refresh_aggregate = refresh_aggregate
        self.parse_aggregate = parse_aggregate
        self.logger = logger
        self.on_tags_registered = on_tags_registered

    def register(self, body: dict) -> dict:
        tag = (body.get("tag") or "").strip().lstrip("#").strip()
        description = (body.get("description") or "").strip()
        with_sub = bool(body.get("with_sub"))
        if not tag:
            return {"ok": False, "error": "tag 名不能为空"}
        if not re.match(r"^[\w\-一-鿿/]+$", tag):
            return {
                "ok": False,
                "error": (
                    f"tag 只能用字母/数字/下划线/连字符/中文,得到:{tag}"
                ),
            }
        if "/" in tag:
            return {
                "ok": False,
                "error": "注册 parent tag(不带 /sub);sub-tag 自动 roll-up",
            }
        with self.lock_factory(str(self.path)):
            if not self.path.exists():
                return {"ok": False, "error": "标签聚合.md 不存在"}
            text = self.path.read_text(encoding="utf-8")
            next_text = _register_tag_section(text, tag, description, with_sub)
            if next_text is None:
                return {"ok": False, "error": f"#{tag} 已经注册过了"}
            self.write_text(
                self.path,
                next_text,
                rotate=True,
            )
            self.commit_after_write(
                self.vault_dir,
                f"aggregate register #{tag}",
                author="system",
                paths=[self.path],
            )
        self.on_tags_registered([tag])
        return {"ok": True, "tag": tag, "with_sub": with_sub}

    def refresh(self) -> dict:
        try:
            return {"ok": True, **self.refresh_aggregate()}
        except Exception as e:
            self.logger.exception("tag aggregate refresh failed")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def get(self) -> dict:
        if not self.path.exists():
            return {
                "sections": [],
                "warning": f"not found: {self.path}",
            }
        return {
            "sections": self.parse_aggregate(
                self.path.read_text(encoding="utf-8")
            )
        }
