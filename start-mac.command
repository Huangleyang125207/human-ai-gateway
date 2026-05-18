#!/bin/bash
# Human-AI Gateway — Mac 一键启动(双击即可,也可 bash 直接跑)
# Fresh-from-zero 测试:无任何 state 时也能跑起来引导填 config
set -e
cd "$(dirname "$0")"

GATEWAY_DIR="$(pwd)"
APP_STATE_DIR="$HOME/Library/Application Support/HumanAI"
CONFIG_PATH="$APP_STATE_DIR/config/gateway-config.json"
EXAMPLE_PATH="$GATEWAY_DIR/.gateway-config.example.json"

echo "════════════════════════════════════════════"
echo "   Human-AI Gateway · Mac 启动"
echo "   代码: $GATEWAY_DIR"
echo "   状态: $APP_STATE_DIR"
echo "════════════════════════════════════════════"
echo

# ── 1. python3 ─────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
  echo "✗ 没装 python3"
  echo "  推荐: brew install python  (或 https://www.python.org/downloads/macos/)"
  echo
  read -p "按回车关闭..."
  exit 1
fi
PY_VER=$(python3 --version 2>&1)
echo "✓ $PY_VER"

# ── 2. 依赖 ────────────────────────────────────────
echo "→ 检查依赖..."
if ! python3 -c "import fastapi, uvicorn, openai, multipart, PIL, requests" 2>/dev/null; then
  echo "  首次启动,装依赖(--user,不会污染系统 python)..."
  python3 -m pip install --user --quiet -r requirements.txt || {
    echo "✗ pip install 失败"
    read -p "按回车关闭..."
    exit 1
  }
fi
echo "✓ 依赖齐全"

# ── 3. config ──────────────────────────────────────
if [ ! -f "$CONFIG_PATH" ]; then
  echo "→ 首次启动:落 config 模板"
  mkdir -p "$(dirname "$CONFIG_PATH")"
  cp "$EXAMPLE_PATH" "$CONFIG_PATH"
  echo "✓ 已落到: $CONFIG_PATH"
  echo
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  下一步: 编辑该文件,填进真的 api_key,然后重启脚本"
  echo "  打开:    open '$CONFIG_PATH'"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo
  open "$CONFIG_PATH" || true
  read -p "按回车关闭..."
  exit 0
fi

if grep -q "YOUR_.*API_KEY" "$CONFIG_PATH"; then
  echo "✗ $CONFIG_PATH 里还有占位符 YOUR_*_API_KEY"
  echo "  open '$CONFIG_PATH' → 填进真 key → 重启"
  open "$CONFIG_PATH" || true
  read -p "按回车关闭..."
  exit 1
fi
echo "✓ config OK"

# ── 4. 启动 server + 自动开浏览器 ──────────────────
URL="http://127.0.0.1:4321"
echo "→ 启动 server: $URL"
echo "  关掉这个 Terminal 窗口 = 停止 server"
echo
# 后台延迟开浏览器(等 server 监听就绪)
(
  for i in {1..20}; do
    if curl -s "$URL/api/health" >/dev/null 2>&1; then
      open "$URL"
      exit 0
    fi
    sleep 0.5
  done
) &

exec python3 -m uvicorn server:app --host 127.0.0.1 --port 4321 --log-level info
