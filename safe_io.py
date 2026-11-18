# PATTERN: util — atomic-write storage layer extracted from god module (Parallel Change)
# USE WHEN: vault/data 落盘写路径改动(原子写 / bak 轮转 / fsync 契约)
# COPY THIS: 无 — 本模块是 server.py §2(清册01)的搬迁体,契约在 server re-export
#
# 抽出记录(2026-07-21, 清册01-§2 第二刀):
# - 原址 server.py L220–329;server.py 保留同名适配器(Parallel Change expand 阶段),
#   caller(scrapbook/journal_routes/thread_routes/pulse_*/... 的 lazy `from server import`)
#   与测试 monkeypatch.setattr(server, "_safe_write_text", ...) 一字不改。
# - 应用侧 reporter、显示路径 roots、lock/rotate patch 点通过窄参数传入;本模块不导入
#   FastAPI 组装根。
# - 疤原样保留:A-H3 uuid tmp 名 + path-keyed lock;A-M5 fd+parent fsync;
#   A-H2/H12 rotate catch-all 接 silent-failure(CLAUDE.md Do-not 三条硬合同)。
import os
import threading as _threading_wg
from pathlib import Path

from runtime_paths import APP_STATE_DIR, CODE_ROOT, DATA_HOME


# ── 安全写(原子 tmpfile+rename + 可选 5-rotate 备份)──
# A-H3: tmp 文件名固定 .tmp → 同 path 并发写者撞;模块级 path-keyed lock + uuid tmp 名
# A-M5: tmp fd fsync + parent dir fsync → 断电后 atomic rename 才真到盘
# A-H2/H12: _rotate_backup bak.1 走 tmp+replace;catch-all 改 silent-failure 上报
_WRITE_GUARD_LOCKS: dict[str, "_threading_wg.Lock"] = {}
_WRITE_GUARD_LOCKS_GUARD = _threading_wg.Lock()


def _get_write_guard_lock(path_str: str) -> "_threading_wg.Lock":
    with _WRITE_GUARD_LOCKS_GUARD:
        lk = _WRITE_GUARD_LOCKS.get(path_str)
        if lk is None:
            lk = _threading_wg.Lock()
            _WRITE_GUARD_LOCKS[path_str] = lk
        return lk


def _fsync_parent(path: Path) -> None:
    """fsync 父目录:保证 atomic rename 在断电后真持久(POSIX 必需,Win 无效)。"""
    try:
        dfd = os.open(str(path.parent), os.O_DIRECTORY) if hasattr(os, "O_DIRECTORY") else None
        if dfd is not None:
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    except Exception:
        pass  # Win 没 O_DIRECTORY,或权限不够 — 跳过(rename 自身仍 atomic)


def _rotate_backup(path: Path, keep: int = 5, report_failure=None):
    """把 path 旋转出去:bak.{N-1} → bak.N(老的先掉),原 path 内容写进 bak.1。
    用于写之前调一次,即使下次写出错或被错数据覆盖,bak.1..bak.5 还能 rollback。
    """
    if not path.exists():
        return
    try:
        # 老的最旧那份清掉
        oldest = Path(f"{path}.bak.{keep}")
        if oldest.exists():
            oldest.unlink()
        # bak.{N-1} → bak.N 从大到小依次推
        for i in range(keep, 1, -1):
            src = Path(f"{path}.bak.{i-1}")
            if src.exists():
                src.rename(Path(f"{path}.bak.{i}"))
        # 当前文件 → bak.1 走 atomic tmp+replace(A-H2)
        bak1 = Path(f"{path}.bak.1")
        bak1_tmp = Path(f"{path}.bak.1.{os.getpid()}.tmp")
        bak1_tmp.write_bytes(path.read_bytes())
        bak1_tmp.replace(bak1)
    except Exception as e:
        # A-H2: catch-all 改可观测;rotate 自身崩了应当报出来
        try:
            if report_failure is not None:
                report_failure(
                    "rotate_backup_failed",
                    f"{type(e).__name__}: {str(e)[:120]}",
                    context={"op": "rotate_backup"},
                )
        except Exception:
            pass


def _pretty_rel(p: Path, roots=None) -> str:
    """Display-friendly 相对路径。Phase 1/2 后 vault 和 app-state 分属不同 root,
    单一 PLATFORM_ROOT 不够用。逐个尝试合理 base,落空返绝对 path。
    URL 构造也走它(APP_STATE_DIR 命中 → `data/...`,可直接接前缀 `/`)。
    """
    p = Path(p)
    for base in roots or (APP_STATE_DIR, DATA_HOME, CODE_ROOT):
        try:
            return str(p.relative_to(base))
        except ValueError:
            continue
    return str(p)


def _safe_write_text(
    path: Path,
    content: str,
    rotate: bool = False,
    encoding: str = "utf-8",
    *,
    lock_factory=None,
    rotate_backup=None,
):
    """原子写文本。rotate=True 先把旧的旋转成 bak.1..bak.5 再写。
    用 tmpfile + rename 实现原子(POSIX:os.rename 是 atomic;Windows 用 os.replace)。
    A-H3:tmp 文件名 uuid + path-keyed lock 防同 path 并发写者撞 tmp。
    A-M5:tmp fd fsync + parent dir fsync 保证断电场景内容到盘。
    """
    import uuid as _uuid
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path_str = str(path)
    get_lock = lock_factory or _get_write_guard_lock
    do_rotate = rotate_backup or _rotate_backup
    with get_lock(path_str):
        if rotate:
            do_rotate(path)
        tmp = Path(f"{path}.{os.getpid()}.{_uuid.uuid4().hex[:8]}.tmp")
        try:
            with tmp.open("w", encoding=encoding) as fh:
                fh.write(content)
                fh.flush()
                try:
                    os.fsync(fh.fileno())  # A-M5: 内容真落盘
                except Exception:
                    pass
            tmp.replace(path)
            _fsync_parent(path)  # A-M5: rename 的方向真持久
        finally:
            # 异常退出时残留 tmp 清掉
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
