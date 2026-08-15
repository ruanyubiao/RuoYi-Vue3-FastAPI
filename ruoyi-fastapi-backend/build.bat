@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if /i "%~1"=="--nested" (set "NESTED=1") else (set "NESTED=")

set "BE=%~dp0"
if "%BE:~-1%"=="\" set "BE=%BE:~0,-1%"
for %%I in ("%BE%\..") do set "OUT=%%~fI\dist"

if not exist "%BE%\version.py" (
    echo ERROR: 找不到 version.py
    if not defined NESTED pause
    exit /b 1
)

for /f "tokens=2 delims='" %%A in ('findstr /c:"appVersion" "%BE%\version.py"') do set "BE_VERSION=%%A"
if not defined BE_VERSION (
    echo ERROR: 无法从 version.py 读取 appVersion
    if not defined NESTED pause
    exit /b 1
)

echo [后端] 版本 %BE_VERSION%
if not exist "%OUT%" mkdir "%OUT%"
call :clean_backend_build

echo [后端] 复制配置到 config 包（写入 wheel）
copy /Y "%BE%\.env.*" "%BE%\config\" >nul
if exist "%BE%\alembic.ini" (
    copy /Y "%BE%\alembic.ini" "%BE%\config\alembic.ini" >nul
    python -c "from pathlib import Path; p=Path(r'%BE%\config\alembic.ini'); t=p.read_text(encoding='utf-8'); p.write_text(t.replace('%%(here)s/alembic','%%(here)s/../alembic'), encoding='utf-8')"
)

echo [后端] python -m build --wheel
python -m build -q --wheel --outdir "%OUT%"
if errorlevel 1 (
    echo ERROR: 后端 wheel 构建失败
    call :clean_backend_build
    if not defined NESTED pause
    exit /b 1
)

if exist "%BE%\whl\*.whl" copy /Y "%BE%\whl\*.whl" "%OUT%\" >nul

call :clean_backend_build

echo 后端打包完成:
dir /b "%OUT%\*%BE_VERSION%*.whl"
echo.
echo 安装: pip install --find-links dist dist\pgt-%BE_VERSION%-py3-none-any.whl
echo 启动: ruoyi app run
echo 调试: python app.py --env=dev
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
