@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "FE=%ROOT%\ruoyi-fastapi-frontend"
set "BE=%ROOT%\ruoyi-fastapi-backend"
set "OUT=%ROOT%\dist"

:: -------- 前端 --------
if not exist "%FE%\version.js" (
    echo ERROR: 找不到 %FE%\version.js
    pause
    exit /b 1
)

for /f "tokens=2 delims='" %%A in ('findstr /c:"appVersion" "%FE%\version.js"') do set "APP_VERSION=%%A"
if not defined APP_VERSION (
    echo ERROR: 无法从 version.js 读取 appVersion
    pause
    exit /b 1
)

echo [前端] 版本 %APP_VERSION%
echo [前端] npm run build:prod
cd /d "%FE%"
call npm run build:prod
if errorlevel 1 (
    echo ERROR: 前端构建失败
    pause
    exit /b 1
)

if not exist "%FE%\dist\index.html" (
    echo ERROR: 构建后未找到 dist\index.html
    pause
    exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"
set "ZIP_NAME=html_%APP_VERSION%.zip"
set "ZIP_PATH=%OUT%\%ZIP_NAME%"
if exist "%ZIP_PATH%" del /f /q "%ZIP_PATH%"

echo [前端] 打包 %ZIP_NAME%
cd /d "%FE%\dist"
zip -r "%ZIP_PATH%" .
if errorlevel 1 (
    echo ERROR: 打包 html zip 失败
    pause
    exit /b 1
)

echo 前端打包完成: %ZIP_PATH%

:: -------- 后端 --------
if not exist "%BE%\version.py" (
    echo ERROR: 找不到 %BE%\version.py
    pause
    exit /b 1
)

for /f "tokens=2 delims='" %%A in ('findstr /c:"appVersion" "%BE%\version.py"') do set "BE_VERSION=%%A"
if not defined BE_VERSION (
    echo ERROR: 无法从 version.py 读取 appVersion
    pause
    exit /b 1
)

echo [后端] 版本 %BE_VERSION%
if not exist "%OUT%" mkdir "%OUT%"
call :clean_backend_build

echo [后端] python -m build --wheel
cd /d "%BE%"
python -m build --wheel --outdir "%OUT%"
if errorlevel 1 (
    echo ERROR: 后端 wheel 构建失败
    call :clean_backend_build
    pause
    exit /b 1
)

call :clean_backend_build

echo 后端打包完成:
dir /b "%OUT%\*%BE_VERSION%*.whl"
echo.

pause
endlocal
exit /b 0

:clean_backend_build
if exist "%BE%\build" rd /s /q "%BE%\build"
if exist "%BE%\.eggs" rd /s /q "%BE%\.eggs"
pushd "%BE%"
for /d %%D in (*.egg-info) do rd /s /q "%%D"
popd
if exist "%BE%\__pycache__" rd /s /q "%BE%\__pycache__"
exit /b 0
