"""
gateway/cutout.py — 百度智能云「智能抠图」客户端

走 /image-process/v1/segment, JSON body, 返 base64 透明 PNG。
复用 ocr.py 的 _get_access_token (同一 OAuth 体系,token 通用)。

decision: 跟 OCR 同一对 key,不需要新账号。100 次/月免费,后 0.03/次。
revisit if: 100 次不够 / 边缘抠不干净 → 切 remove.bg(50/月免费,$0.20/次)。

API 文档: https://cloud.baidu.com/doc/IMAGEPROCESS/s/rm8zl3koj

用法:
  from cutout import baidu_cutout_image
  png_bytes = baidu_cutout_image(file_path, api_key, secret_key)  # 失败返 None
"""
from __future__ import annotations

import base64
import io
import json
import logging
from pathlib import Path

import requests

from ocr import _get_access_token  # 复用 token 缓存

# B-#6: silent-failure sink, server.py 启动时注入
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

log = logging.getLogger("cutout")

_ENDPOINT = "https://aip.baidubce.com/rest/2.0/image-process/v1/segment"
# 百度限制:base64 后 ≤ 10MB,长边 ≤ 3000px,短边 ≥ 128px
_MAX_EDGE_PX = 2800
_MIN_EDGE_PX = 128
_MAX_BASE64_BYTES = int(9 * 1024 * 1024)


def _prep_image_bytes(file_path: Path) -> bytes | None:
    """读图,如超百度限就 resize / 重编码。返 bytes 或 None。"""
    raw = file_path.read_bytes()
    base64_size = (len(raw) + 2) // 3 * 4
    try:
        from PIL import Image
    except ImportError:
        if base64_size > _MAX_BASE64_BYTES:
            log.warning(f"image too large for cutout and Pillow not installed")
        return raw

    try:
        img = Image.open(io.BytesIO(raw))
        w, h = img.size
        long_edge, short_edge = max(w, h), min(w, h)
        if (long_edge <= _MAX_EDGE_PX and short_edge >= _MIN_EDGE_PX
                and base64_size <= _MAX_BASE64_BYTES):
            return raw
        # 等比缩
        scale = 1.0
        if long_edge > _MAX_EDGE_PX:
            scale = _MAX_EDGE_PX / long_edge
        new_size = (max(int(w * scale), _MIN_EDGE_PX), max(int(h * scale), _MIN_EDGE_PX))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        img = img.resize(new_size, Image.LANCZOS)
        for q in (90, 80, 70, 60):
            buf = io.BytesIO()
            # 抠图前用 JPG 提交即可(server 会返 PNG); 节省体积
            img.convert("RGB").save(buf, format="JPEG", quality=q, optimize=True)
            data = buf.getvalue()
            if (len(data) + 2) // 3 * 4 <= _MAX_BASE64_BYTES:
                log.info(f"cutout resized {w}x{h} → {new_size[0]}x{new_size[1]} q={q} ({len(data)} bytes)")
                return data
        return data
    except Exception as e:
        log.warning(f"image prep failed: {type(e).__name__}: {e}")
        return raw


def normalize_subject_frame(png_bytes: bytes,
                             padding_ratio: float = 0.08,
                             target_size: int = 1024) -> bytes:
    """裁到主体 alpha 外框 → 等比缩使主体长边 = target × (1 − 2×padding) → 居中放方形透明画布。
    保证瘦长瓶/矮胖罐/方块罐显示时长边视觉大小一致。
    旧版按 bbox 长边 + pad 做画布尺寸 → 瘦长画布瘦长,object-fit:contain 后视觉小一截。
    """
    try:
        from PIL import Image
    except ImportError:
        return png_bytes
    try:
        img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        alpha = img.split()[3]
        bbox = alpha.point(lambda v: 255 if v > 8 else 0).getbbox()
        if not bbox:
            return png_bytes
        cropped = img.crop(bbox)
        cw, ch = cropped.size
        # 主体长边目标尺寸(留 padding_ratio 透明边)
        subject_target = max(1, int(target_size * (1 - 2 * padding_ratio)))
        scale = subject_target / max(cw, ch)
        new_w = max(1, int(round(cw * scale)))
        new_h = max(1, int(round(ch * scale)))
        scaled = cropped.resize((new_w, new_h), Image.LANCZOS)
        canvas = Image.new("RGBA", (target_size, target_size), (0, 0, 0, 0))
        ox = (target_size - new_w) // 2
        oy = (target_size - new_h) // 2
        canvas.paste(scaled, (ox, oy), scaled)
        out = io.BytesIO()
        canvas.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception as e:
        log.warning(f"normalize_subject_frame failed: {type(e).__name__}: {e}")
        return png_bytes


