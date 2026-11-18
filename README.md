# Wetter-App

## Schlanke SPCK-Version (ohne Modellraster)

Für SPCK wird aus `index.html`, `assets/` und dieser README automatisch ein eigenständiger Branch **`spck-lite`** gebaut. Er enthält keine Wettermodell-Rohdaten und **keinen** gemeinsamen Git-Verlauf mit dem umfangreichen Daten-Repository.

- Für eine frische, kompakte SPCK-Installation ZIP herunterladen: https://github.com/colinheinz07-spec/Wetter-App/archive/refs/heads/spck-lite.zip und in SPCK als ZIP-Projekt importieren.
- Die ursprüngliche, gigabytegroße SPCK-Kopie erst entfernen, nachdem eigene lokale Änderungen gesichert und die neue Version getestet wurden.
- Die Modellkarten, Ortsprognosen und Radarprodukte werden nach Bedarf aus den bestehenden veröffentlichten Datenquellen geladen. **Die ZIP-Version ist kein Git-Synchronisationsprojekt.** Weitere Änderungen an `main` werden im Branch automatisch neu veröffentlicht, aber in SPCK muss das ZIP erneut importiert werden.
- Die großen Datendateien und der Git-Verlauf im Original-Repository sind damit **nicht** automatisch kleiner geworden.

## Straßenwetter & Hochwasser

Der Navigationsbereich **Gefahren** hat die Tabs „Straßenwetter“ und „Pegel & Hochwasser“. Beide Datenquellen werden erst beim Öffnen abgerufen, damit die Startseite klein bleibt.

- **Straßenwetter:** `scripts/ingest-road-weather.py` bereitet die frei veröffentlichten stündlichen DWD-SWSMOS-Fahrbahnprognosen als kleines `data/road-weather.json` auf. Angezeigt wird die nächste gültige Station bis 55 km Entfernung, mit Fahrbahn-/Lufttemperatur, prognostiziertem Straßenzustand, Lauf- und Datenzeit. Ein Stationswert gilt **nicht automatisch für alle Straßen** in der Umgebung. Fehlende oder alte Daten werden nicht als aktuell ausgegeben.
- **Hochwasser:** Die WSV-API PEGELONLINE stellt Bundeswasserstraßen-Pegel und teils Wasserstandsvorhersagen bereit. Die Anzeige listet nahe Pegel, Messzeit und 24-h-Veränderung; wo möglich auch amtliche Wasserstandsvorhersagen. Keine künstliche lokale Hochwasserwarnstufe aus absoluten Wasserständen. Kleine Flüsse und Landespegel sind teilweise nicht von PEGELONLINE abgedeckt; dafür Links zu den amtlichen Hochwasserzentralen.
- Sicherheitsrelevante Entscheidungen erfordern offizielle amtliche Hochwasser- und Straßenwarnungen. Die Anzeige ist keine Meldung einer befahrbaren oder gesperrten Straße.
- Testen: `node scripts/test-hazards.cjs`, `python3 scripts/test-road-weather.py`.

## Wetterdaten

Die App nutzt reproduzierbar aufbereitete Modellraster (keine Stationswerte als
Ersatz für eine Ortsprognose). Die Modellkarten zeigen einen Europa- bzw.
Deutschland-Ausschnitt; die Raster sind nicht die native Modellauflösung.

| Modell | Quelle | Karten-Zeitschritte | Horizont |
| --- | --- | --- | --- |
| ICON-D2 | DWD Open Data | Deutschland: 1 h | 48 h |
| ICON-EU | DWD Open Data | Deutschland: 1 h bis +78 h, danach 3 h; Wind ggf. durchgehend stündlich | 120 h |
| IFS | ECMWF Open Data | Deutschland: 3 h bis +144 h, danach 6 h | 360 h (06/18 UTC: 90 h) |
| GFS | NOAA/NCEP NOMADS | Deutschland: 1 h bis +120 h, danach 3 h | 384 h |
| AIFS | ECMWF Open Data (Single) | 6 h | 360 h |
| AIFS-ENS Control | ECMWF Open Data (Kontrolllauf) | 6 h | 360 h |

AIFS-ENS Control ist der ungestörte Kontrolllauf, keine Berechnung des
Ensemblemittels, der Streuung oder von Wahrscheinlichkeiten. Die KI-Modelle
werden bei Bedarf geladen; automatisierte GitHub-Workflows veröffentlichen
erst vollständige Grundfelder aus einem konsistenten Lauf.

Die Deutschland-Karten verwenden separate, geografisch zugeschnittene Originalraster
mit den tatsächlichen Zeitpunkten pro Parameter. Die Europa- und Ortsdaten behalten
ihre bestehende Struktur. Keine zeitliche Interpolation der Karten. Die erzeugten
Deutschland-Snapshots enthalten keine duplizierten Ortskacheln und ersetzen bei
vollständigem Import den vorigen Datenstand. Vergangene Zeiten sind als Karten nicht
auswählbar; notwendige frühere Eingaben für Niederschlagssummen bleiben erhalten.

## Datenqualität

`python scripts/audit-models.py` prüft alle veröffentlichten Raster auf korrekte
Prognoseschritte, Feldlängen, Pflichtfelder, Prozentbereiche und kumulativen
Niederschlag. Nicht vorhandene optionale Daten werden ausdrücklich angezeigt.
`node scripts/test-forecast.cjs` prüft die Anwendungslogik einschließlich
Modellübergängen, Niederschlagsintervallen und abgeleiteten Indizes.

Nicht jeder Modellanbieter veröffentlicht dieselben Parameter. Insbesondere
fehlende Böen, Niederschlagsphasen, Schneehöhen, CAPE/CIN und Gefahrenindizes
dürfen nicht aus einem anderen Modell als Werte dieses Modells ausgegeben werden.
Die Karten und Expertendaten kennzeichnen ihre Quelle. TT und K-Index werden
aus Temperatur und relativer Feuchte derselben Modellzeit und Zelle berechnet.

## Quellen und Nutzungsrechte

- DWD: [Open Data](https://opendata.dwd.de/), [FAQ / Nutzungsbedingungen](https://www.dwd.de/DE/leistungen/opendata/faqs_opendata.html).
- ECMWF: [Open Data](https://www.ecmwf.int/en/forecasts/datasets/open-data),
  Daten © ECMWF, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/),
  räumlich/zeitlich aufbereitet. Die Quelle und Bearbeitung werden angezeigt.
- NOAA/NCEP: [GFS](https://www.nco.ncep.noaa.gov/pmb/products/gfs/),
  [NOMADS](https://nomads.ncep.noaa.gov/).

Es werden keine API-Schlüssel oder kostenpflichtigen Wetter-APIs verwendet.
Open-Data-Lizenzen bedeuten nicht, dass alle Hosting- oder Rechenkosten bei
großen Nutzerzahlen entfallen. Kommerzielle Drittdienste (z. B. SuperHD) sind
ohne geklärte Rechte nicht integriert.

