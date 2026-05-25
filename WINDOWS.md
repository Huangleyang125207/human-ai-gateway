# Windows build & run

> 跟 Mac 流程对称。Mac 用 build-mac-pyinstaller.sh / release.sh,Windows 用本文。
> 不需要 Visual Studio / WSL / Docker。

---

## 一次性 setup(Windows 机)

```
1. 装 Python 3.10+ (https://www.python.org/downloads/windows/)
   ☑ Add Python to PATH(安装器勾选)
2. 把整个 gateway/ 目录从 Mac cp 到 Windows
   (用 OneDrive / Git / U 盘都行;若用 git,clone 之后只关心 gateway/)
```

## 第一次 build

```
cd C:\path\to\gateway
build-win.bat
```

跑 1-3 分钟(首次装 onnxruntime + rembg 模型权重慢)。
出在 `dist-pyinstaller\Gateway\Gateway.exe`。

## 第一次跑 smoke

```cmd
REM 隔离 state 测试(不动你真 vault):
set HUMAN_AI_HOME=%TEMP%\gateway-test-vault
set HUMAN_AI_STATE=%TEMP%\gateway-test-state
dist-pyinstaller\Gateway\Gateway.exe
```

浏览器开 http://127.0.0.1:4321 应该见 index.html。

测几个 endpoint:
```cmd
curl http://127.0.0.1:4321/api/health
curl http://127.0.0.1:4321/api/journal/days
curl http://127.0.0.1:4321/api/history/stats
curl http://127.0.0.1:4321/consent.html
```

---

## 分发

把 `dist-pyinstaller\Gateway\` 整个目录打成 `.zip` 发用户。
用户解压 → 双击 `Gateway.exe` → 浏览器自动开 http://127.0.0.1:4321。

> 暂不签名。装的时候 Windows SmartScreen 会弹 "未识别的发行者"。
> 长期方案见 RELEASE_TEMPLATE.md 的 Windows DigiCert OV($200/年)或 EV($500/年)。
> 短期方案:用户点 "更多信息 → 仍要运行"。

---

## 跟 Mac 差异

| | Mac | Windows |
|---|---|---|
| 抠图 backend | macOS Subject Lift (Vision Framework binary) | rembg ONNX(~176MB 模型,首次自动下) |
| OCR backend | macOS Vision (Swift binary, 150ms) | rapidocr-onnxruntime(~50MB 模型,1-3s) |
| vault 默认路径 | `~/.human-ai/vault/` | `%USERPROFILE%\.human-ai\vault\` |
| app state | `~/Library/Application Support/HumanAI/` | `%APPDATA%\HumanAI\` |
| config | `~/Library/Application Support/human-ai/config.json` | `%APPDATA%\human-ai\config.json` |
| .gateway-config | `~/Library/Application Support/HumanAI/config/gateway-config.json` | 同 |
| cron(daily eval / pulse refresh) | launchd plist | Task Scheduler(手工配,见下) |

## Task Scheduler 装 cron(可选)

```cmd
REM daily-eval 21:30
schtasks /Create /TN "HumanAI Daily Eval" /TR "curl -sS -X POST http://127.0.0.1:4321/api/eval/run -H \"Content-Type: application/json\" -d {} --max-time 120" /SC DAILY /ST 21:30

REM pulse-refresh 21:00
schtasks /Create /TN "HumanAI Pulse Refresh" /TR "curl -sS -X POST http://127.0.0.1:4321/api/pulse/refresh-mirror -H \"Content-Type: application/json\" -d {} --max-time 60" /SC DAILY /ST 21:00
```

卸:`schtasks /Delete /TN "HumanAI Daily Eval" /F`(同 Pulse Refresh)。

---

## 故障

- **PyInstaller 装不了 onnxruntime wheel**:
  装 [Visual C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/),
  重跑 build-win.bat。
- **SmartScreen 弹窗**:点 "更多信息" → "仍要运行"。买 DigiCert 签证书可以一劳永逸。
- **localhost:4321 已占**:同 Mac,关掉占端口的进程,或者编辑 server.py 改端口。
- **vault 路径 / 中文乱码**:Windows 10+ Python 3 默认 UTF-8,正常工作。出乱码看
  `chcp 65001`(命令行切 UTF-8)。
