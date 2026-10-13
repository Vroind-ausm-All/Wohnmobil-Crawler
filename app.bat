@echo off
rem Wohnmobil-Scout starten: Doppelklick genuegt.
rem Beim ersten Start wird automatisch eine eigene Python-Umgebung (.venv) eingerichtet.
setlocal
cd /d "%~dp0"
title Wohnmobil-Scout

call "%~dp0installieren.bat" /still
if errorlevel 1 goto ende

echo.
echo Wohnmobil-Scout startet, der Browser oeffnet sich gleich.
echo Dieses Fenster bitte offen lassen. Beenden: Fenster schliessen oder Strg+C.
echo.
"%~dp0.venv\Scripts\python.exe" scout.py app

:ende
echo.
pause
