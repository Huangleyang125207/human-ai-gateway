"""本地端侧抠图 — 替换原来"必须联网调百度"的 baseline。

backend 优先级(按当前平台自动选,不让用户配):
  1. macOS Subject Lift  — tools/cutout_subject_lift 二进制,系统 Vision API,
     ~200ms,质量顶级。无依赖,无下载。
  2. rembg (u2net ONNX)  — 跨平台,Linux/Win/老 macOS 都能跑。模型 176MB 由
     prewarm_u2net() 首启后台从自家 COS 镜像预热到 ~/.u2net/(rembg 内置的
     GitHub 下载在大陆不可达);之后离线推理,session 进程内复用。
  3. None  — 上面都失败 → 返 None,调用方走 Baidu fallback 或直接放原图。

调用 entry: cutout_local(src_path: Path) → bytes | None  (PNG 字节,失败 None)
"""
from __future__ import annotations
import os
import platform
import subprocess
import sys
import tempfile
import threading
import logging
from pathlib import Path

log = logging.getLogger("cutout_local")

# silent-failure 上报针脚 — 跟 cutout.py 同款模式,server import-time 注入;
# 没注入时静默(library 独立可用)。本地抠图死因必须分桶可区分:
# import 失败(打包断链,lxml 复刻位)/ session 失败(模型缺失或加载崩)/ 推理失败。
_FAILURE_SINK = None


def set_failure_sink(sink) -> None:
    global _FAILURE_SINK
    _FAILURE_SINK = sink


def _emit_failure(error_type: str, message: str = "", context: dict = None) -> None:
    if _FAILURE_SINK is None:
        return
    try:
        _FAILURE_SINK(error_type, message, context or {})
    except Exception:
        pass


# ── u2net 模型预热(绕开 rembg 内置 GitHub 下载,大陆不可达)──────────────
# rembg 钉死 v0.0.0 资产 + md5,模型内容永不变 → 自家 COS 镜像一次永不再传。
# pooch 对"文件已存在 + md5 命中"不联网,把文件放进 ~/.u2net/ 即根治,零侵入。
U2NET_MD5 = "60024c5c889badc19c04ad937298a77b"   # rembg sessions/u2net.py 钉死的值
U2NET_SIZE = 175_997_641
U2NET_MIRROR_URL = "https://gateway-updates-1341853738.cos.ap-shanghai.myqcloud.com/models/u2net.onnx"


def _u2net_path() -> Path:
    return Path(os.environ.get("U2NET_HOME", str(Path.home() / ".u2net"))) / "u2net.onnx"


def u2net_model_ready() -> bool:
    p = _u2net_path()
    return p.exists() and p.stat().st_size == U2NET_SIZE


def prewarm_u2net() -> dict:
    """首启后台预热:从自家 COS 拉 u2net.onnx 到 rembg 的默认目录。
    幂等:已就绪直接返回。失败分桶上报但不 raise(预热挂了走原有兜底链)。
    macOS 有 Subject Lift 二进制时跳过 — rembg 在那是从不命中的冷路径,
    不值得让全体 Mac 用户多扛 176MB。
    """
    if platform.system() == "Darwin" and _macos_binary() is not None:
        return {"skipped": "darwin-subject-lift"}
    p = _u2net_path()
    if u2net_model_ready():
        return {"ready": True, "cached": True}
    import hashlib
    import requests
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"u2net.onnx.{os.getpid()}.tmp")
    try:
        h = hashlib.md5()
        with requests.get(U2NET_MIRROR_URL, stream=True, timeout=60) as r:
            r.raise_for_status()
            with tmp.open("wb") as fh:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    fh.write(chunk)
                    h.update(chunk)
        if h.hexdigest() != U2NET_MD5:
            _emit_failure("u2net_prewarm_md5_mismatch",
                          f"got {h.hexdigest()}", {"url": U2NET_MIRROR_URL})
            return {"error": "md5-mismatch"}
        tmp.replace(p)
        log.info(f"u2net model prewarmed to {p}")
        return {"ready": True, "downloaded": True}
    except Exception as e:
        _emit_failure("u2net_prewarm_download_failed",
                      f"{type(e).__name__}: {str(e)[:120]}", {"url": U2NET_MIRROR_URL})
        return {"error": type(e).__name__}
    finally:
        tmp.unlink(missing_ok=True)


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
        _emit_failure("subject_lift_failed", f"rc={r.returncode} {r.stderr[:80]!r}")
        return None
    except Exception as e:
        log.warning(f"macOS subject-lift exception: {e}")
        _emit_failure("subject_lift_failed", f"{type(e).__name__}: {str(e)[:120]}")
        return None
    finally:
        out_path.unlink(missing_ok=True)


# rembg session 进程内复用:不传 session 时 rembg 每次调用都重建 InferenceSession
# + 全量重读 176MB 算 md5(Windows CPU 每图多 2-6s + 数百 MB 内存峰值)。缓存一次。
_REMBG_SESSION = None
_REMBG_SESSION_LOCK = threading.Lock()


def _get_rembg_session():
    global _REMBG_SESSION
    if _REMBG_SESSION is None:
        with _REMBG_SESSION_LOCK:
            if _REMBG_SESSION is None:
                from rembg import new_session
                _REMBG_SESSION = new_session("u2net")
    return _REMBG_SESSION


def _cutout_rembg(src_path: Path) -> bytes | None:
    """rembg lazy import — 三段分桶:import / session(模型) / 推理。失败返 None。"""
    try:
        from rembg import remove  # type: ignore
    except ImportError as e:
        # 打包断链时这里就是唯一信号(lxml 复刻位)— 必须远程可见
        log.info("rembg not importable; skipping local ONNX cutout")
        _emit_failure("rembg_import_failed", f"{type(e).__name__}: {str(e)[:120]}",
                      {"frozen": bool(getattr(sys, "frozen", False))})
        return None
    try:
        session = _get_rembg_session()
    except Exception as e:
        _emit_failure("rembg_session_failed", f"{type(e).__name__}: {str(e)[:120]}",
                      {"model_ready": u2net_model_ready()})
        log.warning(f"rembg session failed: {e}")
        return None
    try:
        return remove(src_path.read_bytes(), session=session)
    except Exception as e:
        log.warning(f"rembg failed: {e}")
        _emit_failure("rembg_inference_failed", f"{type(e).__name__}: {str(e)[:120]}")
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
    info = {"platform": platform.system(), "macos_subject_lift": None, "rembg": None,
            "u2net_model_ready": u2net_model_ready()}
    if platform.system() == "Darwin":
        b = _macos_binary()
        info["macos_subject_lift"] = {"available": b is not None, "path": str(b) if b else None}
    try:
        import rembg  # noqa: F401
        info["rembg"] = {"available": True, "version": getattr(__import__("rembg"), "__version__", "?")}
    except ImportError:
        info["rembg"] = {"available": False, "version": None}
    return info
