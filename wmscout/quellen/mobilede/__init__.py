"""mobile.de (mobile.de) – ausschließlich im Browser gespeicherte Such- und Detailseiten (ADR-010).

Keine `Quelle` mit Netzabruf: Die AGB von mobile.de untersagen automatisierte Abfragen (docs/SOURCES.md). Der Parser
liest nur Dateien, die der Betreiber selbst gespeichert hat; erkannt werden sie in wmscout/eingang/seiten.py.
"""
from .parser import (ID_PRAEFIX, KENNUNG, anzeigen_id_aus_url, detail_url, parse_detailseite, parse_suchseite,
                     parse_suchseite_mit_hinweisen)

__all__ = ["ID_PRAEFIX", "KENNUNG", "anzeigen_id_aus_url", "detail_url", "parse_detailseite", "parse_suchseite",
           "parse_suchseite_mit_hinweisen"]
