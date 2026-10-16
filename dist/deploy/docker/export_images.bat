@echo off
chcp 65001 >nul

cd /d "%~dp0"

docker save -o docker_image_nginx_redis_mysql.tar nginx:1.30-alpine mysql:8.0 redis:latest
