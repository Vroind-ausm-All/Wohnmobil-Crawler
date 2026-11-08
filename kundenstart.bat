@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title CampRCrawlR - Einrichtung und Start
set "NUR_EINRICHTEN="
for %%A in (%*) do if /i "%%~A"=="-NurEinrichten" set "NUR_EINRICHTEN=1"
where powershell.exe >nul 2>nul
if errorlevel 1 (
  echo [FEHLER] Windows PowerShell fehlt. Bitte Windows aktualisieren oder Python 3.13 manuell installieren und app.bat starten.
  set "RC=1"
  goto ende
)
rem RemoteSigned gilt nur fuer diesen Prozess. Keine dauerhafte Richtlinienaenderung.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0kundenstart.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo Falls Windows die Skriptausfuehrung blockiert:
  echo Rechtsklick auf die vertrauenswuerdige ZIP - Eigenschaften - Zulassen, dann erneut entpacken.
  echo Unternehmensrichtlinien bitte durch die IT pruefen lassen. Keine Schutzpruefungen deaktivieren.
  echo Alternativ Python 3.13 installieren und app.bat starten. Details: docs\KUNDENINSTALLATION.md
)
:ende
if not "%RC%"=="0" if not defined NUR_EINRICHTEN pause
endlocal & exit /b %RC%
