# TEST PATTERN: effect — derived Markdown index rebuilds from journal truth
# USE WHEN: tag aggregate identity, lifecycle, or year parsing changes
# COPY THIS: seed registered sections, scan journal truth, assert replacement effects

from datetime import datetime
from contextlib import nullcontext

import journal_task_tools
import tag_aggregate
from tag_vocabulary import (
    apply_tag_metadata,
    build_tag_disclosure,
    build_annotation_prompt,
    missing_metadata_tags,
    parse_annotation_response,
    render_tag_vocabulary_context,
)
from tag_annotation import enrich_tag_metadata


def test_scan_accepts_future_year_and_keeps_same_slot_entries(tmp_path):
    journal_dir = tmp_path / "半小时复盘"
    journal_dir.mkdir()
    journal = journal_dir / "27.1.2(第245天).md"
    journal.write_text(
        "# 9：00\n\n## #项目 第一条 @user\n正文\n\n## #项目 第二条 @user\n正文\n",
        encoding="utf-8",
    )

    rows = tag_aggregate._scan_journal_file_for_project_tags({"项目"}, journal)["项目"]

    assert [row["iso_date"] for row in rows] == ["2027-01-02", "2027-01-02"]
    assert [row["content"] for row in rows] == ["第一条 @user", "第二条 @user"]
    assert all("27.1.2(第245天).md" in row["link_target"] for row in rows)


def test_reconcile_replaces_stale_rows_and_preserves_section_notes():
    text = (
        "# 标签聚合\n\n## #项目\n\n项目说明\n\n"
        "| 日期 | 时间 | 链接 | 内容 |\n"
        "|------|------|------|------|\n"
        "| 1.1 | 9：00 | [26.1.1#9：00](半小时复盘/26.1.1.md#9：00) | 旧标题 |\n\n"
        "> 人工备注必须保留\n\n---\n"
    )
    rows = {
        "项目": [
            {
                "iso_date": "2027-01-02",
                "date_short": "1.2",
                "time": "9：00",
                "sub_tag": None,
                "content": "第一条 @user",
                "link_target": "半小时复盘/27.1.2.md#9：00",
            },
            {
                "iso_date": "2027-01-02",
                "date_short": "1.2",
                "time": "9：00",
                "sub_tag": None,
                "content": "第二条 @user",
                "link_target": "半小时复盘/27.1.2.md#9：00",
            },
        ]
    }

    rebuilt = tag_aggregate._reconcile_rows_in_aggregate(text, rows)
    parsed = tag_aggregate._parse_tag_aggregate(rebuilt)

    assert "旧标题" not in rebuilt
    assert "项目说明" in rebuilt
    assert "> 人工备注必须保留" in rebuilt
    assert [row["content"] for row in parsed[0]["rows"]] == [
        "第一条 @user",
        "第二条 @user",
    ]


def test_reconcile_preserves_later_manual_table_and_escaped_pipe_content():
    text = (
        "# 标签聚合\n\n## #项目\n\n"
        "| 日期 | 时间 | 链接 | 内容 |\n|---|---|---|---|\n"
        "| 1.1 | 9：00 | [x](半小时复盘/26.1.1.md#9：00) | 旧标题 |\n\n"
        "---\n## 附录\n| 名称 | 值 |\n|---|---|\n| 手工 | 必须保留 |\n"
    )
    rows = {"项目": [{
        "iso_date": "2027-01-02", "date_short": "1.2", "time": "9：00",
        "sub_tag": None, "content": "A | B", "link_target": "半小时复盘/27.1.2.md#9：00",
    }]}

    rebuilt = tag_aggregate._reconcile_rows_in_aggregate(text, rows)
    parsed = tag_aggregate._parse_tag_aggregate(rebuilt)

    assert "| 手工 | 必须保留 |" in rebuilt
    assert r"A \| B" in rebuilt
    assert parsed[0]["rows"][0]["content"] == "A | B"
    assert len(parsed[0]["rows"]) == 1


def test_scan_accepts_ascii_time_and_normalizes_anchor(tmp_path):
    journal = tmp_path / "27.1.2.md"
    journal.write_text("# 9:00\n\n## #项目 ASCII 时间\n", encoding="utf-8")

    row = tag_aggregate._scan_journal_file_for_project_tags({"项目"}, journal)["项目"][0]

    assert row["time"] == "9：00"
    assert row["link_target"].endswith("#9：00")


