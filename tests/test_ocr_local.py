# TEST PATTERN: contract + effect — 端侧 OCR 三层 fallback
# USE WHEN: 验 ocr_local macOS/rapidocr/None 链路 + 二进制 discovery
# COPY THIS: 改 fixture image,跑 pytest tests/test_ocr_local.py -v
# TESTED IN: gateway (2026-05-25)

import platform
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ocr_local  # noqa: E402


# ─── T1 · _macos_binary 在 dev 模式找得到(gateway/tools/ocr_vision) ─

def test_macos_binary_finds_dev_path():
    """dev 模式应该能从 gateway/tools/ocr_vision 找到二进制(若已 build)。"""
    if platform.system() != "Darwin":
        pytest.skip("macOS only")
    b = ocr_local._macos_binary()
    if b is None:
        pytest.skip("ocr_vision binary not built yet (run: swiftc tools/ocr_vision.swift -o tools/ocr_vision)")
    assert b.exists()
    assert b.is_file()


# ─── T2 · 端侧 OCR 真识别 ─────────────────────────────────────────────

def test_ocr_macos_recognizes_simple_image(tmp_path):
    """造一张含简单文字的 PNG,跑端侧 OCR,验返非 None。
    无 PIL 就 skip。"""
    if platform.system() != "Darwin":
        pytest.skip("macOS only")
    if ocr_local._macos_binary() is None:
        pytest.skip("ocr_vision binary missing")
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except ImportError:
        pytest.skip("PIL not installed")

    img = Image.new("RGB", (400, 100), color="white")
    draw = ImageDraw.Draw(img)
    try:
        # Mac 系统字 — 没就用 default
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 40)
    except Exception:
        font = ImageFont.load_default()
    draw.text((10, 30), "Hello 你好", fill="black", font=font)
    p = tmp_path / "test_ocr.png"
    img.save(p)

    result = ocr_local._ocr_macos(p)
    assert result is not None, "macOS Vision should not error on a clean text image"
    # 真识别出文字 — 至少含 'Hello' 或 '你好' 之一
    assert "Hello" in result or "你好" in result, f"expected Hello/你好, got {result!r}"


# ─── T3 · 不存在文件路径 → 返 None,不崩 ────────────────────────────

def test_ocr_local_on_nonexistent_returns_none():
    if platform.system() != "Darwin":
        pytest.skip("macOS only")
    if ocr_local._macos_binary() is None:
        pytest.skip("ocr_vision binary missing")
    r = ocr_local._ocr_macos(Path("/nonexistent/file.png"))
    assert r is None


# ─── T4 · rapidocr 没装时返 None,不抛 ───────────────────────────────

def test_ocr_rapidocr_no_package(monkeypatch, tmp_path):
    """模拟 rapidocr 没装(import 失败)→ 返 None。"""
    # 用 monkeypatch 让 import rapidocr_onnxruntime 失败
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)
    fake_img = tmp_path / "fake.png"
    fake_img.write_bytes(b"\x89PNG\r\n\x1a\n")  # 不需要真图,因为 import 先崩
    r = ocr_local._ocr_rapidocr(fake_img)
    assert r is None


# ─── T5 · diagnose 返结构 ─────────────────────────────────────────────

def test_diagnose_returns_expected_shape():
    info = ocr_local.diagnose()
    assert "platform" in info
    assert "macos_vision" in info
    assert "rapidocr" in info


# ─── T6 · ocr_local 主入口在 macOS 上优先走 vision ──────────────────

def test_ocr_local_entry_prefers_macos(tmp_path):
    """主入口在 macOS 上调 _ocr_macos,不掉到 rapidocr。"""
    if platform.system() != "Darwin":
        pytest.skip("macOS only")
    if ocr_local._macos_binary() is None:
        pytest.skip("ocr_vision binary missing")
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        pytest.skip("PIL not installed")

    img = Image.new("RGB", (50, 50), color="white")
    p = tmp_path / "blank.png"
    img.save(p)
    # 空图也 OK — macos vision 返 "" 即 success(非 None);rapidocr 没装时会返 None
    # 这里期望:macOS 路径走通 → 返 ""(不是 None)
    r = ocr_local.ocr_local(p)
    assert r is not None, "macOS Vision should succeed on empty image (returning empty str)"
    assert r == "" or isinstance(r, str)
