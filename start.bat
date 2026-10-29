@echo off
rem Power Widget launcher. Double-click to set up (first run) and start.
rem Runs as administrator: reading CPU power needs it.
setlocal
cd /d "%~dp0"
title Power Widget

fltmc >nul 2>&1
if errorlevel 1 (
    echo Administratorrechte werden benoetigt, um die CPU-Leistung zu messen.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "VENV=%~dp0.venv"
set "PY=%VENV%\Scripts\python.exe"
set "PYW=%VENV%\Scripts\pythonw.exe"
set "TASK=PowerWidget"
set "OLDTASK=PowerWidget Logger"

if exist "%PY%" goto checkdeps

echo Erster Start: Power Widget wird eingerichtet. Das dauert ein bis zwei Minuten.
echo.
set "BASEPY="
where py >nul 2>nul && set "BASEPY=py -3"
if not defined BASEPY where python >nul 2>nul && set "BASEPY=python"
if not defined BASEPY (
    echo Python wurde nicht gefunden. Bitte Python 3.11 oder neuer von https://www.python.org/downloads/
    echo installieren und dabei "Add python.exe to PATH" ankreuzen. Danach diese Datei erneut starten.
    pause
    exit /b 1
)
%BASEPY% -c "import sys; sys.exit(sys.version_info < (3, 11))"
if errorlevel 1 (
    echo Python 3.11 oder neuer wird benoetigt. Bitte Python aktualisieren und diese Datei erneut starten.
    pause
    exit /b 1
)
%BASEPY% -m venv "%VENV%" || goto setupfail

:checkdeps
rem (Re)install when pyproject.toml changed, e.g. after an update added dependencies.
fc /b pyproject.toml "%VENV%\installed-pyproject.toml" >nul 2>nul && goto checkdriver
echo Pakete werden installiert...
"%PY%" -m pip install --quiet --upgrade pip
"%PY%" -m pip install --quiet -e ".[nvidia]" || goto setupfail
copy /y pyproject.toml "%VENV%\installed-pyproject.toml" >nul
echo Fertig.
echo.

:checkdriver
reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO" >nul 2>&1 && goto menu
reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO" >nul 2>&1 && goto menu
echo Fuer echte CPU-Messwerte fehlt noch der kleine Treiber PawnIO (einmalige Installation,
echo signierter Treiber, wird auch von LibreHardwareMonitor und FanControl benutzt).
choice /c JN /n /m "Jetzt installieren? [J/N] "
if errorlevel 2 goto menu
call :installdriver
echo.

:menu
echo ==============================================
echo   Power Widget
echo ==============================================
echo   1  Widget oeffnen (zeichnet auch auf)
echo   2  Aktuelle Leistung hier anzeigen
echo   3  Verbrauch der letzten Tage (kWh)
echo   4  Pruefen, welche Sensoren funktionieren
echo   5  Widget bei Windows-Anmeldung automatisch starten
echo   6  Automatischen Start wieder entfernen
echo   7  Treiber PawnIO installieren
echo   0  Beenden
echo.
choice /c 12345670 /n /m "Auswahl 1-7 oder 0: "
set "SEL=%errorlevel%"
echo.
if "%SEL%"=="1" goto widget
if "%SEL%"=="2" goto live
if "%SEL%"=="3" goto stats
if "%SEL%"=="4" goto probe
if "%SEL%"=="5" goto autostart
if "%SEL%"=="6" goto noautostart
if "%SEL%"=="7" goto driver
exit /b 0

:widget
start "" "%PYW%" -m powerwidget widget
echo Das Widget wurde gestartet. Doppelklick darauf zeigt Verlauf und Diagramme,
echo Rechtsklick oeffnet das Menue.
echo.
goto menu

:live
echo Mit Strg+C beenden, danach N fuer zurueck zum Menue.
"%PY%" -m powerwidget now --watch
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
schtasks /Delete /F /TN "%OLDTASK%" >nul 2>nul
schtasks /Create /F /TN "%TASK%" /SC ONLOGON /RL HIGHEST /TR "\"%PYW%\" -m powerwidget widget" >nul
if errorlevel 1 (
    echo Der automatische Start konnte nicht eingerichtet werden.
) else (
    echo Das Widget startet jetzt bei jeder Anmeldung automatisch, mit Administratorrechten
    echo und ohne Rueckfrage.
)
echo.
goto menu

:noautostart
schtasks /Delete /F /TN "%OLDTASK%" >nul 2>nul
schtasks /Delete /F /TN "%TASK%" >nul 2>nul && echo Automatischer Start entfernt. || echo Automatischer Start war nicht eingerichtet.
echo.
goto menu

:driver
call :installdriver
echo.
goto menu

:installdriver
where winget >nul 2>nul
if errorlevel 1 (
    echo winget wurde nicht gefunden. Bitte PawnIO von https://pawnio.eu laden und installieren.
    exit /b 1
)
winget install --id namazso.PawnIO --exact --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo Die Installation von PawnIO hat nicht geklappt. Alternativ von https://pawnio.eu laden.
) else (
    echo PawnIO ist installiert. Bitte das Widget neu starten.
)
exit /b 0

:setupfail
echo.
echo Einrichtung fehlgeschlagen. Bitte Internetverbindung pruefen und diese Datei erneut starten.
rmdir /s /q "%VENV%" 2>nul
pause
exit /b 1
