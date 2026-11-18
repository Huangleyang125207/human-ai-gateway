# PATTERN: service — telemetry state and algorithms with injected edge effects
# USE WHEN: silent-failure ring log / heartbeat / sink drain 相关改动
# COPY THIS: 具名 effect 注入 + 模块内状态唯一所有权；不要反向导入组装根
#
# 抽出记录(2026-07-21, 清册01-§4 第一刀):
# - 原址 server.py L516–1026;server.py 保留同名 re-export(Parallel Change expand 阶段),
#   caller(vault_git/scrapbook/web_tools/ocr/... 的 lazy `from server import`)一字不改。
# - telemetry.py 现在是遥测常量、缓存、锁与 sender thread 状态的唯一所有者。
# - 配置读写、原子写、日志、通知、版本号等边缘能力由 server.py 组装根具名注入。
# - server.py 可继续 re-export 公共兼容面，但不再是状态权威，也不存在反向导入。
import json
import logging
import os
import random
import re
import sys
import threading
import time
import uuid
import platform as _platform
from datetime import datetime

import requests

from runtime_paths import DATA_DIR


_LOAD_CONFIG = None
_SAVE_CONFIG = None
_ENV_OVERLAY = None
_SAFE_WRITE_TEXT = None
_LOGGER = lambda: logging.getLogger(__name__)
_PUSH_NOTIFICATION = None
_APP_VERSION = lambda: "unknown"


def configure_effects(
    *,
    load_config,
    save_config,
    env_overlay,
    safe_write_text,
    logger,
    push_notification,
    app_version,
) -> None:
    global _LOAD_CONFIG, _SAVE_CONFIG, _ENV_OVERLAY, _SAFE_WRITE_TEXT
    global _LOGGER, _PUSH_NOTIFICATION, _APP_VERSION
    _LOAD_CONFIG = load_config
    _SAVE_CONFIG = save_config
    _ENV_OVERLAY = env_overlay
    _SAFE_WRITE_TEXT = safe_write_text
    _LOGGER = logger
    _PUSH_NOTIFICATION = push_notification
    _APP_VERSION = app_version


SILENT_FAILURES_LOG = DATA_DIR / "silent-failures.jsonl"
CLIENT_ID_PATH = DATA_DIR / "client-id.txt"
_SILENT_FAILURES_RING_MAX = 5000
_CLIENT_ID_CACHE = None


def _load_or_create_client_id() -> str:
    """读持久化 client_id,不存在则 UUID4 生成 + 写入。
    匿名 ID:跨 .app 启动稳定,但跟用户身份无关。
    """
    try:
        if CLIENT_ID_PATH.exists():
            cid = CLIENT_ID_PATH.read_text(encoding="utf-8").strip()
            uuid.UUID(cid)  # 验格式
            return cid
    except Exception:
        pass
    new_id = str(uuid.uuid4())
    try:
        # A-M2: PULSE "client_id 文件不能动" 硬合同 — atomic + rotate=True 兜底
        _SAFE_WRITE_TEXT(CLIENT_ID_PATH, new_id, rotate=True)
    except Exception as e:
        _LOGGER().warning(f"client_id 持久化失败,本次启动用内存版: {e}")
    return new_id


def get_client_id() -> str:
    global _CLIENT_ID_CACHE
    if _CLIENT_ID_CACHE is None:
        _CLIENT_ID_CACHE = _load_or_create_client_id()
    return _CLIENT_ID_CACHE


def set_client_id_cache(value) -> None:
    global _CLIENT_ID_CACHE
    _CLIENT_ID_CACHE = value


def _telemetry_consent() -> dict:
    """返当前 cloud_telemetry 同意状态。
    无 config / 无字段 → 视为未同意(默认全关,直到 consent modal 写入)。
    """
    cfg = _LOAD_CONFIG() or {}
    ct = cfg.get("cloud_telemetry") or {}
    return {
        "failures": bool(ct.get("failures", False)),
        "heartbeat": bool(ct.get("heartbeat", False)),
        "consented_at": ct.get("consented_at"),  # ISO string or None
    }


