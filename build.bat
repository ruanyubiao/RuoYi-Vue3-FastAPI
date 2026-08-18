@echo off
chcp 65001 >nul
cd /d "%~dp0"

call "%~dp0ruoyi-fastapi-frontend\build.bat" --nested
if errorlevel 1 (
    echo ERROR: Frontend build failed
    pause
    exit /b 1
)

call "%~dp0ruoyi-fastapi-backend\build.bat" --nested
if errorlevel 1 (
    echo ERROR: Backend build failed
    pause
    exit /b 1
)

echo.
echo All builds completed: %~dp0dist
pause
exit /b 0