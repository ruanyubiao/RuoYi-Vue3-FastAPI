@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
for %%I in ("%SCRIPT_DIR%\..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%"

set "NESTED="
if /i "%~1"=="--nested" set "NESTED=1"

call "%SCRIPT_DIR%\build_front.bat" --nested
if errorlevel 1 (
    echo ERROR: Frontend build failed
    if not defined NESTED pause
    exit /b 1
)

call "%SCRIPT_DIR%\build_backend.bat" --nested
if errorlevel 1 (
    echo ERROR: Backend build failed
    if not defined NESTED pause
    exit /b 1
)

if not defined NESTED pause
exit /b 0