def _telemetry_save(failures: bool, heartbeat: bool):
    """写 consent 状态,记录 consented_at 戳子。"""
    cfg = _LOAD_CONFIG() or {}
    cfg["cloud_telemetry"] = {
        "failures": bool(failures),
        "heartbeat": bool(heartbeat),
        "consented_at": datetime.now().isoformat(),
    }
    _SAVE_CONFIG(cfg)


# consent.js 明文承诺只收"错误码、调用元数据(模型标识、文件尺寸、网络层标记)"。
# 任何 caller 误塞用户原文(task name / curator query / patch preview / LLM eval 输出)
# 必须在入口被 drop,避免逐处审。 _dropped_keys 留作 drift 信号。
_SF_CONTEXT_ALLOWLIST = frozenset({
    "model", "model_id", "fallback_to", "fallback_from",
    "network_marker", "status_code", "http_status",
    "file_size_kb", "text_len", "cleaned_len", "lines",
    "attempt", "retry_count", "dropped_count",
    "err", "bak_err", "err_class",
    "op", "phase",
    # #2 折叠:同一指纹时间窗内重复次数(coalesced 汇总条带)
    "occurrences", "coalesced", "window_sec",
})
_SF_CONTEXT_VALUE_MAX_LEN = 120

# #1 隐私:home 路径含 OS 登录名(/Users/<name>/、/home/<name>/、C:\Users\<name>\)。
# message 是 raw git stderr / 异常串,不走 context 白名单,会把用户名带上服务器。
# 上送前统一塌成 ~。context 的字符串值(err/bak_err 等)同样过一道。
_PII_UNIX_PATH_RE = re.compile(r'/(?:Users|home)/[^/\s\'"]+')
_PII_WIN_PATH_RE = re.compile(r'[A-Za-z]:\\Users\\[^\\\s\'"]+', re.IGNORECASE)


def _scrub_pii(text):
    """把 home 目录路径(含用户名)塌成 ~。非字符串原样返回。"""
    if not text or not isinstance(text, str):
        return text
    text = _PII_UNIX_PATH_RE.sub('~', text)
    text = _PII_WIN_PATH_RE.sub('~', text)
    return text


def _sanitize_sf_context(ctx) -> dict:
    """白名单过滤 + 标量类型限制 + 字符串截断 + home 路径脱敏。
    dict/list/object 一律 drop(可能嵌套用户内容)。"""
    if not ctx or not isinstance(ctx, dict):
        return {}
    out = {}
    dropped = []
    for k, v in ctx.items():
        if not isinstance(k, str) or k not in _SF_CONTEXT_ALLOWLIST:
            dropped.append(str(k)[:40])
            continue
        if isinstance(v, bool) or isinstance(v, (int, float)) or v is None:
            out[k] = v
        elif isinstance(v, (str, bytes)):
            s = v.decode("utf-8", errors="replace") if isinstance(v, bytes) else v
            out[k] = _scrub_pii(s[:_SF_CONTEXT_VALUE_MAX_LEN])
        else:
            dropped.append(k)
    if dropped:
        out["_dropped_keys"] = ",".join(sorted(set(dropped)))[:_SF_CONTEXT_VALUE_MAX_LEN]
    return out


# A-H6+H11: silent-failures.jsonl 3 写者(append / trim / cursor)+ sender drain
# 同进程互不撞;append+trim 用同一个 lock,cursor 独立 lock(cursor 是 byte-size 不会撞 line)。
_SF_FILE_LOCK = threading.Lock()

