@echo off
chcp 65001 >nul

setlocal

cd /d "%~dp0"
set "ScriptPath=%cd%"

echo.
echo Running backend tests...
cd /d "%ScriptPath%\ruoyi-fastapi-backend"
venv\Scripts\pytest.exe
if errorlevel 1 exit /b %errorlevel%

echo.
echo Running frontend tests...
cd /d "%ScriptPath%\ruoyi-fastapi-frontend"
call npm run test:run
if errorlevel 1 exit /b %errorlevel%

echo.
echo Running playwright e2e tests...
cd /d "%ScriptPath%\ruoyi-fastapi-test"
call .\run_test.bat
if errorlevel 1 exit /b %errorlevel%

cd /d "%ScriptPath%"
endlocal
