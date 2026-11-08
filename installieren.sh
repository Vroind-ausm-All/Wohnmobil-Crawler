#!/usr/bin/env sh
# Wohnmobil-Scout – Python-Umgebung (.venv) für macOS/Linux einrichten (Gegenstück zu installieren.bat).
# Nur Python 3.13 (F9, P1-10), installiert nur fertige Pakete aus der gesperrten requirements.txt.
# Aufruf: ./installieren.sh [--neu]    Rückgabe: 0 = bereit, 1 = Fehler
set -u
cd "$(dirname "$0")" || exit 1
VENV_PY=".venv/bin/python"
STEMPEL=".venv/requirements.installiert"
VERSION_OK='import sys; sys.exit(0 if sys.version_info[:2] == (3, 13) else 1)'

if [ "${1:-}" = "--neu" ] && [ -d .venv ]; then echo "Umgebung .venv wird neu angelegt ..."; rm -rf .venv; fi
if [ -x "$VENV_PY" ] && ! "$VENV_PY" -c "$VERSION_OK" 2>/dev/null; then
  echo "Die vorhandene Umgebung .venv passt nicht (falsche Python-Version) – wird neu angelegt ..."
  rm -rf .venv
fi

if [ ! -x "$VENV_PY" ]; then
  BASIS=""
  for kandidat in python3.13 python3; do
    if command -v "$kandidat" >/dev/null 2>&1 && "$kandidat" -c "$VERSION_OK" 2>/dev/null; then BASIS="$kandidat"; break; fi
  done
  if [ -z "$BASIS" ]; then
    echo "Python 3.13 wurde nicht gefunden (ältere Versionen werden nicht unterstützt, 3.14+ noch nicht)."
    echo "macOS: https://www.python.org/downloads/macos/ oder 'brew install python@3.13'"
    echo "Linux: Paket python3.13 (inkl. python3.13-venv) über die Paketverwaltung installieren."
    exit 1
  fi
  echo "$($BASIS --version) gefunden – lege die Umgebung .venv an ..."
  "$BASIS" -m venv .venv || { echo "[FEHLER] .venv konnte nicht angelegt werden (fehlt python3-venv?)."; rm -rf .venv; exit 1; }
fi

if ! cmp -s requirements.txt "$STEMPEL" || ! "$VENV_PY" -c "import requests, bs4, yaml, jinja2" 2>/dev/null; then
  echo "Zusatzpakete werden in .venv installiert ..."
  if ! "$VENV_PY" -m pip install --disable-pip-version-check --no-input --only-binary=:all: -r requirements.txt; then
    echo "[FEHLER] Installation fehlgeschlagen – Internetverbindung prüfen, danach ./installieren.sh --neu"
    exit 1
  fi
  cp requirements.txt "$STEMPEL"
fi
echo "Python-Umgebung bereit: $("$VENV_PY" --version)"
