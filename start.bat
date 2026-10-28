@echo off
rem Power Widget launcher. Double-click to set up (first run) and start.
setlocal
cd /d "%~dp0"
title Power Widget

set "VENV=%~dp0.venv"
set "PY=%VENV%\Scripts\python.exe"
set "PYW=%VENV%\Scripts\pythonw.exe"
set "TASK=PowerWidget Logger"

if exist "%PY%" goto menu

echo First start: setting up Power Widget. This takes a minute.
echo.
set "BASEPY="
where py >nul 2>nul && set "BASEPY=py -3"
if not defined BASEPY where python >nul 2>nul && set "BASEPY=python"
if not defined BASEPY (
    echo Python was not found. Install Python 3.11 or newer from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup. Then run this file again.
    pause
    exit /b 1
)
%BASEPY% -c "import sys; sys.exit(sys.version_info < (3, 11))"
if errorlevel 1 (
    echo Python 3.11 or newer is needed. Please update Python and run this file again.
    pause
    exit /b 1
)
%BASEPY% -m venv "%VENV%" || goto setupfail
"%PY%" -m pip install --quiet --upgrade pip
"%PY%" -m pip install --quiet -e ".[nvidia]" || goto setupfail
echo Setup done.
echo.

:menu
echo ==============================================
echo   Power Widget
echo ==============================================
echo   1  Show live power usage
echo   2  Start logging in the background
echo   3  Show usage history (kWh)
echo   4  Check which sensors work on this PC
echo   5  Start logging automatically at Windows logon
echo   6  Stop automatic logging at logon
echo   0  Exit
echo.
echo   Tip: start LibreHardwareMonitor as administrator with its
echo   Remote Web Server turned on for real CPU and GPU readings.
echo.
choice /c 1234560 /n /m "Choose 1-6 or 0: "
set "SEL=%errorlevel%"
echo.
if "%SEL%"=="1" goto live
if "%SEL%"=="2" goto log
if "%SEL%"=="3" goto stats
if "%SEL%"=="4" goto probe
if "%SEL%"=="5" goto autostart
if "%SEL%"=="6" goto noautostart
exit /b 0

:live
echo Press Ctrl+C to stop, then N to return to the menu.
"%PY%" -m powerwidget now --watch
goto menu

:log
start "Power Widget Logger" /min "%PY%" -m powerwidget log
echo Logger started in a minimized window. Close that window to stop logging.
echo.
goto menu

:stats
"%PY%" -m powerwidget stats
echo.
pause
goto menu

:probe
"%PY%" -m powerwidget probe
echo.
pause
goto menu

:autostart
schtasks /Create /F /TN "%TASK%" /SC ONLOGON /RL LIMITED /TR "\"%PYW%\" -m powerwidget log" >nul
if errorlevel 1 (
    echo Could not create the logon task.
) else (
    echo The logger will now start hidden every time you log on to Windows.
    schtasks /Run /TN "%TASK%" >nul && echo It is running now as well.
)
echo.
goto menu

:noautostart
schtasks /End /TN "%TASK%" >nul 2>nul
schtasks /Delete /F /TN "%TASK%" >nul 2>nul && echo Automatic logging removed. || echo Automatic logging was not set up.
echo.
goto menu

:setupfail
echo.
echo Setup failed. Check your internet connection and run this file again.
rmdir /s /q "%VENV%" 2>nul
pause
exit /b 1
