#!/usr/bin/env sh
# Wohnmobil-Scout starten (macOS/Linux). Richtet beim ersten Mal automatisch .venv ein.
cd "$(dirname "$0")" || exit 1
./installieren.sh || exit 1
exec .venv/bin/python scout.py app "$@"
