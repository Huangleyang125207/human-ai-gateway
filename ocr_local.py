"""本地端侧 OCR — 替原来"必须联网调百度"的 baseline。

完全镜像 cutout_local.py 的三层 fallback 设计。

backend 优先级(按当前平台自动选,不让用户配):
  1. macOS Vision Framework — tools/ocr_vision 二进制,系统 VNRecognizeTextRequest,
     ~150-400ms,简繁中文 + 英 + 日韩都好。无依赖,无下载。
  2. rapidocr-onnxruntime — 跨平台 PaddleOCR ONNX,Linux/Win/老 macOS 都能跑。
     首次自动下 ~50MB 模型(det+cls+rec),之后离线 1-3s 推理。
  3. None — 上面都失败 → 返 None,调用方走 Baidu fallback 或不 OCR。

调用 entry: ocr_local(src_path: Path) → str | None  (文本字符串,失败 None)
"""
from __future__ import annotations
import logging
import platform
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("ocr_local")


# 二进制位置:dev 时是 GATEWAY_DIR/tools/,frozen 时是 _MEIPASS/tools/
def _macos_binary() -> Path | None:
    """找 ocr_vision 二进制。dev + PyInstaller frozen 都兜得住。"""
    candidates = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "tools" / "ocr_vision")
        # .app bundle: _MEIPASS 在 Frameworks/,资源真在 Resources/
        candidates.append(Path(sys._MEIPASS).parent / "Resources" / "tools" / "ocr_vision")
    candidates.append(Path(__file__).parent / "tools" / "ocr_vision")
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    return None


def _ocr_macos(src_path: Path) -> str | None:
    """调 macOS Vision binary。失败返 None,识别但无文字返空字符串(都算成功)。"""
    binary = _macos_binary()
    if not binary:
        return None
    try:
        r = subprocess.run(
            [str(binary), str(src_path)],
            capture_output=True, timeout=20, text=True,
        )
        if r.returncode == 0:
            # stdout 是识别出的文本(\n 分行),空也算成功
            return r.stdout.rstrip("\n")
        log.warning(f"macOS ocr_vision failed (rc={r.returncode}): {r.stderr.strip()[:200]}")
        return None
    except Exception as e:
        log.warning(f"macOS ocr_vision exception: {e}")
        return None


def _ocr_rapidocr(src_path: Path) -> str | None:
    """rapidocr-onnxruntime lazy import — 没装就返 None。
    首次调用会下载 ~50MB 模型到 ~/.cache/rapidocr/(rapidocr 自管缓存)。
    """
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
    except ImportError:
        log.info("rapidocr-onnxruntime not installed; skipping ONNX OCR fallback")
        return None
    try:
        ocr = RapidOCR()
        result, _ = ocr(str(src_path))
        if not result:
            return ""  # 识别但无文字
        # result 是 [[box, text, confidence], ...]
        lines = [item[1] for item in result if len(item) >= 2 and item[1]]
        return "\n".join(lines)
    except Exception as e:
        log.warning(f"rapidocr failed: {type(e).__name__}: {e}")
        return None


def ocr_local(src_path: Path) -> str | None:
    """主入口。按平台尝试 macOS → rapidocr → None。
    成功返文本字符串(可能空 = 图里没文字);失败返 None(调用方决定 fallback)。

    注意 macOS vs rapidocr 语义区分:
      - macOS:返 ""(空)= 真没文字;None = binary 出错
      - rapidocr:返 ""(空)= 真没文字;None = 没装 / 推理崩
    """
    if platform.system() == "Darwin":
        result = _ocr_macos(src_path)
        if result is not None:
            return result
    return _ocr_rapidocr(src_path)


def diagnose() -> dict:
    """返当前平台可用的 backend 状态,for 设置页 / 启动 self-check。"""
    info = {"platform": platform.system(), "macos_vision": None, "rapidocr": None}
    if platform.system() == "Darwin":
        b = _macos_binary()
        info["macos_vision"] = {"available": b is not None, "path": str(b) if b else None}
    try:
        import rapidocr_onnxruntime  # noqa: F401
        info["rapidocr"] = {"available": True}
    except ImportError:
        info["rapidocr"] = {"available": False}
    return info
