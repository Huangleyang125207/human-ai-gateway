# Task: 在 Windows 上 build Gateway.exe + 跑 smoke

> 把这整个 .md 交给 Windows 那边的 Claude Code(VSCode/Cursor)。
> 它跑完后让你把 report 贴回 Mac 端的 session。

---

## 背景

这是 human-ai-schedule 项目的 viewer/server(FastAPI + uvicorn + vanilla JS),
Mac 端已经 ship 了 .dmg,现在要在 Windows 上打 self-contained .exe。
跨平台核心代码已对齐(端侧 OCR 走 rapidocr ONNX,抠图走 rembg ONNX,
不需要 macOS Vision binary)。

## 前置

1. **Python 3.10+** 装好,`where python` 能看到
2. **gateway/ 源码目录** 在本机(用户应该已经 cp/clone 到某路径,假设 C:\gateway 或类似)
3. **可联网**(pip install 拉 rapidocr-onnxruntime + rembg + onnxruntime 一次性)

---

## 你做的事(按顺序)

### 1. 找到 gateway 目录

- 先 `dir C:\` 或 `dir %USERPROFILE%\Desktop\` 找 gateway 文件夹
- 找到后 `cd <那个路径>`
- 应该能看到 server.py / build-win.bat / WINDOWS.md 等文件
- 没找到就问用户:"请告诉我 gateway 目录的完整路径"

### 2. 读 WINDOWS.md

- 完整看一遍,了解 build / smoke / 分发流程
- 跟下面要做的对照,有差异以 WINDOWS.md 为准

### 3. 跑 build-win.bat

```cmd
build-win.bat
```

- 首次 1-3 分钟(装 onnxruntime + rembg 模型权重比较慢)
- **若 onnxruntime wheel 装不上**:报错给用户,说要装 VS C++ Build Tools
- **若 PyInstaller 报缺包**:`pip install <缺的包>` 后重跑
- 成功标志:`dist-pyinstaller\Gateway\Gateway.exe` 生成

### 4. 隔离 state 跑 smoke

```cmd
set HUMAN_AI_HOME=%TEMP%\gateway-test-vault
set HUMAN_AI_STATE=%TEMP%\gateway-test-state
start /b dist-pyinstaller\Gateway\Gateway.exe
```

等 5 秒,然后 verify:

```cmd
curl http://127.0.0.1:4321/api/health
curl http://127.0.0.1:4321/api/journal/days
curl http://127.0.0.1:4321/api/history/stats
curl -o nul -w "%%{http_code}\n" http://127.0.0.1:4321/history.html
curl -o nul -w "%%{http_code}\n" http://127.0.0.1:4321/consent.html
```

期望:health 返 `{"ok":true}`,html 页面都 200。

### 5. 端侧 OCR + 抠图 verify

关键 — 验跨平台 fallback 真的工作了:

```cmd
python -c "from rapidocr_onnxruntime import RapidOCR; print('rapidocr OK')"
python -c "import rembg; print('rembg OK')"
```

要都 print 出 OK 才算 backend 装齐。

### 6. cleanup

```cmd
REM 杀掉 test server
taskkill /F /IM Gateway.exe
REM 清 test state
rmdir /s /q %TEMP%\gateway-test-vault
rmdir /s /q %TEMP%\gateway-test-state
```

---

## 报告给我(Windows CC 回来时的格式)

跑完所有步骤,回下面这几条信息:

1. **build 成功?**(Y/N + 关键 log 节选若 N)
2. **dist-pyinstaller\Gateway\ 体积**(`dir dist-pyinstaller\Gateway` 看)
3. **5 个 curl smoke 全过?**(列每个的 status code 或返回值)
4. **rapidocr + rembg 两个 import 都 OK?**(Y/Y 或 Y/N + 错误)
5. **任何报错 / 警告 / 不寻常输出**(整段贴,别筛)
6. **环境信息**:`python --version` + `pip list | findstr "rapidocr rembg onnxruntime pyinstaller fastapi uvicorn"`

---

## 重要

- 不要修改 server.py / 任何 .py 文件 — 跨平台问题应该在 Mac 端 fix,Windows 这边只 build + report
- 不要 git commit 任何东西
- 不要装 launchd / Task Scheduler(用户后续决定)
- build 期间任何"是否覆盖"提示都按 yes
- 全程不要碰用户 %USERPROFILE%\.human-ai\ 真实数据,smoke 用 %TEMP% 隔离

完事之后用户会把你的 report 贴回 Mac 这边,然后我决定要不要改代码再让你重 build。
