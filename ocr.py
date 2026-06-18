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
import re
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


# B-#2: baidu error_code 不再静默返 "",抛 BaiduOCRError 让 caller 区分 quota/token/QPS
# 5.20 长鑫存储 → 港币 凭空猜 那次根因就是 "" 被 caller 当作 "图里没字" 看
class BaiduOCRError(Exception):
    """百度 OCR API 返 error_code 时抛出。code 对照:
    110/111 token 失效,17 QPS 超,18/19 quota,4 file too large(已被 _prep_image_bytes 兜住)
    """
    def __init__(self, code: int, msg: str):
        super().__init__(f"baidu ocr error {code}: {msg}")
        self.code = code
        self.msg = msg


# B-#6: 给 ocr.py 装上报针脚。server.py 启动时调 set_failure_sink 注入 _report_silent_failure,
# 避免 lazy import 循环 + 给 library 模块统一的上报范式
_FAILURE_SINK = None


def set_failure_sink(sink) -> None:
    """server.py 启动期一次性调用,注入 _report_silent_failure。
    sink 签名: (error_type: str, message: str, context: dict = None) → None
    """
    global _FAILURE_SINK
    _FAILURE_SINK = sink


def _emit_failure(error_type: str, message: str = "", context: dict = None) -> None:
    """library 模块上报失败的统一入口。sink 没注入(单测 / cli 使用)时静音。"""
    if _FAILURE_SINK is None:
        return
    try:
        _FAILURE_SINK(error_type, message, context or {})
    except Exception:
        pass  # 反馈通道挂了不阻塞主路径


def _baidu_error_type(code: int) -> str:
    """B-#2: error_code → silent-failure error_type 桶。"""
    if code in (110, 111):
        return "ocr_baidu_token_invalid"
    if code == 17:
        return "ocr_baidu_qps_exceeded"
    if code in (18, 19):
        return "ocr_baidu_quota_exhausted"
    return "ocr_baidu_failed"


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
        # B-#6: 网络异常时 stale cache 也清掉,避免下个 caller 命中过期的 token
        _TOKEN_CACHE.pop(cache_key, None)
        _emit_failure("baidu_oauth_network_failed",
                      f"{type(e).__name__}: {str(e)[:80]}",
                      context={"network_marker": "baidu_oauth_post_failed"})
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
            code = int(data.get("error_code") or 0)
            msg = str(data.get("error_msg") or "")[:120]
            log.warning(f"baidu ocr error {code}: {msg}")
            # B-#3: token 失效 → 清 cache 让下次重新换
            if code in (110, 111):
                cache_key = f"{api_key}:{secret_key}"
                _TOKEN_CACHE.pop(cache_key, None)
            # B-#2+#6: 不再静默返 "" — 抛 BaiduOCRError 让 _ocr_text 能 silent-failure 上报
            _emit_failure(_baidu_error_type(code),
                          f"baidu_code={code}", context={"status_code": code})
            raise BaiduOCRError(code, msg)
        words = [w.get("words", "") for w in data.get("words_result", [])]
        return "\n".join(words).strip()
    except BaiduOCRError:
        raise  # error_code 路径已经 emit + raise,不再 swallow
    except Exception as e:
        log.warning(f"baidu ocr request failed: {type(e).__name__}: {e}")
        # B-#2+#6: 网络层异常也不再静默 — 让 _ocr_text 知道 "" 不是"图里没字"是"调用挂了"
        _emit_failure("ocr_baidu_network_failed",
                      f"{type(e).__name__}: {str(e)[:80]}",
                      context={"network_marker": "baidu_ocr_post_failed"})
        return ""


# ── dispatcher 层 ─ 从 server.py 抽出(行为零变化) ──────────────────
# 上层 file_path → 端侧链(macOS Vision + rapidocr ONNX)→ 百度兜底 → 空串。
# 跟 server.py 解耦:load_config 走函数体内 lazy import 避循环;silent-failure
# 走本模块的 _emit_failure(server 启动时已注入 sink)。

