@echo off
REM build-win.bat -- 出 self-contained Gateway.exe(免装 python)
REM
REM 用法:在 Windows 上 cd gateway && build-win.bat
REM 输出:.\dist-pyinstaller\Gateway\Gateway.exe + 一坨 dll/数据文件(同目录)
REM       打 zip 发出去 -> 用户解压双击 Gateway.exe 即跑
REM
REM 跟 build-mac-pyinstaller.sh 对齐:同样的 --add-data 资源 + 同样的 hidden imports
REM (差别:Windows 端 ocr_local/cutout_local 走 rapidocr/rembg ONNX 而不是 macOS
REM Vision binary,故 pip install 多装这俩 ONNX backend)
REM
REM 需要:Python 3.9+(本机装,build 用;打出来的 exe 不依赖)
REM      VS C++ Build Tools(onnxruntime wheel 装不了时需要,但通常 wheel 有)

setlocal enabledelayedexpansion
cd /d "%~dp0"
set "GATEWAY_DIR=%cd%"
set "DIST=%GATEWAY_DIR%\dist-pyinstaller"
set "VENV=%GATEWAY_DIR%\.venv-build"

REM 1. python check
where python >nul 2>&1
if errorlevel 1 (
    echo X 需要 python ^(https://www.python.org/downloads/windows/^)
    pause
    exit /b 1
)

echo -^> 1. 建 build venv
if not exist "%VENV%" python -m venv "%VENV%"

REM 2. 装 requirements + Windows 端跨平台 ONNX backends + PyInstaller
echo -^> 2. 装 deps
"%VENV%\Scripts\pip" install --quiet --upgrade pip
"%VENV%\Scripts\pip" install --quiet -r requirements.txt
REM Windows/Linux 端缺 macOS Vision/Subject Lift,改走 ONNX 兜底:
"%VENV%\Scripts\pip" install --quiet rapidocr-onnxruntime rembg
"%VENV%\Scripts\pip" install --quiet pyinstaller

REM 3. ico from svg(可选,缺就用默认 PyInstaller icon)
set "ICO=%GATEWAY_DIR%\brand\logo.ico"
if not exist "%ICO%" (
    "%VENV%\Scripts\python" -c "from PIL import Image; im=Image.open(r'%GATEWAY_DIR%\brand\logo.png'); im.save(r'%ICO%', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])" 2>nul
    if not exist "%ICO%" (
        echo   ^(没有 brand\logo.png,跳过 icon^)
    )
)

REM 4. PyInstaller — 跟 build-mac-pyinstaller.sh 对齐的 --add-data 清单
echo -^> 3. PyInstaller 打包
if exist "%DIST%" rmdir /s /q "%DIST%"
if exist "%GATEWAY_DIR%\build" rmdir /s /q "%GATEWAY_DIR%\build"
if exist "%GATEWAY_DIR%\Gateway.spec" del "%GATEWAY_DIR%\Gateway.spec"

set "ICON_FLAG="
if exist "%ICO%" set "ICON_FLAG=--icon %ICO%"

"%VENV%\Scripts\pyinstaller" ^
    --name Gateway ^
    --noconsole ^
    --noconfirm ^
    --distpath "%DIST%" ^
    --workpath "%GATEWAY_DIR%\build" ^
    %ICON_FLAG% ^
    --add-data "index.html;." ^
    --add-data "day.html;." ^
    --add-data "reset.html;." ^
    --add-data "history.html;." ^
    --add-data "consent.html;." ^
    --add-data "shared;shared" ^
    --add-data "widgets;widgets" ^
    --add-data "vendor;vendor" ^
    --add-data "brand;brand" ^
    --add-data "protocols;protocols" ^
    --add-data ".gateway-config.example.json;." ^
    --add-data "vault_config.py;." ^
    --add-data "vault_git.py;." ^
    --add-data "history_exporter.py;." ^
    --add-data "outcome_tracker.py;." ^
    --add-data "cutout.py;." ^
    --add-data "cutout_local.py;." ^
    --add-data "ocr.py;." ^
    --add-data "ocr_local.py;." ^
    --add-data "tools;tools" ^
    --hidden-import uvicorn.logging ^
    --hidden-import uvicorn.loops.auto ^
    --hidden-import uvicorn.loops.asyncio ^
    --hidden-import uvicorn.protocols.http.h11_impl ^
    --hidden-import uvicorn.protocols.http.auto ^
    --hidden-import uvicorn.protocols.websockets.auto ^
    --hidden-import uvicorn.protocols.websockets.websockets_impl ^
    --hidden-import uvicorn.lifespan.on ^
    --hidden-import uvicorn.lifespan.off ^
    --hidden-import multipart ^
    --hidden-import email_validator ^
    --hidden-import rapidocr_onnxruntime ^
    --hidden-import rembg ^
    server.py

if errorlevel 1 (
    echo X PyInstaller 失败
    pause
    exit /b 1
)

rmdir /s /q "%GATEWAY_DIR%\build"
del "%GATEWAY_DIR%\Gateway.spec"

echo.
echo ════════════════════════════════════════════
echo  完成 ^(self-contained,免装 python^)
echo    folder: %DIST%\Gateway\
echo    binary: %DIST%\Gateway\Gateway.exe
echo.
echo    分发:把整个 Gateway\ 文件夹打 zip,用户解开双击 Gateway.exe
echo    日志 / vault / 配置走 OS 标准路径:
echo      vault:     %%USERPROFILE%%\.human-ai\vault\
echo      state:     %%APPDATA%%\HumanAI\
echo      config:    %%APPDATA%%\HumanAI\config\gateway-config.json
echo ════════════════════════════════════════════
pause
