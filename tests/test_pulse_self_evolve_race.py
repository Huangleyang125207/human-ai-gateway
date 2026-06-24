# TEST PATTERN: boundary — _self_evolve_run external-edit race guard / mid-LLM file deletion
# USE WHEN: 锁住 sha256 外部编辑 guard + FileNotFoundError 双分支(creating vs non-creating)
# TESTED IN: gateway PULSE refactor P0+ TDD net (2026-06-18, must-add #1)
#
# 红线背景(PULSE.md Cannot break):
#   _self_evolve_run 在 read→LLM→write 这段窗口里,用户可能在 Obsidian 真源上手编。
#   server.py L7757-7790 用 sha256 baseline + 重读对比守这条 race:
#     ① external-edit:重读出来 sha256 ≠ baseline → push 通知 + skipped:true(reason=external-edit)
#     ② file-deleted (non-creating):重读 FileNotFoundError + creating=False
#                     → push 通知 + skipped:true(reason=file-deleted)
#     ③ file-deleted (creating=True):user_pulse bootstrap,文件本就不存在
#                     → FileNotFoundError 不算"被删",继续走首版写入,不 push
#   这三条分支被 refactor 漏一条 → 用户手编日记被 LLM 输出静默覆盖(silent corruption,
#   最高风险红线)。fixture 走 tests/conftest.py(跨 P2 refactor 鲁棒)。

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
from conftest import FakeChat, FakeClient, VALID_PULSE  # noqa: E402


# ── helper:在 LLM .create() 调用瞬间 mutate 真源文件 ──────────────────

class MutatingFakeChat(FakeChat):
    """LLM 调用瞬间外部 mutator 改/删真源文件,模拟 mid-LLM race。

    用法:
      chat = MutatingFakeChat(VALID_PULSE, mutator=lambda: path.write_text("外部手编"))
      chat = MutatingFakeChat(VALID_PULSE, mutator=lambda: path.unlink())
    """
    def __init__(self, responses, mutator):
        super().__init__(responses)
        self._mutator = mutator

    def create(self, **kwargs):
        # 关键:先 mutate 再返 LLM 输出 — 模拟 LLM 在重写期间用户/外部进程改了文件
        self._mutator()
        return super().create(**kwargs)


def _inject_mutating_chat(monkeypatch, mutating_chat):
    """fixture 已 patch get_client 返默认 FakeChat,这里覆写指向 mutating 版"""
    monkeypatch.setattr(server, "get_client",
                        lambda profile: FakeClient(mutating_chat))


# ── 分支 ① external-edit:sha256 不一致 ───────────────────────────────

def test_external_edit_mid_llm_skips_and_pushes(
        stubbed_llm, isolated_pulse_paths, monkeypatch):
    """LLM 重写期间外部修改文件 → sha256 baseline 不一致 → skip + push 通知 + 不写盘"""
    path = isolated_pulse_paths.project
    original = (
        "<!-- ts:2026-06-10 -->\n"
        "# 一句话\n旧版协作日记\n\n"
        "## 现在\n🟢 healthy · 旧状态\n\n"
        "## Cannot break\n- ts 在\n"
    )
    path.write_text(original, encoding="utf-8")

    # mid-LLM:外部进程把用户手编的新版本写进去
    user_edited = (
        "<!-- ts:2026-06-18 -->\n"
        "# 一句话\n用户刚手编的版本 — 不能被 LLM 覆盖\n\n"
        "## 现在\n🟡 in progress · 手编中\n\n"
        "## Cannot break\n- ts 在\n"
    )
    mutator = lambda: path.write_text(user_edited, encoding="utf-8")
    _inject_mutating_chat(monkeypatch, MutatingFakeChat(VALID_PULSE, mutator))

    result = server._self_evolve_run("project_pulse", "对话原文")

    # 契约 1:返 graceful skip(HTTP 200 + skipped:true)
    assert result["ok"] is True
    assert result["skipped"] is True
    assert result["reason"] == "external-edit"
    assert result["target"] == "project_pulse"
    assert result["name"] == "项目 PULSE"

    # 契约 2:_push_notification 被调,kind 是 pulse-skip-external-edit
    assert len(stubbed_llm.push_calls) == 1, \
        f"应该刚好 1 次 push 通知,实际 {len(stubbed_llm.push_calls)}: {stubbed_llm.push_calls}"
    kind, payload = stubbed_llm.push_calls[0]
    assert kind == "pulse-skip-external-edit"
    assert "外部编辑" in payload["message"] or "LLM 重写期间被外部编辑" in payload["message"]
    assert payload["context"] == {"target": "project_pulse"}

    # 契约 3:用户手编内容保留,LLM 输出丢弃
    assert path.read_text(encoding="utf-8") == user_edited, \
        "用户手编必须保留,LLM 输出不能写回(silent-corruption 红线)"

    # 契约 4:vault_git 不被调(没有真正 commit)
    stubbed_llm.vault_git.assert_not_called()


