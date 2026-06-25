#!/usr/bin/env bash
# 组装移动端 web bundle → app/www/。入口 = 移动原生前端 mobile/m/。
# Capacitor sync 时把 www/ 整个塞进原生工程,所以只带 webview 要的文件。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"     # gateway/mobile
GW="$(cd "$HERE/.." && pwd)"              # gateway 根
WWW="$HERE/app/www"

rm -rf "$WWW"
mkdir -p "$WWW/shared" "$WWW/vendor" "$WWW/brand"

# 入口:移动原生 index.html 扁平到 www 根,相对路径重写(../ → ./)
sed -e 's#\.\./mobile-api\.js#./mobile-api.js#g' \
    -e 's#\.\./\.\./shared/#./shared/#g' \
    -e 's#\.\./\.\./vendor/#./vendor/#g' \
    -e 's#\.\./\.\./brand/#./brand/#g' \
    "$GW/mobile/m/index.html" > "$WWW/index.html"

# cd v0(2026-06-25)tokens + components.css 双模式 + mobile-overrides 兜底 onboarding
cp "$GW/mobile/m/tokens.css"            "$WWW/tokens.css"
cp "$GW/mobile/m/components.css"        "$WWW/components.css"
cp "$GW/mobile/m/mobile-overrides.css"  "$WWW/mobile-overrides.css"

# JS:mobile.js 主逻辑 + mobile-api.js shim
cp "$GW/mobile/m/mobile.js"    "$WWW/mobile.js"
cp "$GW/mobile/mobile-api.js"  "$WWW/mobile-api.js"

# manifest.json — PWA 添加到主屏支持
cp "$GW/mobile/m/manifest.json" "$WWW/manifest.json"

# 渲染器:marked + DOMPurify + 字体走系统 CJK 衬线,不带 webfont/CDN
cp "$GW/shared/md.js"             "$WWW/shared/md.js"
cp "$GW/vendor/marked.min.js"     "$WWW/vendor/marked.min.js"
cp "$GW/vendor/dompurify.min.js"  "$WWW/vendor/dompurify.min.js"

# brand:apple-touch-icon(PWA)
cp "$GW/brand/logo.svg"            "$WWW/brand/logo.svg" 2>/dev/null || true
cp "$GW/brand/logo-animated.svg"   "$WWW/brand/logo-animated.svg" 2>/dev/null || true

echo "[build-web] 移动原生 bundle 就绪 → $WWW"
du -sh "$WWW" 2>/dev/null || true
ls "$WWW" | head -20
