#!/bin/bash
# human-ai gateway 启动脚本
# 用法：bash start.sh
#
# 数据 root 解析: $HUMAN_AI_HOME → ~/.human-ai/ (默认)
# 代码 root: 本脚本所在目录的父级 (= ~/human-ai-dev/)

set -e
cd "$(dirname "$0")"
DATA_HOME="${HUMAN_AI_HOME:-$HOME/.human-ai}"
CONFIG_PATH="$DATA_HOME/config/gateway-config.json"
EXAMPLE_PATH="$(cd .. && pwd)/config.example/gateway-config.example.json"

# 1. 检查 python
if ! command -v python3 >/dev/null; then
  echo "✗ 需要 python3。装 brew install python 或从 python.org 下"
  exit 1
fi

# 2. 检查依赖
if ! python3 -c "import fastapi, uvicorn, openai, multipart" 2>/dev/null; then
  echo "→ 装依赖（首次启动）..."
  python3 -m pip install --user fastapi uvicorn openai python-multipart pillow requests
fi

# 3. 检查 config
if [ ! -f "$CONFIG_PATH" ]; then
  if [ -f "$EXAMPLE_PATH" ]; then
    mkdir -p "$DATA_HOME/config"
    cp "$EXAMPLE_PATH" "$CONFIG_PATH"
    echo "→ 已复制 example → $CONFIG_PATH"
    echo "→ 编辑该文件填入真 api_key 后重新运行 start.sh"
    exit 0
  else
    echo "✗ 缺 $CONFIG_PATH 且无 example,无法启动"
    exit 1
  fi
fi

if grep -q "YOUR_.*API_KEY" "$CONFIG_PATH"; then
  echo "✗ $CONFIG_PATH 里有 YOUR_*_API_KEY 占位符。编辑它填入真 key 后重启。"
  exit 1
fi

# 4. 起 server
export HUMAN_AI_HOME="$DATA_HOME"
echo "→ 启动 server on http://localhost:4321 (data home: $DATA_HOME)"
python3 server.py
