# TEST PATTERN: contract + effect — /api/pulse/refresh-mirror 主路径
# USE WHEN: 验扫源 → 拷贝/skip/覆盖 → vault_git commit → silent_failure 兜底全链路
# TESTED IN: gateway PULSE refactor P0+ TDD net (2026-06-18, must-add #4)
#
# 之前只测了 sources 为空时的早退分支(scanned=0, updated=0)。但真正干活的代码在
# L8011-8063:扫 ~/agents创作平台/agents/*/PULSE.md → 比对内容 → _safe_write_text
# → vault_git.commit_after_write。这条路径完全没有测试守。重构 P1+P2 把 endpoint 搬到
# pulse_routes.py 时,如果漏拷扫源逻辑或漏掉 vault_git audit 调用,monolith 没人会发现。
#
# 5 个 contract:
#   1. copies_new_source   — 全新 mirror → 拷过去、files 含 stem
#   2. skips_unchanged     — dest 字节同源 → updated=0、files=[]
#   3. updates_changed     — dest 不一致 → 覆盖、updated=1
#   4. partial_failure     — 一源 _safe_write_text raise → silent_calls 记 / 另一源仍正常
#   5. no_vault_git_when_all_skip — 全 skip → vault_git.commit_after_write 不被调
#
# fixture 走 tests/conftest.py(isolated_pulse_paths + stubbed_llm + client),
# Path.home() monkeypatch 到 tmp_path 让 ~/agents创作平台 落到隔离区。

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


# ── 辅助:在 tmp_path 下造 ~/agents创作平台/agents/<proj>/PULSE.md ───────────

def _make_source(home: Path, project: str, content: str) -> Path:
    """在 home/agents创作平台/agents/<project>/ 下造 PULSE.md,返回文件路径"""
    src_dir = home / "agents创作平台" / "agents" / project
    src_dir.mkdir(parents=True, exist_ok=True)
    src = src_dir / "PULSE.md"
    src.write_text(content, encoding="utf-8")
    return src


