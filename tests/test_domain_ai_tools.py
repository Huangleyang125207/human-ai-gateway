from datetime import datetime

from domain_ai_tools import DomainAITools


class FakeTagService:
    def __init__(self):
        self.registered = []

    def get(self):
        return {"sections": list(self.registered)}

    def register(self, body):
        self.registered.append({"tag": body["tag"]})
        return {"ok": True, "tag": body["tag"]}

    def refresh(self):
        return {"ok": True, "added": 2}


def make_tools(tmp_path, journal=None):
    service = FakeTagService()
    scrapbook = {}
    def find(target):
        if journal and target.strftime("%Y-%m-%d") == "2026-08-05":
            return journal
        return None
    def top(text):
        lines = text.splitlines()
        return (0, next((i for i, line in enumerate(lines) if line == "---"), len(lines)))
    return DomainAITools(
        tag_service=lambda: service, find_journal=find, top_section_bounds=top,
        load_task_meta=lambda: {}, load_task_images=lambda: {},
        load_scrapbook=lambda date: list(scrapbook.get(date, [])),
        save_scrapbook=lambda date, items: scrapbook.__setitem__(date, list(items)),
        write_text=lambda path, text, **_: path.write_text(text, encoding="utf-8"),
        sync_tag_aggregate=lambda path: {"ok": True}, app_state_dir=tmp_path,
        pretty_rel=lambda path: path.name,
    ), service, scrapbook


def test_register_tag_auto_refreshes(tmp_path):
    tools, service, _ = make_tools(tmp_path)
    result = tools.manage_tag_aggregate({"action": "register", "tag": "项目"})
    assert result["refresh"] == {"ok": True, "added": 2}
    assert service.registered == [{"tag": "项目"}]


def test_delete_one_entry_preserves_sibling_and_mood_roundtrips(tmp_path):
    journal = tmp_path / "26.8.5.md"
    journal.write_text(
        "# 10：00\n\n## #工作 第一条 @user\n\n正文一\n\n"
        "## #生活 第二条 @ai\n\n正文二\n", encoding="utf-8",
    )
    tools, _, _ = make_tools(tmp_path, journal)
    result = tools.delete_journal_entry({"date": "2026-08-05", "time": "10:00", "entry_index": 1})
    assert result["ok"] is True
    assert "第一条" in journal.read_text(encoding="utf-8")
    assert "第二条" not in journal.read_text(encoding="utf-8")
    assert tools.manage_mood({"action": "set", "date": "2026-08-05", "value": "好"})["value"] == "好"
    assert tools.manage_mood({"action": "get", "date": "2026-08-05"})["value"] == "好"
