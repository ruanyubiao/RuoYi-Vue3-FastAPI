@echo off
chcp 65001 >nul
cd /d "%~dp0"


start install_frontend.bat
start install_backend.bat
