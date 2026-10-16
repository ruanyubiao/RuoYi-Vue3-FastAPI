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

if not exist "%~dp0install_base.bat" (
    echo [ERROR] install_base.bat was not found.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

call "%~dp0install_base.bat"
if errorlevel 1 (
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

echo.
echo ==== Check Docker engine

docker --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker CLI is not available. docker --version failed.
    echo Install Docker Desktop, wait until it finishes installing, then run this script again.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Desktop is installed, but the engine is not running.
    echo Start Docker Desktop and wait until initialization finishes, then run this script again.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

echo [INFO] Docker engine is running.

if not exist "%DataPath%" mkdir "%DataPath%"
if not exist "%AppPath%" mkdir "%AppPath%"

echo.
echo ==== Starting Docker Containers
if not exist "%APPDATA%\Docker" mkdir "%APPDATA%\Docker"
copy /Y .\docker\settings-store.json "%APPDATA%\Docker\" >nul 2>&1
reg delete "HKEY_CURRENT_USER\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run" /v "Docker Desktop" /f >nul 2>&1
reg delete "HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run" /v "Docker Desktop" /f >nul 2>&1


echo.
echo ==== Extracting Files, This process will take approximately 2 minutes

unzip -o -q .\docker.zip -d D:\
unzip -o -q DesktopPGT.zip -d %DesktopPath%

if exist Python.zip (
    unzip -o -q Python.zip -d D:\docker\
)

:: Installing Windows Startup Task
start "" /D "%ServicePath%\init" /B /wait ".\create_py_startup.bat"

if exist "D:\docker\Python\python.exe" (
	D:\docker\Python\python.exe -m pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
)


echo.
echo ==== Firewall rules settings

:: Step 1: Remove any existing rules with the same names (clean start)
netsh advfirewall firewall delete rule name="PGT Python Service" >nul 2>&1
netsh advfirewall firewall delete rule name="PGT Python Service Out" >nul 2>&1
netsh advfirewall firewall delete rule name="nginx" >nul 2>&1
netsh advfirewall firewall delete rule name="nginx Out" >nul 2>&1
netsh advfirewall firewall delete rule name="Open Http Ports" >nul 2>&1
netsh advfirewall firewall delete rule name="Allow Python 9099 for WSL" >nul 2>&1
netsh advfirewall firewall delete rule name="Allow Python 9099 for WSL Out" >nul 2>&1

:: Step 2: Add original rules (based on program paths)
netsh advfirewall firewall add rule name="PGT Python Service" dir=in action=allow program="D:\docker\Python\python.exe" enable=yes
netsh advfirewall firewall add rule name="PGT Python Service Out" dir=out action=allow program="D:\docker\Python\python.exe" enable=yes
netsh advfirewall firewall add rule name="nginx" dir=in action=allow program="D:\tools\nginx\nginx.exe" enable=yes
netsh advfirewall firewall add rule name="nginx Out" dir=out action=allow program="D:\tools\nginx\nginx.exe" enable=yes
:: Step 3: Add rule for HTTP ports (80 and 12580)
netsh advfirewall firewall add rule name="Open Http Ports" dir=in action=allow protocol=TCP localport=80,12580
:: Step 4: Add WSL2‑specific rules for Python backend port 9099
netsh advfirewall firewall add rule name="Allow Python 9099 for WSL" dir=in action=allow protocol=TCP localport=9099 profile=any
netsh advfirewall firewall add rule name="Allow Python 9099 for WSL Out" dir=out action=allow protocol=TCP localport=9099 profile=any


docker load -i .\docker\docker_image_nginx_redis_mysql.tar

docker compose --project-directory D:\docker\mysql up -d
docker compose --project-directory D:\docker\redis up -d
docker compose --project-directory D:\docker\nginx up -d


echo.
echo All deployment steps completed successfully.
pause