# ── 分支 ② file-deleted mid-LLM (non-creating) ───────────────────────

def test_file_deleted_mid_llm_non_creating_skips_and_pushes(
        stubbed_llm, isolated_pulse_paths, monkeypatch):
    """project_pulse 文件先在,LLM 期间被删 → FileNotFoundError → file-deleted skip + push"""
    path = isolated_pulse_paths.project
    original = (
        "<!-- ts:2026-06-10 -->\n"
        "# 一句话\n旧版\n\n"
        "## 现在\n🟢 healthy\n\n"
        "## Cannot break\n- ts 在\n"
    )
    path.write_text(original, encoding="utf-8")

    # mid-LLM:外部进程删了文件(用户在 Finder/git checkout 把这文件移走)
    mutator = lambda: path.unlink()
    _inject_mutating_chat(monkeypatch, MutatingFakeChat(VALID_PULSE, mutator))

    result = server._self_evolve_run("project_pulse", "对话")

    # 契约 1:返 file-deleted skip
    assert result["ok"] is True
    assert result["skipped"] is True
    assert result["reason"] == "file-deleted"
    assert result["target"] == "project_pulse"
    assert result["name"] == "项目 PULSE"

    # 契约 2:_push_notification 调 pulse-skip-external-edit
    assert len(stubbed_llm.push_calls) == 1
    kind, payload = stubbed_llm.push_calls[0]
    assert kind == "pulse-skip-external-edit"
    assert "删除" in payload["message"]
    assert payload["context"] == {"target": "project_pulse"}

    # 契约 3:文件仍不存在,LLM 输出没被偷偷写回
    assert not path.exists(), "文件被删后 LLM 输出不能写回创建新文件"

    # 契约 4:vault_git 不被调
    stubbed_llm.vault_git.assert_not_called()


# ── 分支 ③ file-deleted mid-LLM (creating=True bootstrap) ────────────

def test_file_deleted_during_user_pulse_bootstrap_creates_anyway(
        stubbed_llm, isolated_pulse_paths, monkeypatch):
    """user_pulse bootstrap 中,文件本就不存在 → FileNotFoundError 进 creating 分支
    → 跳过 push,继续写首版,bootstrap=True
    """
    path = isolated_pulse_paths.user
    assert not path.exists(), "起点:user_pulse 不存在(triggers create_if_absent)"

    # mid-LLM mutator 是 no-op:文件本来就不存在,read 自然 FileNotFoundError;
    # 关键是验 creating=True 分支跳过 push、继续写。
    # 但更严格:用一个会"删"路径的 mutator 也行(不存在就 unlink 抛 FileNotFoundError,
    # 用 missing_ok=True 兜)— 验 creating 分支不被这个 mutator 影响
    def mutator():
        # 双保险:如果意外存在就删,确保 read_text 抛 FileNotFoundError
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    _inject_mutating_chat(monkeypatch, MutatingFakeChat(VALID_PULSE, mutator))

    result = server._self_evolve_run("user_pulse", "对话原文 ABC")

    # 契约 1:不 skip,真创建
    assert result["ok"] is True
    assert result.get("skipped") is not True, \
        "user_pulse creating 模式 FileNotFoundError 不该当 file-deleted skip"
    assert result["bootstrap"] is True
    assert result["target"] == "user_pulse"

    # 契约 2:文件真被写入(首版)
    assert path.exists(), "首版应该真写到盘上"
    written = path.read_text(encoding="utf-8")
    # 用 strip 比对:_self_evolve_run 会 strip LLM 输出尾部空白,这是已知行为
    assert written.strip() == VALID_PULSE.strip(), \
        f"LLM 输出真写盘(内容契约),实际:{written!r}"
    assert "<!-- ts:" in written, "首版必带 ts 标记"
    assert "# 一句话" in written, "首版必有 H1"

    # 契约 3:_push_notification 没被调 pulse-skip-external-edit(creating 分支跳过 push)
    skip_pushes = [p for p in stubbed_llm.push_calls
                   if p[0] == "pulse-skip-external-edit"]
    assert len(skip_pushes) == 0, \
        f"creating 分支不该 push pulse-skip-external-edit,实际:{skip_pushes}"
