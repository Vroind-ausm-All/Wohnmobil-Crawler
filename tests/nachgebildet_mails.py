"""NACHGEBILDETE Benachrichtigungs-Mails für die Tests des E-Mail-Eingangs (P2-06) – keine Originale.

Der Aufbau ist dem öffentlich bekannten Muster nachempfunden (Anzeigenblock je Treffer mit Bild, Titel, Preis, Ort, Link; Absender der
Plattform); Texte, Namen, Adressen und Anzeigen-IDs sind erfunden. Jede Mail trägt den Kopf `X-Scout-Testdaten`. Dass die Parser
echte Mails lesen können, belegt das NICHT – das ist die Abnahme mit echten Mails (F3, docs/QUELLEN.md).
"""
from __future__ import annotations

from email.message import EmailMessage
from urllib.parse import quote

TESTKOPF, TESTWERT = "X-Scout-Testdaten", "nachgebildet – kein Original"
EMPFAENGER = "max.mustermann.test@example.org"
KA_ABSENDER = "noreply-test@mail.kleinanzeigen.de"
MD_ABSENDER = "suchagent-test@mobile.de"
KA_BASIS = "https://www.kleinanzeigen.de"
MD_BASIS = "https://suchen.mobile.de"

KA_ANZEIGEN = [
    {"id": "3500000101", "slug": "knaus-sky-ti-650-meg", "titel": "Knaus Sky TI 650 MEG", "preis": 38500, "plz": "70173", "ort": "Stuttgart"},
    {"id": "3500000102", "slug": "huebsches-wohnmobil", "titel": "Hymer ML-T 570 Kastenwagen", "preis": 54900, "plz": "80331", "ort": "München"},
    {"id": "3500000103", "slug": "buerstner-lyseo", "titel": "Bürstner Lyseo TD 728 G", "preis": 41000, "plz": "40213", "ort": "Düsseldorf"},
]
MD_ANZEIGEN = [
    {"id": "3900000011", "titel": "Beispiel-Camper Kastenwagen 2.0 TDI", "preis": 26400, "plz": "23456", "ort": "Beispielstadt",
     "ez": "11/2015", "km": "87.350"},
    {"id": "3900000012", "titel": "Beispiel Bulli Aufstelldach", "preis": 27900, "plz": "34567", "ort": "Beispielstadt", "ez": "06/2014", "km": "141.250"},
]


def zahl(x: int) -> str:
    return f"{x:,}".replace(",", ".")


def ka_link(a: dict, zusatz: str = "?utm_source=suchagent&utm_medium=email&uid=ABC123") -> str:
    return f"{KA_BASIS}/s-anzeige/{a['slug']}/{a['id']}-220-1234{zusatz}"


def md_link(a: dict, zusatz: str = "&searchId=xyz&utm_source=suchagent") -> str:
    return f"{MD_BASIS}/fahrzeuge/details.html?id={a['id']}{zusatz}"


def weiterleitung(ziel: str, host: str = "click.mail.kleinanzeigen.de") -> str:
    return f"https://{host}/redirect?token=opak123&url={quote(ziel, safe='')}&ref=suchagent"


def nachgebildet_ka_html(anzeigen=None, link=ka_link) -> str:
    zeilen = []
    for a in anzeigen if anzeigen is not None else KA_ANZEIGEN:
        zeilen.append(f"""<tr><td width="120"><a href="{link(a)}"><img src="https://img.kleinanzeigen.de/images/x.jpg?uid=GEHEIM" alt="Foto"></a></td>
<td><a href="{link(a)}"><b>{a['titel']}</b></a><br><span>{zahl(a['preis'])} € VB</span><br><span>{a['plz']} {a['ort']}</span><br>
<a href="{link(a)}">Anzeige ansehen</a></td></tr>""")
    return ("<html><head><title>Neue Anzeigen</title></head><body><p>Hallo Max, neue Anzeigen zu Deinem Suchauftrag „Wohnmobil“:</p>"
            f"<table>{''.join(zeilen)}</table><p>Kleinanzeigen GmbH · <a href=\"{KA_BASIS}/m-suchauftraege.html?uid=ABC123\">Suchauftrag verwalten</a> · "
            f"<a href=\"https://www.facebook.com/kleinanzeigen\">Facebook</a></p></body></html>")


