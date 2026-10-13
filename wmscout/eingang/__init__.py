"""Eingangskanäle ohne Netzabruf (ADR-010): vom Nutzer im Browser gespeicherte Seiten u. Ä."""
from .seiten import (HTML_ENDUNGEN, BegleitordnerFehler, erkenne_seite, fahrzeugart_der_suchseite, html_dateien,
                     import_ordner, lies_html, relativ_zum_projekt, verschiebe)

__all__ = ["HTML_ENDUNGEN", "BegleitordnerFehler", "erkenne_seite", "fahrzeugart_der_suchseite", "html_dateien",
           "import_ordner", "lies_html", "relativ_zum_projekt", "verschiebe"]
