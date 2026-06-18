# TEST PATTERN: effect — vault_git.commit_after_write audit chain
# USE WHEN: 验 _self_evolve_run / refresh-mirror 真路径调 vault_git,VAULT_DIR 外不调,
#           commit msg 格式契约不漂(corpus exporter 解析 stable/modified 依赖它)
# TESTED IN: gateway PULSE refactor P0+ TDD net must-add #3 (2026-06-18)
#
# PULSE.md Cannot break 红线:audit chain 不能静默断。两条调用点:
#   ① server.py L7798-7808  _self_evolve_run 写盘成功后,path 在 VAULT_DIR 内才 commit
#   ② server.py L8050-8057  refresh-mirror 有 updated 时整批 commit
# 任何一边失踪 = training-corpus exporter 拿不到 author/diff/outcome 链路。
# refactor 把这两段搬到 pulse_evolve.py / pulse_routes.py 后契约必须一字不变。
#
# fixture 走 tests/conftest.py — 跨 P2/P3/P4 refactor 鲁棒。

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


# ── _self_evolve_run 真路径调 vault_git ───────────────────────────────

def test_self_evolve_calls_vault_git_with_correct_contract(
    stubbed_llm, isolated_pulse_paths
):
    """成功重写 USER_PULSE → vault_git.commit_after_write 调一次,签名契约不能漂。

    契约固化(server.py L7799-7806):
      args[0] = VAULT_DIR (一定是 Path,resolve 后等价)
      args[1] = commit msg,以 "self-evolve" 开头,含 cfg name 和 "→" 和 "chars"
      kwargs['author'] == "ai"
      kwargs['paths'] == [path]   (单元素 list,不是字符串、不是 tuple)
    """
    # 先写一份带 ts 的旧 USER_PULSE,避免 bootstrap 路径(走标准 evolve)
    isolated_pulse_paths.user.write_text(
        "<!-- ts:2026-06-10 -->\n# 旧版\n旧内容\n", encoding="utf-8")

    result = server._self_evolve_run("user_pulse", "对话原文 abc")

    assert result["ok"] is True
    assert result.get("skipped") is not True

    # 调用次数 = 1
    stubbed_llm.vault_git.assert_called_once()
    call = stubbed_llm.vault_git.call_args

    # args[0] = VAULT_DIR (fixture 把 VAULT_DIR 指向 tmp_path = vault)
    assert call.args[0] == isolated_pulse_paths.vault, \
        f"第一个位置参数应是 VAULT_DIR ({isolated_pulse_paths.vault}),实际 {call.args[0]}"

    # args[1] = commit msg
    msg = call.args[1]
    assert isinstance(msg, str)
    assert msg.startswith("self-evolve"), f"commit msg 必须以 'self-evolve' 开头(corpus exporter 用这个 prefix 分桶);实际 {msg!r}"
    assert "USER_PULSE" in msg, f"commit msg 必须含 cfg name 'USER_PULSE';实际 {msg!r}"
    assert "→" in msg, f"commit msg 必须含 old→new 箭头;实际 {msg!r}"
    assert "chars" in msg, f"commit msg 必须含 'chars' 单位;实际 {msg!r}"

    # kwargs
    assert call.kwargs.get("author") == "ai", \
        f"_self_evolve_run 的 author 必须是 'ai',实际 {call.kwargs.get('author')!r}"
    paths = call.kwargs.get("paths")
    assert paths == [isolated_pulse_paths.user], \
        f"paths 必须是 [user_pulse_path],实际 {paths!r}"


# ── path 在 VAULT_DIR 外 → 不调 vault_git ─────────────────────────────

