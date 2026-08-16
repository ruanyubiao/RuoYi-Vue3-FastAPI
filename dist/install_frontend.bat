@echo off
chcp 65001 >nul
cd /d %~dp0

setlocal enabledelayedexpansion

set "CUR_DIR=."
set "TARGET_FILE="

:: 按修改时间降序取最新的 .whl 文件
for /f "delims=" %%f in ('dir /b /o-d "%CUR_DIR%\html_*.zip" 2^>nul') do (
    set "TARGET_FILE=%%f"
    goto :found
)
:found

if not defined TARGET_FILE (
    echo 错误：未找到 html_*.zip 文件
    pause
    exit /b 1
)

echo 找到最新文件: !TARGET_FILE!
echo.

:: ===== 打印将要执行的命令 =====
echo 即将执行：
echo unzip -o "!TARGET_FILE!" -d D:\docker\nginx\html\
echo.

:: ===== 暂停，等待用户确认 =====
pause


:: ===== 实际执行安装 =====
unzip -o "!TARGET_FILE!" -d D:\docker\nginx\html\

if %errorlevel% equ 0 (
    echo 安装成功！
) else (
    echo 安装失败！
)

pause
endlocal