def _configure_local_aggregate(tmp_path, monkeypatch, aggregate_text):
    journal_dir = tmp_path / "半小时复盘"
    journal_dir.mkdir()
    aggregate = tmp_path / "标签聚合.md"
    aggregate.write_text(aggregate_text, encoding="utf-8")
    monkeypatch.setattr(tag_aggregate, "_JOURNAL_DIR", lambda: journal_dir)
    monkeypatch.setattr(tag_aggregate, "_AGGREGATE_PATH", lambda: aggregate)
    monkeypatch.setattr(tag_aggregate, "_LOCK_FACTORY", lambda: (lambda _key: nullcontext()))
    monkeypatch.setattr(
        tag_aggregate, "_WRITE_TEXT",
        lambda: (lambda path, text, rotate=False: path.write_text(text, encoding="utf-8")),
    )
    monkeypatch.setattr(tag_aggregate, "_VAULT_DIR", lambda: tmp_path)
    monkeypatch.setattr(tag_aggregate, "_ON_TAGS_REGISTERED", lambda _tags: None)
    monkeypatch.setattr(tag_aggregate.vault_git, "commit_after_write", lambda *_args, **_kwargs: None)
    return journal_dir, aggregate


def test_local_sync_scans_all_same_date_files_instead_of_deleting_sibling(tmp_path, monkeypatch):
    base = (
        "# 标签聚合\n\n## #项目\n\n"
        "| 日期 | 时间 | 链接 | 内容 |\n|---|---|---|---|\n"
    )
    journal_dir, aggregate = _configure_local_aggregate(tmp_path, monkeypatch, base)
    first = journal_dir / "27.1.2.md"
    second = journal_dir / "27.1.2(第245天).md"
    first.write_text("# 9：00\n## #项目 第一份\n", encoding="utf-8")
    second.write_text("# 10：00\n## #项目 第二份\n", encoding="utf-8")

    result = tag_aggregate._sync_tag_aggregate_for_file(first)
    rebuilt = aggregate.read_text(encoding="utf-8")

    assert result["ok"] is True
    assert "第一份" in rebuilt and "第二份" in rebuilt


def test_local_sync_auto_creates_registry_and_parent_tag(tmp_path, monkeypatch):
    journal_dir, aggregate = _configure_local_aggregate(
        tmp_path, monkeypatch, "# 标签聚合\n"
    )
    aggregate.unlink()
    journal = journal_dir / "27.1.2.md"
    journal.write_text(
        "# 9：00\n## #新项目/阶段 自动发现\n", encoding="utf-8"
    )

    result = tag_aggregate._sync_tag_aggregate_for_file(journal)
    rebuilt = aggregate.read_text(encoding="utf-8")

    assert result["ok"] is True
    assert result["registered"] == ["新项目"]
    assert "## #新项目" in rebuilt
    assert "| 日期 | 时间 | 链接 | 内容 | Sub |" in rebuilt
    assert "自动发现" in rebuilt
    assert "/阶段" in rebuilt


def test_refresh_discovers_new_tag_without_removing_existing_registry(tmp_path, monkeypatch):
    base = (
        "# 标签聚合\n\n## #旧项目\n\n旧说明\n\n"
        "| 日期 | 时间 | 链接 | 内容 |\n|---|---|---|---|\n"
    )
    journal_dir, aggregate = _configure_local_aggregate(tmp_path, monkeypatch, base)
    (journal_dir / "27.1.2.md").write_text(
        "# 9：00\n## #新项目 新条目\n", encoding="utf-8"
    )

    result = tag_aggregate._refresh_tag_aggregate()
    rebuilt = aggregate.read_text(encoding="utf-8")

    assert result["registered"] == ["新项目"]
    assert "## #旧项目" in rebuilt and "旧说明" in rebuilt
    assert "## #新项目" in rebuilt and "新条目" in rebuilt


def test_refresh_read_failure_preserves_existing_index(tmp_path, monkeypatch):
    base = (
        "# 标签聚合\n\n## #项目\n\n"
        "| 日期 | 时间 | 链接 | 内容 |\n|---|---|---|---|\n"
        "| 1.2 | 9：00 | [x](半小时复盘/27.1.2.md#9：00) | 保留旧索引 |\n"
    )
    journal_dir, aggregate = _configure_local_aggregate(tmp_path, monkeypatch, base)
    journal = journal_dir / "27.1.2.md"
    journal.write_text("# 9：00\n## #项目 真源\n", encoding="utf-8")
    original_read_text = tag_aggregate.Path.read_text

    def fail_journal_read(path, *args, **kwargs):
        if path == journal:
            raise OSError("temporary read failure")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(tag_aggregate.Path, "read_text", fail_journal_read)
    result = tag_aggregate._refresh_tag_aggregate()

    assert "读取失败" in result["error"]
    assert original_read_text(aggregate, encoding="utf-8") == base


