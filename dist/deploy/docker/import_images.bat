@echo off
chcp 65001 >nul

cd /d "%~dp0"

docker load -i docker_image_nginx_redis_mysql.tar
