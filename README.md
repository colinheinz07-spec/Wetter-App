# Wetter-App

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

