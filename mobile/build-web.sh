#!/usr/bin/env bash
# 组装移动端 web bundle → app/www/。入口 = 移动原生前端 mobile/m/。
# Capacitor sync 时把 www/ 整个塞进原生工程,所以只带 webview 要的文件。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"     # gateway/mobile
GW="$(cd "$HERE/.." && pwd)"              # gateway 根
WWW="$HERE/app/www"

# ★ H1:版本单源一致性 gate。mobile/VERSION 是唯一真源(受版本控制)。
#   gate 只校验同样受控的 mobile-api.js APP_VERSION == VERSION(android/ 是 gitignore 的
#   Capacitor 生成物,其 versionName 由 scripts/android-setup.sh 从 VERSION 盖章,不在此校验)。
VERSION="$(tr -d ' \t\n\r' < "$HERE/VERSION")"
API_VER="$(sed -n 's/.*var APP_VERSION = "\([^"]*\)".*/\1/p' "$HERE/mobile-api.js" | head -1)"
if [ "$API_VER" != "$VERSION" ]; then
  echo "✗ 版本漂移:mobile/VERSION=$VERSION 但 mobile-api.js APP_VERSION=$API_VER" >&2
  echo "  改 mobile/VERSION 后须同步 mobile-api.js 的 APP_VERSION(Android 版本走 scripts/android-setup.sh 自动盖章)。" >&2
  exit 1
fi
echo "✓ 版本一致 v$VERSION (mobile/VERSION == mobile-api APP_VERSION)"

rm -rf "$WWW"
mkdir -p "$WWW/shared" "$WWW/vendor" "$WWW/brand"

# 入口:移动原生 index.html 扁平到 www 根,相对路径重写(../ → ./)
sed -e 's#\.\./mobile-api\.js#./mobile-api.js#g' \
    -e 's#\.\./\.\./shared/#./shared/#g' \
    -e 's#\.\./\.\./vendor/#./vendor/#g' \
    -e 's#\.\./\.\./brand/#./brand/#g' \
    -e 's#\.\./parity/interaction/run-in-app\.js#./run-in-app.js#g' \
    "$GW/mobile/m/index.html" > "$WWW/index.html"

# parity 交互层 case runner(P2 + ★Cannot-break case demo)
cp "$GW/mobile/parity/interaction/run-in-app.js" "$WWW/run-in-app.js"

# cd v0 (2026-06-25 v2 全套接管) tokens + components.css 双模式,零裸色值
cp "$GW/mobile/m/tokens.css"            "$WWW/tokens.css"
cp "$GW/mobile/m/components.css"        "$WWW/components.css"
cp "$GW/mobile/m/copy-allow.css"        "$WWW/copy-allow.css"

# cd v0 5 件套(顺序固定:mock → widgets → journal → chat → app)
# gw-mock.js 含 mock data + gatewayMd stub + GW.ICON + toolLabel(18 自然句)
# gw-app.js 含 GW.mount() 总入口(顶栏/日期带/care/timeline/nib/chatbar/抽屉/设置)
cp "$GW/mobile/m/gw-mock.js"     "$WWW/gw-mock.js"
cp "$GW/mobile/m/gw-widgets.js"  "$WWW/gw-widgets.js"
cp "$GW/mobile/m/gw-journal.js"  "$WWW/gw-journal.js"
cp "$GW/mobile/m/gw-chat.js"     "$WWW/gw-chat.js"
cp "$GW/mobile/m/gw-pretext.js"  "$WWW/gw-pretext.js"
cp "$GW/mobile/m/gw-app.js"      "$WWW/gw-app.js"

# bridge:接通 cd 5 件套 mock → mobile-api.js shim 真后端
# 8 个 P0 patch:gatewayMd/scanIntent/days/tasks/water/journal/thread/sendChat + bus hooks
cp "$GW/mobile/m/gw-real-bridge.js" "$WWW/gw-real-bridge.js"

# 22 tool shim(api 路由 + 后端调用)
cp "$GW/mobile/mobile-api.js"  "$WWW/mobile-api.js"

# manifest.json — PWA 添加到主屏支持
cp "$GW/mobile/m/manifest.json" "$WWW/manifest.json"

# 渲染器:marked + DOMPurify + 字体走系统 CJK 衬线,不带 webfont/CDN
cp "$GW/shared/md.js"             "$WWW/shared/md.js"
cp "$GW/vendor/marked.min.js"     "$WWW/vendor/marked.min.js"
cp "$GW/vendor/dompurify.min.js"  "$WWW/vendor/dompurify.min.js"
# pretext(文字绕图 ESM)— gw-pretext.js 只在"摆过的贴纸"场景唤醒
cp -R "$GW/vendor/pretext"        "$WWW/vendor/pretext"

# brand:apple-touch-icon(PWA)
cp "$GW/brand/logo.svg"            "$WWW/brand/logo.svg" 2>/dev/null || true
cp "$GW/brand/logo-animated.svg"   "$WWW/brand/logo-animated.svg" 2>/dev/null || true

echo "[build-web] 移动原生 bundle 就绪 → $WWW"
du -sh "$WWW" 2>/dev/null || true
ls "$WWW" | head -20
