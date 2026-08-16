@echo off
chcp 65001 >nul
cd /d %~dp0

setlocal enabledelayedexpansion

set "CUR_DIR=."
set "CACHE_DIR=pkg_cache"
set "TARGET_FILE="

:: 按修改时间降序取最新的 .whl 文件
for /f "delims=" %%f in ('dir /b /o-d "%CUR_DIR%\pgt-*-py3-none-any.whl" 2^>nul') do (
    set "TARGET_FILE=%%f"
    goto :found
)
:found

if not defined TARGET_FILE (
    echo 错误：未找到 pgt-*-py3-none-any.whl 文件
    pause
    exit /b 1
)

echo 找到最新文件: !TARGET_FILE!
echo.

:: ===== 打印将要执行的命令 =====
echo 即将执行：
echo python -m pip install "!TARGET_FILE!" --no-index --find-links "%CACHE_DIR%" --find-links "%CUR_DIR%"
echo.

:: ===== 暂停，等待用户确认 =====
pause

echo 卸载旧版
python -m pip uninstall pgt -y

:: ===== 实际执行安装 =====
python -m pip install "!TARGET_FILE!" --no-index --find-links "%CACHE_DIR%" --find-links "%CUR_DIR%"

if %errorlevel% equ 0 (
    echo 安装成功！
) else (
    echo 安装失败！
)

pause
endlocal