@echo off
chcp 65001 >nul

cd /d "%~dp0"

rem accepts the compressed image (preferred) or a plain tar; docker load reads .tar.gz directly
set "IMG="
if exist "docker_image_nginx_redis_mysql.tar.gz" (set "IMG=docker_image_nginx_redis_mysql.tar.gz") else if exist "docker_image_nginx_redis_mysql.tar" (set "IMG=docker_image_nginx_redis_mysql.tar")
if not defined IMG (
    echo [ERROR] docker_image_nginx_redis_mysql.tar.gz / .tar not found in "%~dp0"
    pause
    exit /b 1
)
echo [INFO] docker load -i %IMG%
docker load -i "%IMG%"
if errorlevel 1 (
    echo [ERROR] docker load failed
    pause
    exit /b 1
)
