# TEST PATTERN: contract — P0 后台 init 不堵 server bind
# USE WHEN: 验 startup 重活挪后台 + /api/init-status 进度契约
# COPY THIS: monkeypatch 两个 step,验编排顺序 + ready 兜底
# TESTED IN: gateway (2026-06-10)
#
# 边界:
#   T1 init-status 初始 not ready
#   T2 后台 init 按序跑 git→audit 后置 ready
#   T3 某步崩也置 ready(finally 兜底,不困住前端初始化屏)

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


def _reset():
    server._INIT_STATE.update(
        {"ready": False, "phase": "starting", "detail": "",
         "started_at": None, "finished_at": None, "error": None}
    )


def test_init_status_initial_not_ready():
    _reset()
    s = server.api_init_status()
    assert s["ready"] is False
    assert s["phase"] == "starting"
    # 返的是副本,外部改不动内部
    s["ready"] = True
    assert server._INIT_STATE["ready"] is False


def test_background_init_runs_steps_in_order_then_ready(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_vault_git_init_step", lambda: calls.append("git"))
    monkeypatch.setattr(server, "_vault_audit_step", lambda: calls.append("audit"))
    _reset()
    server._background_vault_init()
    assert calls == ["git", "audit"], "git 必须先于 audit(audit 依赖 repo 在)"
    assert server._INIT_STATE["ready"] is True
    assert server._INIT_STATE["phase"] == "ready"
    assert server._INIT_STATE["error"] is None


def test_background_init_readies_even_if_step_crashes(monkeypatch):
    def boom():
        raise RuntimeError("git broke")
    monkeypatch.setattr(server, "_vault_git_init_step", boom)
    monkeypatch.setattr(server, "_vault_audit_step", lambda: None)
    _reset()
    server._background_vault_init()
    # finally 兜底:崩了也 ready,否则前端初始化屏永远转圈
    assert server._INIT_STATE["ready"] is True
    assert server._INIT_STATE["error"] is not None
    assert "git broke" in server._INIT_STATE["error"]