# #2 折叠:同指纹失败在时间窗内"首条立即落盘(保即时信号)+ 窗内其余只内存累加",
# 窗口过期(下一条触发 rollover 或 sender tick)落一条 coalesced 汇总
# (occurrences = 被折叠掉的额外次数,首条已单独落)。把"1 个 bug 刷 26 行"
# 压成"1 即时 + 1 汇总"。回归 feedback-sink 26 条 index.lock 噪音。
_SF_DEDUP_WINDOW_SEC = 300
_SF_DEDUP_MAX = 500  # dedup 表上限,无 sink 时兜底防无界增长
_sf_dedup_lock = threading.Lock()
_sf_dedup: dict = {}  # fp -> {first, last, count, error_type, message, context}
_SF_FP_NUM_RE = re.compile(r'\d+')


def _sf_fingerprint(error_type: str, message: str) -> str:
    """error_type + 归一化 message(数字塌成 #,取前 80 字)。
    同根因不同实例(行号/时间/字节数变化)归同一指纹。"""
    norm = _SF_FP_NUM_RE.sub('#', message or '')
    return f"{error_type}|{norm[:80]}"


def _sf_make_entry(error_type, message, context, occurrences=1, coalesced=False):
    ctx = dict(context or {})
    if coalesced or occurrences > 1:
        ctx["occurrences"] = occurrences
        ctx["coalesced"] = coalesced
        ctx["window_sec"] = _SF_DEDUP_WINDOW_SEC
    return {
        "ts": datetime.now().isoformat(),
        "client_id": get_client_id(),
        "error_type": error_type,
        "message": message,
        "context": ctx,
        "app_version": _APP_VERSION(),
        "platform": f"{sys.platform}-{_platform.machine()}",
    }


def _sf_write_entry(entry: dict):
    """锁内 append + flush + fsync 单条。A-H6+H11 写盘契约。"""
    SILENT_FAILURES_LOG.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _SF_FILE_LOCK:
        with SILENT_FAILURES_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            try:
                os.fsync(f.fileno())  # 反馈通道本身崩了最不该悄无声息
            except Exception:
                pass
    # 偶尔 trim(每 100 条采样一次,均摊 IO)
    if random.random() < 0.01:
        _trim_silent_failures()


def _sf_flush_dedup(force: bool = False):
    """sender tick 调:窗口静默过期(或 force)且 count>1 → 落 coalesced 汇总。
    burst 停止后由这条兜底(rollover 路径只在下一条同指纹到达时触发)。"""
    now = time.time()
    to_emit = []
    with _sf_dedup_lock:
        for fp, rec in list(_sf_dedup.items()):
            if force or (now - rec["last"] >= _SF_DEDUP_WINDOW_SEC):
                if rec["count"] > 1:
                    to_emit.append((rec["error_type"], rec["message"],
                                    rec["context"], rec["count"] - 1))
                del _sf_dedup[fp]
    for et, msg, ctx, extra in to_emit:
        try:
            _sf_write_entry(_sf_make_entry(et, msg, ctx, occurrences=extra, coalesced=True))
        except Exception:
            pass


