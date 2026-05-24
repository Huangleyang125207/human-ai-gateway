# TEST PATTERN: contract — license filter logic
# USE WHEN: 验 consent _matches_filters 各条件正交 + 边界
# COPY THIS: 改 fixture row 加新条件
# TESTED IN: gateway (2026-05-24)

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


ROW = {
    "commit": "abc",
    "source": "vault",
    "ts": "2026-05-24T15:00:00+08:00",
    "author": "ai",
    "action": "patch ...",
    "tags": ["投资", "协作"],
}


# ─── T1 · 空 filter 全包 ─────────────────────────────────────

def test_empty_filter_matches_everything():
    assert server._matches_filters(ROW, {}) is True


# ─── T2 · sources 不在 list 拒 ───────────────────────────────

def test_source_mismatch_rejects():
    assert server._matches_filters(ROW, {"sources": ["pulse"]}) is False


def test_source_match_passes():
    assert server._matches_filters(ROW, {"sources": ["vault"]}) is True


# ─── T3 · authors ──────────────────────────────────────────

def test_author_mismatch_rejects():
    assert server._matches_filters(ROW, {"authors": ["user"]}) is False


def test_author_match_passes():
    assert server._matches_filters(ROW, {"authors": ["ai", "system"]}) is True


# ─── T4 · tags_include(至少有一个交集) ─────────────────────

def test_tags_include_intersects_passes():
    assert server._matches_filters(ROW, {"tags_include": ["投资"]}) is True


def test_tags_include_no_intersect_rejects():
    assert server._matches_filters(ROW, {"tags_include": ["ESP32"]}) is False


# ─── T5 · tags_exclude(任何交集就 reject) ──────────────────

def test_tags_exclude_intersect_rejects():
    assert server._matches_filters(ROW, {"tags_exclude": ["协作"]}) is False


def test_tags_exclude_no_intersect_passes():
    assert server._matches_filters(ROW, {"tags_exclude": ["ESP32"]}) is True


# ─── T6 · 日期范围 ─────────────────────────────────────────

def test_since_after_ts_rejects():
    assert server._matches_filters(ROW, {"since": "2026-06-01"}) is False


def test_since_before_ts_passes():
    assert server._matches_filters(ROW, {"since": "2026-05-01"}) is True


def test_until_before_ts_rejects():
    assert server._matches_filters(ROW, {"until": "2026-05-01"}) is False


def test_until_after_ts_passes():
    assert server._matches_filters(ROW, {"until": "2026-06-01"}) is True


# ─── T7 · 多条件 AND ───────────────────────────────────────

def test_multiple_filters_all_must_pass():
    # source 通过 + author 通过 + tag include 通过 + exclude 没踩
    assert server._matches_filters(ROW, {
        "sources": ["vault"], "authors": ["ai"],
        "tags_include": ["投资"], "tags_exclude": ["健康"],
        "since": "2026-01-01", "until": "2026-12-31",
    }) is True

    # 但任一不通过即 fail
    assert server._matches_filters(ROW, {
        "sources": ["vault"], "authors": ["ai"],
        "tags_include": ["投资"], "tags_exclude": ["协作"],  # ← exclude 撞 row tag
    }) is False


# ─── T8 · save / load licenses 持久化 ──────────────────────

def test_load_returns_empty_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CONSENT_LICENSES_PATH", tmp_path / "nope.json")
    assert server._load_licenses() == []


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / "lic.json"
    monkeypatch.setattr(server, "CONSENT_LICENSES_PATH", p)
    licenses = [{"id": "lic_1", "label": "test", "buyer": "X", "filters": {}, "preview_count": 5,
                 "created": "2026-05-24T15:00:00"}]
    server._save_licenses(licenses)
    assert p.exists()
    loaded = server._load_licenses()
    assert loaded == licenses
