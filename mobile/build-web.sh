#!/usr/bin/env bash
# 组装移动端 web bundle → app/www/。入口 = 移动原生前端 mobile/m/。
# Capacitor sync 时把 www/ 整个塞进原生工程,所以只带 webview 要的文件。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"     # gateway/mobile
GW="$(cd "$HERE/.." && pwd)"              # gateway 根
WWW="$HERE/app/www"

rm -rf "$WWW"
mkdir -p "$WWW/shared" "$WWW/vendor"

# 入口:移动原生 index.html 扁平到 www 根,相对路径重写(../ → ./)
sed -e 's#\.\./mobile-api\.js#./mobile-api.js#g' \
    -e 's#\.\./\.\./shared/#./shared/#g' \
    -e 's#\.\./\.\./vendor/#./vendor/#g' \
    "$GW/mobile/m/index.html" > "$WWW/index.html"
cp "$GW/mobile/m/mobile.css"   "$WWW/mobile.css"
cp "$GW/mobile/m/mobile.js"    "$WWW/mobile.js"
cp "$GW/mobile/mobile-api.js"  "$WWW/mobile-api.js"

# 渲染器 + 设计 token(纸系)。字体走系统 CJK 衬线(iOS Songti/Kaiti),不带 webfont/CDN。
cp "$GW/shared/md.js"             "$WWW/shared/md.js"
cp "$GW/shared/design-tokens.css" "$WWW/shared/design-tokens.css"
cp "$GW/vendor/marked.min.js"     "$WWW/vendor/marked.min.js"
cp "$GW/vendor/dompurify.min.js"  "$WWW/vendor/dompurify.min.js"

echo "[build-web] 移动原生 bundle 就绪 → $WWW"
du -sh "$WWW" 2>/dev/null || true
