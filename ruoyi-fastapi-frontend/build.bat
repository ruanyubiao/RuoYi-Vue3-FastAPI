@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if /i "%~1"=="--nested" (set "NESTED=1") else (set "NESTED=")

set "FE=%~dp0"
if "%FE:~-1%"=="\" set "FE=%FE:~0,-1%"
for %%I in ("%FE%\..") do set "OUT=%%~fI\dist"

if not exist "%FE%\version.js" (
    echo ERROR: Cannot find version.js
    if not defined NESTED pause
    exit /b 1
)

for /f "tokens=2 delims='" %%A in ('findstr /c:"appVersion" "%FE%\version.js"') do set "APP_VERSION=%%A"
if not defined APP_VERSION (
    echo ERROR: Failed to read appVersion from version.js
    if not defined NESTED pause
    exit /b 1
)

echo [Frontend] Version %APP_VERSION%
echo [Frontend] npm run build:prod
call npm run build:prod -- --logLevel silent
if errorlevel 1 (
    echo ERROR: Frontend build failed
    if not defined NESTED pause
    exit /b 1
)

if not exist "%FE%\dist\index.html" (
    echo ERROR: dist\index.html not found after build
    if not defined NESTED pause
    exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"
set "ZIP_NAME=html_%APP_VERSION%.zip"
set "ZIP_PATH=%OUT%\%ZIP_NAME%"
if exist "%ZIP_PATH%" del /f /q "%ZIP_PATH%"

echo [Frontend] Packaging %ZIP_NAME%
pushd "%FE%\dist"
zip -r -q "%ZIP_PATH%" .
set "ZIP_ERR=!errorlevel!"
popd
if not "!ZIP_ERR!"=="0" (
    echo ERROR: Failed to package html zip
    if not defined NESTED pause
    exit /b 1
)

echo Frontend build completed: %ZIP_PATH%
if not defined NESTED pause
endlocal
exit /b 0