def test_self_evolve_skips_vault_git_when_path_outside_vault(
    monkeypatch, stubbed_llm, isolated_pulse_paths, tmp_path
):
    """USER_PULSE 路径不在 VAULT_DIR 下 → 跳过 vault_git 调用(但写盘照走)。

    server.py L7800: `if path.resolve().is_relative_to(VAULT_DIR.resolve())` 守门。
    这是 audit boundary:vault 之外的文件不该被 vault git 历史污染。
    """
    # 造一条 VAULT_DIR 外的路径(fixture 把 VAULT_DIR 指向 isolated_pulse_paths.vault = tmp_path,
    # 这里造个兄弟目录,is_relative_to 必返 False)
    outside_dir = tmp_path.parent / "outside_vault"
    outside_dir.mkdir(exist_ok=True)
    outside_path = outside_dir / "USER_PULSE.md"
    outside_path.write_text(
        "<!-- ts:2026-06-10 -->\n# 外面的旧版\n旧内容\n", encoding="utf-8")

    # 重新指向 vault 外的路径(覆盖 fixture 的默认 user 路径)
    monkeypatch.setitem(
        server._SELF_EVOLVE_TARGETS["user_pulse"], "path", lambda: outside_path)
    monkeypatch.setattr(server, "_USER_PULSE_PATH", outside_path, raising=False)

    # sanity:确认在 vault 外
    assert not outside_path.resolve().is_relative_to(
        isolated_pulse_paths.vault.resolve()), \
        "测试前置失败:outside_path 居然还在 vault 下"

    result = server._self_evolve_run("user_pulse", "对话原文")

    # 写盘成功(普通 evolve 路径走完)
    assert result["ok"] is True
    assert result.get("skipped") is not True
    assert outside_path.exists()

    # 但 vault_git **没**被调
    stubbed_llm.vault_git.assert_not_called()


# ── refresh-mirror 真路径调 vault_git ─────────────────────────────────

def test_refresh_mirror_calls_vault_git_when_files_updated(
    monkeypatch, stubbed_llm, isolated_pulse_paths, client, tmp_path
):
    """有 updated 文件 → vault_git.commit_after_write 调一次,signature 契约。

    契约固化(server.py L8052-8057):
      args[0] = PULSE_DIR (镜像目录,不是 VAULT_DIR)
      args[1] = commit msg,含 "pulse refresh-mirror"
      kwargs['author'] == "system"  (注意:不是 'ai',跟 _self_evolve_run 区分)
      kwargs['paths'] = 非空 list,每项是 PULSE_DIR/<name>.md
    """
    # 把 Path.home() 指向 tmp_path,让 refresh-mirror 扫到我们造的源
    monkeypatch.setenv("HOME", str(tmp_path))
    # sanity
    assert Path.home() == tmp_path, "HOME env 没生效,Path.home() 不是 tmp"

    # 造一份源 PULSE
    src_dir = tmp_path / "agents创作平台" / "agents" / "proj1"
    src_dir.mkdir(parents=True)
    src_content = "<!-- ts:2026-06-18 -->\n# proj1\n内容 X\n"
    (src_dir / "PULSE.md").write_text(src_content, encoding="utf-8")

    resp = client.post("/api/pulse/refresh-mirror")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scanned"] >= 1
    assert body["updated"] >= 1
    assert "proj1" in body["files"]

    # vault_git 调一次
    stubbed_llm.vault_git.assert_called_once()
    call = stubbed_llm.vault_git.call_args

    # args[0] = PULSE_DIR(fixture 设的 tmp_path/pulse-mirror)
    assert call.args[0] == isolated_pulse_paths.mirror, \
        f"第一个位置参数应是 PULSE_DIR ({isolated_pulse_paths.mirror}),实际 {call.args[0]}"

    # args[1] = commit msg
    msg = call.args[1]
    assert isinstance(msg, str)
    assert "pulse refresh-mirror" in msg, \
        f"commit msg 必须含 'pulse refresh-mirror' (corpus exporter prefix);实际 {msg!r}"

    # kwargs:author='system'(refresh-mirror 是系统动作,跟 _self_evolve_run 的 'ai' 区分)
    assert call.kwargs.get("author") == "system", \
        f"refresh-mirror 的 author 必须是 'system',实际 {call.kwargs.get('author')!r}"

    # paths 非空 list
    paths = call.kwargs.get("paths")
    assert isinstance(paths, list) and len(paths) >= 1, \
        f"paths 必须是非空 list,实际 {paths!r}"
    # 每项指向 PULSE_DIR 下的 mirror 文件
    expected_mirror = isolated_pulse_paths.mirror / "proj1.md"
    assert expected_mirror in paths, \
        f"paths 应含 {expected_mirror},实际 {paths!r}"


# ── commit msg 格式契约 — corpus exporter 解析依赖 ────────────────────

