@echo off
REM build-win.bat -- 出 self-contained Gateway.exe(免装 python)
REM
REM 用法:在 Windows 上 cd gateway && build-win.bat
REM 输出:.\dist-pyinstaller\Gateway\Gateway.exe + 一坨 dll/数据文件(同目录)
REM 用户拿到压缩包 -> 解开 -> 双击 Gateway.exe 就跑
REM
REM 不依赖 Visual Studio / WSL / Docker。
REM 需要:Python 3.9+(本机装,build 用;打出来的 exe 不依赖)

setlocal enabledelayedexpansion
cd /d "%~dp0"
set "GATEWAY_DIR=%cd%"
set "DIST=%GATEWAY_DIR%\dist-pyinstaller"
set "VENV=%GATEWAY_DIR%\.venv-build"

REM 1. python check
where python >nul 2>&1
if errorlevel 1 (
    echo X 需要 python(https://www.python.org/downloads/windows/^)
    pause
    exit /b 1
)

echo -^> 1. 建 build venv
if not exist "%VENV%" python -m venv "%VENV%"

REM 2. 装依赖
echo -^> 2. 装 requirements + PyInstaller
"%VENV%\Scripts\pip" install --quiet --upgrade pip
"%VENV%\Scripts\pip" install --quiet -r requirements.txt
"%VENV%\Scripts\pip" install --quiet pyinstaller

REM 3. ico from svg(可选,缺就用默认 PyInstaller icon)
REM Pillow 装了就用它把 brand\logo.svg 转 .ico。SVG 解析靠 cairosvg(可能没装),
REM 那就 fallback 直接用 PNG 做 icon
set "ICO=%GATEWAY_DIR%\brand\logo.ico"
if not exist "%ICO%" (
    "%VENV%\Scripts\python" -c "from PIL import Image; im=Image.open(r'%GATEWAY_DIR%\brand\logo.png'); im.save(r'%ICO%', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])" 2>nul
    if not exist "%ICO%" (
        echo   ^(没有 brand\logo.png,跳过 icon^)
    )
)

REM 4. PyInstaller
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
    --add-data "shared;shared" ^
    --add-data "widgets;widgets" ^
    --add-data "vendor;vendor" ^
    --add-data "brand;brand" ^
    --add-data "system_prompt_schedule.md;." ^
    --add-data ".gateway-config.example.json;." ^
    --add-data "vault_config.py;." ^
    --add-data "cutout.py;." ^
    --add-data "ocr.py;." ^
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
echo  ^✓ 打包完成
echo    folder: %DIST%\Gateway\
echo    binary: %DIST%\Gateway\Gateway.exe
echo    分发:把整个 Gateway\ 文件夹打 zip,用户解开双击 Gateway.exe
echo ════════════════════════════════════════════
pause
