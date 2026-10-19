@echo off
rem ======================================================================
rem  Wohnmobil-Scout - Python-Umgebung einrichten
rem
rem  Legt im Projektordner eine eigene Python-Umgebung (.venv) an und
rem  installiert dort die Zusatzpakete aus requirements.txt.
rem  Globale Python-Installationen und andere Projekte bleiben unberuehrt.
rem
rem  Bevorzugt wird Python 3.13 (danach 3.12, 3.11, 3.10). Neuere Versionen
rem  wie 3.14/3.15 werden bewusst nicht verwendet: Fuer sie gibt es noch nicht
rem  alle Pakete fertig fuer Windows (PyYAML muesste dann kompiliert werden).
rem
rem  Aufruf: Doppelklick (mit Pause am Ende) oder von app.bat/lauf.bat
rem  mit "/still" (ohne Pause). Rueckgabe: 0 = alles bereit, 1 = Fehler.
rem  Komplett neu einrichten: installieren.bat /neu
rem ======================================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "STILL="
set "NEU="
for %%A in (%*) do (
  if /i "%%~A"=="/still" set "STILL=1"
  if /i "%%~A"=="/neu" set "NEU=1"
)
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "STEMPEL=%~dp0.venv\requirements.installiert"
set "VERSION_OK=import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) else 1)"

if not exist "scout.py" (
  echo [FEHLER] scout.py fehlt in diesem Ordner.
  echo Bitte die ZIP-Datei zuerst entpacken: Rechtsklick auf die ZIP, "Alle extrahieren",
  echo und dann app.bat im entpackten Ordner starten.
  goto fehler
)

rem --- 1. Vorhandene Umgebung pruefen -----------------------------------
if defined NEU if exist ".venv" (
  echo Umgebung .venv wird neu angelegt ...
  rmdir /s /q ".venv"
)
if exist "%VENV_PY%" (
  "%VENV_PY%" -c "%VERSION_OK%" >nul 2>nul
  if errorlevel 1 (
    echo Die vorhandene Umgebung .venv passt nicht ^(falsche Python-Version oder Python wurde entfernt^).
    echo Sie wird mit einer passenden Version neu angelegt ...
    rmdir /s /q ".venv"
  )
)

rem --- 2. Umgebung anlegen -----------------------------------------------
if not exist "%VENV_PY%" (
  call :venv_anlegen
  if errorlevel 1 goto fehler
)

rem --- 3. Pakete installieren (nur wenn noetig) ---------------------------
fc /b "requirements.txt" "%STEMPEL%" >nul 2>nul
if errorlevel 1 goto pakete
"%VENV_PY%" -c "import requests, bs4, yaml, jinja2" >nul 2>nul
if errorlevel 1 goto pakete
goto fertig

:pakete
echo.
echo Zusatzpakete werden in .venv installiert, das dauert beim ersten Mal 1-2 Minuten ...
rem --only-binary: nur fertige Pakete, niemals kompilieren (kein Visual C++ noetig)
"%VENV_PY%" -m pip install --disable-pip-version-check --no-input --only-binary=:all: -r requirements.txt
if errorlevel 1 (
  echo.
  echo [FEHLER] Die Zusatzpakete konnten nicht installiert werden.
  echo  - Besteht eine Internetverbindung? Blockiert eine Firewall oder ein Proxy pypi.org?
  echo  - Die Meldungen oberhalb zeigen, welches Paket betroffen ist.
  echo  - Danach erneut starten. Hilft das nicht: installieren.bat /neu
  goto fehler
)
"%VENV_PY%" -c "import requests, bs4, yaml, jinja2" >nul 2>nul
if errorlevel 1 (
  echo [FEHLER] Installation gemeldet, aber die Pakete lassen sich nicht laden.
  echo Bitte installieren.bat /neu ausfuehren.
  goto fehler
)
copy /y "requirements.txt" "%STEMPEL%" >nul

:fertig
if defined STILL goto erfolg
echo.
echo Fertig: Die Python-Umgebung ist eingerichtet.
"%VENV_PY%" --version
echo Starten mit Doppelklick auf app.bat
echo.
pause
:erfolg
endlocal & exit /b 0

:fehler
if not defined STILL (
  echo.
  pause
)
endlocal & exit /b 1


rem ======================================================================
:venv_anlegen
set "BASIS="
rem Python-Launcher "py": gezielt nach 3.13, dann 3.12, 3.11, 3.10 fragen.
rem Vorher in der Versionsliste nachsehen - der neue Python Install Manager
rem wuerde bei einer fehlenden Version sonst unsichtbar nach Installation fragen.
for %%V in (3.13 3.12 3.11 3.10) do (
  if not defined BASIS (
    call :launcher_kennt %%V && py -%%V -c "%VERSION_OK%" >nul 2>nul && set "BASIS=py -%%V"
  )
)
rem Ohne Launcher: "python" aus dem PATH, falls die Version passt
if not defined BASIS (
  python -c "%VERSION_OK%" >nul 2>nul && set "BASIS=python"
)
if not defined BASIS (
  call :anleitung
  exit /b 1
)
for /f "tokens=2" %%I in ('%BASIS% --version 2^>^&1') do set "GEFUNDEN=%%I"
echo Python %GEFUNDEN% gefunden - lege die Umgebung .venv im Projektordner an ...
%BASIS% -m venv ".venv"
if errorlevel 1 (
  echo [FEHLER] Die Umgebung .venv konnte nicht angelegt werden.
  echo Liegt der Projektordner an einem Ort mit Schreibrechten, z. B. unter Dokumente?
  if exist ".venv" rmdir /s /q ".venv"
  exit /b 1
)
if not exist "%VENV_PY%" (
  echo [FEHLER] .venv wurde angelegt, aber .venv\Scripts\python.exe fehlt.
  exit /b 1
)
exit /b 0


rem ======================================================================
:launcher_kennt
rem %1 = Version, z. B. 3.13 - fragt nur die Liste ab, installiert nichts
py --list 2>nul | findstr /c:"%~1" >nul 2>nul && exit /b 0
py list 2>nul | findstr /c:"%~1" >nul 2>nul && exit /b 0
exit /b 1


rem ======================================================================
:anleitung
echo.
echo ======================================================================
echo  Python 3.13 wird benoetigt, ist aber nicht installiert.
echo ======================================================================
echo.
echo  Gefundene Python-Versionen auf diesem PC:
py --list 2>nul || echo    ^(keine ueber den Python-Launcher gefunden^)
python --version 2>nul
echo.
echo  Wohnmobil-Scout braucht Python 3.13 ^(3.10 bis 3.12 gehen auch^).
echo  Neuere Versionen wie 3.14 oder 3.15 funktionieren noch nicht, weil
echo  dafuer nicht alle Pakete fertig fuer Windows verfuegbar sind.
echo.
echo  So installierst du Python 3.13 - zusaetzlich, deine anderen
echo  Python-Versionen und Projekte bleiben unveraendert:
echo.
echo   1. Im Browser oeffnen: https://www.python.org/downloads/windows/
echo   2. Unter "Stable Releases" den neuesten Eintrag "Python 3.13.x" suchen
echo      und "Windows installer (64-bit)" herunterladen.
echo   3. Installer starten, "Install Now" klicken.
echo      Den Haken "Add python.exe to PATH" brauchst du NICHT zu setzen.
echo   4. Danach app.bat erneut per Doppelklick starten.
echo.
echo  Alternativen in der Eingabeaufforderung:
echo     py install 3.13                        ^(wenn der Python Install Manager vorhanden ist^)
echo     winget install Python.Python.3.13
echo.
exit /b 0
