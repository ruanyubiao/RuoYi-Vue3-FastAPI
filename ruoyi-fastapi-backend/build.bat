@echo off
call "%~dp0..\scripts\build_backend.bat" %*
exit /b %ERRORLEVEL%
