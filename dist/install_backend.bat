@echo off
chcp 65001 >nul
cd /d "%~dp0"

setlocal enabledelayedexpansion


set "ServicePath=D:\docker\service"
cmd /c ""%ServicePath%\stop_py.bat""

set "PYTHON_EXE=D:\docker\Python\python.exe"
if not exist "%PYTHON_EXE%" (
    for /f "delims=" %%i in ('where python.exe 2^>nul') do (
        set "PYTHON_EXE=%%i"
        goto :python_found
    )

    echo [ERROR] Python not found.
    echo.
    echo Waiting for 5 seconds, press a key to continue ...
    timeout /t 5
    exit /b 1
)

:python_found
echo Python: %PYTHON_EXE%




:: Check if service is already running
powershell -NoProfile -Command "if (Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.ExecutablePath -eq '%PYTHON_EXE%' -and $_.CommandLine -like '*pgt.app*' }) { exit 0 } else { exit 1 }"
if %errorlevel% equ 0 (
    echo PGT service is already running.
    echo Installation failed.
    powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.ExecutablePath -eq '%PYTHON_EXE%' -and $_.CommandLine -like '*pgt.app*' } | Select-Object ProcessId,CommandLine"
    timeout /t 10
    exit /b 1
)


set "CUR_DIR=."
set "CACHE_DIR=pkg"
set "TARGET_FILE="

for /f "delims=" %%f in ('dir /b /o-d "%CUR_DIR%\pgt-*-py3-none-any.whl" 2^>nul') do (
    set "TARGET_FILE=%%f"
    goto :found
)
:found

if not defined TARGET_FILE (
    echo Error: pgt-*-py3-none-any.whl file not found
    pause
    exit /b 1
)

echo Found latest file: !TARGET_FILE!
echo Will execute:
echo %PYTHON_EXE% -m pip uninstall pgt -y
echo %PYTHON_EXE% -m pip install "!TARGET_FILE!" --find-links "%CACHE_DIR%" --find-links "%CACHE_DIR%/pkg_cache" --find-links "%CUR_DIR%"

echo.
echo Waiting 10 seconds before upgrade...
timeout /t 10

%PYTHON_EXE% -m pip uninstall pgt -y
%PYTHON_EXE% -m pip install "!TARGET_FILE!" --find-links "%CACHE_DIR%" --find-links "%CACHE_DIR%/pkg_cache" --find-links "%CUR_DIR%"

if %errorlevel% equ 0 (
    echo Installation successful.
) else (
    echo Installation failed.
)


cmd /c ""%ServicePath%\start_py.bat" hide"

timeout /t 5 /nobreak
cmd /c ""%ServicePath%\status_py.bat""


endlocal