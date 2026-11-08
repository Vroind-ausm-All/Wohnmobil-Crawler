# CampRCrawlR: Python 3.13 und Projektumgebung einrichten, danach die App starten.
# Ausfuehrung nur lokal; keine heruntergeladenen Skripte oder globalen pip-Pakete.
[CmdletBinding()]
param([switch]$NurEinrichten)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

function Test-Python313 {
    param([string]$Programm, [string[]]$Argumente = @())
    try {
        & $Programm @Argumente -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 13) else 1)' 1>$null 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-Python313 {
    # Eine funktionierende Projektumgebung benoetigt keine weitere Python-Installation.
    $venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if ((Test-Path -LiteralPath $venvPython -PathType Leaf) -and (Test-Python313 $venvPython)) {
        return [pscustomobject]@{ Programm = $venvPython; Argumente = @(); Projektumgebung = $true }
    }
    $launcher = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($launcher) {
        # Der neue Python Install Manager darf beim reinen Pruefen nichts installieren.
        $bekannt = ''
        try { $bekannt = (& $launcher.Source --list 2>$null) -join "`n" } catch { }
        if ($bekannt -notmatch '3[.]13(?:[^0-9]|$)') {
            try { $bekannt = (& $launcher.Source list 2>$null) -join "`n" } catch { }
        }
        if (($bekannt -match '3[.]13(?:[^0-9]|$)') -and (Test-Python313 $launcher.Source @('-3.13'))) {
            return [pscustomobject]@{ Programm = $launcher.Source; Argumente = @('-3.13'); Projektumgebung = $false }
        }
    }
    $python = Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    # WindowsApps-Aliase koennen den Store oeffnen; sie sind kein nachgewiesener Interpreter.
    if ($python -and $python.Source -notmatch '\\WindowsApps\\' -and (Test-Python313 $python.Source)) {
        return [pscustomobject]@{ Programm = $python.Source; Argumente = @(); Projektumgebung = $false }
    }
    # Ein gerade installiertes Python muss ohne dauerhafte PATH-Aenderung gefunden werden.
    $kandidaten = @()
    if ($env:LOCALAPPDATA) { $kandidaten += Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe' }
    if ($env:ProgramFiles) { $kandidaten += Join-Path $env:ProgramFiles 'Python313\python.exe' }
    foreach ($pfad in $kandidaten) {
        if ((Test-Path -LiteralPath $pfad -PathType Leaf) -and (Test-Python313 $pfad)) {
            return [pscustomobject]@{ Programm = $pfad; Argumente = @(); Projektumgebung = $false }
        }
    }
    return $null
}

try {
    if ($env:OS -ne 'Windows_NT') { throw 'Dieser Kundenstart ist fuer Windows. Unter Linux/macOS: ./start.sh' }
    Set-Location -LiteralPath $PSScriptRoot
    foreach ($datei in @('scout.py', 'installieren.bat', 'app.bat', 'requirements.txt')) {
        if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $datei) -PathType Leaf)) {
            throw "Projektdatei $datei fehlt. Bitte die vollstaendige ZIP zuerst mit 'Alle extrahieren' entpacken."
        }
    }
    $python313 = Find-Python313
    if (-not $python313) {
        if ($env:CI) { throw 'CI: Python 3.13 zuerst mit actions/setup-python bereitstellen. Kein interaktiver Installer in CI.' }
        $winget = Get-Command winget.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $winget) {
            throw ('Python 3.13 und winget fehlen. Bitte Python 3.13.x von https://www.python.org/downloads/windows/ ' +
                   'mit Python-Launcher installieren und kundenstart.bat erneut starten. Alternativ den Microsoft App Installer aktualisieren.')
        }
        Write-Host 'Python 3.13 wird ueber das offizielle winget-Paket Python.Python.3.13 fuer diesen Benutzer installiert.'
        Write-Host 'Vorhandene andere Python-Versionen werden nicht entfernt.'
        # Das offizielle Manifest setzt sonst PrependPath=1. Unterstuetzte Python-Installeroptionen
        # halten vorhandene Python-/Launcher-Zuordnungen und den dauerhaften PATH unveraendert.
        $installerOptionen = '/quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 AssociateFiles=0 Shortcuts=0'
        & $winget.Source install --id Python.Python.3.13 --exact --source winget --scope user --silent --disable-interactivity `
            --accept-package-agreements --accept-source-agreements --override $installerOptionen
        if ($LASTEXITCODE -ne 0) {
            throw ("Python-Installation fehlgeschlagen (winget-Code $LASTEXITCODE). Bitte die Meldung oben pruefen. " +
                   'Manuell: Python 3.13.x von https://www.python.org/downloads/windows/ installieren, dann Kundenstart erneut ausfuehren.')
        }
        $python313 = Find-Python313
        if (-not $python313) {
            throw ('Python 3.13 wurde noch nicht gefunden. Fenster schliessen und kundenstart.bat erneut starten. ' +
                   'Falls noetig Python 3.13.x samt Launcher von https://www.python.org/downloads/windows/ installieren.')
        }
    }
    $projektPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    $venvOrdner = Join-Path $PSScriptRoot '.venv'
    if ((Test-Path -LiteralPath $venvOrdner) -and -not (Test-Python313 $projektPython)) {
        throw ('Die vorhandene .venv ist unvollstaendig oder passt nicht zu Python 3.13. ' +
               'App beenden und den Ordner .venv zur Aufbewahrung umbenennen, dann erneut starten. Kundendaten bleiben unangetastet.')
    }
    if (-not (Test-Path -LiteralPath $venvOrdner)) {
        Write-Host 'Eigene Python-Umgebung im Projektordner wird angelegt ...'
        $programm = $python313.Programm
        $argumente = $python313.Argumente
        & $programm @argumente -m venv $venvOrdner
        if ($LASTEXITCODE -ne 0 -or -not (Test-Python313 $projektPython)) {
            throw 'Die lokale .venv konnte nicht angelegt werden. Schreibrechte und Python-Installation pruefen; keine Kundendaten loeschen.'
        }
    }
    Write-Host 'Projektabhaengigkeiten werden mit dem vorhandenen Installationsskript geprueft ...'
    & (Join-Path $PSScriptRoot 'installieren.bat') /still
    if ($LASTEXITCODE -ne 0) { throw 'Projektinstallation fehlgeschlagen. Die Meldung oben zeigt das betroffene Paket oder Zugriffsproblem.' }
    & $projektPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Die Projektabhaengigkeiten sind inkonsistent. Installation bitte pruefen.' }
    Write-Host 'CampRCrawlR ist eingerichtet. Daten und config.local.yaml wurden nicht ersetzt.'
    if ($NurEinrichten) { exit 0 }
    & (Join-Path $PSScriptRoot 'app.bat')
    exit $LASTEXITCODE
} catch {
    Write-Host ''
    Write-Host ('[FEHLER] ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'Weitere Hinweise: docs\KUNDENINSTALLATION.md'
    exit 1
}
