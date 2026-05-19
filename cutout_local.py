"""本地端侧抠图 — 替换原来"必须联网调百度"的 baseline。

backend 优先级(按当前平台自动选,不让用户配):
  1. macOS Subject Lift  — tools/cutout_subject_lift 二进制,系统 Vision API,
     ~200ms,质量顶级。无依赖,无下载。
  2. rembg (u2net ONNX)  — 跨平台,Linux/Win/老 macOS 都能跑。首次自动下 176MB
     模型到 ~/.u2net/,之后离线 ~1-3s 推理。
  3. None  — 上面都失败 → 返 None,调用方走 Baidu fallback 或直接放原图。

调用 entry: cutout_local(src_path: Path) → bytes | None  (PNG 字节,失败 None)
"""
from __future__ import annotations
import platform
import subprocess
import sys
import tempfile
import logging
from pathlib import Path

log = logging.getLogger("cutout_local")

# 二进制位置:dev 时是 GATEWAY_DIR/tools/,frozen 时是 _MEIPASS/tools/
def _macos_binary() -> Path | None:
    """找 cutout_subject_lift 二进制。dev + PyInstaller frozen 都兜得住。"""
    candidates = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "tools" / "cutout_subject_lift")
        # .app bundle: _MEIPASS 在 Frameworks/,资源真在 Resources/
        candidates.append(Path(sys._MEIPASS).parent / "Resources" / "tools" / "cutout_subject_lift")
    candidates.append(Path(__file__).parent / "tools" / "cutout_subject_lift")
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    return None


def _cutout_macos(src_path: Path) -> bytes | None:
    """调 Swift Subject Lift 二进制。失败返 None。"""
    binary = _macos_binary()
    if not binary:
        return None
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        out_path = Path(tf.name)
    try:
        r = subprocess.run(
            [str(binary), str(src_path), str(out_path)],
            capture_output=True, timeout=15, text=True,
        )
        if r.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
            return out_path.read_bytes()
        log.warning(f"macOS subject-lift failed (rc={r.returncode}): {r.stdout!r} {r.stderr!r}")
        return None
    except Exception as e:
        log.warning(f"macOS subject-lift exception: {e}")
        return None
    finally:
        out_path.unlink(missing_ok=True)


def _cutout_rembg(src_path: Path) -> bytes | None:
    """rembg lazy import — 没装就返 None。"""
    try:
        from rembg import remove  # type: ignore
    except ImportError:
        log.info("rembg not installed; skipping local ONNX cutout")
        return None
    try:
        return remove(src_path.read_bytes())
    except Exception as e:
        log.warning(f"rembg failed: {e}")
        return None


def cutout_local(src_path: Path) -> bytes | None:
    """主入口。按平台尝试 macOS → rembg → None。
    成功返 PNG bytes,失败返 None(调用方自己决定 fallback 策略)。
    """
    if platform.system() == "Darwin":
        result = _cutout_macos(src_path)
        if result:
            return result
    return _cutout_rembg(src_path)


def diagnose() -> dict:
    """返当前平台可用的 backend 状态,for 设置页 / 启动 self-check。"""
    info = {"platform": platform.system(), "macos_subject_lift": None, "rembg": None}
    if platform.system() == "Darwin":
        b = _macos_binary()
        info["macos_subject_lift"] = {"available": b is not None, "path": str(b) if b else None}
    try:
        import rembg  # noqa: F401
        info["rembg"] = {"available": True, "version": getattr(__import__("rembg"), "__version__", "?")}
    except ImportError:
        info["rembg"] = {"available": False, "version": None}
    return info
