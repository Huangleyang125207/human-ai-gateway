"""Process-control, external-open, root static and cache-policy routes."""

import os
import re
import subprocess
import sys
import threading
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter(tags=["system"])

_GATEWAY_DIR = None
_SERVER_FILE = None


def configure_effects(*, gateway_dir, server_file) -> None:
    global _GATEWAY_DIR, _SERVER_FILE
    _GATEWAY_DIR = gateway_dir
    _SERVER_FILE = server_file


@router.post("/api/quit")
def quit_gateway():
    """返响应后延迟退出进程。"""
    def shutdown():
        time.sleep(0.4)
        os._exit(0)

    threading.Thread(target=shutdown, daemon=True).start()
    return {"ok": True, "message": "gateway shutting down"}


@router.post("/api/abort")
def abort_worker():
    """触发 reload watcher 后终止当前 worker。"""
    server_file = _SERVER_FILE()

    def kill():
        time.sleep(0.3)
        server_file.touch()
        time.sleep(0.2)
        os._exit(1)

    threading.Thread(target=kill, daemon=True).start()
    return {
        "ok": True,
        "message": "worker aborting; server will respawn in ~2s",
    }


@router.post("/api/open-external")
async def open_external(req: Request):
    """仅通过系统默认浏览器打开 http(s) URL。"""
    body = await req.json()
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "need url")
    if not re.match(r"^https?://", url, flags=re.I):
        raise HTTPException(400, "only http(s) allowed")
    try:
        if sys.platform == "darwin":
            subprocess.Popen(
                ["open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif sys.platform == "win32":
            subprocess.Popen(
                ["cmd", "/c", "start", "", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
        else:
            subprocess.Popen(
                ["xdg-open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return {"ok": True}
    except Exception as error:
        raise HTTPException(
            500,
            f"open failed: {type(error).__name__}: {error}",
        )


@router.get("/")
def root():
    return FileResponse(_GATEWAY_DIR() / "index.html")


async def no_cache_for_static_assets(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if (
        path.endswith((".html", ".js", ".css"))
        or path == "/"
        or path.startswith("/api/")
    ):
        response.headers["Cache-Control"] = (
            "no-cache, no-store, must-revalidate"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response
