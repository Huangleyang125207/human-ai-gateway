#!/bin/bash
# test-bundle.sh — 在隔离 state 里跑 bundled Gateway,端点 smoke 测试
#
# 用法:bash test-bundle.sh [path/to/Gateway.app]
#   默认: ./dist-pyinstaller/Gateway.app
#
# 隔离:HUMAN_AI_STATE=/tmp/gateway-test-state · HUMAN_AI_HOME=/tmp/gateway-test-vault
#       不会动你的真 ~/.human-ai 和 ~/Library/Application Support/HumanAI
# 端口:4322(避开 dev server 4321)
#
# 跑完自动 cleanup(kill process + rm temp state)。

set -e
cd "$(dirname "$0")"

APP_PATH="${1:-./dist-pyinstaller/Gateway.app}"
BIN="$APP_PATH/Contents/MacOS/Gateway"

if [ ! -x "$BIN" ]; then
  echo "✗ 没找到 $BIN — 先 bash build-mac-pyinstaller.sh"
  exit 1
fi

# 隔离临时目录
TEST_STATE="/tmp/gateway-test-state-$$"
TEST_VAULT="/tmp/gateway-test-vault-$$"
TEST_PORT=4322
LOG_FILE="/tmp/gateway-test-$$.log"

cleanup() {
  if [ -n "$BUNDLE_PID" ]; then
    # disown 防 bash 打 "Killed: 9" 行(进程被信号杀死的 default 输出)
    disown "$BUNDLE_PID" 2>/dev/null || true
    kill "$BUNDLE_PID" 2>/dev/null || true
    sleep 0.3
    kill -9 "$BUNDLE_PID" 2>/dev/null || true
    wait "$BUNDLE_PID" 2>/dev/null || true
  fi
  rm -rf "$TEST_STATE" "$TEST_VAULT" "$LOG_FILE"
}
trap cleanup EXIT INT

PASS=0
FAIL=0

# ── helpers ────────────────────────────────────────────
GREEN=$'\033[32m'
RED=$'\033[31m'
DIM=$'\033[2m'
RESET=$'\033[0m'

check() {
  local name="$1"
  local actual="$2"
  local pattern="$3"
  if echo "$actual" | grep -qE "$pattern"; then
    echo "  ${GREEN}✓${RESET} $name"
    PASS=$((PASS+1))
  else
    echo "  ${RED}✗${RESET} $name"
    echo "    expected pattern: $pattern"
    echo "    actual: ${actual:0:200}"
    FAIL=$((FAIL+1))
  fi
}

echo "════════════════════════════════════════════"
echo "  Gateway bundle smoke test"
echo "  binary: $BIN"
echo "  state:  $TEST_STATE"
echo "  vault:  $TEST_VAULT"
echo "  port:   $TEST_PORT"
echo "════════════════════════════════════════════"

# ── 1. 启动 bundled binary ──────────────────────────
echo
echo "→ 1. 启动 bundled binary(隔离 env)"
HUMAN_AI_STATE="$TEST_STATE" \
HUMAN_AI_HOME="$TEST_VAULT" \
GATEWAY_PORT=$TEST_PORT \
GATEWAY_NO_OPEN=1 \
"$BIN" > "$LOG_FILE" 2>&1 &
BUNDLE_PID=$!
echo "  PID=$BUNDLE_PID"

# 等 server 就绪(最多 10 秒)
for i in {1..20}; do
  if curl -s "http://127.0.0.1:$TEST_PORT/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
if ! curl -s "http://127.0.0.1:$TEST_PORT/api/health" >/dev/null 2>&1; then
  echo "  ${RED}✗ server 10 秒内没起来${RESET}"
  echo "  最后 20 行 log:"
  tail -20 "$LOG_FILE"
  exit 1
fi
echo "  ${GREEN}✓${RESET} server 起来了"

# ── 2. 端点 smoke ─────────────────────────────────────
echo
echo "→ 2. 关键端点(fresh state,跟 user's other Mac 同条件)"

# /api/health
R=$(curl -s "http://127.0.0.1:$TEST_PORT/api/health")
check "/api/health 返 ok"     "$R" '"ok"[[:space:]]*:[[:space:]]*true'

# /api/user-widgets:fresh 时无文件,应返默认 {active:[]}(而非 404)
R=$(curl -s "http://127.0.0.1:$TEST_PORT/api/user-widgets")
check "/api/user-widgets 返 JSON" "$R" '"active"'

# /api/journal/days:fresh 应返空数组
R=$(curl -s "http://127.0.0.1:$TEST_PORT/api/journal/days")
check "/api/journal/days 返 days 数组" "$R" '"days"[[:space:]]*:[[:space:]]*\['

# /api/journal/today:fresh 应返 error(无今天文件),但 200 + JSON 格式
R=$(curl -s "http://127.0.0.1:$TEST_PORT/api/journal/today")
check "/api/journal/today 在 fresh 时返 error JSON" "$R" '"error"[[:space:]]*:[[:space:]]*"no journal file'

