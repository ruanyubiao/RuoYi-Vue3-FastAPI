@echo off
rem ---- self-elevate: not admin -> run this script again as administrator (UAC), wait for it, return its exit code ----
REG QUERY "HKU\S-1-5-19" >nul 2>&1 && goto :pgt_admin
set "PGT_ARGS=%*"
powershell -NoP -Command "try { $a=$env:PGT_ARGS; if ($a) { $p=Start-Process -FilePath '%~f0' -ArgumentList $a -Verb RunAs -Wait -PassThru } else { $p=Start-Process -FilePath '%~f0' -Verb RunAs -Wait -PassThru }; exit $p.ExitCode } catch { Write-Host '[ERROR] administrator rights are required (UAC was declined)'; Start-Sleep 5; exit 1 }"
exit /b %errorlevel%
:pgt_admin

@echo off
set "ScriptPath=%~dp0"
cd /d "%ScriptPath%"
rem usage: install.bat [1, 2 or 3] [collector name] [server address]
rem   1 = collector : collector on this PC (no Docker), it uses Redis on the server
rem   2 = server    : backend in Docker container backend, mysql/redis/nginx, frontend (no collector)
rem   3 = embedded  : backend on Windows, it starts the collector itself; mysql/redis/nginx in Docker
rem   1 and 2 add to what is installed in split mode, so one PC can have both
rem the mode goes to <install dir>\releases\role.env, the update scripts read it

rem install dir: D:\PGT, or C:\PGT when there is no D: drive (PGT.zip has a top-level "PGT" folder)
if exist D:\ (set "InstallParent=D:") else (set "InstallParent=C:")
set "INSTALL_DIR=%InstallParent%\PGT"
set "DataPath=%INSTALL_DIR%\data"
set "ROLE_FILE=%INSTALL_DIR%\releases\role.env"


rem ---- installed mode (role.env; an install without it is embedded) ----
set "OLD_PGT_MODE="
set "OLD_PGT_SERVER=0"
set "OLD_PGT_COLLECTOR=0"
set "OLD_COLLECTOR_HOST="
set "OLD_REDIS_HOST="
if exist "%ROLE_FILE%" (
    for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%ROLE_FILE%") do set "OLD_%%a=%%b"
)
if not defined OLD_PGT_MODE if exist "%INSTALL_DIR%\service\" set "OLD_PGT_MODE=embedded"
if defined OLD_PGT_MODE if /i not "%OLD_PGT_MODE%"=="split" set "OLD_PGT_MODE=embedded"
if not "%OLD_PGT_MODE%"=="split" (
    set "OLD_PGT_SERVER=0"
    set "OLD_PGT_COLLECTOR=0"
)


rem ---- mode to install: parameter or menu ----
set "PGT_CHOICE=%~1"
if /i "%PGT_CHOICE%"=="collector" set "PGT_CHOICE=1"
if /i "%PGT_CHOICE%"=="server" set "PGT_CHOICE=2"
if /i "%PGT_CHOICE%"=="embedded" set "PGT_CHOICE=3"
if defined PGT_CHOICE goto :choice_check
echo ==== PGT install, target %INSTALL_DIR%
if "%OLD_PGT_MODE%"=="split" echo installed: split mode, server %OLD_PGT_SERVER%, collector %OLD_PGT_COLLECTOR%
if "%OLD_PGT_MODE%"=="embedded" echo installed: embedded mode
echo   1  collector  collector only, no Docker; it uses Redis on the server
echo   2  server     backend in Docker, mysql/redis/nginx, frontend
echo   3  embedded   backend and collector on this PC, mysql/redis/nginx in Docker
choice /c 123 /n /m "Select 1, 2 or 3: "
set "PGT_CHOICE=%errorlevel%"
:choice_check
if not "%PGT_CHOICE%"=="1" if not "%PGT_CHOICE%"=="2" if not "%PGT_CHOICE%"=="3" (
    echo [ERROR] unknown mode "%~1", use 1/collector, 2/server or 3/embedded
    pause
    exit /b 1
)

