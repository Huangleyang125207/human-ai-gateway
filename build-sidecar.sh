#!/usr/bin/env bash
# build-sidecar.sh — 把 server.py 打成 Tauri sidecar 用的单文件可执行(非 .app)。
# 跟 build-mac-pyinstaller.sh 的资源清单一致,但:
#   · onefile(Tauri externalBin 要单文件)
#   · 不 --windowed(这是被 Tauri spawn 的 headless 进程,不是 GUI app)
#   · 输出命名 gateway-server-<target-triple>(Tauri sidecar 约定)放进 src-tauri/binaries/
# 运行时 Tauri 会设 GATEWAY_NO_OPEN=1 + GATEWAY_PORT=<port>。
set -euo pipefail
cd "$(dirname "$0")"
GATEWAY_DIR="$(pwd)"
VENV="$GATEWAY_DIR/.venv-build"
TRIPLE="$(rustc -vV 2>/dev/null | grep '^host:' | cut -d' ' -f2)"
[ -z "$TRIPLE" ] && { echo "X 拿不到 rust target triple(需 rustc 在 PATH)"; exit 1; }
OUT_DIR="$GATEWAY_DIR/src-tauri/binaries"
mkdir -p "$OUT_DIR"

echo "-> sidecar target triple: $TRIPLE"
[ -d "$VENV" ] || { echo "X 没有 .venv-build(先跑过 build-mac-pyinstaller.sh)"; exit 1; }

ADDS=(
  --add-data "index.html:." --add-data "day.html:." --add-data "reset.html:."
  --add-data "history.html:." --add-data "consent.html:."
  --add-data "shared:shared" --add-data "widgets:widgets" --add-data "vendor:vendor"
  --add-data "brand:brand" --add-data "protocols:protocols"
  --add-data ".gateway-config.example.json:."
  --add-data "vault_config.py:." --add-data "vault_git.py:."
  --add-data "history_exporter.py:." --add-data "outcome_tracker.py:."
  --add-data "cutout.py:." --add-data "cutout_local.py:."
  --add-data "ocr.py:." --add-data "ocr_local.py:." --add-data "tools:tools"
)
HIDDEN=(
  --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto
  --hidden-import uvicorn.loops.asyncio --hidden-import uvicorn.protocols.http.h11_impl
  --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto
  --hidden-import uvicorn.protocols.websockets.websockets_impl
  --hidden-import uvicorn.lifespan.on --hidden-import uvicorn.lifespan.off
  --hidden-import multipart --hidden-import email_validator
  --hidden-import lxml._elementpath --hidden-import lxml.etree
)

rm -rf "$GATEWAY_DIR/build-sidecar" "$GATEWAY_DIR/gateway-server.spec"
"$VENV/bin/pyinstaller" \
  --name gateway-server \
  --onefile \
  --noconfirm \
  --distpath "$GATEWAY_DIR/dist-sidecar" \
  --workpath "$GATEWAY_DIR/build-sidecar" \
  "${ADDS[@]}" "${HIDDEN[@]}" \
  server.py

rm -rf "$GATEWAY_DIR/build-sidecar" "$GATEWAY_DIR/gateway-server.spec"
# 改名成 Tauri sidecar 约定 + 放进 src-tauri/binaries/
cp "$GATEWAY_DIR/dist-sidecar/gateway-server" "$OUT_DIR/gateway-server-$TRIPLE"
chmod +x "$OUT_DIR/gateway-server-$TRIPLE"
echo "✓ sidecar: $OUT_DIR/gateway-server-$TRIPLE ($(du -h "$OUT_DIR/gateway-server-$TRIPLE" | cut -f1))"
