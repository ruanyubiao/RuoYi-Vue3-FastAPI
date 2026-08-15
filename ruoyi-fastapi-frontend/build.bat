@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if /i "%~1"=="--nested" (set "NESTED=1") else (set "NESTED=")

set "FE=%~dp0"
if "%FE:~-1%"=="\" set "FE=%FE:~0,-1%"
for %%I in ("%FE%\..") do set "OUT=%%~fI\dist"

if not exist "%FE%\version.js" (
    echo ERROR: 找不到 version.js
    if not defined NESTED pause
    exit /b 1
)

for /f "tokens=2 delims='" %%A in ('findstr /c:"appVersion" "%FE%\version.js"') do set "APP_VERSION=%%A"
if not defined APP_VERSION (
    echo ERROR: 无法从 version.js 读取 appVersion
    if not defined NESTED pause
    exit /b 1
)

echo [前端] 版本 %APP_VERSION%
echo [前端] npm run build:prod
call npm run build:prod
if errorlevel 1 (
    echo ERROR: 前端构建失败
    if not defined NESTED pause
    exit /b 1
)

if not exist "%FE%\dist\index.html" (
    echo ERROR: 构建后未找到 dist\index.html
    if not defined NESTED pause
    exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"
set "ZIP_NAME=html_%APP_VERSION%.zip"
set "ZIP_PATH=%OUT%\%ZIP_NAME%"
if exist "%ZIP_PATH%" del /f /q "%ZIP_PATH%"

echo [前端] 打包 %ZIP_NAME%
pushd "%FE%\dist"
zip -r "%ZIP_PATH%" .
set "ZIP_ERR=!errorlevel!"
popd
if not "!ZIP_ERR!"=="0" (
    echo ERROR: 打包 html zip 失败
    if not defined NESTED pause
    exit /b 1
)

echo 前端打包完成: %ZIP_PATH%
if not defined NESTED pause
endlocal
exit /b 0