def _whiten_to_transparent(png_bytes: bytes,
                           opaque_max: int = 220,
                           transparent_min: int = 250) -> bytes:
    """Baidu segment 实测常返白底而非透明,这里把白色软化成透明。
    像素的 min(R,G,B):
      ≤ opaque_max     → alpha 保留 (确实是物体)
      ≥ transparent_min → alpha = 0  (背景)
      中间             → alpha 线性渐变 (柔和边缘,避免锯齿)
    """
    try:
        from PIL import Image
    except ImportError:
        return png_bytes  # 没 Pillow 就放弃后处理
    try:
        img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        data = img.getdata()
        span = max(transparent_min - opaque_max, 1)
        new_data = []
        for r, g, b, a in data:
            min_ch = r if r < g else g
            if b < min_ch:
                min_ch = b
            if min_ch >= transparent_min:
                new_data.append((r, g, b, 0))
            elif min_ch <= opaque_max:
                new_data.append((r, g, b, a))
            else:
                # 渐变带:越接近白越透明
                fade = int(a * (transparent_min - min_ch) / span)
                new_data.append((r, g, b, fade))
        img.putdata(new_data)
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception as e:
        log.warning(f"whiten_to_transparent failed: {type(e).__name__}: {e}")
        return png_bytes


def baidu_cutout_image(file_path: Path | str, api_key: str, secret_key: str) -> bytes | None:
    """对单张本地图片去背,返回透明 PNG 的 bytes。失败返 None。"""
    f = Path(file_path)
    if not f.exists():
        return None
    if not api_key or not secret_key or api_key.startswith("YOUR_") or secret_key.startswith("YOUR_"):
        log.warning("baidu key not configured")
        return None

    token = _get_access_token(api_key, secret_key)
    if not token:
        return None

    img_bytes = _prep_image_bytes(f)
    if img_bytes is None:
        return None
    b64 = base64.b64encode(img_bytes).decode("ascii")

    try:
        r = requests.post(
            _ENDPOINT,
            params={"access_token": token},
            data=json.dumps({
                "image": b64,
                "method": "auto",       # 自动主体检测
                "refine_mask": "true",  # 边缘平滑
                "return_form": "rgba",  # 透明 PNG (vs "mask" = 黑白蒙版)
            }),
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        if "error_code" in data:
            code = int(data.get("error_code") or 0)
            msg = str(data.get("error_msg") or "")[:120]
            log.warning(f"baidu cutout error {code}: {msg}")
            # B-#6: 通报具体桶,caller 看 silent-failure 通道知道是 quota/token/QPS 还是别的
            if code in (110, 111):
                bucket = "cutout_baidu_token_invalid"
            elif code == 17:
                bucket = "cutout_baidu_qps_exceeded"
            elif code in (18, 19):
                bucket = "cutout_baidu_quota_exhausted"
            else:
                bucket = "cutout_baidu_failed"
            _emit_failure(bucket, f"baidu_code={code}",
                          context={"status_code": code})
            return None
        b64_result = data.get("image", "")
        if not b64_result:
            log.warning(f"baidu cutout missing image field: {data}")
            _emit_failure("cutout_baidu_missing_image",
                          "baidu 返 200 但 image 字段空")
            return None
        raw_png = base64.b64decode(b64_result)
        whitened = _whiten_to_transparent(raw_png)
        return normalize_subject_frame(whitened)
    except Exception as e:
        log.warning(f"baidu cutout request failed: {type(e).__name__}: {e}")
        # B-#6: 网络/响应解析挂了也走通道
        _emit_failure("cutout_baidu_network_failed",
                      f"{type(e).__name__}: {str(e)[:80]}",
                      context={"network_marker": "baidu_cutout_post_failed"})
        return None
