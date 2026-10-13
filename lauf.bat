@echo off
rem Suchlauf ohne Oberflaeche, z. B. fuer die Windows-Aufgabenplanung.
rem Verwendet - wie app.bat - die projekteigene Python-Umgebung .venv.
setlocal
cd /d "%~dp0"
call "%~dp0installieren.bat" /still
if errorlevel 1 exit /b 1
"%~dp0.venv\Scripts\python.exe" scout.py lauf
exit /b %errorlevel%
