@ECHO OFF&(PUSHD "%~DP0")&(REG QUERY "HKU\S-1-5-19">NUL 2>&1)||(
powershell -Command "Start-Process '%~sdpnx0' -Verb RunAs"&&EXIT)


@echo off
cd /d "%~dp0"

set "ScriptPath=%~dp0"
set "DataPath=%LOCALAPPDATA%\PGT"
set "DesktopPath=%USERPROFILE%\Desktop"
set "AppPath=%USERPROFILE%\Desktop\PGT"
set "InstallPath=D:\docker"
set "ServicePath=D:\docker\service"

set "NEED_REBOOT=0"
set "INSTALL_FAILED=0"

echo.
echo ==== Check WSL

if exist "%ProgramFiles%\WSL\wsl.exe" goto wsl_installed
wsl --version >nul 2>&1
if not errorlevel 1 goto wsl_installed

echo [INFO] WSL is not installed. Starting installation.
if not exist "%ScriptPath%wsl.2.7.11.0.x64.msi" (
    echo [WARN] wsl.2.7.11.0.x64.msi was not found. Falling back to command install.
    goto wsl_fallback
)

echo [INFO] Installing wsl.2.7.11.0.x64.msi ...
msiexec /i "%ScriptPath%wsl.2.7.11.0.x64.msi" /qn /norestart
set "MSI_ERR=%ERRORLEVEL%"
if "%MSI_ERR%"=="0" goto wsl_ok
if "%MSI_ERR%"=="3010" goto wsl_ok
if "%MSI_ERR%"=="1641" goto wsl_ok

echo [WARN] MSI install failed with code %MSI_ERR%. Falling back to command install.
goto wsl_fallback

:wsl_fallback
echo [INFO] Running wsl --install --no-distribution ...
wsl --install --no-distribution
if errorlevel 1 (
    echo [ERROR] WSL command install failed.
    set "INSTALL_FAILED=1"
) else (
    echo [INFO] WSL command install finished.
    set "NEED_REBOOT=1"
)
goto docker_check

:wsl_installed
echo [INFO] WSL is already installed. Skipping.
goto docker_check

:wsl_ok
echo [INFO] WSL installed.
set "NEED_REBOOT=1"
goto docker_check

:docker_check
echo.
echo ==== Check Docker Desktop

if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" goto docker_installed

echo [INFO] Docker Desktop is not installed. Starting installation.
if not exist "%ScriptPath%Docker Desktop Installer.exe" (
    echo [ERROR] Docker Desktop Installer.exe was not found.
    set "INSTALL_FAILED=1"
    goto finish
)

echo [INFO] Installing Docker Desktop for the system user ...
start /wait "" "%ScriptPath%Docker Desktop Installer.exe" install --quiet --accept-license --backend=wsl-2
set "DOCKER_ERR=%ERRORLEVEL%"
if "%DOCKER_ERR%"=="0" goto docker_need_reboot
if "%DOCKER_ERR%"=="3010" goto docker_need_reboot
echo [WARN] Docker Desktop installer returned code %DOCKER_ERR%.
set "INSTALL_FAILED=1"
goto finish

:docker_need_reboot
echo [INFO] Docker Desktop installed.
set "NEED_REBOOT=1"
goto finish

:docker_installed
echo [INFO] Docker Desktop is already installed. Skipping.

:finish
if "%INSTALL_FAILED%"=="1" goto finish_fail
if "%NEED_REBOOT%"=="1" goto finish_reboot
echo [INFO] WSL and Docker Desktop are ready.
exit /b 0

:finish_reboot
echo.
echo Please restart the system.
pause
exit /b 1

:finish_fail
echo.
echo [ERROR] Base software installation failed.
if "%NEED_REBOOT%"=="1" echo Please restart the system.
pause
exit /b 1