_OCR_BLOCK_RE = re.compile(r'<图片 OCR 识别结果>.*?</图片 OCR 识别结果>', re.DOTALL)
_OCR_FILENAME_RE = re.compile(r'图片 \[([^\]]+)\]:')

# OCR 颗数识别:匹配 "60 粒" / "30 capsules" / "120 softgels"
# 数字范围 1-9999,常见单位中英都覆盖。取所有匹配中的最大数(避免把规格 mg 误抓)。
_PILL_COUNT_RE = re.compile(
    r'(\d{1,4})\s*(?:粒|片|颗|錠|锭|capsules?|caps|tablets?|tabs?|softgels?|gummies|count\b)',
    re.IGNORECASE,
)


def _ocr_text(file_path: Path) -> str:
    """统一 OCR 出口:端侧优先(macOS Vision / rapidocr ONNX),失败兜底百度云。

    返恒非 None 的字符串(空 = 没识别出 / 全失败)。3 个 caller 共用,
    替换原 from ocr import baidu_ocr_image 的散落模式。

    优先级:
      1. ocr_local.ocr_local(file_path) → 端侧链(macOS Vision Swift binary +
         rapidocr ONNX fallback)。返 str = 成功(可能空),None = 端侧不可用
      2. 端侧 None → 走 baidu(若 config 有 key);无 key → 返 ""
    """
    from server import load_config
    try:
        from ocr_local import ocr_local
        local_result = ocr_local(file_path)
        if local_result is not None:
            return local_result
    except Exception as e:
        log.info(f"ocr_local failed for {file_path.name}: {e}")
        _emit_failure("ocr_local_exception",
                      f"{type(e).__name__}: {str(e)[:120]}")
    # 端侧不可用 → baidu cloud fallback
    try:
        cfg = load_config() or {}
        api_key = cfg.get("baidu_ocr_api_key", "")
        secret_key = cfg.get("baidu_ocr_secret_key", "")
        if not api_key or not secret_key:
            # 端侧不行 + baidu 没 key — 用户图里的文字 server 看不见 → AI 也看不见
            _emit_failure("ocr_all_unavailable",
                          "端侧 OCR 不可用且百度 OCR 未配 key,返空")
            return ""
        try:
            return baidu_ocr_image(file_path, api_key, secret_key) or ""
        except BaiduOCRError as be:
            # B-#2: baidu_ocr_image 内部已按 code 分桶上报过(_emit_failure),这里不重复;
            # 但 _ocr_text 返 "" 给上层 → 上层把"返空"区分不出"图里没字"和"API 挂了"
            # 看 silent-failure 上报通道,不要靠这个返回值
            log.warning(f"baidu OCR error code {be.code} for {file_path.name}: {be.msg}")
            return ""
    except Exception as e:
        log.warning(f"baidu OCR also failed for {file_path.name}: {e}")
        _emit_failure("ocr_baidu_failed",
                      f"{type(e).__name__}: {str(e)[:120]}")
        return ""


def _strip_ocr_from_history(text: str) -> str:
    """history 里的 user msg 不需要重发 OCR 全文(首发时已给过)。
    保留 [图片占位:filename] 让模型还知道当时贴过图,实际 OCR 文本去掉。
    """
    if '<图片 OCR 识别结果>' not in text:
        return text
    filenames = _OCR_FILENAME_RE.findall(text)
    placeholder = f'[历史含图片: {", ".join(filenames)} (OCR 文本省略)]' if filenames else '[历史含图片]'
    return _OCR_BLOCK_RE.sub(placeholder, text)


def _parse_pill_count_from_ocr(ocr_text: str):
    """从 OCR 文本里抽 '60粒/120 capsules' 这类总数。失败返 None。
    取所有匹配的最大值 — 避免把规格 (e.g. '500 mg × 60粒' 里的 500) 算进来。
    """
    if not ocr_text:
        return None
    nums = [int(m.group(1)) for m in _PILL_COUNT_RE.finditer(ocr_text)]
    nums = [n for n in nums if 1 <= n <= 9999]
    return max(nums) if nums else None
