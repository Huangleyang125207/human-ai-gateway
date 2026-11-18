import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cache_usage import build_cache_record, load_cache_records, summarize_cache_records


def test_build_cache_record_extracts_usage_without_content():
    response = SimpleNamespace(
        id="req-1",
        model="deepseek-v4-flash",
        system_fingerprint="fp-1",
        usage=SimpleNamespace(
            prompt_cache_hit_tokens=7296,
            prompt_cache_miss_tokens=136,
        ),
    )

    row = build_cache_record(response, source="chat/stream-final")

    assert row["source"] == "chat/stream-final"
    assert row["model"] == "deepseek-v4-flash"
    assert row["hit_tokens"] == 7296
    assert row["miss_tokens"] == 136
    assert row["prompt_tokens"] == 7432
    assert row["cache_fields_present"] is True
    assert "messages" not in row and "content" not in row


def test_build_cache_record_marks_provider_without_cache_fields():
    response = SimpleNamespace(
        model="compatible-model",
        usage=SimpleNamespace(prompt_tokens=42),
    )

    row = build_cache_record(response, source="eval/main")

    assert row["prompt_tokens"] == 42
    assert row["cache_fields_present"] is False
    assert row["hit_tokens"] == 0
    assert row["miss_tokens"] == 0


def test_summarize_cache_records_reports_token_and_request_hit_rates():
    report = summarize_cache_records([
        {"source": "chat", "model": "m", "hit_tokens": 80, "miss_tokens": 20,
         "prompt_tokens": 100, "cache_fields_present": True},
        {"source": "chat", "model": "m", "hit_tokens": 0, "miss_tokens": 100,
         "prompt_tokens": 100, "cache_fields_present": True},
        {"source": "eval", "model": "m", "hit_tokens": 0, "miss_tokens": 0,
         "prompt_tokens": 50, "cache_fields_present": False},
    ])

    assert report["requests"] == 3
    assert report["observed_requests"] == 2
    assert report["token_hit_rate"] == pytest.approx(0.4)
    assert report["request_hit_rate"] == pytest.approx(0.5)
    assert report["missing_usage_requests"] == 1
    assert report["groups"]["chat|m"]["token_hit_rate"] == pytest.approx(0.4)


def test_load_cache_records_skips_corrupt_lines_and_filters(tmp_path: Path):
    path = tmp_path / "cache.jsonl"
    path.write_text(
        json.dumps({"at": "2026-08-10T10:00:00+00:00", "source": "chat", "model": "a",
                    "hit_tokens": 10, "miss_tokens": 2, "prompt_tokens": 12,
                    "cache_fields_present": True}) + "\n" +
        "not json\n" +
        json.dumps({"at": "2026-08-11T10:00:00+00:00", "source": "eval", "model": "b",
                    "hit_tokens": 20, "miss_tokens": 3, "prompt_tokens": 23,
                    "cache_fields_present": True}) + "\n",
        encoding="utf-8",
    )

    rows = load_cache_records(path, source="eval", model="b", since="2026-08-11")

    assert len(rows) == 1
    assert rows[0]["source"] == "eval"
