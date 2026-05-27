#!/usr/bin/env bash
# gw-cron.sh — 给 launchd cron 用:从 .gateway-port 读 Tauri sidecar 的**动态端口**再 POST。
#
# 为什么:Tauri 壳给 server 分动态端口(不再固定 4321,见里程碑 A 动态端口根治孤儿/重绑),
# 但 launchd 的 daily-eval(21:30) / pulse-refresh(21:00) 原本写死 4321 → Tauri 上线后
# 连不上、cron 全哑(5.27 留言板 + PULSE 停更真因)。改成这个 wrapper 现场读端口。
#
# 用法: gw-cron.sh <api-path> [json-body] [max-time-sec]
#   gw-cron.sh /api/eval/run '{"model_id":"deepseek-v4-pro"}' 120
#   gw-cron.sh /api/pulse/refresh-mirror '{}' 60
set -euo pipefail

PORT_FILE="$HOME/.human-ai/.gateway-port"
API_PATH="${1:?usage: gw-cron.sh <api-path> [json-body] [max-time]}"
BODY="${2:-{}}"
MAXT="${3:-120}"

if [ ! -f "$PORT_FILE" ]; then
  echo "[gw-cron] 没有 $PORT_FILE — gateway 没在跑?cron 跳过。" >&2
  exit 1
fi
PORT="$(tr -dc '0-9' < "$PORT_FILE")"
if [ -z "$PORT" ]; then
  echo "[gw-cron] $PORT_FILE 内容不是端口号。" >&2
  exit 1
fi

URL="http://127.0.0.1:${PORT}${API_PATH}"
echo "[gw-cron] $(date '+%F %T') → POST $URL"
curl -sS -X POST "$URL" \
  -H "Content-Type: application/json" \
  -d "$BODY" \
  --max-time "$MAXT"
