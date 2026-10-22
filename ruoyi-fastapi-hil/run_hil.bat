@echo off
setlocal EnableDelayedExpansion
REM 本文件为 GBK 编码（cmd 默认代码页 936），不要改成 UTF-8，否则中文 REM 行会被 cmd 误解析
REM 硬件在环验收入口：有头浏览器 + 硬件模拟器。工控机（被测）= 192.168.100.52；测试机（本机）= 运行本脚本的电脑
REM 用法：
REM   run_hil.bat unit                     本机自测（不连工控机、不开硬件）
REM   run_hil.bat ui                       有头逐页冒烟（只读）
REM   run_hil.bat can biu^|xl^|yj216        CAN 硬件在环，只测当前接入的那个设备（A/B 两路）
REM   run_hil.bat serial ^<设备键^>          串口硬件在环：xl-camera xl-camera-v17 xl-rkdj xl-zk xl-cpazx yj216-rs422
REM   run_hil.bat udp                      地检板 UDP（工控机:66 对接 测试机:99，测试机 IP 自动探测）
REM   run_hil.bat round can^|serial [设备...] 交互轮测：逐个提示「请接入 XXX 后按回车」，结果进同一目录
REM   run_hil.bat plan                     只列出 CAN/串口/UDP 各目标下会 RUN/SKIP 的用例，不碰硬件
REM   run_hil.bat all                      依次跑 unit ui can serial udp（默认）；没选目标的硬件分组全部 skip
REM   之后的参数原样透传给 pytest，如 run_hil.bat ui -k index
REM 硬件接线默认值在 hil.local.json（可被 HIL_* 环境变量覆盖），说明见 README。
cd /d %~dp0
set PYTHONPATH=%~dp0;%PYTHONPATH%

REM ---------- 正式环境（按需取消注释）----------
REM set HIL_FRONTEND_URL=http://192.168.100.52:12580
REM set HIL_USERNAME=admin
REM set HIL_PASSWORD=admin123
REM set HIL_HEADED=1
REM set HIL_SLOW_MO_MS=200
REM ---------- 硬件覆盖示例（默认见 hil.local.json）----------
REM set HIL_CAN_VENDOR=2
REM set HIL_IPC_CAN_VENDOR=3
REM set HIL_SERIAL_PORT=COM9
REM set HIL_IPC_SERIAL_PORT=COM8
REM set HIL_TEST_PC_IP=192.168.100.10

REM ---------- 本次任务输出目录：任务开始时生成一次时间戳，所有分组共用 ----------
if "%HIL_RUN_DIR%"=="" (
  for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set HIL_TS=%%i
  set "HIL_RUN_DIR=%~dp0artifacts\!HIL_TS!"
)
if not exist "%HIL_RUN_DIR%" mkdir "%HIL_RUN_DIR%"
echo [HIL] 本次输出目录: %HIL_RUN_DIR%

set SUITE=%~1
if "%SUITE%"=="" set SUITE=all
set TARGET=
set SKIPN=1
if /i "%SUITE%"=="can" set NEEDT=1
if /i "%SUITE%"=="serial" set NEEDT=1
if "%NEEDT%"=="1" (
  set "A2=%~2"
  if not "!A2!"=="" if not "!A2:~0,1!"=="-" (
    set "TARGET=!A2!"
    set SKIPN=2
  )
)
REM 第 SKIPN 个参数之后的全部作为额外 pytest 参数
set EXTRA=
set /a ARGN=0
for %%a in (%*) do (
  set /a ARGN+=1
  if !ARGN! GTR %SKIPN% set "EXTRA=!EXTRA! %%a"
)

set HTML=0
python -c "import pytest_html" 2>nul && set HTML=1

set RC=0
if /i "%SUITE%"=="round" (
  python -m hil.round %2 %3 %4 %5 %6 %7 %8 %9
  set RC=!ERRORLEVEL!
  goto :done
)
if /i "%SUITE%"=="plan" (
  python -m hil.round can --plan
  python -m hil.round serial --plan
  set HIL_UDP_ENABLE=1
  set HIL_GROUP=udp_plan
  python -m pytest -m hil_udp --hil-plan -q
  goto :done
)
if /i "%SUITE%"=="all" (
  for %%g in (unit ui can serial udp) do call :run_group %%g
) else (
  if /i "%SUITE%"=="udp" if not defined HIL_UDP_ENABLE set HIL_UDP_ENABLE=1
  call :run_group %SUITE% %TARGET%
)

:done
echo.
echo [HIL] 本次输出目录: %HIL_RUN_DIR%
REM summary.txt 为 UTF-8，用 python 打印避免 GBK 控制台乱码
if exist "%HIL_RUN_DIR%\summary.txt" python -c "import sys;print(open(sys.argv[1],encoding='utf-8').read())" "%HIL_RUN_DIR%\summary.txt"
endlocal & exit /b %RC%

:run_group
set G=%1
set T=%2
set MARK=
if /i "%G%"=="unit" set MARK=-m unit
if /i "%G%"=="ui" set MARK=-m ui_only
if /i "%G%"=="can" set MARK=-m hil_can
if /i "%G%"=="serial" set MARK=-m hil_serial
if /i "%G%"=="udp" set MARK=-m hil_udp
set GN=%G%
if not "%T%"=="" (
  set GN=%G%_%T%
  if /i "%G%"=="can" set HIL_CAN_TARGET=%T%
  if /i "%G%"=="serial" set HIL_SERIAL_TARGET=%T%
)
set HIL_GROUP=%GN%
set REPORT=--junitxml="%HIL_RUN_DIR%\junit_%GN%.xml" --log-file="%HIL_RUN_DIR%\pytest_%GN%.log" --log-file-level=INFO
if "%HTML%"=="1" set REPORT=%REPORT% --html="%HIL_RUN_DIR%\report_%GN%.html" --self-contained-html
echo.
echo ===================== [HIL] 分组 %GN% =====================
python -m pytest %MARK% -v -s %REPORT% %EXTRA%
set GRC=%ERRORLEVEL%
REM 退出码 5 = 该分组没有收集到用例，不算失败
if not "%GRC%"=="0" if not "%GRC%"=="5" set RC=%GRC%
set HIL_GROUP=
goto :eof
