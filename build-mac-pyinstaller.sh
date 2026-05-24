#!/bin/bash
# build-mac-pyinstaller.sh — 出 self-contained Gateway.app(免装 python)+ .dmg
#
# 跟 build-mac-app.sh 区别:那个是 thin launcher(824 KB,要系统 python3 + pip install)。
# 这个是 PyInstaller 打的 fat .app(80-150 MB)— python 解释器 + 所有 wheel 全塞进去,
# 用户拖到 Applications 双击就跑,啥都不用装。
#
# 用法:cd gateway && bash build-mac-pyinstaller.sh
# 输出:./dist-pyinstaller/Gateway.app + ./dist-pyinstaller/Gateway-Installer.dmg
#
# 默认尝试 universal2(arm64 + x86_64 同包,两台 Mac 都 native 跑,无 Rosetta)。
# 失败(某个 wheel 缺 universal2)→ fallback 到当前机器 native 架构。

set -e
cd "$(dirname "$0")"
GATEWAY_DIR="$(pwd)"
DIST="$GATEWAY_DIR/dist-pyinstaller"
VENV="$GATEWAY_DIR/.venv-build"

# 工具 check
command -v python3 >/dev/null || { echo "✗ 需要 python3"; exit 1; }
command -v hdiutil >/dev/null || { echo "✗ 需要 hdiutil(macOS 默认)"; exit 1; }

echo "→ 1. 建 build venv($VENV)"
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
PY="$VENV/bin/python3"
PIP="$VENV/bin/pip"

echo "→ 2. 装 requirements + PyInstaller"
"$PIP" install --quiet --upgrade pip
"$PIP" install --quiet -r requirements.txt
"$PIP" install --quiet pyinstaller

echo "→ 3. 烤 icon(若上次没烤过)"
ICNS="$GATEWAY_DIR/brand/logo.icns"
if [ ! -f "$ICNS" ]; then
  ISET="$GATEWAY_DIR/brand/.iconset.iconset"
  rm -rf "$ISET" && mkdir -p "$ISET"
  for sz in 16 32 64 128 256 512 1024; do
    sips -s format png -z $sz $sz "$GATEWAY_DIR/brand/logo.svg" --out "$ISET/icon_${sz}x${sz}.png" >/dev/null 2>&1
  done
  cp "$ISET/icon_32x32.png"     "$ISET/icon_16x16@2x.png"
  cp "$ISET/icon_64x64.png"     "$ISET/icon_32x32@2x.png"
  cp "$ISET/icon_256x256.png"   "$ISET/icon_128x128@2x.png"
  cp "$ISET/icon_512x512.png"   "$ISET/icon_256x256@2x.png"
  cp "$ISET/icon_1024x1024.png" "$ISET/icon_512x512@2x.png"
  rm "$ISET/icon_64x64.png" "$ISET/icon_1024x1024.png"
  iconutil -c icns "$ISET" -o "$ICNS"
  rm -rf "$ISET"
fi

echo "→ 4. PyInstaller 打包"
rm -rf "$DIST" "$GATEWAY_DIR/build" "$GATEWAY_DIR/Gateway.spec"
mkdir -p "$DIST"

# --add-data 把静态资源塞进 _MEIPASS,server.py 已改成 frozen 时读 _MEIPASS
ADDS=(
  --add-data "index.html:."
  --add-data "day.html:."
  --add-data "reset.html:."
  --add-data "history.html:."
  --add-data "shared:shared"
  --add-data "widgets:widgets"
  --add-data "vendor:vendor"
  --add-data "brand:brand"
  --add-data "protocols:protocols"
  --add-data ".gateway-config.example.json:."
  --add-data "vault_config.py:."
  --add-data "vault_git.py:."
  --add-data "history_exporter.py:."
  --add-data "outcome_tracker.py:."
  --add-data "cutout.py:."
  --add-data "cutout_local.py:."
  --add-data "ocr.py:."
  --add-data "tools:tools"
)
# uvicorn 的隐式 import(PyInstaller 默认抓不到)
HIDDEN=(
  --hidden-import uvicorn.logging
  --hidden-import uvicorn.loops.auto
  --hidden-import uvicorn.loops.asyncio
  --hidden-import uvicorn.protocols.http.h11_impl
  --hidden-import uvicorn.protocols.http.auto
  --hidden-import uvicorn.protocols.websockets.auto
  --hidden-import uvicorn.protocols.websockets.websockets_impl
  --hidden-import uvicorn.lifespan.on
  --hidden-import uvicorn.lifespan.off
  --hidden-import multipart
  --hidden-import email_validator
)

# 默认 native(arm64 / x86_64 跟当前机器一致)。
# 想要 universal2(arm64+x86_64 fat)可以 BUILD_UNIVERSAL=1 触发 — 但要求所有 wheel
# 都有 universal2 build(Pillow 的 AVIF 子模块就常缺),失败率比较高。
ARCH_FLAG=""
if [ "$BUILD_UNIVERSAL" = "1" ]; then
  ARCH_FLAG="--target-arch universal2"
  echo "  ⚠ 强制 universal2(可能因某 wheel 缺 universal2 build 失败)"
fi
"$VENV/bin/pyinstaller" \
  --name Gateway \
  --windowed \
  --noconfirm \
  --distpath "$DIST" \
  --workpath "$GATEWAY_DIR/build" \
  --icon "$ICNS" \
  $ARCH_FLAG \
  "${ADDS[@]}" \
  "${HIDDEN[@]}" \
  server.py 2>&1 | tail -30
PYI_EXIT=${PIPESTATUS[0]}
if [ "$PYI_EXIT" != "0" ]; then
  echo "✗ PyInstaller 失败 (exit $PYI_EXIT)"
  exit 1
fi
rm -rf "$GATEWAY_DIR/build" "$GATEWAY_DIR/Gateway.spec"

APP="$DIST/Gateway.app"
[ -d "$APP" ] || { echo "✗ PyInstaller 没出 Gateway.app"; exit 1; }

echo "→ 5. arch check + Info.plist 后处理(LSUIElement=true 防 Dock 一直 bounce)"
ARCH=$(file "$APP/Contents/MacOS/Gateway" | sed 's/^.*: //')
echo "  $ARCH"
# server 是 headless,没 GUI 窗口。--windowed 出来的 plist 没 LSUIElement,
# Dock 图标会一直 bounce 等窗口。改成 background app(无 Dock 图标),
# server.py 启动时自动开浏览器,用户看到的就是网页 UI。
/usr/libexec/PlistBuddy -c "Delete :LSUIElement" "$APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$APP/Contents/Info.plist"
echo "  ✓ LSUIElement = true"

echo "→ 6. 打 DMG"
STAGE="$DIST/.dmg-stage"
rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
[ -f "$GATEWAY_DIR/MIGRATION-TEST.md" ] && cp "$GATEWAY_DIR/MIGRATION-TEST.md" "$STAGE/README.md"

DMG="$DIST/Gateway-Installer.dmg"
hdiutil create -volname "Gateway" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

APP_SIZE=$(du -sh "$APP" | awk '{print $1}')
DMG_SIZE=$(du -sh "$DMG" | awk '{print $1}')
echo
echo "════════════════════════════════════════════"
echo "  ✓ 打包完成(self-contained,免装 python)"
echo "    Gateway.app:           $APP  ($APP_SIZE)"
echo "    Gateway-Installer.dmg: $DMG  ($DMG_SIZE)"
echo "    架构: $ARCH"
echo "════════════════════════════════════════════"