def nachgebildet_ka_text(anzeigen=None, link=ka_link) -> str:
    bloecke = [f"{a['titel']}\n{zahl(a['preis'])} € VB\n{a['plz']} {a['ort']}\n{link(a)}" for a in (anzeigen if anzeigen is not None else KA_ANZEIGEN)]
    return "Hallo Max, neue Anzeigen zu Deinem Suchauftrag:\n\n" + "\n\n".join(bloecke) + "\n\n-- \nKleinanzeigen GmbH\nAbmelden: https://www.kleinanzeigen.de/m-abmelden?uid=ABC123\n"


def nachgebildet_md_html(anzeigen=None, link=md_link) -> str:
    teile = []
    for a in anzeigen if anzeigen is not None else MD_ANZEIGEN:
        ziel = link(a).replace("&", "&amp;")
        teile.append(f"""<div style="border:1px"><a href="{ziel}"><img src="https://img.mobile.de/x.jpg?t=GEHEIM" alt=""></a>
<h3><a href="{ziel}">{a['titel']}</a></h3><p>{zahl(a['preis'])} €</p>
<p>Kastenwagen • EZ {a['ez']} • {a['km']} km • 96 kW (131 PS) • Diesel</p><p>{a['plz']} {a['ort']}</p></div>""")
    return ("<html><body><p>Ihr Suchagent hat neue Fahrzeuge gefunden:</p>" + "".join(teile) +
            "<p>mobile.de GmbH, Albert-Einstein-Ring 3, 14532 Kleinmachnow</p></body></html>")


def nachgebildet_md_text(anzeigen=None, link=md_link) -> str:
    bloecke = [f"{a['titel']}\n{zahl(a['preis'])} €\nEZ {a['ez']} • {a['km']} km • 96 kW (131 PS)\n{a['plz']} {a['ort']}\n{link(a)}"
               for a in (anzeigen if anzeigen is not None else MD_ANZEIGEN)]
    return "Ihr Suchagent hat neue Fahrzeuge gefunden:\n\n" + "\n\n".join(bloecke) + "\n"


def nachgebildet_mail(absender: str, betreff: str, html: str | None = None, text: str | None = None, *, kodierung: str | None = None,
                      zeichensatz: str = "utf-8", datum: str = "Sat, 17 Oct 2026 08:15:00 +0200") -> EmailMessage:
    """multipart/alternative (Text + HTML), nur text/plain, nur text/html. kodierung: None | 'quoted-printable' | 'base64' | '7bit'."""
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Date"], m[TESTKOPF] = absender, EMPFAENGER, betreff, datum, TESTWERT
    optionen = {"charset": zeichensatz, **({"cte": kodierung} if kodierung else {})}
    if text is not None:
        m.set_content(text, **optionen)
    if html is not None:
        if text is None:
            m.set_content(html, subtype="html", **optionen)
        else:
            m.add_alternative(html, subtype="html", **optionen)
    return m


def nachgebildet_ka_mail(**kw) -> bytes:
    return nachgebildet_mail(KA_ABSENDER, "Neue Anzeigen für Deinen Suchauftrag „Wohnmobil“", nachgebildet_ka_html(), nachgebildet_ka_text(), **kw).as_bytes()


def nachgebildet_md_mail(**kw) -> bytes:
    return nachgebildet_mail(MD_ABSENDER, "Neue Treffer für Ihren Suchagenten", nachgebildet_md_html(), nachgebildet_md_text(), **kw).as_bytes()
