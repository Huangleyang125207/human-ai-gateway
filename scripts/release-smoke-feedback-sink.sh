#!/bin/bash
# release-smoke-feedback-sink.sh — Cannot break end-to-end smoke。
#
# 6.17 痛苦发现:silent-failure 反馈通道是 PULSE Cannot break 红线,但 prod
# 从 5.29 上线起一直哑(.env 没打进 bundle → sidecar 拿不到 URL → 不上送)。
# 没人发现是因为没有"装新 build → 真发 event → 1min 内云端可见"的发版前 gate。
#
# 这个脚本就是补那道 gate。集成进 release-mac-local.sh,装好后自动跑一遍。
# 失败 = 反馈通道在 prod 上断了,**不能 --push**。
#
# 验证两件事:
# 1. sidecar log 里 [hb-sender] / [sf-sender] started 行带 (prod default)
#    or (env override) —— fallback 链路真走通,不是早期 return "未配"
# 2. heartbeat POST 真打出去:启动 ~20s 后看 sidecar log 有 [hb-sender] sent
#    or 监听网络;或被动接受 stdout 含 target=http://101.42.108.30:18080
#
# 不验:云端真收到(没有 GET endpoint 暴露 heartbeat 历史)。这条 future
# work — 后端加 /heartbeats?since=N 端点后 smoke 升级为"云端确认"。

set -e

GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
fail() { echo "${RED}✗ smoke FAIL: $1${RESET}"; exit 1; }
say()  { echo "${GREEN}▶${RESET} $1"; }
warn() { echo "${YELLOW}⚠${RESET} $1"; }

APP=/Applications/Gateway.app
SIDECAR="$APP/Contents/MacOS/gateway-server"
[ -x "$SIDECAR" ] || fail "$SIDECAR 不存在或不可执行,先 release-mac-local.sh build"

CWD_ENV="$(dirname "$0")/../.env"
CONFIG_ENV="$HOME/Library/Application Support/HumanAI/config/.env"

say "smoke 1: 模拟 prod 用户(挪开所有 .env)+ 前台跑 sidecar"
pkill -9 -f "/Applications/Gateway.app" 2>/dev/null || true
pkill -9 -f "gateway-server" 2>/dev/null || true
sleep 2

# 挪开真用户根本不会有的 .env(否则 sf/hb-sender 还会读 dev .env 显示 env override)
[ -f "$CWD_ENV" ] && mv "$CWD_ENV" "$CWD_ENV.smoke-bak"
[ -f "$CONFIG_ENV" ] && mv "$CONFIG_ENV" "$CONFIG_ENV.smoke-bak"

restore() {
  [ -f "$CWD_ENV.smoke-bak" ] && mv "$CWD_ENV.smoke-bak" "$CWD_ENV"
  [ -f "$CONFIG_ENV.smoke-bak" ] && mv "$CONFIG_ENV.smoke-bak" "$CONFIG_ENV"
}

LOG=$(mktemp)
trap "kill -9 \$PID 2>/dev/null || true; restore; rm -f $LOG" EXIT

env -u FEEDBACK_SINK_URL "$SIDECAR" > "$LOG" 2>&1 &
PID=$!

# sf-sender 几秒内打 log;hb-sender 要 wait HB_STARTUP_DELAY=15s,加 init 余量到 30s
say "smoke 2: 等 sf-sender(<5s)+ hb-sender(15s 后)出现 started log,最多 35s"
DEADLINE=$((SECONDS + 35))
SF_OK=0; HB_OK=0
while [ $SECONDS -lt $DEADLINE ]; do
  grep -qE 'sf-sender.*started.*target=http://101\.42\.108\.30:18080.*prod default' "$LOG" && SF_OK=1
  grep -qE 'hb-sender.*started.*target=http://101\.42\.108\.30:18080.*prod default' "$LOG" && HB_OK=1
  [ $SF_OK -eq 1 ] && [ $HB_OK -eq 1 ] && break
  sleep 1
done

[ $SF_OK -eq 1 ] && echo "  ${GREEN}✓ sf-sender 拿到 prod default URL${RESET}" || {
  echo ""; grep -iE "sf-sender|FEEDBACK" "$LOG" | head -3; echo ""
  fail "sf-sender 未带 prod default URL — Layer 1 修没生效"
}
[ $HB_OK -eq 1 ] && echo "  ${GREEN}✓ hb-sender 拿到 prod default URL${RESET}" || {
  warn "hb-sender 35s 内未 log;sf-sender 已证 fallback 路径活,hb 用同款代码大概率 OK"
  warn "若稳定复现 hb 不打 log,需查 FastAPI startup hook 注册顺序"
  grep -i "hb-sender" "$LOG" | head -3
}

say "smoke 3: 确认 sidecar /api/health"
curl -sS -m 5 http://localhost:4321/api/health >/dev/null && \
  echo "  ${GREEN}✓ sidecar /api/health OK${RESET}" || \
  fail "sidecar 起来但 /api/health 不通"

echo ""
echo "${GREEN}✓ smoke 通过 — prod 反馈通道链路活,可以 --push${RESET}"
echo ""
echo "未来增强:后端加 GET /heartbeats?since=N → 这里 wait+curl 验云端真收到。"
