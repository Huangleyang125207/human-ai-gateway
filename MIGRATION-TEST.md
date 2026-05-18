# Human-AI Gateway · Fresh-from-Zero 迁移测试

> 测一台**从没装过 gateway 的 Mac**能不能跑起来。
> 不带任何 state(无 vault、无 config、无 thread-history),全靠首次启动引导。

---

## 测试前提

- macOS 11+(理论上 10.x 也行,没测)
- 装了 Python 3.9+ (`python3 --version` 能跑出版本号)
  - 没有就 `brew install python` 或下 https://www.python.org/downloads/macos/
- 装了 `pip`(随 python3 来,默认就有)
- 有 DeepSeek API key(或其他 OpenAI-compat 服务的 key)

---

## Step 1 — 解包

把 `gateway-migration-*.tar.gz` 解到任意位置,比如桌面或 `~/Apps/`:

```bash
mkdir -p ~/Apps
cd ~/Apps
tar xzf ~/Downloads/gateway-migration-2026-05-18.tar.gz
cd gateway
ls
```

应该看到:`server.py` / `index.html` / `start-mac.command` / `shared/` / `widgets/` / `brand/` 等等。

---

## Step 2 — 双击 `start-mac.command`

Finder 里找到 `start-mac.command`,**右键 → 打开**(第一次必须右键,因为没签名,直接双击会被 Gatekeeper 拦)。

会自动:

1. 检查 python3 ✓
2. 装依赖到 `~/Library/Python/3.x/lib/...`(--user 模式,不污染系统)
3. 发现 `~/Library/Application Support/HumanAI/config/gateway-config.json` 不存在 → 拷模板过去 + open 该文件
4. 弹一个文本编辑器,你把 `YOUR_DEEPSEEK_API_KEY` 改成真 key,保存
5. **再次** 双击 `start-mac.command`
6. 这次直接启动 server + 自动开浏览器到 http://127.0.0.1:4321

---

## Step 3 — 验证

打开浏览器后应当看到:

- 顶部品牌区有 `🔷 Gateway` logo(碳硅共价键)
- "载入中⋯" → 几秒后出现"还没新建今天的日记"或类似空状态
- 中部 care strip:8 个空水杯,无补剂 tile
- 右下角 thread tab(AI 浮起)

**关键验证点**:

```bash
# OS-标准状态目录应当自动创建
ls -la "$HOME/Library/Application Support/HumanAI/"
# 应有:
#   config/gateway-config.json   ← Step 2 填的 config
#   data/                        ← 启动后会陆续填(thread-history、daily-task-meta 等)

# vault(用户数据)默认 path
ls -la "$HOME/.human-ai/" 2>/dev/null
# 没有也没事,首次"新一天"会创建
```

---

## Step 4 — 走一遍完整路径

1. 顶栏点 `+`(新一天)→ 应当创建 `~/.human-ai/vault/半小时复盘/{今日}.md`
2. 右下角 thread tab → 跟 AI 说一句"hello"→ 应当返回 streaming 输出
3. care strip:点水杯任意一个 → 应当填充 + md 顶部出现 `- [ ] 喝水` + 8 个子 box
4. 关闭浏览器 + Terminal,再次双击 `start-mac.command`,刷新页面 → 之前喝的水还在(数据持久化 OK)

---

## 出问题怎么报

终端窗口会有所有日志。如果起不来,把这部分发回来:

```bash
# 1. python 版本
python3 --version

# 2. 已装依赖
python3 -m pip list 2>/dev/null | grep -iE "fastapi|uvicorn|openai|pillow|requests|multipart"

# 3. 配置存在性
ls -la "$HOME/Library/Application Support/HumanAI/"

# 4. server 启动报错(最后 30 行)
# 直接复制 Terminal 输出
```

---

## 干净卸载

```bash
rm -rf ~/Apps/gateway                                      # 代码
rm -rf "$HOME/Library/Application Support/HumanAI"         # 所有 app state
rm -rf "$HOME/.human-ai"                                   # vault(若不想删用户数据可跳)
# pip 装的依赖留着没事,也可:python3 -m pip uninstall fastapi uvicorn openai ...
```

---

## 下一步(本次测过后)

- [ ] Windows 版 `start-win.bat`(同款逻辑)
- [ ] PyInstaller 单二进制(免装 python)
- [ ] Mac `.app` 套壳(Platypus 或 PyInstaller --onefile + .app bundle)