def _patch_home(monkeypatch, tmp_path):
    """让 Path.home() 返 tmp_path,这样源扫描走隔离目录"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)


# ── T1: 全新源 → 镜像目录是空的 → 拷过去 ────────────────────────────────

def test_copies_new_source(monkeypatch, tmp_path, isolated_pulse_paths, stubbed_llm):
    """有源、mirror 没对应文件 → 拷过去,scanned/updated/files 三字段都对"""
    _patch_home(monkeypatch, tmp_path)
    content = "# 项目 foo\n气压 OK\n"
    _make_source(tmp_path, "proj_foo", content)

    result = server.pulse_refresh_mirror()

    assert result["scanned"] == 1, "扫到 1 个源"
    assert result["updated"] == 1, "1 个新写入"
    assert result["files"] == ["proj_foo"], "files 用源目录的 stem"

    # 真的写到 mirror 了
    dest = isolated_pulse_paths.mirror / "proj_foo.md"
    assert dest.exists(), "mirror dest 必须真存在"
    assert dest.read_text(encoding="utf-8") == content

    # vault_git audit chain 被调一次
    stubbed_llm.vault_git.assert_called_once()
    call_kwargs = stubbed_llm.vault_git.call_args
    assert call_kwargs.kwargs.get("author") == "system", \
        "镜像同步以 system 身份 commit,不是用户"
    # paths 参数含 dest
    paths_arg = call_kwargs.kwargs.get("paths")
    assert paths_arg is not None and dest in paths_arg


# ── T2: dest 已存在且字节相同 → skip ────────────────────────────────────

def test_skips_unchanged_dest(monkeypatch, tmp_path, isolated_pulse_paths, stubbed_llm):
    """源和 dest 字节一致 → updated=0、files=[],也不调 vault_git"""
    _patch_home(monkeypatch, tmp_path)
    content = "# 一致内容\nts:2026-06-18\n"
    _make_source(tmp_path, "proj_same", content)
    # 预先把 dest 写成跟源一样
    dest = isolated_pulse_paths.mirror / "proj_same.md"
    dest.write_text(content, encoding="utf-8")

    result = server.pulse_refresh_mirror()

    assert result["scanned"] == 1
    assert result["updated"] == 0, "字节一致不该重写"
    assert result["files"] == []


# ── T3: dest 已存在但内容不一致 → 覆盖 ──────────────────────────────────

def test_updates_changed_dest(monkeypatch, tmp_path, isolated_pulse_paths, stubbed_llm):
    """dest 是旧版,源是新版 → 覆盖、updated=1"""
    _patch_home(monkeypatch, tmp_path)
    new_content = "# 新版\nts:2026-06-18\n"
    _make_source(tmp_path, "proj_bar", new_content)
    dest = isolated_pulse_paths.mirror / "proj_bar.md"
    dest.write_text("# 旧版\nts:2026-05-01\n", encoding="utf-8")

    result = server.pulse_refresh_mirror()

    assert result["updated"] == 1
    assert result["files"] == ["proj_bar"]
    assert dest.read_text(encoding="utf-8") == new_content, "dest 必须是新内容"

    # 有 updated_files → vault_git 必须被调
    stubbed_llm.vault_git.assert_called_once()


# ── T4: 一源写失败 → silent_failure 记;另一源仍正常 ────────────────────

def test_partial_failure_reports_silent(monkeypatch, tmp_path,
                                         isolated_pulse_paths, stubbed_llm):
    """两源,其中一个 _safe_write_text raise → silent_calls 记 pulse_mirror_write_failed,
    另一源 updated 仍正常,vault_git 仍因健康源被调"""
    _patch_home(monkeypatch, tmp_path)
    _make_source(tmp_path, "proj_bad", "# bad\n")
    _make_source(tmp_path, "proj_good", "# good\n")

    real_safe_write = server._safe_write_text

    def selective_raise(path, content, rotate=False, encoding="utf-8"):
        # bad 那条文件名包 proj_bad → 抛
        if "proj_bad" in str(path):
            raise OSError("disk full simulated")
        return real_safe_write(path, content, rotate=rotate, encoding=encoding)

    monkeypatch.setattr(server, "_safe_write_text", selective_raise)

    result = server.pulse_refresh_mirror()

    assert result["scanned"] == 2
    assert result["updated"] == 1, "只 good 那条成功"
    assert "proj_good" in result["files"]
    assert "proj_bad" not in result["files"]

    # silent_calls 含 pulse_mirror_write_failed
    error_types = [c[0] for c in stubbed_llm.silent_calls]
    assert "pulse_mirror_write_failed" in error_types, \
        f"应记 pulse_mirror_write_failed,实际 silent_calls: {stubbed_llm.silent_calls}"

    # 健康源走完 → vault_git 仍被调(只为 good 那个)
    stubbed_llm.vault_git.assert_called_once()


# ── T5: 全部 skip → vault_git 不调(没 updated_files 不该触发 audit) ────

def test_no_vault_git_when_all_skip(monkeypatch, tmp_path,
                                     isolated_pulse_paths, stubbed_llm):
    """两源都跟 dest 字节一致 → updated=0 → 不该触发 vault_git commit"""
    _patch_home(monkeypatch, tmp_path)
    c1 = "# a 内容\n"
    c2 = "# b 内容\n"
    _make_source(tmp_path, "proj_a", c1)
    _make_source(tmp_path, "proj_b", c2)
    (isolated_pulse_paths.mirror / "proj_a.md").write_text(c1, encoding="utf-8")
    (isolated_pulse_paths.mirror / "proj_b.md").write_text(c2, encoding="utf-8")

    result = server.pulse_refresh_mirror()

    assert result["scanned"] == 2
    assert result["updated"] == 0
    assert result["files"] == []
    stubbed_llm.vault_git.assert_not_called()


# ── T6(加分):monorepo 根级 PULSE.md 也算源,落地 _root.md ───────────────

def test_root_pulse_picked_up_as_root_stem(monkeypatch, tmp_path,
                                            isolated_pulse_paths, stubbed_llm):
    """~/agents创作平台/PULSE.md 存在 → 进 sources,以 _root 为 stem 写镜像"""
    _patch_home(monkeypatch, tmp_path)
    root_pulse_dir = tmp_path / "agents创作平台"
    root_pulse_dir.mkdir(parents=True, exist_ok=True)
    (root_pulse_dir / "PULSE.md").write_text("# INDEX\n", encoding="utf-8")

    result = server.pulse_refresh_mirror()

    assert result["scanned"] == 1
    assert result["updated"] == 1
    assert "_root" in result["files"]
    assert (isolated_pulse_paths.mirror / "_root.md").exists()
