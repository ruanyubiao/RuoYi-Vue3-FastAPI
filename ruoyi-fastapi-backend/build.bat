@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if /i "%~1"=="--nested" (set "NESTED=1") else (set "NESTED=")

set "PY=%~dp0venv\Scripts\python.exe"
if not exist "%PY%" (
    echo ERROR: Cannot find "%PY%", please create venv in ruoyi-fastapi-backend first
    if not defined NESTED pause
    exit /b 1
)

"%PY%" -c "import build" >nul 2>&1
if errorlevel 1 (
    echo build module not installed, installing to venv...
    "%PY%" -m pip install build
    if errorlevel 1 (
        echo ERROR: pip install build failed
        if not defined NESTED pause
        exit /b 1
    )
)

set "BE=%~dp0"
if "%BE:~-1%"=="\" set "BE=%BE:~0,-1%"
for %%I in ("%BE%\..") do set "OUT=%%~fI\dist"

if not exist "%BE%\version.py" (
    echo ERROR: Cannot find version.py
    if not defined NESTED pause
    exit /b 1
)

for /f "tokens=2 delims='" %%A in ('findstr /c:"appVersion" "%BE%\version.py"') do set "BE_VERSION=%%A"
if not defined BE_VERSION (
    echo ERROR: Failed to read appVersion from version.py
    if not defined NESTED pause
    exit /b 1
)

echo [Backend] Version %BE_VERSION%
if not exist "%OUT%" mkdir "%OUT%"
call :clean_backend_build

echo [Backend] Copying config to config package (for wheel)
copy /Y "%BE%\.env.*" "%BE%\config\" >nul
if exist "%BE%\alembic.ini" (
    copy /Y "%BE%\alembic.ini" "%BE%\config\alembic.ini" >nul
    "%PY%" -c "from pathlib import Path; p=Path(r'%BE%\config\alembic.ini'); t=p.read_text(encoding='utf-8'); p.write_text(t.replace('%%(here)s/alembic','%%(here)s/../alembic'), encoding='utf-8')"
)

echo [Backend] python -m build --wheel
"%PY%" -m build --wheel --outdir "%OUT%"
if errorlevel 1 (
    echo ERROR: Backend wheel build failed
    call :clean_backend_build
    if not defined NESTED pause
    exit /b 1
)

if exist "%BE%\whl\*.whl" copy /Y "%BE%\whl\*.whl" "%OUT%\" >nul

call :clean_backend_build

echo Backend build completed:
dir /b "%OUT%\*%BE_VERSION%*.whl"
echo.
echo Install: pip install --find-links dist dist\pgt-%BE_VERSION%-py3-none-any.whl
echo Code location: site-packages\pgt\
echo Runtime data: %%LOCALAPPDATA%%\pgt\ (do not write logs into site-packages)
echo To start the application:
echo To start the application:
echo Method 1: ruoyi app run
echo Method 2: python -m pgt.app --env prod
echo For  Dev: python app.py --env=dev
echo.
if not defined NESTED pause
endlocal
exit /b 0

:clean_backend_build
if exist "%BE%\build" rd /s /q "%BE%\build"
if exist "%BE%\.eggs" rd /s /q "%BE%\.eggs"
pushd "%BE%"
for /d %%D in (*.egg-info) do rd /s /q "%%D"
popd
if exist "%BE%\__pycache__" rd /s /q "%BE%\__pycache__"
del /q "%BE%\config\.env.*" >nul 2>nul
if exist "%BE%\config\alembic.ini" del /q "%BE%\config\alembic.ini" >nul 2>nul
exit /b 0