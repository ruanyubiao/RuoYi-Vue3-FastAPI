@echo off
setlocal EnableDelayedExpansion
REM ���ļ�Ϊ GBK ���루cmd Ĭ�ϴ���ҳ 936������Ҫ�ĳ� UTF-8���������� REM �лᱻ cmd �����
REM Ӳ���ڻ�������ڣ���ͷ����� + Ӳ��ģ���������ػ������⣩= 192.168.100.52�����Ի���������= ���б��ű��ĵ���
REM �÷���
REM   run_hil.bat unit                     �����Բ⣨�������ػ�������Ӳ����
REM   run_hil.bat ui                       ��ͷ��ҳð�̣�ֻ����
REM   run_hil.bat can [biu^|xl^|yj216]      CAN��ʡ��=�����п�ʱ --auto ���� biu/xl/yj216 ȫ��
REM   run_hil.bat serial [�豸��]           ���ڣ�ʡ��=������ COM ʱ --auto ����ȫ��Э���
REM   run_hil.bat udp                      �ؼ�� UDP�������ܰ���Զ˿���Ĭ�����ã�HIL_UDP_ENABLE=0 �ɹأ�
REM   run_hil.bat round can^|serial [�豸...] �����ֲ⣺�����ʾ������� XXX �󰴻س���
REM   run_hil.bat plan                     ֻ�г� CAN/����/UDP ��Ŀ���»� RUN/SKIP ������������Ӳ��
REM   run_hil.bat all                      unit+ui+CANȫ��+����ȫ��+UDP��̽�ⲻ���� skip��ͬʱ���Ŀ¼��
REM   ֮��Ĳ���ԭ��͸���� pytest���� run_hil.bat ui -k index
REM Ӳ������Ĭ��ֵ�� hil.local.json���ɱ� HIL_* �����������ǣ���˵���� README��
cd /d %~dp0
set PYTHONPATH=%~dp0;%PYTHONPATH%

REM ---------- ��ʽ����������ȡ��ע�ͣ�----------
REM set HIL_FRONTEND_URL=http://192.168.100.52:12580
REM set HIL_USERNAME=admin
REM set HIL_PASSWORD=admin123
REM set HIL_HEADED=1
REM set HIL_SLOW_MO_MS=200
REM ---------- Ӳ������ʾ����Ĭ�ϼ� hil.local.json��----------
REM set HIL_CAN_VENDOR=2
REM set HIL_IPC_CAN_VENDOR=3
REM set HIL_SERIAL_PORT=COM9
REM set HIL_IPC_SERIAL_PORT=COM8
REM set HIL_TEST_PC_IP=192.168.100.10

REM ---------- �����������Ŀ¼������ʼʱ����һ��ʱ��������з��鹲�� ----------
if "%HIL_RUN_DIR%"=="" (
  for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set HIL_TS=%%i
  set "HIL_RUN_DIR=%~dp0artifacts\!HIL_TS!"
)
if not exist "%HIL_RUN_DIR%" mkdir "%HIL_RUN_DIR%"
echo [HIL] �������Ŀ¼: %HIL_RUN_DIR%

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
REM �� SKIPN ������֮���ȫ����Ϊ���� pytest ����
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
  call :run_group unit
  call :run_group ui
  call :run_auto can
  call :run_auto serial
  if not defined HIL_UDP_ENABLE set HIL_UDP_ENABLE=1
  call :run_group udp
  goto :done
)
if /i "%SUITE%"=="can" if "%TARGET%"=="" (
  call :run_auto can
  goto :done
)
if /i "%SUITE%"=="serial" if "%TARGET%"=="" (
  call :run_auto serial
  goto :done
)
if /i "%SUITE%"=="udp" if not defined HIL_UDP_ENABLE set HIL_UDP_ENABLE=1
call :run_group %SUITE% %TARGET%

:done
echo.
echo [HIL] �������Ŀ¼: %HIL_RUN_DIR%
REM summary.txt Ϊ UTF-8���� python ��ӡ���� GBK ����̨����
if exist "%HIL_RUN_DIR%\summary.txt" python -c "import sys;print(open(sys.argv[1],encoding='utf-8').read())" "%HIL_RUN_DIR%\summary.txt"
echo.
echo [HIL] 填写测试清单报告...
python -m hil.report sync
python -m hil.report fill "%HIL_RUN_DIR%"
echo [HIL] 报告: %HIL_RUN_DIR%\PGT测试清单_填写.xlsx
endlocal & exit /b %RC%

:run_auto
REM �ǽ���ȫ���ֲ⣺python -m hil.round <can|serial> --auto��ÿ��Э�鵥�����飬ͬ HIL_RUN_DIR��
set KIND=%1
echo.
echo ===================== [HIL] �Զ��ֲ� %KIND%��ȫ��Э�飩 =====================
python -m hil.round %KIND% --auto %EXTRA%
set GRC=%ERRORLEVEL%
if not "%GRC%"=="0" if not "%GRC%"=="5" set RC=%GRC%
goto :eof

:run_group
set G=%1
set T=%2
if /i "%G%"=="udp" if not defined HIL_UDP_ENABLE set HIL_UDP_ENABLE=1
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
echo ===================== [HIL] ���� %GN% =====================
python -m pytest %MARK% -v -s %REPORT% %EXTRA%
set GRC=%ERRORLEVEL%
REM �˳��� 5 = �÷���û���ռ�������������ʧ��
if not "%GRC%"=="0" if not "%GRC%"=="5" set RC=%GRC%
set HIL_GROUP=
goto :eof
