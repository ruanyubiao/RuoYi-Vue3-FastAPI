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
rem ==== Update: runs %INSTALL_DIR%\service\update\update.bat with this folder as the update package (one window, elevated) ====
rem it updates what releases\role.env lists: embedded backend + frontend, or the split server and/or collector
rem ("%~dp0." : a trailing \" would escape the closing quote). Works from Desktop or USB, spaces allowed.
if exist D:\ (set "INSTALL_DIR=D:\PGT") else (set "INSTALL_DIR=C:\PGT")
if not exist "%INSTALL_DIR%\service\update\update.bat" (
    echo [ERROR] %INSTALL_DIR%\service\update\update.bat not found. Run deploy\install.bat first.
    pause
    exit /b 1
)
call "%INSTALL_DIR%\service\update\update.bat" "%~dp0." nopause
set "RC=%errorlevel%"
echo.
pause
exit /b %RC%
