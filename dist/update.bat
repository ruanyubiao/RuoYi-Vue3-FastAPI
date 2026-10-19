@echo off
rem ---- self-elevate: not admin -> run this script again as administrator (UAC), wait for it, return its exit code ----
REG QUERY "HKU\S-1-5-19" >nul 2>&1 && goto :pgt_admin
set "PGT_ARGS=%*"
powershell -NoP -Command "try { $a=$env:PGT_ARGS; if ($a) { $p=Start-Process -FilePath '%~f0' -ArgumentList $a -Verb RunAs -Wait -PassThru } else { $p=Start-Process -FilePath '%~f0' -Verb RunAs -Wait -PassThru }; exit $p.ExitCode } catch { Write-Host '[ERROR] administrator rights are required (UAC was declined)'; Start-Sleep 5; exit 1 }"
exit /b %errorlevel%
:pgt_admin


@echo off
setlocal
cd /d "%~dp0"
rem ==== Update: backend first, frontend only if the backend succeeded; one window (runs elevated) ====
rem the install scripts live in %INSTALL_DIR%\service (installed by deploy\install.bat); this folder is passed as SRC
rem ("%~dp0." : a trailing \" would escape the closing quote). Works from Desktop or USB, spaces allowed.
if exist D:\ (set "INSTALL_DIR=D:\PGT") else (set "INSTALL_DIR=C:\PGT")
for %%s in (install_backend install_frontend) do if not exist "%INSTALL_DIR%\service\%%s.bat" (
    echo [ERROR] %INSTALL_DIR%\service\%%s.bat not found. Run deploy\install.bat first.
    pause
    exit /b 1
)

echo ==== 1/2 backend update
call "%INSTALL_DIR%\service\install_backend.bat" "%~dp0." nopause
if errorlevel 1 (
    echo.
    echo ==== [ERROR] backend update FAILED. Frontend was NOT updated. The old version keeps running.
    echo ==== log: %INSTALL_DIR%\data\logs\install\
    echo.
    pause
    exit /b 1
)

echo.
echo ==== 2/2 frontend update
call "%INSTALL_DIR%\service\install_frontend.bat" "%~dp0." nopause
if errorlevel 1 (
    echo.
    echo ==== [ERROR] frontend update FAILED ^(the backend was updated^).
    echo.
    pause
    exit /b 1
)

echo.
echo ==== [OK] update finished: backend and frontend updated.
echo.
pause
exit /b 0
