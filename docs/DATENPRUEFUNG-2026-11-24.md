# Datenprüfung – 24. November 2026

## Nachgewiesene Fehler

1. **ICON-EU wurde nach erfolgreichem Import nicht veröffentlicht.** Job `138401017250` des Laufs `45381391712` scheiterte an der Größenprüfung vor dem Push. Der zuletzt veröffentlichte EU-Snapshot enthielt 1.456.728.326 Byte, davon 790.793.218 Byte doppelt vorgehaltene Ortskacheln. Das Größenlimit beträgt weiterhin 1,5 GB.
2. **Ein IFS-Lauf ging beim Veröffentlichen verloren.** Job `138377234745` des Laufs `45374576772` verlor zwei Push-Rennen gegen andere Importe nach jeweils erfolgreichem Rebase. Die bisherige einmalige Wiederholung reichte nicht aus.
3. **Konvektive Wolkenbasis und -obergrenze wurden unter falschen Quellnamen angefragt.** Die DWD-Verzeichnisse heißen `hbas_con` und `htop_con`; `bas_con` und `top_con` lieferten HTTP 404. Die internen App-Felder `cloudbase` und `cloudtop` bleiben unverändert.

## Korrekturen

- Originale Kartenfelder bleiben für alle veröffentlichten Prognosezeiten vorhanden. Die zusätzlichen Ortskacheln behalten sämtliche Boden-/Wetterwerte und die Druckflächenprofile für die ersten 36 Stunden des Modelllaufs. Spätere Druckflächenprofile werden aus den vorhandenen Originalkarten geladen, statt in jeder Ortskachel nochmals über die gesamte Reichweite gespeichert zu werden. Die aktuellen Expertenwerte frischer Läufe bleiben abgedeckt.
- Gemessener Vergleich an einer vorhandenen ICON-EU-Ortskachel: 1.025.667 → 657.937 Byte, **35,9 % weniger**, bei unveränderten Original-Kartenfeldern. Dies ist ein Beispiel, keine garantierte Reduktion jedes zukünftigen Laufs.
- Die Größenprüfung zählt veröffentlichte Nutzdateien, meldet deren Umfang und behält das bestehende Limit bei. Git-Metadaten zählen nicht zum Datenpaket.
- Die `main`-Datenveröffentlichungen verwenden einen gemeinsamen Helfer mit bis zu sechs Versuchen. Jeder Versuch holt den neuen Stand und führt erneut einen Rebase aus. Konflikte oder Berechtigungsfehler brechen ab; es gibt keinen erzwungenen Push auf `main`.
- Die richtigen DWD-Wolkenhöhenprodukte werden angefordert, sofern sie im jeweiligen Modelllauf tatsächlich vorliegen.

## Prüfung

`test-native-publication.py` prüft Profilhorizont, unveränderte langfristige Bodenwerte, vorhandene Originalfelder, Größenlimit und Quellnamen. `test-push-data-commit.py` prüft konkurrierende Pushes, erneuten Rebase pro Versuch, begrenzte Wiederholung, Berechtigungsfehler und Konfliktabbruch. Bestehende native Orts-, Temperatur-, Modellschritt-, Straßenwetter- und Indexprüfungen bleiben erhalten. Die neue Datenqualitätsprüfung läuft bei Pull Requests und relevanten Änderungen.

Neue Datenwerte erscheinen erst nach einem erfolgreich veröffentlichten Import. Eine Codekorrektur allein beweist noch keinen neuen Modelllauf. Alte Daten werden weder umdatiert noch durch erfundene Werte ersetzt.

Quellkontrolle: [DWD ICON-EU](https://opendata.dwd.de/weather/nwp/icon-eu/grib/00/) und [ICON-Ausgabefelder](https://www.dwd.de/SharedDocs/downloads/DE/modelldokumentationen/nwv/icon_d2/icon_d2_dbbeschr_aktuell.pdf?nn=344870&view=nasPublication).