def _report_silent_failure(error_type: str, message: str = "", context: dict = None):
    """记一条 silent failure 进本地 ring buffer。fire-and-forget,自身永不 raise。

    error_type: 枚举 snake_case,server 侧分类用
                例: vision_classify_auth / cutout_all_failed / web_search_degraded
    message:    最长 200 字截断,不放用户内容;入口走 _scrub_pii 塌 home 路径(#1)
    context:    可选 dict,入口走 _sanitize_sf_context 白名单过滤,
                consent.js 承诺范围外的 key 直接 drop(记 _dropped_keys 作 drift 信号)

    折叠(#2): 同指纹窗内首条立即落,其余内存累加,过期落 coalesced 汇总。

    consent: 用户未同意"错误上报"时**连本地 jsonl 都不写**(C-#4 收口)。
    现在:撤回期间通道完全静音,本地不增长,云端不回灌。
    """
    try:
        # consent gate(C-#4):撤回期间连本地都不写。
        # try/except 兜:_telemetry_consent → load_config → 损坏路径理论上会回拨
        # _report_silent_failure;若 config + bak.1 双损则递归。挂了直接静音。
        try:
            if not _telemetry_consent().get("failures", False):
                return
        except Exception:
            return
        # #1 隐私:message 是 raw stderr,塌 home 路径去用户名;context 在 sanitize 内塌
        msg = _scrub_pii((message or "")[:200])
        sanitized = _sanitize_sf_context(context)
        # #2 折叠:同指纹窗内只首条落盘,其余累加
        fp = _sf_fingerprint(error_type, msg)
        now = time.time()
        flush = None
        emit_first = True
        with _sf_dedup_lock:
            rec = _sf_dedup.get(fp)
            if rec and (now - rec["first"] < _SF_DEDUP_WINDOW_SEC):
                rec["count"] += 1
                rec["last"] = now
                emit_first = False
            else:
                # 新窗口:旧窗口若累加过 extra,rollover 落汇总
                if rec and rec["count"] > 1:
                    flush = (rec["error_type"], rec["message"],
                             rec["context"], rec["count"] - 1)
                _sf_dedup[fp] = {"first": now, "last": now, "count": 1,
                                 "error_type": error_type, "message": msg,
                                 "context": sanitized}
                # 兜底:无 sink 配置时 sender flush 不跑,dedup 不会被清。
                # 超上限淘汰最旧(按 last)条目,防长 session 无界增长。
                if len(_sf_dedup) > _SF_DEDUP_MAX:
                    oldest = min(_sf_dedup, key=lambda k: _sf_dedup[k]["last"])
                    _sf_dedup.pop(oldest, None)
        # 落盘在 dedup lock 外(避免与 _SF_FILE_LOCK 嵌套)
        if flush:
            et, m, c, extra = flush
            _sf_write_entry(_sf_make_entry(et, m, c, occurrences=extra, coalesced=True))
        if emit_first:
            _sf_write_entry(_sf_make_entry(error_type, msg, sanitized))
    except Exception as e:
        # 反馈通道自己挂了不能反复上报(避免递归),只 warn
        try:
            _LOGGER().warning(f"silent_failure 记录失败: {e}")
        except Exception:
            pass


def _trim_silent_failures():
    """保留最近 _SILENT_FAILURES_RING_MAX 条。
    A-H6+H11: lock + atomic write;trim 时通过 cursor 调整(drop_count)避免漏发。
    """
    try:
        with _SF_FILE_LOCK:
            if not SILENT_FAILURES_LOG.exists():
                return
            lines = SILENT_FAILURES_LOG.read_text(encoding="utf-8").splitlines()
            if len(lines) <= _SILENT_FAILURES_RING_MAX:
                return
            drop_count = len(lines) - _SILENT_FAILURES_RING_MAX
            kept = lines[-_SILENT_FAILURES_RING_MAX:]
            _SAFE_WRITE_TEXT(SILENT_FAILURES_LOG, "\n".join(kept) + "\n", rotate=False)
            # 同步调整 cursor 避免漏发(drain 是按行号续上的,trim 后行号往左挪)
            try:
                old_cursor = _sf_cursor_read()
                new_cursor = max(0, old_cursor - drop_count)
                _sf_cursor_write(new_cursor)
            except Exception:
                pass
    except Exception as e:
        try:
            _LOGGER().warning(f"silent_failures trim 失败: {e}")
        except Exception:
            pass


# ── P3: silent-failure 上送 cloud sink (feedback-sink 接收端) ────
# 上送 cursor 记录"上送到哪一行了",下次启动从这里 +1 续上。
# 失败重试 N 次后丢弃(不阻塞主流程),本地 jsonl 永远兜底,出问题事后能回灌。
_SF_CURSOR_PATH = DATA_DIR / "silent-failures.cursor"
_SF_SENDER_THREAD = None
_SF_SENDER_STOP = threading.Event()
SF_SENDER_INTERVAL = 60       # 秒,每分钟扫一次
SF_SENDER_BATCH_MAX = 50      # 每批最多多少条(跟 server 端 BatchIn.max_length 对齐)
SF_SENDER_HTTP_TIMEOUT = 10   # 秒