# / 静态文件应 200
R=$(curl -s "http://127.0.0.1:$TEST_PORT/")
check "/ 返 index.html(<!DOCTYPE html>)" "$R" '<!DOCTYPE html>'

# /api/daily-tasks:fresh 应返 tasks 数组(可能空,无 daily-tasks.md)
R=$(curl -s "http://127.0.0.1:$TEST_PORT/api/daily-tasks")
check "/api/daily-tasks 返 JSON" "$R" '"tasks"[[:space:]]*:[[:space:]]*\['

# POST /api/journal/new-day:创建今天
R=$(curl -s -X POST -H 'Content-Type: application/json' -d '{}' \
    "http://127.0.0.1:$TEST_PORT/api/journal/new-day")
check "POST /api/journal/new-day 创建今天" "$R" '"ok"[[:space:]]*:[[:space:]]*true.*"created"[[:space:]]*:[[:space:]]*true'

# 再 POST 一次应幂等(created=false)
R=$(curl -s -X POST -H 'Content-Type: application/json' -d '{}' \
    "http://127.0.0.1:$TEST_PORT/api/journal/new-day")
check "POST /api/journal/new-day 幂等(再调返 created=false)" "$R" '"created"[[:space:]]*:[[:space:]]*false'

# 这下 /api/journal/today 应该有 blocks 了
R=$(curl -s "http://127.0.0.1:$TEST_PORT/api/journal/today")
check "/api/journal/today 现在返 blocks" "$R" '"blocks"[[:space:]]*:[[:space:]]*\['

# 验今天文件真的落到了隔离 vault
TODAY_FILE=$(ls "$TEST_VAULT/vault/半小时复盘/"*.md 2>/dev/null | head -1)
if [ -n "$TODAY_FILE" ]; then
  echo "  ${GREEN}✓${RESET} 今天文件落在 $TODAY_FILE"
  PASS=$((PASS+1))
else
  echo "  ${RED}✗${RESET} 今天文件没出现在 $TEST_VAULT/vault/半小时复盘/"
  FAIL=$((FAIL+1))
fi

# 验 APP_STATE_DIR env 真的生效(看 startup log)
# 注:fresh 时没 endpoint 触发 APP_STATE_DIR 落盘,所以查 log 比查目录靠谱
if grep -q "config: $TEST_STATE" "$LOG_FILE"; then
  echo "  ${GREEN}✓${RESET} HUMAN_AI_STATE env 生效(log 里 config 路径指 $TEST_STATE)"
  PASS=$((PASS+1))
else
  echo "  ${RED}✗${RESET} HUMAN_AI_STATE env 没生效"
  FAIL=$((FAIL+1))
fi

# 触发写 APP_STATE_DIR,然后验目录真出现(daily-tasks/check 写 meta.json)
curl -s -X POST -H 'Content-Type: application/json' \
     -d '{"task_name":"smoketest","intake":1}' \
     "http://127.0.0.1:$TEST_PORT/api/daily-tasks/check" >/dev/null
if [ -f "$TEST_STATE/data/daily-task-meta.json" ]; then
  echo "  ${GREEN}✓${RESET} POST 写真的落到 $TEST_STATE/data/"
  PASS=$((PASS+1))
else
  echo "  ${RED}✗${RESET} POST 没把 meta.json 落到隔离 state"
  FAIL=$((FAIL+1))
fi

# history.html 页面 200(static asset 真打进 _MEIPASS)
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$TEST_PORT/history.html")
if [ "$HTTP" = "200" ]; then
  echo "  ${GREEN}✓${RESET} GET /history.html → 200(asset 在 bundle 里)"
  PASS=$((PASS+1))
else
  echo "  ${RED}✗${RESET} GET /history.html → $HTTP(asset 没打进 bundle?)"
  FAIL=$((FAIL+1))
fi

# /api/history/stats(vault 没 git 时返 error JSON,但 200)
R=$(curl -s "http://127.0.0.1:$TEST_PORT/api/history/stats")
check "/api/history/stats 返 JSON" "$R" '"(error|total)"'

# /api/history/recent(同上)
R=$(curl -s "http://127.0.0.1:$TEST_PORT/api/history/recent?limit=5")
check "/api/history/recent 返 JSON" "$R" '"(error|commits)"'

# ── 3. 结果 ────────────────────────────────────────
echo
echo "════════════════════════════════════════════"
if [ "$FAIL" -eq 0 ]; then
  echo "  ${GREEN}✓ 全部 $PASS 项通过${RESET}"
  EXIT=0
else
  echo "  ${RED}✗ $FAIL 项失败${RESET} · ${GREEN}$PASS 项通过${RESET}"
  echo
  echo "  bundled binary log(最后 30 行):"
  tail -30 "$LOG_FILE" | sed 's/^/    /'
  EXIT=1
fi
echo "════════════════════════════════════════════"
exit $EXIT
