@echo off
chcp 65001 >nul
cd /d "%~dp0"

call "%~dp0ruoyi-fastapi-frontend\build.bat" --nested
if errorlevel 1 (
    echo ERROR: 前端打包失败
    pause
    exit /b 1
)

call "%~dp0ruoyi-fastapi-backend\build.bat" --nested
if errorlevel 1 (
    echo ERROR: 后端打包失败
    pause
    exit /b 1
)

echo.
echo 全部打包完成: %~dp0dist
pause
exit /b 0
