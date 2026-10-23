@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
for %%I in ("%SCRIPT_DIR%\..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%"

set "NESTED="
if /i "%~1"=="--nested" set "NESTED=1"

set "PY=%REPO_ROOT%\ruoyi-fastapi-backend\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" "%SCRIPT_DIR%\_build_front.py" %*
set "ERR=!ERRORLEVEL!"
if not "!ERR!"=="0" (
    if not defined NESTED pause
    exit /b !ERR!
)
if not defined NESTED pause
exit /b 0
