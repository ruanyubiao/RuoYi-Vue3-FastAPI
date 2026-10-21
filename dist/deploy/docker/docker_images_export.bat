@echo off
chcp 65001 >nul

cd /d "%~dp0"

rem one image list, record digests + SHA256 of the .tar.gz in images.txt.
rem Tags are kept equal to the compose.yml files in PGT.zip (nginx:1.30-alpine, mysql:8.0, redis:8.2; redis 8.2 = Extended release line, supported until 2030-09-01; tag tracks latest 8.2.x patch, exact digest goes to images.txt).
rem To pin exact versions, change IMAGES here AND the three compose.yml AND README together, then re-export.
set "IMAGES=nginx:1.30-alpine mysql:8.0 redis:8.2"
rem local-built images: always rebuilt by backend\docker_image_backend_build.bat before export, never pulled
set "LOCAL_IMAGES=backend-py313slim:3.13"

rem gzip.exe must sit next to this script (note: variable is not named GZIP, gzip reads GZIP as options)
set "GZEXE=%~dp0gzip.exe"
if not exist "%GZEXE%" (
    echo [ERROR] gzip.exe not found next to this script: "%GZEXE%"
    pause
    exit /b 1
)

rem each pinned image: use the local copy if present, otherwise pull; a failed pull stops the export
for %%i in (%IMAGES%) do (
    docker image inspect %%i >nul 2>&1
    if errorlevel 1 (
        echo [INFO] %%i not found locally, pulling...
        docker pull %%i
        if errorlevel 1 (
            echo [ERROR] docker pull %%i failed. Nothing was exported. Check network / Docker Desktop and retry.
            pause
            exit /b 1
        )
    ) else (
        echo [OK] %%i present locally
    )
)

rem always rebuild so the image matches current pyproject.toml dependencies (docker layer cache keeps it fast when unchanged)
echo [INFO] building backend image with backend\docker_image_backend_build.bat...
call "%~dp0backend\docker_image_backend_build.bat"
if errorlevel 1 (
    echo [ERROR] building backend image failed. Nothing was exported.
    exit /b 1
)
for %%i in (%LOCAL_IMAGES%) do (
    docker image inspect %%i >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] %%i missing after build. Nothing was exported.
        pause
        exit /b 1
    )
)

set "OUT=docker_image_pgt.tar.gz"
set "TMPTAR=docker_image_pgt.tar"
rem gzip -n: no name and a zero time in the .gz header, so the same tar gives the same .gz
rem save to a plain tar first (binary-safe in cmd), then compress it; gzip replaces .tar with .tar.gz
if exist "%TMPTAR%" del /f /q "%TMPTAR%"
docker save -o "%TMPTAR%" %IMAGES% %LOCAL_IMAGES%
if errorlevel 1 (
    echo [ERROR] docker save failed. Nothing was exported.
    if exist "%TMPTAR%" del /f /q "%TMPTAR%"
    pause
    exit /b 1
)
rem docker save lists the images in a random order; sort them so the same images give the same file
powershell -NoP -ExecutionPolicy Bypass -File "%~dp0docker_tar_sort.ps1" "%TMPTAR%"
if errorlevel 1 (
    echo [ERROR] sorting the image lists in %TMPTAR% failed. Nothing was exported.
    if exist "%TMPTAR%" del /f /q "%TMPTAR%"
    pause
    exit /b 1
)
"%GZEXE%" -n -f "%TMPTAR%"
if errorlevel 1 goto :gzfail
if not exist "%OUT%" goto :gzfail
"%GZEXE%" -t "%OUT%"
if errorlevel 1 goto :gzfail
if exist "%TMPTAR%" del /f /q "%TMPTAR%"
(for %%i in (%IMAGES% %LOCAL_IMAGES%) do @docker image inspect --format "%%i {{if .RepoDigests}}{{index .RepoDigests 0}}{{else}}local-build{{end}} {{.Id}}" %%i) > images.txt
echo %OUT% SHA256:>> images.txt
certutil -hashfile "%OUT%" SHA256 | findstr /v ":" >> images.txt
type images.txt
echo [OK] exported %OUT%
exit /b 0

:gzfail
echo [ERROR] gzip compression failed; the uncompressed "%TMPTAR%" (if present) was left for inspection.
if exist "%OUT%" del /f /q "%OUT%"
pause
exit /b 1
