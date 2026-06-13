#!/usr/bin/env bash
# 组装移动端 web bundle:只把 webview 需要的静态文件拷进 app/www/。
# Capacitor sync 时会把 www/ 整个塞进原生工程 —— 所以绝不能让 server.py /
# .venv / .git / dist 之类进来(那会让 app 膨胀几百 MB)。
#
# 用法:bash mobile/build-web.sh   (或在 app/ 里 npm run build:web)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"     # gateway/mobile
GW="$(cd "$HERE/.." && pwd)"              # gateway 根
WWW="$HERE/app/www"

rm -rf "$WWW"
mkdir -p "$WWW/mobile"

# 入口页 + 核心前端资源(与桌面同一份,零分叉)
cp "$GW/index.html"            "$WWW/index.html"
cp -R "$GW/shared"             "$WWW/shared"
cp -R "$GW/vendor"             "$WWW/vendor"
cp -R "$GW/brand"              "$WWW/brand"
cp "$GW/mobile/mobile-api.js"  "$WWW/mobile/mobile-api.js"

# 本地后端拦截层在真机靠 Capacitor 注入的 window.Capacitor 自动启用,
# 无需 ?mobile=1;桌面仍惰性。

echo "[build-web] bundle 就绪 → $WWW"
du -sh "$WWW" 2>/dev/null || true
