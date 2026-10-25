# Analyse des Ankaufsrechners (P5-01, Stand 25.10.2026)

Grundlage für Phase 5. Beschreibt, **wie** der Rechner heute zu Max-EK und Erstangebot kommt, **wie empfindlich** das Ergebnis auf
die Parameter reagiert, und **wo** die fachlichen Schwächen liegen – jeweils mit dem Arbeitspaket, das sie angeht. Code:
`wmscout/bewertung/rechner.py`; Parameter: `config.yaml → rechner`. Die Kalibrierung (P5-01) vergleicht die Rechnung mit echten
Ankäufen, siehe ADR-052.

## 1. Formelkette

| Schritt | Formel | Parameter |
|---|---|---|
| Referenzwert | Neupreis(Art) × Markenklasse × Restwert(Alter) × (1 + km-Korrektur) × (1 + Σ Wertfaktoren) | `marktmodell.*`, `wertfaktoren` |
| Marktfaktor | gewichteter Median (Preis ÷ Referenzwert) vergleichbarer **Privat**angebote (gleiche Art, EZ ± 3 J., km ± 50.000; seit P5-02 nach Ähnlichkeit: gleiches Modell 2,5, Modellreihe 1,8, Marke 1,0, Markenklasse 0,7, andere 0,5, Länge und Basisfahrzeug, Einzelangebot höchstens 25 %; alte Anzeigen ×0,5; Ausreißer nach Tukey) | `vergleich_*` |
| Marktniveau | Referenzwert × (g × Marktfaktor + (1 − g)), g = n ÷ (n + 4) | `vergleich_gewicht_k` |
| Marktwert privat | Marktniveau × (1 − 7 %) – Angebot → Abschluss | `abschlag_angebot_auf_privatwert` |
| Händler-VK | Marktwert privat × (1 + 10 %) | `aufschlag_haendler_vk` |
| Kosten | Aufbereitung + HU/Gas + Transport (Entfernung) + Standkosten + 2,5 % Gewährleistung vom VK + Reparaturrisiko (Alter) + km-Zuschlag | `kosten.*` |
| Ziel-Marge | max(12 % vom VK, 2.500 €) | `ziel_marge_*` |
| Max-EK (§25a) | VK − (Marge + Kosten) × 1,19 | `differenzbesteuerung` |
| Erstangebot | Max-EK × Faktor, mindestens Fair-Untergrenze × Marktwert privat, nie über dem Wunschpreis | `erstangebot_faktor`, `fair_untergrenze_privatwert` |
| Sicherheit / Spanne | hoch ab 8 Vergleichen und Streuung ≤ 12 %, mittel ab 5, sonst niedrig; Spanne = Niveau ± gewichtete Streuung (ohne Vergleiche ± 15 %) | `vergleich_min_anzahl`, `unsicherheit_ohne_vergleich` |

Ohne Erstzulassung gibt es **keine** Beträge (P1-12). Die §25a-Kalkulation ist eine fachliche Annahme, keine Steuerberatung.

## 2. Empfindlichkeit (gerechnet)

Beispiel: Knaus Sky TI 650 (Teilintegrierter), EZ 2018, 80.000 km, 150 km entfernt, Stichtag 25.10.2026, **ohne** Vergleichsangebote,
Parameter aus `config.yaml`. Basis: Referenzwert 47.550 €, Marktwert privat 44.250 €, Händler-VK 48.700 €, Kosten 4.550 €,
Ziel-Marge 5.850 €, **Max-EK 36.300 €**, Erstangebot 33.400 €.

| Änderung | Max-EK | Wirkung |
|---|---|---|
| Neupreis Teilintegrierter 82.000 → 86.100 € (+5 %) | 38.300 € | **+5,5 %** |
| 10 Vergleiche mit Marktfaktor 0,90 (Gewicht 71 %) | 33.400 € | **−8,0 %** |
| Abschlag Angebot → Abschluss 7 → 10 % | 35.000 € | −3,6 % |
| Händleraufschlag 10 → 13 % | 37.400 € | +3,0 % |
| Ziel-Marge 12 → 10 % | 37.400 € | +3,0 % |
| Aufbereitung 900 → 1.400 € | 35.700 € | −1,7 % |
| Standzeit 3 → 5 Monate | 36.000 € | −0,8 % |

