# Mobile E2E Test Workflow

> 在 iOS simulator 上自验完整链路,不依赖 simctl tap / XcodeBuildMCP / OpenSafari。
> **核心思路**:让 mobile-api 启动时跑 self-test,把 report 写到 Capacitor Preferences,
> 从 host plist `defaults read` 拉出真值。**真 plist 落盘 = 不可伪造的 evidence。**

## 适用场景

- 验 Storage / Preferences / Filesystem 真存读
- 验 chat tool loop 真触发 + 真副作用
- 验 onboarding / setup_routes contract
- 任何 webview JS 路径行为(不需要看 console.log)

## 工具栈

| 工具 | 用途 |
|---|---|
| `xcrun simctl` | boot / install / launch / get_app_container |
| `plutil -p` | 读真 plist 值 |
| `bash build-web.sh` | 同步 mobile/m → app/www |
| `npx cap copy ios` | 同步 www → ios/App/App/public(`cap run --no-sync` 跳 sync 但必须 cap copy) |
| `npx cap run ios --target=<UDID>` | 真 build + install + launch |

## Workflow:跑一次完整 E2E

```bash
SIMID="F362B9E3-58F3-4E07-A698-B91EFCBF7CA6"  # iPhone 17 Pro
cd ~/human-ai-dev/gateway/mobile

# 1. bump version 防 webview cache
sed -i '' 's/?v=dXX/?v=dYY/g' m/index.html

# 2. build web → www
bash build-web.sh

# 3. 注入真 key(防 source 改动 / 不入 git)
sed -i '' 's|window.__GATEWAY_MOBILE__ = true;|window.__GATEWAY_MOBILE__ = true; window.__GW_REAL_KEY__ = "sk-...";|' app/www/index.html

# 4. cap copy(必须,否则 ios/public 拿不到新 www)
cd app
npx cap copy ios

# 5. 清装重启(防 localStorage / Preferences 残留)
xcrun simctl terminate "$SIMID" com.humanai.gateway
xcrun simctl uninstall "$SIMID" com.humanai.gateway
npx cap run ios --target="$SIMID" --scheme=App --no-sync

# 6. 拿新 app data 路径(uninstall 后 UUID 会变)
NEWDATA=$(xcrun simctl get_app_container "$SIMID" com.humanai.gateway data)

# 7. launch + 等 self-test 跑完(含真 chat ~ 60-90s)
xcrun simctl launch "$SIMID" com.humanai.gateway
sleep 90

# 8. 读真 plist
plutil -p "$NEWDATA/Library/Preferences/com.humanai.gateway.plist"
```

## self-test 结构(mobile-api.js IIFE 末尾)

- `setTimeout 500ms`(等 Capacitor bridge 真就绪)
- T1:Store round-trip 验 Storage 层
- T2-T4:/api/setup/save-partial + /api/setup/current + Store 直读三角验
- T5:/api/setup/test 用假 key 真打 deepseek(期望 401)
- T6:/api/chat 用假 key(期望 error)
- T7-T11:用真 key(`window.__GW_REAL_KEY__`)真打 chat 验 tool loop
- 完整 report 写到 `setting/__self_test_report__`

## 22 TOOL_SPECS 全名单 + 验收状态

