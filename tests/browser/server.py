"""Isolierte App für Browser-Abnahme: keine Kundendaten und keine Netzwerkquellen."""
from pathlib import Path
import signal
import sys
import tempfile

import yaml

BASIS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASIS))
from wmscout.app import erstelle_server  # noqa: E402
from wmscout.datenbank import Datenbank  # noqa: E402


def beenden(_signal, _frame):
    raise SystemExit(0)


signal.signal(signal.SIGTERM, beenden)

with tempfile.TemporaryDirectory(prefix='campr-browser-') as tmp:
    cfg = yaml.safe_load((BASIS / 'config.yaml').read_text(encoding='utf-8'))
    cfg['app']['auto_suche_stunden'] = 0
    cfg['email']['aktiv'] = False
    cfg['whatsapp'] = {'aktiv': False}
    cfg['ausgabe'].update(datenbank=str(Path(tmp) / 'anzeigen.sqlite'), ordner=str(Path(tmp) / 'ausgabe'))
    cfg['import'] = {'ordner': str(Path(tmp) / 'import')}
    cfg['sicherung'] = {'ordner': str(Path(tmp) / 'sicherungen'), 'behalten': 10}
    db = Datenbank(cfg['ausgabe']['datenbank'])
    server, _, _ = erstelle_server(cfg, db, BASIS, port=0)
    print(f'READY http://127.0.0.1:{server.server_address[1]}', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        db.con.close()