rem new flags: 1 and 2 add to an installed split mode
set "NEW_MODE=split"
set "NEW_SERVER=%OLD_PGT_SERVER%"
set "NEW_COLLECTOR=%OLD_PGT_COLLECTOR%"
if "%PGT_CHOICE%"=="1" set "NEW_COLLECTOR=1"
if "%PGT_CHOICE%"=="2" set "NEW_SERVER=1"
if "%PGT_CHOICE%"=="3" (
    set "NEW_MODE=embedded"
    set "NEW_SERVER=0"
    set "NEW_COLLECTOR=0"
)
if defined OLD_PGT_MODE if not "%OLD_PGT_MODE%"=="%NEW_MODE%" (
    choice /c YN /m "Installed: %OLD_PGT_MODE% mode. Switch to %NEW_MODE% mode"
    if errorlevel 2 (
        echo [INFO] nothing changed
        pause
        exit /b 1
    )
)

rem collector name and server address: asked when installing the collector (1)
set "COLLECTOR_HOST=%OLD_COLLECTOR_HOST%"
set "REDIS_HOST=%OLD_REDIS_HOST%"
if not "%PGT_CHOICE%"=="1" goto :ask_done
if not defined REDIS_HOST if "%NEW_SERVER%"=="1" set "REDIS_HOST=127.0.0.1"
call :ask COLLECTOR_HOST host "Collector name (letters, digits, _ and -)" "%~2"
if errorlevel 1 (pause & exit /b 1)
call :ask REDIS_HOST addr "Server address (IP or host name of the PC with Redis)" "%~3"
if errorlevel 1 (pause & exit /b 1)
:ask_done
if "%NEW_COLLECTOR%"=="1" if not defined REDIS_HOST set "REDIS_HOST=127.0.0.1"
if "%PGT_CHOICE%"=="1" (echo [mode] collector %COLLECTOR_HOST%, Redis %REDIS_HOST%) else if "%PGT_CHOICE%"=="2" (echo [mode] server) else (echo [mode] embedded)
if "%PGT_CHOICE%"=="1" goto :docker_done


