@echo off
setlocal EnableDelayedExpansion
REM ASCII-only comments (cmd code page). Do not put non-ASCII in this file.
REM HIL runner: headed browser + hardware sim on this PC; DUT = 192.168.100.52 by default.
REM Usage:
REM   run_hil.bat unit                     unit tests (no browser / no hardware)
REM   run_hil.bat db                       DUT MySQL schema vs local SQL (needs DB password)
REM   run_hil.bat ui                       headed page smoke (browser only)
REM   run_hil.bat can [biu^|xl^|yj216]      CAN; omit target = --auto all when card present
REM   run_hil.bat serial [device]          serial; omit = --auto all protocols when COM ready
REM   run_hil.bat udp                      key UDP; remote port may stay open (HIL_UDP_ENABLE=0 to skip)
REM   run_hil.bat round can^|serial [dev...] interactive rotate; wait Enter between suites
REM   run_hil.bat plan                     list CAN/serial/UDP plan (RUN/SKIP), no hardware
REM   run_hil.bat all                      unit+db+ui+CAN all+serial all+UDP; one run dir, one xlsx
REM   Extra args after suite go to pytest, e.g. run_hil.bat ui -k index
REM Hardware defaults: hil.local.json (override with HIL_* env). See README.
cd /d %~dp0
set PYTHONPATH=%~dp0;%PYTHONPATH%
REM Skip per-pytest fill; only fill once at :done
set HIL_SKIP_TEMPLATE_REPORT=1

REM ---------- Formal env examples (uncomment to override) ----------
REM set HIL_FRONTEND_URL=http://192.168.100.52:12580
REM set HIL_USERNAME=admin
REM set HIL_PASSWORD=admin123
REM set HIL_HEADED=1
REM set HIL_SLOW_MO_MS=200
REM ---------- Hardware examples (defaults in hil.local.json) ----------
REM set HIL_CAN_VENDOR=2
REM set HIL_IPC_CAN_VENDOR=3
REM set HIL_SERIAL_PORT=COM9
REM set HIL_IPC_SERIAL_PORT=COM8
REM set HIL_TEST_PC_IP=192.168.100.10

REM ---------- Shared artifact dir for this run (timestamp once) ----------
if "%HIL_RUN_DIR%"=="" (
  for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set HIL_TS=%%i
  set "HIL_RUN_DIR=%~dp0artifacts\!HIL_TS!"
)
if not exist "%HIL_RUN_DIR%" mkdir "%HIL_RUN_DIR%"
echo [HIL] run dir: %HIL_RUN_DIR%

set SUITE=%~1
if "%SUITE%"=="" set SUITE=all
set TARGET=
set SKIPN=1
if /i "%SUITE%"=="can" set NEEDT=1
if /i "%SUITE%"=="serial" set NEEDT=1
if "%NEEDT%"=="1" (
  set "A2=%~2"
  if not "!A2!"=="" if not "!A2:~0,1!"=="-" (
    set "TARGET=!A2!"
    set SKIPN=2
  )
)
REM Args after SKIPN become pytest extras
set EXTRA=
set /a ARGN=0
for %%a in (%*) do (
  set /a ARGN+=1
  if !ARGN! GTR %SKIPN% set "EXTRA=!EXTRA! %%a"
)

set HTML=0
python -c "import pytest_html" 2>nul && set HTML=1

set RC=0
if /i "%SUITE%"=="round" (
  python -m hil.round %2 %3 %4 %5 %6 %7 %8 %9
  set RC=!ERRORLEVEL!
  goto :done
)
if /i "%SUITE%"=="plan" (
  python -m hil.round can --plan
  python -m hil.round serial --plan
  set HIL_UDP_ENABLE=1
  set HIL_GROUP=udp_plan
  python -m pytest -m hil_udp --hil-plan -q
  goto :done
)
if /i "%SUITE%"=="all" (
  call :run_group unit
  call :run_group db
  call :run_group ui
  call :run_auto can
  call :run_auto serial
  if not defined HIL_UDP_ENABLE set HIL_UDP_ENABLE=1
  call :run_group udp
  goto :done
)
if /i "%SUITE%"=="can" if "%TARGET%"=="" (
  call :run_auto can
  goto :done
)
if /i "%SUITE%"=="serial" if "%TARGET%"=="" (
  call :run_auto serial
  goto :done
)
if /i "%SUITE%"=="udp" if not defined HIL_UDP_ENABLE set HIL_UDP_ENABLE=1
call :run_group %SUITE% %TARGET%

:done
echo.
echo [HIL] run dir: %HIL_RUN_DIR%
REM summary.txt is UTF-8; print via python to avoid console mojibake
if exist "%HIL_RUN_DIR%\summary.txt" python -c "import sys;print(open(sys.argv[1],encoding='utf-8').read())" "%HIL_RUN_DIR%\summary.txt"
echo.
echo [HIL] filling checklist report...
python -m hil.report sync
python -m hil.report fill "%HIL_RUN_DIR%"
REM List filled xlsx under run dir (filename may be non-ASCII; print via python)
python -c "import sys,glob; fs=sorted(glob.glob(sys.argv[1]+'/*.xlsx')); print('[HIL] report:', fs[-1] if fs else '(none)')" "%HIL_RUN_DIR%"
endlocal & exit /b %RC%

:run_auto
REM Non-interactive full rotate: python -m hil.round can|serial --auto; one suite per protocol, same HIL_RUN_DIR
set KIND=%1
echo.
echo ===================== [HIL] auto rotate %KIND% (all protocols) =====================
python -m hil.round %KIND% --auto %EXTRA%
set GRC=%ERRORLEVEL%
if not "%GRC%"=="0" if not "%GRC%"=="5" set RC=%GRC%
goto :eof

:run_group
set G=%1
set T=%2
if /i "%G%"=="udp" if not defined HIL_UDP_ENABLE set HIL_UDP_ENABLE=1
set MARK=
if /i "%G%"=="unit" set MARK=-m unit
if /i "%G%"=="db" set MARK=-m db_schema
if /i "%G%"=="ui" set MARK=-m ui_only
if /i "%G%"=="can" set MARK=-m hil_can
if /i "%G%"=="serial" set MARK=-m hil_serial
if /i "%G%"=="udp" set MARK=-m hil_udp
set GN=%G%
if not "%T%"=="" (
  set GN=%G%_%T%
  if /i "%G%"=="can" set HIL_CAN_TARGET=%T%
  if /i "%G%"=="serial" set HIL_SERIAL_TARGET=%T%
)
set HIL_GROUP=%GN%
set REPORT=--junitxml="%HIL_RUN_DIR%\junit_%GN%.xml" --log-file="%HIL_RUN_DIR%\pytest_%GN%.log" --log-file-level=INFO
if "%HTML%"=="1" set REPORT=%REPORT% --html="%HIL_RUN_DIR%\report_%GN%.html" --self-contained-html
echo.
echo ===================== [HIL] suite %GN% =====================
python -m pytest %MARK% -v -s %REPORT% %EXTRA%
set GRC=%ERRORLEVEL%
REM exit 5 = no tests collected for this marker; not a failure
if not "%GRC%"=="0" if not "%GRC%"=="5" set RC=%GRC%
set HIL_GROUP=
goto :eof
