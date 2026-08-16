@echo off
chcp 65001 >nul
::fltmc >nul 2>&1 || (echo Please run as Administrator && pause && exit /b 1)

cd /d %~dp0

python.exe -m pip download -r ..\ruoyi-fastapi-backend\requirements.txt -d .\pkg_cache

pause
