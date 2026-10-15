@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

rem Only docker\compose.yml (test-* / project test-ruoyi).
rem Does not stop/rm mysql8, redis, or nginx.
set "COMPOSE=docker compose -f docker\compose.yml"
set "BACKEND_DIR=%~dp0..\ruoyi-fastapi-backend"
set "FRONTEND_DIR=%~dp0..\ruoyi-fastapi-frontend"
set "SQL_FILE=%BACKEND_DIR%\sql\ruoyi-fastapi-my.sql"
set "ERR=0"
set "WAIT_N=0"
set "FORCE_BUILD="
set "PYTEST_ARGS="

rem Usage: run_test.bat [rebuild] [pytest args...]   e.g. run_test.bat payload -k pages
:parse_args
if "%~1"=="" goto :args_done
if /I "%~1"=="rebuild" (
  set "FORCE_BUILD=1"
) else (
  set "PYTEST_ARGS=%PYTEST_ARGS% %1"
)
shift
goto :parse_args
:args_done

rem Backend prefers its own venv; tests use E2E_PYTHON or python on PATH.
set "BACKEND_PY=python"
if exist "%BACKEND_DIR%\venv\Scripts\python.exe" set "BACKEND_PY=%BACKEND_DIR%\venv\Scripts\python.exe"
if not defined E2E_PYTHON set "E2E_PYTHON=python"

echo ==== Playwright E2E (test-* containers + PC backend --env=test) ====

where docker >nul 2>&1
if errorlevel 1 (
  echo [ERROR] docker not found
  exit /b 1
)
"%E2E_PYTHON%" -c "import pytest, pytest_asyncio, playwright, requests" >nul 2>&1
if errorlevel 1 (
  echo [ERROR] test deps missing for %E2E_PYTHON%: pip install -r requirements.txt ^&^& playwright install chromium
  exit /b 1
)
if not exist "%SQL_FILE%" (
  echo [ERROR] SQL file not found: %SQL_FILE%
  exit /b 1
)
if not exist "%BACKEND_DIR%\.env.test" (
  echo [ERROR] missing %BACKEND_DIR%\.env.test
  exit /b 1
)

if defined FORCE_BUILD goto :build_fe
if not exist "%FRONTEND_DIR%\dist\index.html" goto :build_fe
rem Source newer than dist (the stale-bundle miss). rebuild still forces a build.
powershell -NoProfile -Command "$root='%FRONTEND_DIR%'; $dist=Join-Path $root 'dist\index.html'; $stamp=(Get-Item -LiteralPath $dist).LastWriteTimeUtc; $rels=@('src','public','vite','index.html','vite.config.js','package.json','package-lock.json','.env.production'); foreach($rel in $rels){ $p=Join-Path $root $rel; if(-not(Test-Path -LiteralPath $p)){continue}; $hit=Get-ChildItem -LiteralPath $p -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTimeUtc -gt $stamp } | Select-Object -First 1; if($hit){ Write-Output ('frontend newer than dist: '+$hit.FullName); exit 2 } }; exit 0"
if errorlevel 1 goto :build_fe
echo ---- frontend dist is up to date ----
goto :stack
:build_fe
echo ---- build frontend dist (/prod-api) ----
pushd "%FRONTEND_DIR%"
call npm run build:prod
if errorlevel 1 (
  popd
  echo [ERROR] npm run build failed
  exit /b 1
)
popd

:stack
echo ---- stop leftover --env=test backend (keep --env=dev) ----
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and ($_.CommandLine -like '*app.py*--env=test*' -or $_.CommandLine -like '*app.py* --env test*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo ---- recreate test-* (no volumes, init from latest SQL) ----
%COMPOSE% down -v --remove-orphans
if errorlevel 1 (
  echo [ERROR] docker compose down failed; dev containers unchanged
  exit /b 1
)
%COMPOSE% up -d
if errorlevel 1 (
  echo [ERROR] docker compose up failed
  exit /b 1
)

echo ---- wait for test-mysql healthy ----
set "WAIT_N=0"
:wait_mysql
docker inspect -f "{{.State.Health.Status}}" test-mysql 2>nul | findstr /i /c:"healthy" >nul
if not errorlevel 1 goto :mysql_ready
set /a WAIT_N+=1
if %WAIT_N% GEQ 60 (
  echo [ERROR] test-mysql not healthy in ~2 minutes
  set "ERR=1"
  goto :cleanup
)
timeout /t 2 /nobreak >nul
goto :wait_mysql

:mysql_ready
echo ---- start PC backend: python app.py --env=test (port 19099) ----
start "pgt-e2e-backend" /D "%BACKEND_DIR%" "%BACKEND_PY%" app.py --env=test

echo ---- wait for http://127.0.0.1:19099/health ----
set "WAIT_N=0"
:wait_api
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:19099/health' -TimeoutSec 2; if ($r.StatusCode -ge 200) { exit 0 } } catch { exit 1 }"
if not errorlevel 1 goto :api_ready
set /a WAIT_N+=1
if %WAIT_N% GEQ 45 (
  echo [ERROR] backend 19099 not ready; check window titled pgt-e2e-backend
  set "ERR=1"
  goto :cleanup
)
timeout /t 2 /nobreak >nul
goto :wait_api

:api_ready
echo ---- pytest ----
"%E2E_PYTHON%" -m pytest -v%PYTEST_ARGS%
set "ERR=%errorlevel%"

:cleanup
echo ---- teardown test stack (this compose only) ----
taskkill /FI "WINDOWTITLE eq pgt-e2e-backend" /T /F >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and ($_.CommandLine -like '*app.py*--env=test*' -or $_.CommandLine -like '*app.py* --env test*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
%COMPOSE% down -v --remove-orphans

if "%ERR%"=="0" (
  echo ==== tests passed ====
) else (
  echo ==== tests failed, exit=%ERR% ====
)
exit /b %ERR%
