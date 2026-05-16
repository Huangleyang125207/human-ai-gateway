"""
gateway/ocr.py — 百度智能云 OCR 客户端(通用文字识别基础版)

decision: MiniMax 中国版 API 没 hosted vision model,折中走 OCR 抽文字 → 喂给文本 LLM。
准确率对手写/截图/印刷字都够用,免费额度 50000 次/月。
revisit if: 想要"看图说话"(描述场景、不仅识字)→ 切豆包/通义千问 VL,本模块可弃。

API 文档:https://cloud.baidu.com/doc/OCR/s/zk3h7xz52

用法:
  from ocr import baidu_ocr_image
  text = baidu_ocr_image(file_path, api_key, secret_key)  # 失败返空字符串

token 自动缓存 25 天(官方 30 天 TTL,留 5 天 buffer)。
"""
from __future__ import annotations

import base64
import io
import json
import logging
import time
from pathlib import Path

import requests

log = logging.getLogger("ocr")

_TOKEN_CACHE: dict = {}  # key: f"{api_key}:{secret}" → {token, expires_at}; 多 app key 各自缓存
_TOKEN_TTL_BUFFER = 5 * 24 * 3600  # 留 5 天 buffer

# 百度通用 OCR 基础版限制:长边 ≤ 4096px,base64 后 ≤ 4MB
# 长截图(微信/微博)经常超 4096,必须 resize
_MAX_EDGE_PX = 4000  # 留 96px 余量
_MAX_BASE64_BYTES = int(3.8 * 1024 * 1024)  # 4MB 留余量


def _prep_image_bytes(file_path: Path) -> bytes | None:
    """读图,如超百度限(分辨率 / base64 体积),用 Pillow 缩到限内。
    返回原始或重编码后的 bytes;失败返 None。
    """
    raw = file_path.read_bytes()
    base64_size = (len(raw) + 2) // 3 * 4  # 粗估
    try:
        from PIL import Image
    except ImportError:
        # Pillow 没装,只能直接返;超限的图会被百度拒
        if base64_size > _MAX_BASE64_BYTES:
            log.warning(f"image too large for OCR ({base64_size} b64 bytes) and Pillow not installed")
        return raw

    try:
        img = Image.open(io.BytesIO(raw))
        w, h = img.size
        long_edge = max(w, h)
        # 不超限 → 原样返
        if long_edge <= _MAX_EDGE_PX and base64_size <= _MAX_BASE64_BYTES:
            return raw
        # 超了 → 等比缩
        scale = _MAX_EDGE_PX / long_edge if long_edge > _MAX_EDGE_PX else 1.0
        new_size = (max(int(w * scale), 1), max(int(h * scale), 1))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img = img.resize(new_size, Image.LANCZOS)
        # 重编码,quality 阶梯下调直到 base64 不超限
        for q in (85, 75, 65, 55):
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=q, optimize=True)
            data = buf.getvalue()
            if (len(data) + 2) // 3 * 4 <= _MAX_BASE64_BYTES:
                log.info(f"resized {w}x{h} → {new_size[0]}x{new_size[1]} q={q} ({len(data)} bytes)")
                return data
        log.warning(f"image still too large after resize+q55: {len(data)} bytes")
        return data
    except Exception as e:
        log.warning(f"image prep failed: {type(e).__name__}: {e}")
        return raw


def _get_access_token(api_key: str, secret_key: str) -> str | None:
    """换 access_token,按 (api_key, secret) 分别缓存。失败返 None。
    fix: 之前 cache 不分 key,多 app 时返第一个 token,导致权限误判。
    """
    now = time.time()
    cache_key = f"{api_key}:{secret_key}"
    cached = _TOKEN_CACHE.get(cache_key)
    if cached and now < cached["expires_at"]:
        return cached["token"]
    try:
        r = requests.post(
            "https://aip.baidubce.com/oauth/2.0/token",
            params={
                "grant_type": "client_credentials",
                "client_id": api_key,
                "client_secret": secret_key,
            },
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
        token = data.get("access_token")
        ttl = data.get("expires_in", 30 * 24 * 3600)
        if not token:
            log.warning(f"baidu token resp missing access_token: {data}")
            return None
        _TOKEN_CACHE[cache_key] = {
            "token": token,
            "expires_at": now + ttl - _TOKEN_TTL_BUFFER,
        }
        return token
    except Exception as e:
        log.warning(f"baidu token fetch failed: {type(e).__name__}: {e}")
        return None


def baidu_ocr_image(file_path: Path | str, api_key: str, secret_key: str) -> str:
    """对单张本地图片做 OCR,返回拼接后的文字(行用 \\n 分隔)。失败/无文字返空字符串。"""
    f = Path(file_path)
    if not f.exists():
        return ""
    if not api_key or not secret_key or api_key.startswith("YOUR_") or secret_key.startswith("YOUR_"):
        return ""

    token = _get_access_token(api_key, secret_key)
    if not token:
        return ""

    try:
        img_bytes = _prep_image_bytes(f)
        if img_bytes is None:
            return ""
        b64 = base64.b64encode(img_bytes).decode("ascii")
        r = requests.post(
            "https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic",
            params={"access_token": token},
            data={"image": b64},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if "error_code" in data:
            log.warning(f"baidu ocr error {data.get('error_code')}: {data.get('error_msg')}")
            # token 失效 → 清 cache 让下次重新换
            if data.get("error_code") in (110, 111):
                _TOKEN_CACHE["token"] = None
            return ""
        words = [w.get("words", "") for w in data.get("words_result", [])]
        return "\n".join(words).strip()
    except Exception as e:
        log.warning(f"baidu ocr request failed: {type(e).__name__}: {e}")
        return ""
