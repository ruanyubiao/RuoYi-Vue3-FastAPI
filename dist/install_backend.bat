@echo off
chcp 65001 >nul
cd /d "%~dp0"

setlocal enabledelayedexpansion

set "CUR_DIR=."
set "CACHE_DIR=pkg_cache"
set "TARGET_FILE="

for /f "delims=" %%f in ('dir /b /o-d "%CUR_DIR%\pgt-*-py3-none-any.whl" 2^>nul') do (
    set "TARGET_FILE=%%f"
    goto :found
)
:found

if not defined TARGET_FILE (
    echo Error: pgt-*-py3-none-any.whl file not found
    pause
    exit /b 1
)

echo Found latest file: !TARGET_FILE!
echo Will execute:
echo python -m pip uninstall pgt -y
echo python -m pip install "!TARGET_FILE!" --no-index --find-links "%CACHE_DIR%" --find-links "%CUR_DIR%"

echo.
echo Waiting 5 seconds before upgrade...
timeout /t 5

python -m pip uninstall pgt -y
python -m pip install "!TARGET_FILE!" --no-index --find-links "%CACHE_DIR%" --find-links "%CUR_DIR%"

if %errorlevel% equ 0 (
    echo Installation successful!
) else (
    echo Installation failed!
)

echo.
echo Waiting 5 seconds before closing...
timeout /t 5
endlocal