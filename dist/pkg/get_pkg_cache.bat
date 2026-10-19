@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
rem Runs on the BUILD machine.
rem usage: get_pkg_cache.bat        download into .\pkg_cache (dist\pkg\pkg_cache) + offline rehearsal
rem        get_pkg_cache.bat probe  only the offline rehearsal (re-run after a successful download)
rem own packages (gpcan-*.whl, telemetryparser-*.whl) stay next to this script in dist\pkg
if /i "%~1"=="probe" goto probe
rem ==== Build the offline pip cache for the target (Windows x64 + CPython 3.13) ====

set "REQ=..\..\ruoyi-fastapi-backend\requirements.txt"
set "PLAT=--platform win_amd64 --python-version 3.13 --implementation cp --abi cp313 --abi abi3 --abi none --only-binary=:all:"

if exist pkg_cache_new rd /s /q pkg_cache_new
python -m pip download %PLAT% -r "%REQ%" -d pkg_cache_new
if errorlevel 1 (echo [ERROR] pip download failed & pause & exit /b 1)
rem make sure mcp and its Windows deps are there (safety net)
python -m pip download %PLAT% -d pkg_cache_new mcp==2.3.0 mcp-types==2.3.0 httpx2 sse-starlette jsonschema jsonschema-specifications referencing rpds-py attrs opentelemetry-api importlib-metadata zipp "pywin32>=311"
if errorlevel 1 (echo [ERROR] mcp deps download failed & pause & exit /b 1)

rem replace pkg_cache only after a complete download
if exist pkg_cache rd /s /q pkg_cache
ren pkg_cache_new pkg_cache

if not exist pkg_cache (echo [ERROR] pkg_cache not found & pause & exit /b 1)
echo [pkg_cache] %~dp0pkg_cache ready
:probe
rem offline rehearsal: clean 3.13 venv, local files only, newest pgt by version
set "WHL="
for /f "delims=" %%f in ('powershell -NoP -C "Get-ChildItem ..\pgt-*-py3-none-any.whl | Sort-Object { [version](($_.Name -replace '^pgt-','' -replace '-py3-none-any\.whl$','') -replace '[^0-9.]','') } | Select-Object -Last 1 -ExpandProperty FullName"') do set "WHL=%%f"
if not defined WHL (echo [WARN] no ..\pgt-*.whl, skip offline rehearsal & pause & exit /b 0)
if exist "%TEMP%\pgt_probe" rd /s /q "%TEMP%\pgt_probe"
rem find Python 3.13: env PGT_PYTHON -> py -3.13 -> python on PATH
set "PY313="
if defined PGT_PYTHON "%PGT_PYTHON%" -c "import sys;sys.exit(0 if sys.version_info[:2]==(3,13) else 1)" >nul 2>&1 && set "PY313=%PGT_PYTHON%"
if not defined PY313 for /f "delims=" %%p in ('py -3.13 -c "import sys;print(sys.executable)" 2^>nul') do set "PY313=%%p"
if not defined PY313 python -c "import sys;sys.exit(0 if sys.version_info[:2]==(3,13) else 1)" >nul 2>&1 && for /f "delims=" %%p in ('python -c "import sys;print(sys.executable)"') do set "PY313=%%p"
if not defined PY313 (echo [ERROR] Python 3.13 not found: set env PGT_PYTHON, or install py launcher / put python 3.13 on PATH & pause & exit /b 1)
echo [probe] using %PY313%
"%PY313%" -m venv "%TEMP%\pgt_probe" || (echo [ERROR] venv creation failed & pause & exit /b 1)
"%TEMP%\pgt_probe\Scripts\python.exe" -m pip install --no-index --find-links . --find-links pkg_cache --find-links .. "%WHL%"
if errorlevel 1 (echo [ERROR] offline rehearsal failed, cache incomplete & pause & exit /b 1)
rem note: the TeleMetryParser package imports as "TeleMetryParser" (case-sensitive)
"%TEMP%\pgt_probe\Scripts\python.exe" -c "import gpcan, TeleMetryParser, pgt.server"
if errorlevel 1 (echo [ERROR] import failed & pause & exit /b 1)
"%TEMP%\pgt_probe\Scripts\python.exe" -c "import mcp"
if errorlevel 1 (echo [ERROR] mcp not installed: %WHL% does not declare mcp - rebuild the pgt wheel from the current pyproject.toml ^(build.bat^) & pause & exit /b 1)
echo offline OK
rd /s /q "%TEMP%\pgt_probe"
pause
