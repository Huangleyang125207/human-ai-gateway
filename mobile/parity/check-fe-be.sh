#!/usr/bin/env bash
# check-fe-be.sh — 前后端对齐 + PC parity 覆盖 的 grep 检查(无运行时,快)。
# 用法: bash mobile/parity/check-fe-be.sh   (从 gateway repo 根跑)
# parity loop 每轮收敛检时跑;输出三类落差,空 = 该维度对齐。
set -euo pipefail
cd "$(dirname "$0")/../.."
API=mobile/mobile-api.js
# 6.25 起 mobile FE 拆成 cd 5 件套 + bridge,grep 整目录而非单文件
FE_DIR=mobile/m

# PC 端真实 /api 端点(桌面 route 模块 + server 的 @app/@router)
pc_routes() {
  grep -rhoE '@(app|router)\.(get|post|put|delete)\("(/api/[^"]+)"' \
    server.py *_routes.py 2>/dev/null | grep -oE '/api/[a-z/_{}-]+' | sort -u
}
# mobile-api.js 真正 handle 的 /api 路由
# regex 收紧:末尾必须 [a-z_-](排除 trailing slash;字符串拼接 "/api/x/" 不算)
mob_handles() { grep -oE '/api/[a-z][a-z/_-]*[a-z_-]' "$API" 2>/dev/null | sort -u; }
# 前端引用到的 /api 路由(扫整个 mobile/m/,排注释行 //  和 /* ... */ 缩写)
fe_refs() {
  grep -rh -oE '/api/[a-z][a-z/_-]*[a-z_-]' "$FE_DIR"/*.js 2>/dev/null \
    | sort -u
}

echo "═══ ① FE↔BE:前端引用了但 shim 没 handle 的(= 死按钮)═══"
comm -23 <(fe_refs) <(mob_handles) | sed 's/^/  ✗ 死引用: /'
echo "  (空 = 前端每个 /api 调用 shim 都接得住)"
echo ""
echo "═══ ② PARITY:PC 有但 mobile shim 没 handle(= 未迁/缺口)═══"
echo "     (OUT-OF-SCOPE 的 chat tool-loop/board/telemetry 等可忽略;其余是真缺口)"
comm -23 <(pc_routes) <(mob_handles) | sed 's/^/  ⚠ 未 shim: /'
echo ""
echo "═══ ③ shim handle 了但 PC 没有的(可能命名漂/陈旧)═══"
comm -13 <(pc_routes) <(mob_handles) | sed 's/^/  ? 仅 mobile: /'
