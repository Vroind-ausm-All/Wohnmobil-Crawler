"""Eingangskanäle ohne Netzabruf (ADR-010): vom Nutzer im Browser gespeicherte Seiten u. Ä."""
from .seiten import HTML_ENDUNGEN, erkenne_seite, html_dateien, import_ordner, lies_html, verschiebe

__all__ = ["HTML_ENDUNGEN", "erkenne_seite", "html_dateien", "import_ordner", "lies_html", "verschiebe"]