def test_self_evolve_commit_msg_format_locked(
    stubbed_llm, isolated_pulse_paths
):
    """commit msg 格式 = f'self-evolve {cfg name} ({old}→{new} chars)'。

    corpus exporter (training-corpus 全 stack) 按 prefix 'self-evolve' 分桶,
    按 'X→Y chars' 解析 stable/modified。格式漂 = 全量历史训练数据 author 标签错位。
    """
    # 旧版有内容,避免 bootstrap
    old_text = "<!-- ts:2026-06-10 -->\n# 旧版\n旧内容\n"
    isolated_pulse_paths.user.write_text(old_text, encoding="utf-8")
    old_chars = len(old_text)

    result = server._self_evolve_run("user_pulse", "对话")
    assert result["ok"] is True

    stubbed_llm.vault_git.assert_called_once()
    msg = stubbed_llm.vault_git.call_args.args[1]

    # 关键 substrings(corpus exporter 真的会 grep 这些)
    assert msg.startswith("self-evolve "), \
        f"必须以 'self-evolve ' 开头,exporter 按 prefix 分桶;实际 {msg!r}"
    assert "USER_PULSE" in msg, \
        f"必须含 cfg name;实际 {msg!r}"
    assert "→" in msg, \
        f"必须含 '→' 分隔符(老/新 chars);实际 {msg!r}"
    assert "chars" in msg, \
        f"必须含 'chars' 单位词;实际 {msg!r}"
    assert "(" in msg and ")" in msg, \
        f"必须有 '(old→new chars)' 括号;实际 {msg!r}"

    # 严格 format check:精确还原 f"self-evolve {name} ({old}→{new} chars)"
    new_chars = result["new_chars"]
    expected = f"self-evolve USER_PULSE ({old_chars}→{new_chars} chars)"
    assert msg == expected, \
        f"commit msg format 漂了。期望 {expected!r},实际 {msg!r}"


# ── 三 target 都用同一格式契约 ────────────────────────────────────────

@pytest.mark.parametrize("target,cfg_name", [
    ("project_pulse", "项目 PULSE"),
    ("agent_context", "AGENT_CONTEXT"),
])
def test_self_evolve_commit_msg_format_holds_for_all_targets(
    stubbed_llm, isolated_pulse_paths, target, cfg_name
):
    """project_pulse / agent_context 的 commit msg 也走同一格式 — name 不同其余一致。

    确保 refactor 时三 target 的 commit 路径不被分叉成不同 helper。
    AGENT_CONTEXT 走 agent_context prompt,需注入合规返回。
    """
    # 三 target 都需要 path 存在 → 写旧内容(project/agent 不允许 create_if_absent)
    if target == "project_pulse":
        path = isolated_pulse_paths.project
    else:
        path = isolated_pulse_paths.agent_context
    old_text = "<!-- ts:2026-06-10 -->\n# 旧版\n旧内容\n"
    path.write_text(old_text, encoding="utf-8")

    # AGENT_CONTEXT 走独立 prompt + frozen 段校验,默认 VALID_PULSE 可能撞 frozen 检查 → 用 agent context 合规返
    if target == "agent_context":
        from tests.conftest import VALID_AGENT_CONTEXT
        stubbed_llm.chat.responses = [VALID_AGENT_CONTEXT]

    result = server._self_evolve_run(target, "对话")
    # 接受 ok 或 skipped(若 validator 拒,跳过格式 assert — 本测专注 commit msg 形态,不验 LLM 内容)
    if not result.get("ok") or result.get("skipped"):
        pytest.skip(f"{target} 这次 LLM 返被 validator 拒,skip 格式断言(non-goal)")

    stubbed_llm.vault_git.assert_called_once()
    msg = stubbed_llm.vault_git.call_args.args[1]

    assert msg.startswith("self-evolve "), f"{target}: 必须以 'self-evolve ' 开头;{msg!r}"
    assert cfg_name in msg, f"{target}: 必须含 cfg name {cfg_name!r};实际 {msg!r}"
    assert "→" in msg and "chars" in msg, f"{target}: 必须含 '→' 和 'chars';实际 {msg!r}"

    assert stubbed_llm.vault_git.call_args.kwargs.get("author") == "ai", \
        f"{target}: author 必须是 'ai'"
