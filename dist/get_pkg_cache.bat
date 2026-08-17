@echo off
cd /d "%~dp0"

python.exe -m pip download -r ..\ruoyi-fastapi-backend\requirements.txt -d .\pkg_cache

pause