if not exist "%ScriptPath%docker\docker_env_install.bat" (
    echo [ERROR] docker\docker_env_install.bat was not found.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

call "%ScriptPath%docker\docker_env_install.bat"
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

if not exist "%APPDATA%\Docker" mkdir "%APPDATA%\Docker"
copy /Y "%ScriptPath%docker\settings-store.json" "%APPDATA%\Docker\" >nul 2>&1
reg delete "HKEY_CURRENT_USER\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run" /v "Docker Desktop" /f >nul 2>&1
reg delete "HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run" /v "Docker Desktop" /f >nul 2>&1
:docker_done


echo.
echo ==== Service PGT: stop before extracting (its files in %INSTALL_DIR% are in use while it runs)
set "PGT_WAS_RUNNING="
set "PGT_STATE="
for /f "tokens=4" %%s in ('sc query PGT 2^>nul ^| find "STATE"') do set "PGT_STATE=%%s"
if not defined PGT_STATE (
    echo [INFO] PGT service is not installed
) else if /i "%PGT_STATE%"=="STOPPED" (
    echo [INFO] PGT service is already stopped
) else (
    set "PGT_WAS_RUNNING=1"
    call :stop_pgt
    if errorlevel 1 (
        echo [ERROR] PGT service could not be stopped within 30 s, check %INSTALL_DIR%\data\logs\service, then run install.bat again
        pause
        exit /b 1
    )
)


echo.
echo ==== Extracting Files, This process will take approximately 2 minutes

rem -d paths end in "\." : a trailing \" would escape the closing quote
"%ScriptPath%unzip.exe" -o -q "%ScriptPath%PGT.zip" -d "%InstallParent%\."
if errorlevel 1 (
    echo [ERROR] extraction failed: files in %INSTALL_DIR% are in use. Close programs using them and run install.bat again.
    pause
    exit /b 1
)
rem update scripts now live in service\update
for %%f in (install_backend.bat install_frontend.bat db_patches_apply.bat) do if exist "%INSTALL_DIR%\service\%%f" del /q "%INSTALL_DIR%\service\%%f"

if not exist "%DataPath%" mkdir "%DataPath%"

rem pip mirror for this Python (global config)
if exist "%INSTALL_DIR%\Python\python.exe" (
    "%INSTALL_DIR%\Python\python.exe" -m pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
)


echo.
echo ==== Install mode: %ROLE_FILE%
if not exist "%INSTALL_DIR%\releases" mkdir "%INSTALL_DIR%\releases"
(
    echo # written by deploy\install.bat
    echo PGT_MODE=%NEW_MODE%
    echo PGT_SERVER=%NEW_SERVER%
    echo PGT_COLLECTOR=%NEW_COLLECTOR%
    if "%NEW_COLLECTOR%"=="1" echo COLLECTOR_HOST=%COLLECTOR_HOST%
    if "%NEW_COLLECTOR%"=="1" echo REDIS_HOST=%REDIS_HOST%
) > "%ROLE_FILE%"
type "%ROLE_FILE%"
if "%PGT_CHOICE%"=="1" goto :service


if not "%PGT_CHOICE%"=="2" goto :firewall
echo.
echo ==== Backend container settings: %INSTALL_DIR%\backend\env\pgt.env
rem backend worker processes: physical CPU cores / 2; logical processors / 2 when that fails; else 4; at least 1
set "PGT_CORES="
set "PGT_CORE_SRC=cpu cores"
for /f %%c in ('powershell -NoP -C "$n=0; try{ foreach($p in @(Get-CimInstance Win32_Processor -EA Stop)){ $n+=[int]$p.NumberOfCores } }catch{}; if($n -gt 0){ $n }" 2^>nul') do set "PGT_CORES=%%c"
if defined PGT_CORES echo %PGT_CORES%| findstr /r "^[1-9][0-9]*$" >nul || set "PGT_CORES="
if not defined PGT_CORES (
    set "PGT_CORES=%NUMBER_OF_PROCESSORS%"
    set "PGT_CORE_SRC=logical processors"
)
if defined PGT_CORES echo %PGT_CORES%| findstr /r "^[1-9][0-9]*$" >nul || set "PGT_CORES="
set "PGT_WORKERS=4"
if defined PGT_CORES set /a PGT_WORKERS=PGT_CORES/2
if %PGT_WORKERS% lss 1 set "PGT_WORKERS=1"
if defined PGT_CORES echo [INFO] backend workers: %PGT_WORKERS% (%PGT_CORE_SRC%: %PGT_CORES%)
if not defined PGT_CORES echo [INFO] backend workers: %PGT_WORKERS% (cpu cores unknown)
rem created from pgt.env.example only when missing; JWT key from releases\secrets.env, else a new one; APP_WORKERS as computed above
if exist "%INSTALL_DIR%\backend\env\pgt.env" (
    echo [INFO] pgt.env exists, kept
) else (
    powershell -NoP -C "$ErrorActionPreference='Stop'; $d=Join-Path $env:INSTALL_DIR 'backend\env'; $k=''; $s=Join-Path $env:INSTALL_DIR 'releases\secrets.env'; if(Test-Path $s){ foreach($l in Get-Content $s){ if($l -match '^JWT_SECRET_KEY=(\w+)'){ $k=$Matches[1] } } }; if(-not $k){ $b=New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); $k=-join ($b | ForEach-Object { $_.ToString('x2') }) }; $t=@(Get-Content (Join-Path $d 'pgt.env.example')) -replace '^JWT_SECRET_KEY=.*$', ('JWT_SECRET_KEY=' + $k) -replace '^APP_WORKERS=.*$', ('APP_WORKERS=' + $env:PGT_WORKERS) -replace '^APP_RELOAD=.*$', 'APP_RELOAD=false'; [IO.File]::WriteAllLines((Join-Path $d 'pgt.env'), [string[]]$t)"
    if errorlevel 1 (
        echo [ERROR] creating pgt.env failed
        pause
        exit /b 1
    )
    echo [OK] pgt.env created
)
rem an existing pgt.env keeps its values; APP_WORKERS / APP_RELOAD are only added when the key is missing
powershell -NoP -C "$ErrorActionPreference='Stop'; $f=Join-Path $env:INSTALL_DIR 'backend\env\pgt.env'; $t=[IO.File]::ReadAllText($f); $add=@(); if($t -notmatch '(?m)^\s*APP_WORKERS\s*='){ $add+=('APP_WORKERS=' + $env:PGT_WORKERS) }; if($t -notmatch '(?m)^\s*APP_RELOAD\s*='){ $add+='APP_RELOAD=false' }; if($add.Count){ $e=[string][char]13 + [char]10; if($t.Length -and $t.IndexOf([string][char]13) -lt 0){ $e=[string][char]10 }; $nl=''; if($t.Length -and -not $t.EndsWith([string][char]10)){ $nl=$e }; [IO.File]::AppendAllText($f, $nl + ($add -join $e) + $e); '[INFO] pgt.env: added ' + ($add -join ', ') } else { foreach($l in $t -split '\r?\n'){ if($l -match '^\s*APP_WORKERS\s*=\s*(.*)$'){ $v=$Matches[1].Trim(); if($v -eq $env:PGT_WORKERS){ '[INFO] pgt.env: APP_WORKERS=' + $v } else { '[INFO] pgt.env: APP_WORKERS=' + $v + ' (existing value kept)' } } } }"
if errorlevel 1 (
    echo [ERROR] writing APP_WORKERS to pgt.env failed
    pause
    exit /b 1
)

:firewall


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
netsh advfirewall firewall delete rule name="PGT 9099 local+WSL" >nul 2>&1
netsh advfirewall firewall delete rule name="PGT Web 12580" >nul 2>&1
netsh advfirewall firewall delete rule name="PGT Redis 6379" >nul 2>&1

:: 9099 only from localhost / WSL / Docker networks (LAN reaches the backend through nginx on 12580)
netsh advfirewall firewall add rule name="PGT 9099 local+WSL" dir=in action=allow protocol=TCP localport=9099 remoteip=127.0.0.1,172.16.0.0/12,192.168.65.0/24 profile=any
:: Web entry
netsh advfirewall firewall add rule name="Open Http Ports" dir=in action=allow protocol=TCP localport=80,12580
:: server: Redis for the collectors in the local subnet
if "%PGT_CHOICE%"=="2" netsh advfirewall firewall add rule name="PGT Redis 6379" dir=in action=allow protocol=TCP localport=6379 remoteip=localsubnet profile=any

echo.
echo ==== Starting Docker Containers
rem image archive: prefer .tar.gz, fall back to .tar (docker load reads both)
set "IMG=%ScriptPath%docker\docker_image_pgt.tar.gz"
if not exist "%IMG%" set "IMG=%ScriptPath%docker\docker_image_pgt.tar"
if not exist "%IMG%" (
    echo [ERROR] docker\docker_image_pgt.tar.gz / .tar not found
    pause
    exit /b 1
)
docker load -i "%IMG%"
if errorlevel 1 (
    echo [ERROR] docker load failed: "%IMG%"
    pause
    exit /b 1
)

rem embedded: the backend runs on Windows, a backend container would hold port 9099
if not "%PGT_CHOICE%"=="3" goto :compose_up
docker inspect backend >nul 2>&1
if not errorlevel 1 (
    echo [INFO] removing container backend
    docker rm -f backend >nul
)
:compose_up
docker compose --project-directory "%INSTALL_DIR%\mysql" up -d
docker compose --project-directory "%INSTALL_DIR%\redis" up -d
docker compose --project-directory "%INSTALL_DIR%\nginx" up -d
if not "%PGT_CHOICE%"=="2" goto :service
rem server: the backend container starts once update.bat has put the wheels into backend\whl
if exist "%INSTALL_DIR%\backend\whl\pgt-*.whl" (
    docker compose --project-directory "%INSTALL_DIR%\backend" up -d
) else (
    docker compose --project-directory "%INSTALL_DIR%\backend" up --no-start
)


:service
if "%NEW_MODE%"=="split" if not "%NEW_COLLECTOR%"=="1" goto :service_server_only
echo.
echo ==== Windows service PGT: delete and register again from %INSTALL_DIR%\service\winsw\PGT.xml
rem start type: a manual or disabled start type of the old service is kept; otherwise automatic, delayed start
set "PGT_START="
sc query PGT >nul 2>&1
if not errorlevel 1 (
    set "PGT_START=delayed-auto"
    sc qc PGT | findstr START_TYPE | findstr DEMAND_START >nul && set "PGT_START=demand"
    sc qc PGT | findstr START_TYPE | findstr DISABLED >nul && set "PGT_START=disabled"
    call "%INSTALL_DIR%\service\init\delete_backend_service.bat" nopause
    if errorlevel 1 (
        echo [ERROR] deleting the old PGT service failed, run %INSTALL_DIR%\service\init\delete_backend_service.bat
        pause
        exit /b 1
    )
)
call "%INSTALL_DIR%\service\init\create_backend_service.bat" nopause
if errorlevel 1 (
    echo [ERROR] PGT service registration failed, run %INSTALL_DIR%\service\init\create_backend_service.bat
    pause
    exit /b 1
)
if not defined PGT_START (
    echo [service] PGT registered, start type: automatic, delayed start
) else if "%PGT_START%"=="delayed-auto" (
    echo [service] PGT re-registered, start type: automatic, delayed start
) else (
    sc config PGT start= %PGT_START% >nul
    if errorlevel 1 (
        echo [ERROR] setting the PGT start type to %PGT_START% failed, run: sc config PGT start= %PGT_START%
        pause
        exit /b 1
    )
    if "%PGT_START%"=="demand" (echo [service] PGT re-registered, start type kept: manual) else (echo [service] PGT re-registered, start type kept: disabled)
)
rem start PGT again only if it was running before this install and a release is installed
if defined PGT_WAS_RUNNING (
    if exist "%INSTALL_DIR%\releases\current.txt" (
        echo [service] starting PGT
        net start PGT >nul 2>&1 && (echo [OK] PGT service started) || (echo [WARN] net start PGT failed, see %INSTALL_DIR%\data\logs\service)
    ) else (
        echo [INFO] not installed yet, PGT stays stopped
    )
)
goto :shortcuts

:service_server_only
rem server only: the backend runs in Docker, a Windows service PGT is not used
sc query PGT >nul 2>&1 || goto :shortcuts
echo.
echo ==== Windows service PGT: not used on a server without collector, deleting it
call "%INSTALL_DIR%\service\init\delete_backend_service.bat" nopause
if errorlevel 1 echo [WARN] deleting the PGT service failed, run %INSTALL_DIR%\service\init\delete_backend_service.bat


:shortcuts
echo.
echo ==== Desktop shortcuts (Desktop\PGT; re-run later: %INSTALL_DIR%\service\init\desktop_shortcut.bat)
call "%INSTALL_DIR%\service\init\desktop_shortcut.bat" nopause
if errorlevel 1 echo [WARN] desktop shortcuts failed, run %INSTALL_DIR%\service\init\desktop_shortcut.bat again


echo.
echo All deployment steps completed.
if "%NEW_MODE%"=="split" (
    echo Mode: split, server %NEW_SERVER%, collector %NEW_COLLECTOR%
) else (
    echo Mode: embedded
)
if "%PGT_CHOICE%"=="2" echo Backend container backend starts after update.bat. Collectors on other PCs connect to Redis on port 6379 of this PC.
if not "%PGT_CHOICE%"=="2" echo PGT service registered (autostart on/off: %INSTALL_DIR%\service\init\enable_backend_autostart.bat / disable_backend_autostart.bat^).
echo Next: run update.bat from the update package.
pause
exit /b 0


rem ---- ask for a value: %1 variable (its value is the default), %2 host or addr, %3 prompt, %4 value given as parameter ----
rem host: letters, digits, _ and -   addr: letters, digits, . _ and -
:ask
set "PGT_KIND=%~2"
call set "PGT_DEF=%%%~1%%"
set "PGT_PARAM=%~4"
set "PGT_IN=%~4"
if defined PGT_IN goto :ask_check
:ask_loop
set "PGT_IN="
if defined PGT_DEF (set /p "PGT_IN=%~3 [%PGT_DEF%]: ") else (set /p "PGT_IN=%~3: ")
if not defined PGT_IN set "PGT_IN=%PGT_DEF%"
if not defined PGT_IN goto :ask_loop
:ask_check
powershell -NoP -C "$r=@{host='^[A-Za-z0-9_-]+$'; addr='^[A-Za-z0-9._-]+$'}[$env:PGT_KIND]; if($env:PGT_IN -cmatch $r){exit 0}else{exit 1}"
if errorlevel 1 goto :ask_bad
set "%~1=%PGT_IN%"
exit /b 0
:ask_bad
if defined PGT_PARAM (
    echo [ERROR] invalid value given as parameter
    exit /b 1
)
echo [ERROR] invalid value
goto :ask_loop


rem ---- stop service PGT, wait up to 30 s for STOPPED; exit 1 if it is still not stopped ----
:stop_pgt
echo [service] stopping PGT
net stop PGT >nul 2>&1
set "PGT_N=0"
:stop_pgt_wait
set "PGT_STATE="
for /f "tokens=4" %%s in ('sc query PGT 2^>nul ^| find "STATE"') do set "PGT_STATE=%%s"
if /i "%PGT_STATE%"=="STOPPED" (
    echo [service] PGT stopped
    exit /b 0
)
set /a PGT_N+=1
if %PGT_N% geq 15 exit /b 1
timeout /t 2 /nobreak >nul 2>&1
goto :stop_pgt_wait
