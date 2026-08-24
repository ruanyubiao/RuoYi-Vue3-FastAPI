@echo off
chcp 65001 >nul
cd /d "%~dp0"

setlocal enabledelayedexpansion

set "CUR_DIR=."
set "TARGET_FILE="

:: Get the latest .whl file by modification time (descending)
for /f "delims=" %%f in ('dir /b /o-d "%CUR_DIR%\html_*.zip" 2^>nul') do (
    set "TARGET_FILE=%%f"
    goto :found
)
:found

if not defined TARGET_FILE (
    echo Error: html_*.zip file not found
    echo Waiting 5 seconds before closing...
    timeout /t 5
    exit /b 1
)

echo Found latest file: !TARGET_FILE!
echo Will execute:
echo unzip -o -q "!TARGET_FILE!" -d D:\docker\nginx\html\

echo.
echo Waiting 5 seconds before upgrade...
timeout /t 5

unzip -o -q "!TARGET_FILE!" -d D:\docker\nginx\html\

if %errorlevel% equ 0 (
    echo Installation successful!
) else (
    echo Installation failed!
)

echo.
echo Waiting 5 seconds before closing...
timeout /t 5
endlocal