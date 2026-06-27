#!/usr/bin/env bash
# realOsTap.sh — 真 OS-level pixel tap on Simulator webview button
#
# 用法:realOsTap.sh "<selector>"
#   1. osascript 拿 Simulator window position + size
#   2. AppleScript 调 webview JS 拿 button rect
#   3. cliclick c:globalX,globalY 真物理 click
#
# 前提:
#   - Claude 已加进 macOS 辅助功能授权(或 cliclick 单独加)
#   - app 已 launch 且对应 webview 在 frontmost
#   - __GW_TEST_API__.querySelectorInfo 已挂(IIFE 末尾)
#
# 注:webview JS 不能直接被 AppleScript 调到(WKWebView 不暴露 JS API给 Apple Script)。
# 替代:web view 内 提前用 Capacitor Preferences 暂存 button rect → bash 读 plist 拿数。
# 本脚本接收 viewport 坐标作 arg,不动态查 selector。

VIEWPORT_X=${1:-0}
VIEWPORT_Y=${2:-0}
DEVICE_LOGICAL_W=${3:-393}    # iPhone 17 Pro
DEVICE_LOGICAL_H=${4:-852}

# Simulator window position + size from System Events
read WIN_X WIN_Y WIN_W WIN_H <<<$(osascript <<'EOF'
tell application "System Events"
  tell application process "Simulator"
    set p to position of window 1
    set s to size of window 1
    return (item 1 of p as text) & " " & (item 2 of p as text) & " " & (item 1 of s as text) & " " & (item 2 of s as text)
  end tell
end tell
EOF
)

if [ -z "$WIN_X" ]; then
  echo "FAIL: 拿不到 Simulator window 位置" >&2
  exit 1
fi

# Simulator window title bar (top chrome) 高 ~28
TITLE_BAR=28
CONTENT_Y_OFFSET=$((WIN_Y + TITLE_BAR))
CONTENT_H=$((WIN_H - TITLE_BAR))

# scale device logical → Simulator window pixel
X_RATIO=$(echo "scale=4; $WIN_W / $DEVICE_LOGICAL_W" | bc)
Y_RATIO=$(echo "scale=4; $CONTENT_H / $DEVICE_LOGICAL_H" | bc)

# Mac global = window origin + viewport coord * ratio
GLOBAL_X=$(echo "scale=0; $WIN_X + $VIEWPORT_X * $X_RATIO / 1" | bc)
GLOBAL_Y=$(echo "scale=0; $CONTENT_Y_OFFSET + $VIEWPORT_Y * $Y_RATIO / 1" | bc)

echo "Sim win: ($WIN_X,$WIN_Y) ${WIN_W}x${WIN_H}, content y_offset=$CONTENT_Y_OFFSET"
echo "Ratios: xRatio=$X_RATIO yRatio=$Y_RATIO"
echo "viewport ($VIEWPORT_X,$VIEWPORT_Y) → Mac global ($GLOBAL_X,$GLOBAL_Y)"

# activate Simulator + cliclick 真打
osascript -e 'tell application "Simulator" to activate' >/dev/null 2>&1
sleep 0.3
cliclick c:$GLOBAL_X,$GLOBAL_Y 2>&1
echo "exit: $?"
