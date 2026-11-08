"""Schlanker HTML-Baum für Mails (P2-06): `html.parser` der Standardbibliothek, mit festen Grenzen.

Der Baum wird einmal gebaut (Tiefe und Knotenzahl begrenzt, mehr ist ein `MailFehler`) und danach nur gelesen. Jede Abfrage hat eine
Obergrenze, und alle Abfragen einer Mail zusammen teilen sich ein Budget (`Budget`): Eine absichtlich überladene Mail (viele Links, riesige
Elternknoten) bricht mit `MailFehler` ab, statt die Dateischleife des Imports minutenlang zu blockieren.
Gewählt wurde ein eigener Baum, weil die Blockgrenzen (Zeilenumbrüche) beim Lesen entstehen sollen, ohne den Baum zu verändern
(BeautifulSoup wird beim Einfügen in breiten oder tiefen Bäumen quadratisch langsam); beim reinen Bauen war er in der Messung nur etwa
1,6-mal so schnell (0,7 s statt 1,1 s für 0,7 MB). Der Engpass früherer Fassungen lag in `treffer.html_bloecke`: je Link wurde der
Umgebungsblock neu bestimmt – das geschieht jetzt je Anzeige einmal, mit Zwischenspeicher und Budget.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from html.parser import HTMLParser
from typing import NamedTuple

from .nachricht import MailFehler

MAX_TIEFE = 100            # tiefer verschachteltes HTML ist kein Mail-Layout, sondern ein Angriff auf die Laufzeit
MAX_KNOTEN_BAUM = 200_000  # so viele Elemente und Textstücke hat eine Mail höchstens (echte Mails: einige Tausend)
MAX_KNOTEN_ABFRAGE = 5000  # so viele Knoten schaut eine einzelne Abfrage (Text, Links) höchstens an
BUDGET_KNOTEN = 3_000_000  # alle Abfragen einer Mail zusammen
# Überschriften von Empfehlungsblöcken: Links dahinter gehören nicht zur Suche des Nutzers
EMPFEHLUNG = re.compile(
    r"^\W{0,3}(?:das\s+könnte\s+(?:dich|sie|ihnen)\s+(?:auch\s+)?interessieren|"
    r"(?:ähnliche|weitere|ähnlich)\s+(?:anzeigen|fahrzeuge|angebote|inserate|treffer)|"
    r"empfehlungen?(?:\s+für\s+(?:dich|sie))?|das\s+gefällt\s+(?:dir|ihnen)\s+(?:vielleicht\s+)?auch|"
    r"andere\s+(?:nutzer|kunden)\s+(?:haben\s+)?(?:sich\s+)?(?:auch\s+)?(?:angesehen|angeschaut)|"
    r"anzeigen,?\s+die\s+(?:dir|ihnen)\s+gefallen\s+könnten|vielleicht\s+(?:auch\s+)?interessant|"
    r"you\s+might\s+also\s+like|similar\s+(?:ads|listings))\W{0,3}$", re.I)
BLOCK = frozenset({"p", "div", "tr", "td", "th", "li", "ul", "ol", "table", "tbody", "thead", "tfoot", "section", "article", "header", "footer",
                   "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "center", "dl", "dt", "dd", "pre", "address"})
LEER = frozenset({"br", "hr", "img", "meta", "link", "input", "col", "area", "base", "wbr", "source", "param", "embed", "track"})
UEBERSPRINGEN = frozenset({"script", "style", "title", "noscript", "head"})     # Inhalt wird nie gelesen
SELBST_SCHLIESSEND = frozenset({"p", "li", "td", "th", "tr", "dt", "dd"})        # <p>…<p> ohne </p>: der alte Absatz endet


class Knoten:
    __slots__ = ("name", "attrs", "eltern", "kinder", "index", "text", "anzeigen_id", "alt")

    def __init__(self, name: str | None, attrs: dict | None = None, text: str = "", eltern: Knoten | None = None):
        self.name, self.attrs, self.text, self.eltern = name, attrs or {}, text, eltern
        self.kinder: list[Knoten] = []
        self.index = len(eltern.kinder) if eltern else 0
        self.anzeigen_id: str | None = None               # wird für Links auf Anzeigen gesetzt
        self.alt = ""                                     # Alternativtext eines Bildes im Link


ZEILENUMBRUCH = Knoten(None, text="\n")
DURCHGESTRICHEN = frozenset({"s", "del", "strike"})


class Budget:
    """Gemeinsame Obergrenze für alle Abfragen einer Mail."""

    def __init__(self, knoten: int = BUDGET_KNOTEN):
        self.rest = knoten

    def verbrauche(self, n: int) -> None:
        self.rest -= n
        if self.rest < 0:
            raise MailFehler("Mail zu aufwendig auszuwerten (zu viele Links oder zu große Blöcke)")


class Baum(NamedTuple):
    wurzel: Knoten | None
    links: list                      # Links mit href in Dokumentreihenfolge
    empfehlung_ab: int | None        # Index in `links`, ab dem ein Empfehlungsblock beginnt (None = keiner)


class _Baum(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.wurzel = Knoten("#wurzel")
        self.offen = [self.wurzel]
        self.links: list[Knoten] = []
        self.knoten = 0
        self.empfehlung_ab: int | None = None
        self._ueberspringen: str | None = None

    def _zaehle(self):
        self.knoten += 1
        if self.knoten > MAX_KNOTEN_BAUM:
            raise MailFehler(f"HTML der Mail hat mehr als {MAX_KNOTEN_BAUM} Elemente")

    def _neu(self, name: str, attrs: dict) -> Knoten:
        self._zaehle()
        k = Knoten(name, attrs, eltern=self.offen[-1])
        self.offen[-1].kinder.append(k)
        return k

    def handle_starttag(self, tag, attrs):
        if self._ueberspringen:
            return
        if tag in UEBERSPRINGEN:
            if tag != "head":
                self._ueberspringen = tag
            return
        if tag in SELBST_SCHLIESSEND and self.offen[-1].name == tag:
            self.offen.pop()
        k = self._neu(tag, {n: (v or "") for n, v in attrs})
        if tag == "img":
            if (alt := (k.attrs.get("alt") or "").strip()):
                for a in reversed(self.offen):
                    if a.name == "a":
                        a.alt = a.alt or alt
                        break
            return
        if tag in LEER:
            return
        if tag == "a" and k.attrs.get("href"):
            self.links.append(k)
        if len(self.offen) > MAX_TIEFE:
            raise MailFehler(f"HTML der Mail ist mehr als {MAX_TIEFE} Ebenen tief verschachtelt")
        self.offen.append(k)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in LEER and not self._ueberspringen and self.offen[-1].name == tag:
            self.offen.pop()

    def handle_endtag(self, tag):
        if self._ueberspringen:
            if tag == self._ueberspringen:
                self._ueberspringen = None
            return
        for i in range(len(self.offen) - 1, 0, -1):         # bis zum zuletzt geöffneten gleichnamigen Element schließen
            if self.offen[i].name == tag:
                del self.offen[i:]
                return

    def handle_data(self, data):
        if self._ueberspringen:
            return
        eltern = self.offen[-1]
        if self.empfehlung_ab is None and len(data) <= 80 and EMPFEHLUNG.match(" ".join(data.split())):
            self.empfehlung_ab = len(self.links)
        if eltern.kinder and eltern.kinder[-1].name is None and eltern.kinder[-1] is not ZEILENUMBRUCH:
            eltern.kinder[-1].text += data
        else:
            self._zaehle()
            eltern.kinder.append(Knoten(None, text=data, eltern=eltern))


def baue(html: str) -> Baum:
    """HTML → Baum. `MailFehler`, wenn er zu tief wird oder zu viele Elemente hat."""
    baum = _Baum()
    baum.feed(html)
    baum.close()
    return Baum(baum.wurzel, baum.links, baum.empfehlung_ab)


def _unterbaum(knoten: Knoten) -> Iterator[Knoten]:
    stapel = [knoten]
    while stapel:
        k = stapel.pop()
        yield k
        stapel.extend(reversed(k.kinder))


def text(knoten: Knoten, grenze: int | None = None, budget: Budget | None = None) -> str | None:
    """Text des Teilbaums; Blockelemente und <br> werden Zeilenumbrüche, Inline-Elemente bleiben zusammen, Durchgestrichenes (<s>, <del>,
    <strike>, line-through) zählt nicht. None, wenn der Teilbaum mehr als `grenze` Zeichen oder mehr als MAX_KNOTEN_ABFRAGE Knoten hat."""
    teile, laenge, besucht = [], 0, 0
    stapel: list[Knoten] = [knoten]
    try:
        while stapel:
            k = stapel.pop()
            besucht += 1
            if besucht > MAX_KNOTEN_ABFRAGE:
                return None
            if k.name is None:
                teile.append(k.text)
                laenge += len(k.text.strip())
                if grenze is not None and laenge > grenze:
                    return None
                continue
            if k.name in DURCHGESTRICHEN or "line-through" in k.attrs.get("style", "").lower():
                continue
            if k.name in ("br", "hr"):
                teile.append("\n")
            elif k.name in BLOCK:
                teile.append("\n")
                stapel.append(ZEILENUMBRUCH)
            stapel.extend(reversed(k.kinder))
        return "".join(teile)
    finally:
        if budget:
            budget.verbrauche(besucht)


def anzeigen_ids(knoten: Knoten, budget: Budget | None = None) -> set[str] | None:
    """Anzeigen-IDs der Links im Teilbaum; None, wenn der Teilbaum zu groß für eine Abfrage ist."""
    ids = set()
    n = 0
    try:
        for n, k in enumerate(_unterbaum(knoten), 1):
            if n > MAX_KNOTEN_ABFRAGE:
                return None
            if k.anzeigen_id:
                ids.add(k.anzeigen_id)
        return ids
    finally:
        if budget:
            budget.verbrauche(n)
