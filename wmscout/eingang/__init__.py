"""Eingangskanäle ohne Netzabruf (ADR-010): vom Nutzer im Browser gespeicherte Seiten u. Ä."""
from .basis import Eingang, Lesung, Rohdaten, SeitenEingang
from .seiten import (HTML_ENDUNGEN, BegleitordnerFehler, SuchseitenArt, erkenne_seite, erkenne_seite_mit_hinweisen,
                     fahrzeugart_der_suchseite, haupttabelle_ids, html_dateien, import_ordner, ist_mobilede_seite, lies_html, plattform_der_seite,
                     relativ_zum_projekt, verschiebe)
from .text import TextEingang, bereinige, ergebnis_der, lese_text, pruefe_adresse, widerspricht_marke

__all__ = ["Eingang", "Lesung", "Rohdaten", "SeitenEingang", "TextEingang", "HTML_ENDUNGEN", "BegleitordnerFehler", "SuchseitenArt", "bereinige",
           "erkenne_seite", "erkenne_seite_mit_hinweisen", "ergebnis_der", "fahrzeugart_der_suchseite", "haupttabelle_ids", "html_dateien",
           "import_ordner", "ist_mobilede_seite", "lese_text", "lies_html", "plattform_der_seite", "pruefe_adresse", "relativ_zum_projekt",
           "verschiebe", "widerspricht_marke"]
