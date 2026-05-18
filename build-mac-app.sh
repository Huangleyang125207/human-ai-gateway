#!/bin/bash
# build-mac-app.sh — 把当前 gateway/ 打包成 Gateway.app + Gateway-Installer.dmg
#
# 用法:cd gateway && bash build-mac-app.sh
# 输出:./dist/Gateway.app + ./dist/Gateway-Installer.dmg
#
# 依赖系统工具:sips / iconutil / hdiutil(macOS 默认就有)
# 不依赖 brew / pyinstaller — 出来的 .app 是 thin launcher,运行时调系统 python3。
# 用户机器需自带 python3(start-mac.command 启动时检查)。
#
# 后续 P1:加 PyInstaller 路径生成 self-contained 二进制,免装 python。

set -e
cd "$(dirname "$0")"
GATEWAY_DIR="$(pwd)"
DIST="$GATEWAY_DIR/dist"
BUILD="$DIST/.build"

# 工具 check
for cmd in sips iconutil hdiutil; do
  command -v $cmd >/dev/null || { echo "✗ 需要 $cmd(macOS 默认就有)"; exit 1; }
done

# 清旧
rm -rf "$DIST"
mkdir -p "$BUILD/iconset.iconset"

APP="$DIST/Gateway.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# 1. 拷代码进 .app(排同 tarball 的清单 — 不带 state / git / 密钥 / 含硬编码路径的 plist)
echo "→ 拷代码到 Resources/gateway/"
mkdir -p "$APP/Contents/Resources/gateway"
rsync -a \
  --exclude='.env' \
  --exclude='.gateway-config.json' \
  --exclude='.git' \
  --exclude='.user-widgets.json' \
  --exclude='*.log' \
  --exclude='__pycache__' \
  --exclude='.DS_Store' \
  --exclude='data' \
  --exclude='launchd' \
  --exclude='dist' \
  --exclude='build-mac-app.sh' \
  "$GATEWAY_DIR/" "$APP/Contents/Resources/gateway/"

# 2. SVG → icns(7 个尺寸 + retina 副本)
echo "→ 烤 icon"
SRC="$GATEWAY_DIR/brand/logo.svg"
[ -f "$SRC" ] || { echo "✗ 找不到 $SRC"; exit 1; }
for sz in 16 32 64 128 256 512 1024; do
  sips -s format png -z $sz $sz "$SRC" --out "$BUILD/iconset.iconset/icon_${sz}x${sz}.png" >/dev/null 2>&1
done
cp "$BUILD/iconset.iconset/icon_32x32.png"     "$BUILD/iconset.iconset/icon_16x16@2x.png"
cp "$BUILD/iconset.iconset/icon_64x64.png"     "$BUILD/iconset.iconset/icon_32x32@2x.png"
cp "$BUILD/iconset.iconset/icon_256x256.png"   "$BUILD/iconset.iconset/icon_128x128@2x.png"
cp "$BUILD/iconset.iconset/icon_512x512.png"   "$BUILD/iconset.iconset/icon_256x256@2x.png"
cp "$BUILD/iconset.iconset/icon_1024x1024.png" "$BUILD/iconset.iconset/icon_512x512@2x.png"
rm "$BUILD/iconset.iconset/icon_64x64.png" "$BUILD/iconset.iconset/icon_1024x1024.png"
iconutil -c icns "$BUILD/iconset.iconset" -o "$APP/Contents/Resources/Gateway.icns"

# 3. Info.plist
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>             <string>Gateway</string>
    <key>CFBundleDisplayName</key>      <string>Gateway</string>
    <key>CFBundleIdentifier</key>       <string>ai.human-ai.gateway</string>
    <key>CFBundleVersion</key>          <string>0.4</string>
    <key>CFBundleShortVersionString</key><string>0.4</string>
    <key>CFBundlePackageType</key>      <string>APPL</string>
    <key>CFBundleSignature</key>        <string>????</string>
    <key>CFBundleExecutable</key>       <string>Gateway</string>
    <key>CFBundleIconFile</key>         <string>Gateway</string>
    <key>LSMinimumSystemVersion</key>   <string>10.14</string>
    <key>LSUIElement</key>              <false/>
    <key>NSHighResolutionCapable</key>  <true/>
    <key>NSHumanReadableCopyright</key> <string>Human-AI · 葱鸭 × claude-opus-4.7</string>
</dict>
</plist>
PLIST

# 4. Launcher — 开 Terminal 跑 start-mac.command
cat > "$APP/Contents/MacOS/Gateway" <<'LAUNCHER'
#!/bin/bash
# Gateway.app launcher — 用 Terminal 跑 start-mac.command,关 Terminal = 停 server
set -e
BUNDLE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
START="$BUNDLE_DIR/Resources/gateway/start-mac.command"
if [ ! -x "$START" ]; then
  osascript -e "display alert \"Gateway 启动失败\" message \"找不到 $START\""
  exit 1
fi
open -a Terminal "$START"
LAUNCHER
chmod +x "$APP/Contents/MacOS/Gateway"

# 5. DMG — Gateway.app + Applications 符号链接,拖拽安装
echo "→ 打 DMG"
STAGE="$BUILD/dmg-stage"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
[ -f "$GATEWAY_DIR/MIGRATION-TEST.md" ] && cp "$GATEWAY_DIR/MIGRATION-TEST.md" "$STAGE/README.md"

DMG="$DIST/Gateway-Installer.dmg"
hdiutil create -volname "Gateway" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null

# 清中间产物
rm -rf "$BUILD"

echo
echo "════════════════════════════════════════════"
echo "  ✓ 打包完成"
echo "    Gateway.app:           $APP  ($(du -sh "$APP" | awk '{print $1}'))"
echo "    Gateway-Installer.dmg: $DMG  ($(du -sh "$DMG" | awk '{print $1}'))"
echo "════════════════════════════════════════════"
echo "  分发:把 .dmg 发给测试者,他双击挂载 → 把 Gateway 图标拖到 Applications 即可"
