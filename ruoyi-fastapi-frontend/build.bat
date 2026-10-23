@echo off
call "%~dp0..\scripts\build_front.bat" %*
exit /b %ERRORLEVEL%
