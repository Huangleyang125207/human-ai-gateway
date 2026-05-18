# Human-AI Gateway · Fresh-from-Zero 迁移测试 (Mac)

> 测一台**从没装过 gateway 的 Mac**能不能跑起来。
> 不带任何 state(无 vault、无 config、无 thread-history),全靠首次启动引导。

---

## 测试前提

- macOS 10.14+
- 装了 Python 3.9+ (`python3 --version` 能跑出版本号)
  - 没有就 `brew install python` 或下 https://www.python.org/downloads/macos/
- 有 DeepSeek API key(或其他 OpenAI-compat 服务的 key)

---

## Step 1 — 装

1. 双击 `Gateway-Installer.dmg`
2. 弹出的窗口里把 **Gateway** 图标拖到 **Applications** 文件夹
3. 推出 DMG
4. Launchpad / Applications 里找到 **Gateway**,**右键 → 打开**(第一次必须右键,因没签名,直接双击会被 Gatekeeper 拦;之后双击就行)

> 如果想纯走命令行不要 .app:解开 `gateway-migration-*.tar.gz`,见 [start-mac.command](start-mac.command) 路径。

---

## Step 2 — 首次启动

双击 Gateway 后会弹一个 Terminal 窗口:

1. 检查 python3 ✓
2. 装依赖到 `~/Library/Python/3.x/lib/...`(--user 模式,不污染系统)
3. 发现 `~/Library/Application Support/HumanAI/config/gateway-config.json` 不存在 → 拷模板过去 + 自动 open 该文件
4. 弹一个文本编辑器,你把 `YOUR_DEEPSEEK_API_KEY` 改成真 key,保存
5. **再次** 启动 Gateway(双击 .app 即可)
6. 这次直接起 server + 自动开浏览器到 http://127.0.0.1:4321

> 关掉 Terminal 窗口 = 停 server。

---

## Step 3 — 验证

浏览器应该看到:

- 顶部品牌区 Gateway logo(碳硅共价键)
- 中部 care strip:8 个空水杯,无补剂 tile
- 右下角 thread tab(AI 浮起)

**关键验证点**(命令行):

```bash
# OS-标准状态目录自动创建
ls -la "$HOME/Library/Application Support/HumanAI/"
# 应有:
#   config/gateway-config.json   ← Step 2 填的 config
#   data/                        ← 启动后陆续填(thread-history / daily-task-meta / ...)

# vault 默认 path
ls -la "$HOME/.human-ai/" 2>/dev/null
# 没有也没事,首次"新一天"会创建
```

---

## Step 4 — 走一遍完整路径

1. 顶栏点 `+`(新一天)→ 应创建 `~/.human-ai/vault/半小时复盘/{今日}.md`
2. 右下角 thread tab → 跟 AI 说一句"hello"→ 应返回 streaming 输出(字一个一个弹)
3. care strip:点水杯任意一个 → 应填充 + md 顶部出现 `- [ ] 喝水` + 8 个嵌套子 box
4. 关闭浏览器 + Terminal,再次双击 Gateway,刷新页面 → 之前喝的水还在(持久化 OK)

---

## 出问题怎么报

Terminal 窗口里所有日志。起不来就把这些发回来:

```bash
python3 --version
python3 -m pip list 2>/dev/null | grep -iE "fastapi|uvicorn|openai|pillow|requests|multipart"
ls -la "$HOME/Library/Application Support/HumanAI/"
# server 启动报错最后 30 行(Terminal 输出)
```

---

## 干净卸载

```bash
# 1. 应用本体
rm -rf /Applications/Gateway.app

# 2. 所有 app state(状态/config/缓存/图)
rm -rf "$HOME/Library/Application Support/HumanAI"

# 3. vault(用户数据 — 慎删)
# rm -rf "$HOME/.human-ai"
```

依赖 pip 装的 fastapi/uvicorn/openai 留着没事,也可 uninstall。

---

## 重新打包(开发者用)

代码改了想再出一个 DMG:

```bash
cd gateway
bash build-mac-app.sh
# 出:dist/Gateway.app + dist/Gateway-Installer.dmg
```

---

## TODO

- [ ] Windows 版 `Gateway-Setup.exe`(同款拖装体验)
- [ ] PyInstaller 单二进制(免装 python — 当前 .app 是 thin wrapper,user 还得有 python3)
- [ ] 签名 + 公证 (codesign + notarytool,避免右键打开那一步)
