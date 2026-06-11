# TEST PATTERN: effect — u2net 模型预热 + 本地抠图分桶上报
# USE WHEN: 验 prewarm 幂等/md5 守门/失败上报;rembg 三段死因分桶;session 复用
# TESTED IN: gateway (2026-06-11)
#
# 背景:Windows 端 rembg 是唯一端侧抠图,模型内置下载源是 GitHub(大陆不可达),
# 失败全被吞成 None 远程不可见(lxml 复刻位)。修:自家 COS 预热 + 分桶 sink。

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cutout_local  # noqa: E402


@pytest.fixture
def sink():
    events = []
    cutout_local.set_failure_sink(lambda et, msg, ctx: events.append((et, msg, ctx)))
    yield events
    cutout_local.set_failure_sink(None)


@pytest.fixture
def u2net_home(tmp_path, monkeypatch):
    monkeypatch.setenv("U2NET_HOME", str(tmp_path))
    return tmp_path


class _FakeResp:
    def __init__(self, chunks, status=200):
        self._chunks = chunks
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_prewarm_skips_when_model_ready(u2net_home, monkeypatch, sink):
    f = u2net_home / "u2net.onnx"
    f.write_bytes(b"x")
    monkeypatch.setattr(cutout_local, "U2NET_SIZE", 1)
    monkeypatch.setattr(cutout_local.platform, "system", lambda: "Windows")
    out = cutout_local.prewarm_u2net()
    assert out == {"ready": True, "cached": True}
    assert sink == []


def test_prewarm_downloads_and_verifies_md5(u2net_home, monkeypatch, sink):
    import hashlib
    payload = b"fake-model-bytes"
    monkeypatch.setattr(cutout_local, "U2NET_MD5", hashlib.md5(payload).hexdigest())
    monkeypatch.setattr(cutout_local, "U2NET_SIZE", len(payload))
    monkeypatch.setattr(cutout_local.platform, "system", lambda: "Windows")
    fake_requests = types.SimpleNamespace(get=lambda *a, **k: _FakeResp([payload]))
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    out = cutout_local.prewarm_u2net()
    assert out == {"ready": True, "downloaded": True}
    assert (u2net_home / "u2net.onnx").read_bytes() == payload
    assert sink == []


def test_prewarm_md5_mismatch_reports_and_keeps_nothing(u2net_home, monkeypatch, sink):
    monkeypatch.setattr(cutout_local, "U2NET_MD5", "0" * 32)
    monkeypatch.setattr(cutout_local.platform, "system", lambda: "Windows")
    fake_requests = types.SimpleNamespace(get=lambda *a, **k: _FakeResp([b"corrupted"]))
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    out = cutout_local.prewarm_u2net()
    assert out == {"error": "md5-mismatch"}
    assert not (u2net_home / "u2net.onnx").exists(), "坏文件不能落到模型位"
    assert not list(u2net_home.glob("*.tmp")), "tmp 残留要清掉"
    assert sink and sink[0][0] == "u2net_prewarm_md5_mismatch"


def test_prewarm_download_failure_reports(u2net_home, monkeypatch, sink):
    monkeypatch.setattr(cutout_local.platform, "system", lambda: "Windows")

    def boom(*a, **k):
        raise ConnectionError("net down")

    fake_requests = types.SimpleNamespace(get=boom)
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    out = cutout_local.prewarm_u2net()
    assert out["error"] == "ConnectionError"
    assert sink and sink[0][0] == "u2net_prewarm_download_failed"


def test_prewarm_skips_on_darwin_with_subject_lift(monkeypatch, sink):
    monkeypatch.setattr(cutout_local.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(cutout_local, "_macos_binary", lambda: Path("/fake/bin"))
    out = cutout_local.prewarm_u2net()
    assert out == {"skipped": "darwin-subject-lift"}


def test_rembg_import_failure_bucketed(monkeypatch, sink, tmp_path):
    """打包断链(lxml 复刻位)必须有专属桶远程可见。"""
    monkeypatch.setitem(sys.modules, "rembg", None)  # import rembg → ImportError
    img = tmp_path / "a.png"
    img.write_bytes(b"img")
    out = cutout_local._cutout_rembg(img)
    assert out is None
    assert sink and sink[0][0] == "rembg_import_failed"


def test_rembg_session_reused_across_calls(monkeypatch, sink, tmp_path):
    """session 进程内复用:两次抠图只建一次 session,且 remove 带 session 调。"""
    calls = {"new_session": 0, "remove": []}

    def fake_new_session(name):
        calls["new_session"] += 1
        return f"session-{name}"

    def fake_remove(data, session=None):
        calls["remove"].append(session)
        return b"png-bytes"

    fake_rembg = types.ModuleType("rembg")
    fake_rembg.new_session = fake_new_session
    fake_rembg.remove = fake_remove
    monkeypatch.setitem(sys.modules, "rembg", fake_rembg)
    monkeypatch.setattr(cutout_local, "_REMBG_SESSION", None)
    img = tmp_path / "a.png"
    img.write_bytes(b"img")

    assert cutout_local._cutout_rembg(img) == b"png-bytes"
    assert cutout_local._cutout_rembg(img) == b"png-bytes"
    assert calls["new_session"] == 1, "session 只建一次"
    assert calls["remove"] == ["session-u2net", "session-u2net"]
    assert sink == []
    monkeypatch.setattr(cutout_local, "_REMBG_SESSION", None)  # 还原全局


def test_rembg_inference_failure_bucketed(monkeypatch, sink, tmp_path):
    fake_rembg = types.ModuleType("rembg")
    fake_rembg.new_session = lambda name: "s"

    def bad_remove(data, session=None):
        raise ValueError("bad tensor")

    fake_rembg.remove = bad_remove
    monkeypatch.setitem(sys.modules, "rembg", fake_rembg)
    monkeypatch.setattr(cutout_local, "_REMBG_SESSION", None)
    img = tmp_path / "a.png"
    img.write_bytes(b"img")
    assert cutout_local._cutout_rembg(img) is None
    assert sink and sink[0][0] == "rembg_inference_failed"
    monkeypatch.setattr(cutout_local, "_REMBG_SESSION", None)
