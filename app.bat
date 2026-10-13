@echo off
rem Wohnmobil-Scout starten: Doppelklick genuegt.
rem Beim ersten Start werden die Zusatzpakete automatisch installiert.
cd /d "%~dp0"
title Wohnmobil-Scout

if not exist "scout.py" (
  echo Die Datei scout.py fehlt in diesem Ordner.
  echo Bitte die ZIP-Datei zuerst entpacken: Rechtsklick auf die ZIP, "Alle extrahieren",
  echo und dann app.bat im entpackten Ordner starten.
  goto ende
)

rem Python suchen: zuerst den Python-Launcher "py", sonst "python"
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python wurde nicht gefunden.
  echo Bitte Python von python.org installieren und dabei unten den Haken
  echo "Add python.exe to PATH" setzen. Danach app.bat erneut starten.
  goto ende
)

%PY% -c "import requests, bs4, yaml, jinja2" >nul 2>nul
if errorlevel 1 (
  echo Erster Start: Zusatzpakete werden installiert, bitte kurz warten ...
  %PY% -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo Die Installation hat nicht geklappt. Bitte Internetverbindung pruefen
    echo und kontrollieren, ob Python mit dem Haken "Add python.exe to PATH" installiert ist.
    goto ende
  )
)

echo.
echo Wohnmobil-Scout startet, der Browser oeffnet sich gleich.
echo Dieses Fenster bitte offen lassen. Beenden: Fenster schliessen oder Strg+C.
echo.
%PY% scout.py app

:ende
echo.
pause
