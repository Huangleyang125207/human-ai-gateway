# PATTERN: service — thread-history persistence with explicit dependencies
# USE WHEN: changing thread get/restore/save behavior without coupling to FastAPI
# COPY THIS: inject path, lock, writer, reporter, logger, and clock

import json
from datetime import datetime
from pathlib import Path


class ThreadHistoryConflict(Exception):
    def __init__(self, current_mtime: int):
        self.current_mtime = current_mtime
        super().__init__("stale base_mtime")


class ThreadHistoryNotCorrupt(Exception):
    pass


class ThreadHistoryService:
    def __init__(
        self,
        *,
        path,
        data_dir,
        lock,
        write_text,
        report_failure,
        logger,
        now,
        mtime,
        is_stale,
    ):
        self.path = Path(path)
        self.data_dir = Path(data_dir)
        self.lock = lock
        self.write_text = write_text
        self.report_failure = report_failure
        self.logger = logger
        self.now = now
        self.mtime = mtime
        self.is_stale = is_stale

    @staticmethod
    def _compact(value, history_len: int):
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("compact must be an object or null")
        summary = value.get("summary")
        through = value.get("through")
        at = value.get("at")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("compact.summary must be a non-empty string")
        if not isinstance(through, int) or isinstance(through, bool) or not 0 <= through <= history_len:
            raise ValueError("compact.through must be within history")
        if not isinstance(at, str):
            raise ValueError("compact.at must be an ISO timestamp")
        try:
            datetime.fromisoformat(at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("compact.at must be an ISO timestamp") from exc
        return {"summary": summary.strip(), "through": through, "at": at}

    @classmethod
    def _decode(cls, data):
        if isinstance(data, list):
            return data, None
        if not isinstance(data, dict) or data.get("v") != 2 or not isinstance(data.get("history"), list):
            raise ValueError("thread history must be a legacy list or v2 envelope")
        history = data["history"]
        return history, cls._compact(data.get("compact"), len(history))

    def get(self) -> dict:
        if not self.path.exists():
            return {"history": [], "mtime": 0}
        try:
            with self.lock:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                mtime = self.mtime(self.path)
            history, compact = self._decode(data)
            return {"history": history, "compact": compact, "mtime": mtime}
        except Exception as e:
            self.logger.warning(f"thread history read failed: {e}")
            self.report_failure(
                "thread_history_read_failed",
                f"{type(e).__name__}: {str(e)[:120]}",
                context={
                    "file_size_kb": (
                        self.path.stat().st_size // 1024
                        if self.path.exists()
                        else 0
                    )
                },
            )
            baks = []
            for i in range(1, 6):
                bp = Path(f"{self.path}.bak.{i}")
                if bp.exists():
                    try:
                        baks.append({
                            "index": i,
                            "size_kb": bp.stat().st_size // 1024,
                            "mtime": int(bp.stat().st_mtime * 1000),
                        })
                    except Exception:
                        pass
            return {
                "history": [],
                "mtime": 0,
                "status": "corrupt",
                "error": str(e)[:200],
                "baks": baks,
                "message": (
                    "thread-history 读取失败 — 选 bak 恢复或 start-fresh,"
                    "别直接覆盖。"
                ),
            }

    def restore(self, bak_index: int) -> dict:
        bp = Path(f"{self.path}.bak.{bak_index}")
        if not bp.exists():
            raise FileNotFoundError(f"bak.{bak_index} 不存在")
        try:
            data = json.loads(bp.read_text(encoding="utf-8"))
            history, _ = self._decode(data)
        except Exception as e:
            raise ValueError(
                f"bak.{bak_index} 解析失败: {type(e).__name__}: {e}"
            ) from e
        with self.lock:
            if self.path.exists():
                try:
                    ts = int(self.now().timestamp())
                    corrupted = self.path.with_name(
                        f"{self.path.name}.corrupted.{ts}"
                    )
                    self.path.rename(corrupted)
                except Exception:
                    pass
            self.write_text(
                self.path,
                json.dumps(data, ensure_ascii=False, indent=2),
                rotate=False,
            )
            mtime = self.mtime(self.path)
        return {
            "ok": True,
            "restored_from": f"bak.{bak_index}",
            "count": len(history),
            "mtime": mtime,
        }

    def start_fresh(self) -> dict:
        payload = {"v": 2, "history": [], "compact": None}
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with self.lock:
            if self.path.exists():
                try:
                    self._decode(json.loads(self.path.read_text(encoding="utf-8")))
                except Exception:
                    pass
                else:
                    raise ThreadHistoryNotCorrupt("thread history is valid; use normal clear instead")
                stamp = int(self.now().timestamp() * 1000)
                archived = self.path.with_name(f"{self.path.name}.corrupted.{stamp}")
                suffix = 1
                while archived.exists():
                    archived = self.path.with_name(f"{self.path.name}.corrupted.{stamp}.{suffix}")
                    suffix += 1
                self.path.rename(archived)
            self.write_text(
                self.path,
                json.dumps(payload, ensure_ascii=False, indent=2),
                rotate=False,
            )
            mtime = self.mtime(self.path)
        return {"ok": True, "mtime": mtime, "count": 0}

    def save(self, history: list, base_mtime, compact=None) -> dict:
        compact = self._compact(compact, len(history))
        payload = {"v": 2, "history": history, "compact": compact}
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with self.lock:
            current = self.mtime(self.path)
            if self.is_stale(base_mtime, current):
                raise ThreadHistoryConflict(current)
            self.write_text(
                self.path,
                json.dumps(payload, ensure_ascii=False, indent=2),
                rotate=True,
            )
            mtime = self.mtime(self.path)
        return {"ok": True, "mtime": mtime, "count": len(history)}