**Folgerung:** Max-EK hängt mit einem Hebel von gut 1 an der **Marktwert-Schätzung** (Neupreis-Tabelle, Restwertkurve, Marktfaktor) –
1 % Fehler im Marktniveau ist rund 1,1 % Fehler im Max-EK, bei 36.000 € also ≈ 400 €. Kosten und Standzeit wirken deutlich schwächer.
Kalibrierung lohnt deshalb zuerst beim **Verkaufspreis** (Ist-VK gegen geplanten Händler-VK), dann bei den Kosten.

## 3. Schwächen und zuständige Pakete

| Nr. | Schwäche | Folge | Paket |
|---|---|---|---|
| S1 | Keine Rückkopplung mit echten Ankäufen/Verkäufen; Parameter sind Schätzwerte | systematische Über-/Unterbewertung bleibt unbemerkt | **P5-01** (Kalibrierungsbericht) |
| S2 | Vergleich nur nach Art + Jahr + km; Marke gewichtet, Modellreihe nur als Zuschlag; keine Fahrzeugklasse (Länge, Basisfahrzeug) | Teilintegrierte von 6 m und 7,5 m gelten als gleich | P5-02 – **angegangen** (ADR-053: Ähnlichkeitsstufen, Länge/Basisfahrzeug aus dem Text) |
| S3 | Spanne nur aus Vergleichsstreuung, Punktwert in der Oberfläche dominiert; bei 1–4 Vergleichen Mischwert mit dem Modell | falsche Genauigkeit bei dünner Datenlage | P5-03 – **angegangen** (ADR-054: Max-EK und Marktwert privat als Spanne in der Oberfläche) |
| S4 | Angebotspreise statt Abschlusspreisen; fester Abschlag 7 %; Händlerangebote fließen gar nicht ein | Marktwert privat systematisch verschoben | P5-04 – **angegangen** (ADR-055: Händlermarkt als Obergrenze für den Händler-VK, Marktbeobachtung der Preissenkungen; Abschlusspreise nur aus eigenen Ankäufen, ADR-052) |
| S5 | Wertfaktoren nur aus Stichworten im Text, Deckel ±; Mängel aus der Besichtigung fließen nicht zurück | Zustand schlecht abgebildet | P5-05 |
| S6 | Transport nur ab Firmensitz; Reparaturrisiko nur nach Alter | Standorte/Kostenrisiko ungenau | P5-06, P5-05 |
| S7 | Keine Gesamtbewertung (Deal-Score), keine gespeicherte Modellversion | Bewertungen nicht vergleichbar über die Zeit | P5-07 |
| S8 | Restwertkurve und Neupreise gelten für alle Marken gleich (nur Klassenfaktor) | Marken mit stabilerem Wert unterbewertet | P5-02 / Kalibrierung |

## 4. Was die Kalibrierung (P5-01) liefert – und was nicht

* Fälle: **Ankäufe der App** (Plan beim Kauf eingefroren, Ist aus Kaufpreis, Kosten, Verkauf) und **manuell erfasste frühere Ankäufe**
  (Fahrzeugdaten, tatsächlicher Kaufpreis, optional Verkaufspreis/Kosten/Datum), die der Rechner zum Kaufdatum nachrechnet.
* Bericht: Kaufpreis ÷ Max-EK, Verkaufspreis ÷ geplanter Händler-VK, Ist- minus Plankosten, Standzeit – Median, Quartile, Anzahl.
* **Vorschläge** für einzelne Parameter erst ab 5 verwertbaren Fällen und einer Abweichung über der Toleranz; geändert wird nichts
  automatisch – der Betreiber stellt `config.yaml` bewusst nach.
* Grenzen: nachgerechnete Altfälle nutzen **nur das Marktmodell** zum Kaufdatum (Vergleichsangebote von damals fehlen; heutige Angebote
  wären für ein früheres Kaufdatum zu alt bewertet); wenige Fälle sagen wenig (der Bericht weist Anzahl und Streuung aus).
* Vorschläge rechnen je Fall relativ zum Parameterstand bei der Planung (beim Ankauf im Plan gespeichert) – eine übernommene Korrektur
  wird nicht erneut vorgeschlagen.
