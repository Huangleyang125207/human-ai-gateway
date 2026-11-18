# PATTERN: util — sliding-window chat history summarization,从 god module 抽出
# USE WHEN: 改摘要触发阈值(RECENT_KEEP/SUMMARY_MIN_OLD)/ cache 上限 / 摘要 prompt 措辞
# COPY THIS: 无 — 本模块是 server.py §12(清册01)的搬迁体,契约在 server re-export
#
# 抽出记录(2026-07-22, 清册01-§12,Parallel Change expand):
# - 原址 server.py "sliding-window summarization (B 包)" 段(RECENT_KEEP..
#   _summarize_history),日志使用同名 gateway logger,不依赖应用组装根。
# - 与 compact_summary.py **不是同一功能**(那个是 thread-compact 后写 200 字冷启摘要,
#   endpoint 驱动;这个是 chat 发送前把超 RECENT_KEEP 的旧消息压成摘要,client-lib 调用)。
#   现存唯一调用方是 pulse_eval.py:_eval_compress_past_logs(未激活的 stub,留给未来
#   trend-detection),chat_routes.py 当前不摘要(decision 见该文件注释,cache 命中率更高)。
# - RECENT_KEEP / SUMMARY_MIN_OLD / _SUMMARY_CACHE / _SUMMARY_CACHE_MAX 无测试直接
#   monkeypatch,全量搬迁(不同于 THREAD_HISTORY_PATH 那类需要留权威在 server 的常量)。
import hashlib
import logging

RECENT_KEEP = 20            # 最近 N 条原文保留
SUMMARY_MIN_OLD = 5         # 旧消息少于这个数量不触发摘要
_SUMMARY_CACHE: dict = {}   # hash → summary string
_SUMMARY_CACHE_MAX = 64
log = logging.getLogger("gateway")


def _summarize_history(old_messages: list, client, model: str) -> str:
    """把超过 RECENT_KEEP 的旧消息压成 1 段摘要。
    cache by sha256 of concatenated content,避免每轮重算。
    失败返空字符串(调用方 fallback 到不摘要直接发)。
    """
    if not old_messages:
        return ""
    chunk = "\n".join(f"[{m.get('role')}] {m.get('content','')}" for m in old_messages)
    key = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
    if key in _SUMMARY_CACHE:
        return _SUMMARY_CACHE[key]

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content":
                    "你把对话历史压成 1 段中文摘要(~150 字)。"
                    "保留:用户的目标 / 决定 / 关键事实 / 待办。"
                    "丢掉:寒暄 / 流程细节 / 工具名 / 文件路径。"
                    "只输出摘要本身,不加前缀。"},
                {"role": "user", "content": f"压缩以下对话:\n\n{chunk}\n\n摘要:"},
            ],
            max_tokens=400,
        )
        summary = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.warning(f"summary failed: {type(e).__name__}: {e}")
        return ""

    if len(_SUMMARY_CACHE) >= _SUMMARY_CACHE_MAX:
        _SUMMARY_CACHE.pop(next(iter(_SUMMARY_CACHE)))
    _SUMMARY_CACHE[key] = summary
    return summary