def test_ai_journal_tools_sync_only_after_successful_writes(tmp_path, monkeypatch):
    journal = tmp_path / "26.8.5.md"
    journal.write_text("# 9：00\n\n##\n", encoding="utf-8")
    synced = []
    monkeypatch.setattr(journal_task_tools, "_DATETIME", lambda: datetime)
    monkeypatch.setattr(journal_task_tools, "_FIND_TODAY_JOURNAL", lambda *_args: journal)
    monkeypatch.setattr(journal_task_tools, "_SYNC_TAG_AGGREGATE", synced.append)
    monkeypatch.setattr(journal_task_tools, "_INSERT_BLOCK", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(journal_task_tools, "_PATCH_BLOCK", lambda *_args, **_kwargs: {"patched": "9:00"})

    journal_task_tools.tool_insert_journal_block({"time": "9:00", "tag": "项目", "title": "新增", "body": "正文"})
    journal_task_tools.tool_patch_journal_block({"time": "9:00", "new_md": "## #项目 改名 @ai\n正文"})
    assert synced == [journal, journal]

    monkeypatch.setattr(journal_task_tools, "_PATCH_BLOCK", lambda *_args, **_kwargs: {"error": "rejected"})
    journal_task_tools.tool_patch_journal_block({"time": "9:00", "new_md": "bad"})
    assert synced == [journal, journal]


def test_ai_journal_tool_discloses_aggregate_sync_failure(tmp_path, monkeypatch):
    journal = tmp_path / "26.8.5.md"
    journal.write_text("# 9：00\n\n##\n", encoding="utf-8")
    monkeypatch.setattr(journal_task_tools, "_DATETIME", lambda: datetime)
    monkeypatch.setattr(journal_task_tools, "_FIND_TODAY_JOURNAL", lambda *_args: journal)
    monkeypatch.setattr(journal_task_tools, "_INSERT_BLOCK", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(
        journal_task_tools, "_SYNC_TAG_AGGREGATE",
        lambda _path: {"ok": False, "error": "temporary aggregate failure"},
    )

    out = journal_task_tools.tool_insert_journal_block(
        {"time": "9:00", "tag": "项目", "title": "新增", "body": "正文"}
    )

    assert out["ok"] is True
    assert out["aggregate_warning"] == "temporary aggregate failure"


def test_ai_insert_discloses_vocabulary_before_writing_unknown_tag(tmp_path, monkeypatch):
    journal = tmp_path / "26.8.18.md"
    journal.write_text("# 9：00\n\n", encoding="utf-8")
    writes = []
    monkeypatch.setattr(journal_task_tools, "_DATETIME", lambda: datetime)
    monkeypatch.setattr(journal_task_tools, "_FIND_TODAY_JOURNAL", lambda *_args: journal)
    monkeypatch.setattr(journal_task_tools, "_INSERT_BLOCK", lambda *_args, **_kwargs: writes.append(True))
    monkeypatch.setattr(
        journal_task_tools,
        "_DISCLOSE_UNKNOWN_TAGS",
        lambda tags: {
            "ok": False,
            "error": "tag_disclosure_required",
            "requested_tags": tags,
            "tag_vocabulary": "=== TAG_VOCABULARY ===\n- #工作",
        } if "新项目" in tags else None,
    )

    out = journal_task_tools.tool_insert_journal_block(
        {"time": "9:00", "tag": "新项目", "title": "新增", "body": "正文"},
        enforce_tag_vocabulary=True,
    )

    assert out["error"] == "tag_disclosure_required"
    assert out["requested_tags"] == ["新项目"]
    assert writes == []


def test_ai_patch_discloses_vocabulary_before_introducing_unknown_tag(tmp_path, monkeypatch):
    journal = tmp_path / "26.8.18.md"
    journal.write_text("# 9：00\n\n## #工作 原条目 @ai\n正文\n", encoding="utf-8")
    writes = []
    monkeypatch.setattr(journal_task_tools, "_DATETIME", lambda: datetime)
    monkeypatch.setattr(journal_task_tools, "_FIND_TODAY_JOURNAL", lambda *_args: journal)
    monkeypatch.setattr(journal_task_tools, "_PATCH_BLOCK", lambda *_args, **_kwargs: writes.append(True))
    monkeypatch.setattr(
        journal_task_tools,
        "_DISCLOSE_UNKNOWN_TAGS",
        lambda tags: {"ok": False, "error": "tag_disclosure_required", "requested_tags": tags}
        if "新项目" in tags else None,
    )

    out = journal_task_tools.tool_patch_journal_block(
        {"time": "9:00", "new_md": "## #工作 #新项目 改名 @ai\n正文"},
        enforce_tag_vocabulary=True,
    )

    assert out["error"] == "tag_disclosure_required"
    assert writes == []


def test_non_ai_system_insert_can_bypass_tag_disclosure(tmp_path, monkeypatch):
    journal = tmp_path / "26.8.18.md"
    journal.write_text("# 9：00\n\n", encoding="utf-8")
    monkeypatch.setattr(journal_task_tools, "_DATETIME", lambda: datetime)
    monkeypatch.setattr(journal_task_tools, "_FIND_TODAY_JOURNAL", lambda *_args: journal)
    monkeypatch.setattr(journal_task_tools, "_SYNC_TAG_AGGREGATE", lambda _path: {"ok": True})
    monkeypatch.setattr(journal_task_tools, "_INSERT_BLOCK", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(
        journal_task_tools,
        "_DISCLOSE_UNKNOWN_TAGS",
        lambda tags: {"ok": False, "error": "tag_disclosure_required", "requested_tags": tags},
    )

    out = journal_task_tools.tool_insert_journal_block(
        {"time": "9:00", "tag": "备忘", "title": "完成", "body": "正文"},
        enforce_tag_vocabulary=False,
    )

    assert out["ok"] is True


def test_tag_metadata_round_trip_and_harness_context_omit_volatile_rows():
    base = (
        "# 标签聚合\n\n## #跑步\n\n"
        "| 日期 | 时间 | 链接 | 内容 |\n|---|---|---|---|\n"
        "| 8.18 | 9：00 | [x](x.md#9) | 晨跑五公里 |\n"
    )
    enriched = apply_tag_metadata(base, "跑步", {
        "description": "跑步训练与恢复记录",
        "scope": "户外跑、跑步机、配速和跑后恢复",
        "avoid": "普通步行或其他运动",
    })
    sections = tag_aggregate._parse_tag_aggregate(enriched)
    context = render_tag_vocabulary_context(sections)

    assert sections[0]["scope"] == "户外跑、跑步机、配速和跑后恢复"
    assert missing_metadata_tags(sections) == []
    assert "优先复用" in context and "#跑步" in context
    assert "8.18" not in context and "晨跑五公里" not in context
    assert build_tag_disclosure(["跑步/间歇"], sections) is None
    disclosure = build_tag_disclosure(["新运动"], sections)
    assert disclosure["error"] == "tag_disclosure_required"
    assert disclosure["requested_tags"] == ["新运动"]
    assert "#跑步" in disclosure["tag_vocabulary"]
    assert "8.18" not in disclosure["tag_vocabulary"]


def test_annotation_contract_is_strict_and_bounded():
    prompt = build_annotation_prompt("跑步", ["晨跑五公里", "跑步机间歇"])
    parsed = parse_annotation_response(
        '{"description":"跑步训练","scope":"跑步及恢复","avoid":"普通步行"}'
    )

    assert "#跑步" in prompt and "晨跑五公里" in prompt
    assert parsed["scope"] == "跑步及恢复"


def test_enrichment_calls_model_outside_lock_and_preserves_human_race(tmp_path):
    aggregate = tmp_path / "标签聚合.md"
    aggregate.write_text(
        "# 标签聚合\n\n## #跑步\n\n| 日期 | 时间 | 链接 | 内容 |\n|---|---|---|---|\n",
        encoding="utf-8",
    )
    lock_depth = 0

    class Lock:
        def __enter__(self):
            nonlocal lock_depth
            lock_depth += 1

        def __exit__(self, *_args):
            nonlocal lock_depth
            lock_depth -= 1

    def model(_prompt):
        assert lock_depth == 0
        current = aggregate.read_text(encoding="utf-8")
        aggregate.write_text(apply_tag_metadata(current, "跑步", {
            "description": "人工说明", "scope": "人工范围", "avoid": "",
        }), encoding="utf-8")
        return '{"description":"AI说明","scope":"AI范围","avoid":"步行"}'

    result = enrich_tag_metadata(
        path=aggregate,
        parse_aggregate=tag_aggregate._parse_tag_aggregate,
        lock_factory=lambda _key: Lock(),
        write_text=lambda path, text, rotate=False: path.write_text(text, encoding="utf-8"),
        call_model=model,
    )

    assert result["enriched"] == []
    assert "人工说明" in aggregate.read_text(encoding="utf-8")