| # | tool | 状态 | 验收 chat 提示 |
|---|---|---|---|
| 1 | read_today_schedule | ✅ T9 | "把今天 16:30 的一条改成 X(必先 read schedule)" |
| 2 | patch_journal_block | ✅ T9 | 同上 |
| 3 | check_daily_task | ✅ T10 | "我吃了一颗鱼油,用 check_daily_task 打卡" |
| 4 | web_search | ✅ T11 | "用 web_search 搜 X" |
| 5 | insert_journal_block | ⬜ T12 | "在今天 17:00 插入条新条目" |
| 6 | append_journal_comment | ⬜ T12 | "在今天 16:30 那块加批注 X" |
| 7 | search_journal | ⬜ T12 | "搜历史日记里我提过 X 几次" |
| 8 | list_recent_days | ⬜ T12 | "列最近 7 天日记日期" |
| 9 | manage_daily_task | ⬜ T13 | "新增日打卡:维生素 C" |
| 10 | set_daily_task_meta | ⬜ T13 | "鱼油每瓶 60 颗,每天 2 颗" |
| 11 | set_water_cup_image | ⬜ T13 | "把水杯图标换成蓝色" |
| 12 | fetch_url | ⬜ T14 | "fetch_url 取这页内容: https://example.com" |
| 13 | vision_classify | ⬜ T15 | "看一下我刚拖进来的图(需 dummy attachment)" |
| 14 | ocr_image | ⬜ T15 | "OCR 这张图(需 dummy attachment)" |
| 15 | list_my_uploads | ⬜ T16 | "列我最近 10 张图" |
| 16 | search_my_uploads | ⬜ T16 | "搜我图里有 X 的" |
| 17 | ask_photo_curator | ⬜ T16 | "问 photo curator 我 X 时候拍了啥" |
| 18 | delete_attachment | ⬜ T16 | "删 X 张图" |
| 19 | list_widgets | ⬜ T17 | "列我的 widget" |
| 20 | add_widget | ⬜ T17 | "加个 X widget" |
| 21 | remove_widget | ⬜ T17 | "删 X widget" |
| 22 | set_widget_enabled | ⬜ T17 | "关掉 X widget" |

## 升级路径(双 MCP 装法)

### XcodeBuildMCP — UI 自动化 + LLDB debug(by Sentry)

**装(Claude Code 端):**
```bash
claude mcp add XcodeBuildMCP -- npx -y xcodebuildmcp@latest mcp
# 或 brew(无需 Node):
brew tap getsentry/xcodebuildmcp && brew install xcodebuildmcp
```

**能力**(82 tools):
- 真 tap / swipe / drag / type / key press 模拟 simulator
- screenshot / UI hierarchy / accessibility tree
- xcodebuild build / test / archive 全套
- LLDB stateful debug:attach / breakpoint / stack / variables

**装好后 workflow 升级**:替代 self-test 内置真模拟 user 操作(粘 key / 点测试按钮 / 切 chat 输入消息)。

### OpenSafari — WebView console + DOM 实时(by shaun0927)

**前置:**
```bash
brew install ios-webkit-debug-proxy
```

**装(Claude Code 端 — `.mcp.json`)**:
```json
{
  "mcpServers": {
    "opensafari": {
      "command": "npx",
      "args": ["-y", "opensafari-mcp", "serve"]
    }
  }
}
```

**能力**(Tier 1 默认 8 tools):
| tool | 用途 |
|---|---|
| `navigate` | 真 Safari 开 URL |
| `screenshot` | WebKit Protocol 真截屏 |
| `query_dom` | CSS selector 查 DOM |
| `javascript` | 跑 JS in page context(等同 console)|
| `read_page` | 提取可见文字 |
| `click` / `type` | 真点真输 |
| `cookies` | 读写真 cookie |

**装好后 workflow 升级**:不用 plist 反推,**直接读 WebView console.log + DOM query 状态栏文字**。

### 装好后的 workflow

```
1. WKWebView 加载 Capacitor app
2. OpenSafari `javascript` 跑 self-test 函数(不靠 IIFE setTimeout)
3. OpenSafari `read_page` 拿状态栏文字 / DOM 真值
4. XcodeBuildMCP `tap` 真点测试按钮
5. OpenSafari `javascript` 真打 chat 真看 SSE
```

### 装不装的决策

| 场景 | 推荐工具 |
|---|---|
| 验 Storage 真存(本次 fix 验收)| **plist 法**(本文档)|
| 验 chat tool loop 真触发 | **plist + 内置 self-test**(本文档)|
| 验真 user 操作 UI 全流程 | + XcodeBuildMCP |
| WebView console.log debug | + OpenSafari |
| Swift native 代码改 / LLDB | + XcodeBuildMCP |

**当前 plist 法已足够 chat tool loop 全验收**(不依赖 MCP 装好,不需 Claude Code restart)。
