# Task: Windows 机一次性 setup — OpenSSH Server + build Gateway.exe + smoke

> 把这整个 .md 交给 Windows VSCode/Cursor 的 Claude Code。
> 它跑完一次,从此 Mac Cursor 可远程 SSH 实时操作这台 Windows,
> 后续所有 build / debug / smoke 都 Mac 端操控,不用再来回 cp。

---

## 背景

human-ai-schedule 项目的 viewer/server(FastAPI + uvicorn + vanilla JS),
Mac 端已 ship .dmg(端侧 OCR / vault git auto-commit / training corpus / consent UI 全 stack)。
现在要在这台 Windows 上:

1. **装 OpenSSH Server**,让 Mac Cursor Remote-SSH 可以连进来 → 后续 Mac 端实时 dev
2. **build .exe**,把 Mac-side 所有改动 ship 成 Windows self-contained binary
3. **smoke verify**,验跨平台 OCR/抠图 backend (rapidocr ONNX / rembg) 真跑通
4. **回报详细信息**,Mac 端 user 拿着 SSH 信息接进来

---

## 前置 check

```cmd
where python
python --version
where git
where curl
```

预期:python 3.10+,有 git/curl(Windows 10+ 自带 curl)。
没装 python 就告用户去 https://www.python.org/downloads/windows/ 装,**勾"Add Python to PATH"**。

---

## Step 1:装 + 启 OpenSSH Server

```powershell
# PowerShell 管理员模式跑(若没装 OpenSSH Server):
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0

# 启服务 + 设开机自启
Start-Service sshd
Set-Service -Name sshd -StartupType 'Automatic'

# 防火墙开 22 端口(若没自动开)
if (!(Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' `
      -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
}

# 验:服务在跑 + 监听 22
Get-Service sshd
netstat -an | findstr :22
```

预期:`Get-Service sshd` 显示 `Running`,netstat 看 `0.0.0.0:22 LISTENING`。

---

## Step 2:抓 SSH 连接信息(给 Mac 端用)

```powershell
# 1. Windows 的 IPv4(应该是 192.168.x.x 局域网内地址)
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.IPAddress -notmatch '^127\.' -and
    $_.IPAddress -notmatch '^169\.254\.' -and
    $_.PrefixOrigin -eq 'Dhcp'
}).IPAddress
Write-Host "IPv4: $ip"

# 2. Windows 用户名
Write-Host "Username: $env:USERNAME"

# 3. Computer name(备用,IP 不稳时用 hostname)
Write-Host "Hostname: $env:COMPUTERNAME"
```

**这 3 个值贴给 Mac 端 user**(Mac Cursor Remote-SSH 要)。

---

## Step 3:找 gateway 目录 + 进去

```cmd
:: 用户应该 cp 了 gateway/ 过来,问问在哪
:: 常见位置:C:\Users\<name>\Desktop\gateway / D:\gateway / C:\gateway
dir C:\ | findstr gateway
dir %USERPROFILE%\Desktop | findstr gateway
dir %USERPROFILE%\Downloads | findstr gateway
```

找不到就**问用户:"gateway 目录的完整路径是?"**,然后 `cd "<那个路径>"`。

进去验:`dir server.py build-win.bat WINDOWS.md` 应该都在。

---

## Step 4:build .exe(跟 WINDOWS.md 一致)

```cmd
build-win.bat
```

期望:
- 首次 1-3 分钟(装 onnxruntime + rembg 模型权重比较慢)
- 成功 → `dist-pyinstaller\Gateway\Gateway.exe` 生成

常见失败:
- **onnxruntime wheel 装不上** → 装 [VS C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) → 重跑
- **PyInstaller 漏 hidden-import** → 报错 import 哪个就 `pip install` + 加 `--hidden-import <name>` 到 build-win.bat(暂时本地改,别 commit,告诉 Mac 端 user)
- **路径含中文报错** → `chcp 65001` 切 UTF-8 再跑

---

## Step 5:smoke 隔离 state 跑

```cmd
set HUMAN_AI_HOME=%TEMP%\gw-test-vault
set HUMAN_AI_STATE=%TEMP%\gw-test-state
start /b dist-pyinstaller\Gateway\Gateway.exe
```

等 5 秒 → verify:

```cmd
curl http://127.0.0.1:4321/api/health
curl http://127.0.0.1:4321/api/journal/days
curl http://127.0.0.1:4321/api/history/stats
curl -o nul -w "history.html status=%%{http_code}\n" http://127.0.0.1:4321/history.html
curl -o nul -w "consent.html status=%%{http_code}\n" http://127.0.0.1:4321/consent.html
```

期望:health 返 `{"ok":true}`,html 200。

---

## Step 6:端侧 backend verify

```cmd
python -c "from rapidocr_onnxruntime import RapidOCR; o=RapidOCR(); print('rapidocr OK')"
python -c "import rembg; print('rembg version:', rembg.__version__)"
python -c "import onnxruntime; print('onnxruntime version:', onnxruntime.__version__)"
```

要都 print 出来才算 cross-platform fallback 装齐。

---

## Step 7:cleanup

```cmd
taskkill /F /IM Gateway.exe 2>nul
rmdir /s /q %TEMP%\gw-test-vault 2>nul
rmdir /s /q %TEMP%\gw-test-state 2>nul
```

---

## 最终回报(贴回 Mac 端 user)

按下面格式 output 一次,user 全段复制贴回 Mac 这边:

```
══════════════════════════════════════
  Windows setup 报告
══════════════════════════════════════

【SSH 信息】给 Mac Cursor Remote-SSH 用:
  IP:       <Step 2 抓的 IPv4>
  username: <$env:USERNAME>
  hostname: <$env:COMPUTERNAME>
  port:     22(默认)
  连接命令: ssh <username>@<IP>

【环境】
  python:  <python --version 输出>
  pip 主要包:
    <pip list | findstr "rapidocr rembg onnxruntime pyinstaller fastapi uvicorn">

【build】
  成功?   Y / N
  bundle dir 体积: <dir dist-pyinstaller\Gateway 看>
  错误(若 N): <整段贴>

【smoke 5 个 endpoint】
  /api/health:           <返回值>
  /api/journal/days:     <返回值>
  /api/history/stats:    <返回值>
  /history.html:         <status code>
  /consent.html:         <status code>

【端侧 backend】
  rapidocr import:    Y / N + 错误
  rembg import:       Y / N + 错误
  onnxruntime import: Y / N + 错误

【任何报错 / warning / 不寻常】
  <整段贴,别筛>

══════════════════════════════════════
```

---

## 重要 — 别越界

- 不要改 server.py / 任何 .py 文件 — bug 在 Mac 端 fix,Windows 这边只 build + report
- 不要 git commit 任何东西
- 不要装 launchd / Task Scheduler(用户后续决定)
- build 期间任何"是否覆盖"提示按 yes
- 全程不要碰用户 `%USERPROFILE%\.human-ai\` 真实数据,smoke 用 `%TEMP%` 隔离
- SSH 公钥认证暂不配(用密码先够);后续 Mac 端 user 想配再说

---

## 后续

报告贴完之后,Mac 端 user 走:
1. Cursor 装 "Remote - SSH" extension
2. Cmd+Shift+P → "Remote-SSH: Connect to Host" → `<username>@<IP>`
3. 输 Windows 登录密码 → 连
4. Cursor 新窗:File → Open Folder → `C:\<gateway 路径>`
5. 此后 build / debug / 改 .py 都在 Cursor 一窗里搞,你不用再启 Windows CC