def get_sf_sender_thread():
    return _SF_SENDER_THREAD


def set_sf_sender_thread(thread) -> None:
    global _SF_SENDER_THREAD
    _SF_SENDER_THREAD = thread


def _sf_cursor_read() -> int:
    try:
        return int(_SF_CURSOR_PATH.read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def _sf_cursor_write(line_no: int):
    try:
        # A-M3: atomic;cursor 损坏 → 整 ring buffer 重发(空 cursor = 从 0 开始)
        _SAFE_WRITE_TEXT(_SF_CURSOR_PATH, str(line_no), rotate=False)
    except Exception:
        pass  # cursor 丢失最坏后果:下次重发已发条目(server 不去重也无伤大雅)


# Prod default — 跟自更新通道同思路(yanpai box 长期不下线作 hardcoded fallback)。
# 6.17 发现 .env 没打进 PyInstaller bundle,真用户 sidecar 启动一直拿不到 URL
# → events 卡本地从未上送(5.29 通道上线起整个 prod 反馈通道哑了三周半)。
# dev 用 .env override 切 staging/mock;prod 用户直接拿到默认值开始上报。
DEFAULT_FEEDBACK_SINK_URL = "http://101.42.108.30:18080"


def _sf_sender_loop():
    """后台 thread:每 SF_SENDER_INTERVAL 秒读 jsonl 未发条目 → batch POST。
    server 端 URL 来自 env FEEDBACK_SINK_URL,默认走 DEFAULT_FEEDBACK_SINK_URL。
    """
    # 走 _env_overlay() — 这样 .env 文件里的 FEEDBACK_SINK_URL 也能读到
    # (os.environ.get 直读只能拿 process env,装机后 .app 没显式 export 就拿不到)
    env_url = (_ENV_OVERLAY().get("FEEDBACK_SINK_URL", "")
               or os.environ.get("FEEDBACK_SINK_URL", "")).strip().rstrip("/")
    url_base = env_url or DEFAULT_FEEDBACK_SINK_URL
    _LOGGER().info(f"[sf-sender] started, target={url_base}{' (env override)' if env_url else ' (prod default)'}, interval={SF_SENDER_INTERVAL}s")
    while not _SF_SENDER_STOP.wait(SF_SENDER_INTERVAL):
        try:
            # #2 折叠:先 flush 静默过期窗口的 coalesced 汇总进 jsonl,再 drain 上送
            _sf_flush_dedup()
            # consent gate — 用户没同意"错误上报"则 drain 跳过(本地 jsonl 兜底仍在,
            # toggle 打开后历史失败可回灌)
            if not _telemetry_consent().get("failures"):
                continue
            _sf_drain_once(url_base)
        except Exception as e:
            _LOGGER().warning(f"[sf-sender] drain failed: {type(e).__name__}: {e}")


# ── 日活心跳 sender (0.1.3 加) ──────────────────────────────────────
_HB_SENDER_THREAD = None
_HB_SENDER_STOP = threading.Event()
_HB_LAST_SENT_PATH = DATA_DIR / "heartbeat.last"
# 即刻反馈:启动 15s 就首发(原 30min 太久,内测 tester 探几分钟就关 → 一次心跳都不发 → DAU 永远 0)。
# 每天去重(_hb_last_sent_day)保证不刷屏,所以"避开开机 spike"不再靠延迟,靠去重。
HB_STARTUP_DELAY = 15        # 启动后 15s 首发
HB_RETRY_INTERVAL = 120      # 没发成(consent 没开 / 网络抖 / 晚勾同意)→ 2min 后重试,抓短会话
HB_IDLE_INTERVAL = 3600      # 当天已发 → 1h 醒一次看是否跨天
HB_HTTP_TIMEOUT = 10


def get_hb_sender_thread():
    return _HB_SENDER_THREAD


def set_hb_sender_thread(thread) -> None:
    global _HB_SENDER_THREAD
    _HB_SENDER_THREAD = thread


def stop_sender_threads() -> None:
    _SF_SENDER_STOP.set()
    _HB_SENDER_STOP.set()


def _hb_last_sent_day() -> str:
    try:
        return _HB_LAST_SENT_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _hb_mark_sent(day: str):
    try:
        # A-M3: atomic;heartbeat 戳子损坏 → 当日 DAU 多算一次,小代价
        _SAFE_WRITE_TEXT(_HB_LAST_SENT_PATH, day, rotate=False)
    except Exception:
        pass


def _hb_sender_loop():
    """日活心跳 — 每天一次。同 silent-failure sender 一样 fire-and-forget。
    consent 关闭则只 sleep 不发;开启时 day 已发过也跳过。
    """
    # 同 sf-sender:env override > prod default;原"未配就 return"导致 prod 心跳全程沉默
    # (5.29 起 unique_clients 永远 0,你看不到"装机但没出错"的活体内测用户)
    env_url = (_ENV_OVERLAY().get("FEEDBACK_SINK_URL", "")
               or os.environ.get("FEEDBACK_SINK_URL", "")).strip().rstrip("/")
    url_base = env_url or DEFAULT_FEEDBACK_SINK_URL
    # 启动延迟,避开开机 spike(用户重启 app / 重启电脑都不应立刻 ping)
    if _HB_SENDER_STOP.wait(HB_STARTUP_DELAY):
        return
    _LOGGER().info(f"[hb-sender] started, target={url_base}{' (env override)' if env_url else ' (prod default)'}, daily")
    while True:
        sent_today = False
        try:
            if not _telemetry_consent().get("heartbeat"):
                pass  # consent 关,本周期不发(下个 retry 周期再看,用户可能晚点才勾)
            else:
                today = datetime.utcnow().strftime("%Y-%m-%d")
                if _hb_last_sent_day() == today:
                    sent_today = True  # 今天发过了,转 idle 间隔
                else:
                    tz_off = int(-time.timezone / 60)  # local UTC offset(分钟)
                    payload = {
                        "client_id": get_client_id(),
                        "version": _APP_VERSION(),
                        "platform": f"{sys.platform}-{_platform.machine()}",
                        "tz_offset_min": tz_off,
                    }
                    r = requests.post(f"{url_base}/heartbeat", json=payload,
                                      timeout=HB_HTTP_TIMEOUT)
                    if r.status_code == 200:
                        _hb_mark_sent(today)
                        sent_today = True
                    elif r.status_code != 429:
                        _LOGGER().warning(f"[hb-sender] HTTP {r.status_code}: {r.text[:120]}")
        except Exception as e:
            _LOGGER().warning(f"[hb-sender] tick failed: {type(e).__name__}: {e}")
        # 没发成(consent 没开 / 网络 / 晚勾同意)→ 2min 后重试,抓住短会话;发成了 → 1h 看跨天
        if _HB_SENDER_STOP.wait(HB_IDLE_INTERVAL if sent_today else HB_RETRY_INTERVAL):
            break


def _sf_drain_once(url_base: str):
    """读 jsonl 从 cursor 开始的未发条目,POST 上去,成功后推进 cursor。"""
    if not SILENT_FAILURES_LOG.exists():
        return
    cursor = _sf_cursor_read()
    try:
        lines = SILENT_FAILURES_LOG.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    if cursor >= len(lines):
        return  # 都发过了
    pending = lines[cursor:cursor + SF_SENDER_BATCH_MAX]
    if not pending:
        return
    # 解析 jsonl → events
    events = []
    for line in pending:
        try:
            obj = json.loads(line)
            # cursor advance 不依赖单条 parse 成功,坏行也算"处理过了"
            events.append(obj)
        except Exception:
            continue
    if not events:
        # 全坏行,推进 cursor 防卡死
        _sf_cursor_write(cursor + len(pending))
        return
    try:
        r = requests.post(
            f"{url_base}/silent-failure/batch",
            json={"events": events},
            timeout=SF_SENDER_HTTP_TIMEOUT,
        )
        if r.status_code == 200:
            _sf_cursor_write(cursor + len(pending))
            _sf_sink_4xx_reset()  # 成功 = 通道恢复
        elif r.status_code == 429:
            # rate limited — 下次再试,不推进 cursor
            _LOGGER().info("[sf-sender] rate-limited, will retry next interval")
        elif r.status_code in (401, 403, 404):
            # B-#4: 鉴权 / endpoint 路径错 — 不推进 cursor 防把所有 pending 倒进 /dev/null
            # 累计 streak,阈值后 push notification 让用户能看到反馈通道挂了
            _LOGGER().warning(f"[sf-sender] HTTP {r.status_code}: {r.text[:120]}")
            streak = _sf_sink_4xx_bump()
            if streak >= _SF_SINK_4XX_THRESHOLD:
                _maybe_push_sink_broken(r.status_code, r.text[:120])
        elif 400 <= r.status_code < 500:
            # B-#4: 400/422 schema/payload 错 — 单条不可上送,advance 1 条防整批卡死
            # 不是整批 advance(那样把后面的 OK 条目也吞了)
            _LOGGER().warning(f"[sf-sender] HTTP {r.status_code} (schema?): {r.text[:120]}")
            _sf_cursor_write(cursor + 1)
        else:
            _LOGGER().warning(f"[sf-sender] HTTP {r.status_code}: {r.text[:120]}")
            # 5xx 不推进等下次
    except Exception as e:
        _LOGGER().warning(f"[sf-sender] POST failed: {type(e).__name__}: {e}")
        # 网络 / DNS / 超时 — 不推进 cursor,下次再试


# B-#4: sink 4xx streak 跟踪。401/403/404 连续 ≥ 阈值 → push notification 让用户看到
# 反馈通道挂了。文件持久化避免 sidecar 重启 streak 归零。
_SF_SINK_4XX_PATH = DATA_DIR / "silent-failures-sink-4xx-streak"
_SF_SINK_4XX_THRESHOLD = 3
_SF_SINK_BROKEN_NOTIFIED_PATH = DATA_DIR / "silent-failures-sink-broken-notified"


def _sf_sink_4xx_bump() -> int:
    try:
        prev = 0
        if _SF_SINK_4XX_PATH.exists():
            try:
                prev = int(_SF_SINK_4XX_PATH.read_text(encoding="utf-8").strip())
            except Exception:
                prev = 0
        new = prev + 1
        _SAFE_WRITE_TEXT(_SF_SINK_4XX_PATH, str(new), rotate=False)
        return new
    except Exception:
        return 0


def _sf_sink_4xx_reset() -> None:
    try:
        if _SF_SINK_4XX_PATH.exists():
            _SF_SINK_4XX_PATH.unlink()
        if _SF_SINK_BROKEN_NOTIFIED_PATH.exists():
            _SF_SINK_BROKEN_NOTIFIED_PATH.unlink()
    except Exception:
        pass


def _maybe_push_sink_broken(status_code: int, body_snippet: str) -> None:
    """到阈值后只弹一次,直到通道恢复才再弹下一波(避免每 60s 一条骚扰)。"""
    if _SF_SINK_BROKEN_NOTIFIED_PATH.exists():
        return
    try:
        _PUSH_NOTIFICATION(
            "sink-broken",
            f"反馈通道挂了(HTTP {status_code}) — 内测期诊断数据上送暂停。"
            f"检查 FEEDBACK_SINK_URL 配置或 deploy key。",
            {"status_code": status_code, "body_snippet": body_snippet[:200]},
        )
        _SAFE_WRITE_TEXT(_SF_SINK_BROKEN_NOTIFIED_PATH, str(int(time.time())), rotate=False)
    except Exception:
        pass
