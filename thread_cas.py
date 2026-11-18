# PATTERN: util — thread-history.json mtime-based CAS 判定,从 god module 抽出
# USE WHEN: 改 thread-history 冲突检测精度(ms/ns) / CAS 豁免条件
# COPY THIS: 无 — 本模块是 server.py §19(清册01)的搬迁体,契约在 server re-export
#
# 抽出记录(2026-07-22, 清册01-§19,Parallel Change expand):
# - 原址 server.py "chat thread history" 段的两个纯函数(_thread_history_mtime_ms /
#   _thread_save_is_stale),函数体逐字节照搬。
# - 2026-07-26 contract 阶段：mtime helper 改收窄接口(path)，本模块不再反向
#   import composition root。server.py 保留无参兼容 wrapper，现有 HTTP/测试签名不变。
from pathlib import Path


def _thread_history_mtime_ms(path: Path) -> int:
    """毫秒级 mtime。用 ms(~1.78e12)而非 ns(~1.78e18)是因为 ns 超过
    JS Number.MAX_SAFE_INTEGER(9e15),前端存/传时丢精度会导致 CAS 把合法 save 误判成冲突。
    ms 精度对单用户冲突检测绰绰有余(同毫秒两次写几乎不可能)。"""
    try:
        return path.stat().st_mtime_ns // 1_000_000
    except FileNotFoundError:
        return 0


def _thread_save_is_stale(base_mtime, current_mtime: int) -> bool:
    """CAS 判定:client 回传它 save 所基于的 base_mtime,若跟当前存档 mtime 不符,
    说明期间别的 client(或陈旧标签页)写过 → 这次 save 是陈旧覆盖 → 该拒。

    豁免:
    - base_mtime is None(旧 client 没回传)→ 不判定,放行(过渡兼容)
    - current_mtime == 0(文件还不存在,首次写)→ 放行
    防的就是 5.17 / 5.26 那种「开了几天的旧标签页用内存里的旧 history 盖掉新历史」。
    """
    if base_mtime is None:
        return False
    if current_mtime == 0:
        return False
    try:
        return int(base_mtime) != current_mtime
    except (TypeError, ValueError):
        return False
