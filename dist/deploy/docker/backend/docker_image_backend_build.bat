@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem builds the backend shell image backend-py313slim:3.13 (python:3.13-slim, Linux):
rem every dependency of the pgt wheel is installed, except pgt itself, TeleMetryParser and gpcan;
rem those three wheels go to <install dir>\backend\whl and are installed by the container when it starts (backend\entrypoint.sh)
rem dependency list = [project] dependencies of ruoyi-fastapi-backend\pyproject.toml; run again after they change
set "SHELL_IMAGE=backend-py313slim:3.13"
set "BASE_IMAGE=python:3.13-slim"
set "MIRROR_IMAGE=docker.1panel.live/library/python:3.13-slim"
set "CTX=%~dp0."
set "PYPROJECT=%~dp0..\..\..\..\ruoyi-fastapi-backend\pyproject.toml"

if not exist "%CTX%\Dockerfile" (
    echo [ERROR] "%CTX%\Dockerfile" not found
    pause
    exit /b 1
)
if not exist "%PYPROJECT%" (
    echo [ERROR] "%PYPROJECT%" not found
    pause
    exit /b 1
)

rem 1) base image: local copy, otherwise docker hub, otherwise the mirror (tagged back to python:3.13-slim)
docker image inspect %BASE_IMAGE% >nul 2>&1
if not errorlevel 1 goto :base_ok
echo [INFO] %BASE_IMAGE% not found locally, pulling...
docker pull %BASE_IMAGE%
if not errorlevel 1 goto :base_ok
echo [INFO] pull failed, trying %MIRROR_IMAGE%
docker pull %MIRROR_IMAGE%
if errorlevel 1 goto :pull_fail
docker tag %MIRROR_IMAGE% %BASE_IMAGE%
if errorlevel 1 goto :pull_fail
:base_ok
echo [OK] %BASE_IMAGE% present

rem 2) backend\requirements.txt from pyproject.toml, without TeleMetryParser and gpcan
powershell -NoP -C "$ErrorActionPreference='Stop'; $t=[IO.File]::ReadAllText($env:PYPROJECT); $m=[regex]::Match($t, '(?s)\ndependencies = \[(.*?)\n\]'); if(-not $m.Success){ throw 'dependencies = [...] not found in pyproject.toml' }; $deps=@([regex]::Matches($m.Groups[1].Value, '\x22([^\x22]+)\x22') | ForEach-Object { $_.Groups[1].Value } | Where-Object { $_ -notmatch '^(?i)(telemetryparser|gpcan)\b' }); if($deps.Count -eq 0){ throw 'no dependencies found' }; [IO.File]::WriteAllLines((Join-Path $env:CTX 'requirements.txt'), [string[]]$deps); Write-Output ('[INFO] {0} dependencies -> backend\requirements.txt' -f $deps.Count)"
if errorlevel 1 (
    echo [ERROR] generating requirements.txt failed
    pause
    exit /b 1
)

rem 3) build; --provenance=false: no build-time attestation, so an unchanged build keeps the same image id
echo [INFO] docker build -t %SHELL_IMAGE%
docker build --provenance=false -t %SHELL_IMAGE% "%CTX%"
set "RC=%errorlevel%"
del /q "%CTX%\requirements.txt" >nul 2>nul
if not "%RC%"=="0" (
    echo [ERROR] docker build failed
    pause
    exit /b 1
)
docker run --rm --entrypoint python %SHELL_IMAGE% -c "import sys, fastapi, sqlalchemy, redis; print('[OK] python', sys.version.split()[0], 'fastapi', fastapi.__version__)"
if errorlevel 1 (
    echo [ERROR] %SHELL_IMAGE% built but its python check failed
    pause
    exit /b 1
)
echo [OK] %SHELL_IMAGE% ready; docker_images_export.bat exports it with the other images
exit /b 0

:pull_fail
echo [ERROR] could not get %BASE_IMAGE%. Check network / Docker Desktop and retry.
pause
exit /b 1