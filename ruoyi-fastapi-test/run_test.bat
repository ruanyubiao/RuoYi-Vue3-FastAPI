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

echo ==== Playwright E2E (test-* containers + PC backend --env=test) ====

where docker >nul 2>&1
if errorlevel 1 (
  echo [ERROR] docker not found
  exit /b 1
)
where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] python not found
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

if /I "%~1"=="rebuild" goto :build_fe
if exist "%FRONTEND_DIR%\dist\index.html" goto :stack
:build_fe
echo ---- build frontend dist (/prod-api) ----
pushd "%FRONTEND_DIR%"
call npm run build
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
start "pgt-e2e-backend" /D "%BACKEND_DIR%" python app.py --env=test

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
python -m pytest -v
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
