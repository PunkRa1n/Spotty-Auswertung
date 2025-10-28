# CSV Muster-Dateien

In diesem Ordner (`csv_patterns`) werden die Referenz-CSV-Dateien für verschiedene Geräte abgelegt (z. B. Geschirrspüler, Waschmaschine).  
Die App verwendet diese Muster, um den Energieverbrauchsverlauf zu analysieren und die optimalen Startzeiten basierend auf Strompreisen zu berechnen.

---

## 🧩 Zweck

Jede Datei beschreibt **den typischen Energieverbrauchsverlauf eines Geräts** während eines kompletten Durchlaufs.  
Diese Muster werden verwendet, um automatisch Sensoren zu erzeugen und die Startzeit so zu verschieben, dass der größte Energieverbrauch in günstige Preiszeiten fällt.

---

## 🗂️ Aufbau der Dateien

Dateiname:  
```
<beliebiger_name>.csv
```
(z. B. `geschirrspuler.csv` oder `waschmaschine.csv`)

---

## 🧾 Inhalt der CSV-Datei

Der Export muss direkt aus Home Assistant stammen:

1. In Home Assistant den **Energie-Sensor** (z. B. `sensor.geschirrspuler_current_consumption`) auswählen.  
2. Auf **„Mehr anzeigen“** klicken.  
3. Zeitraum so einstellen, dass **ein kompletter Programmablauf** abgedeckt ist (Start → Ende).
4. Über das Menü oben rechts → **„Daten exportieren“** wählen.  
   *Die Genauigkeit des Exports ist wichtig, um den Verlauf korrekt zu analysieren.*

---

## 📋 Beispielinhalt

```csv
entity_id,state,last_changed
sensor.geschirrspuler_current_consumption,0.0,2025-09-30T10:00:00.000Z
sensor.geschirrspuler_current_consumption,5.7,2025-09-30T10:00:00.694Z
sensor.geschirrspuler_current_consumption,10.6,2025-09-30T10:00:06.003Z
sensor.geschirrspuler_current_consumption,15.4,2025-09-30T10:00:11.010Z
sensor.geschirrspuler_current_consumption,11.3,2025-09-30T10:00:16.012Z
...
```

---

## ⚙️ Hinweise

- Die Spalten sind **Sensor-ID**, **Wert (Leistung in Watt)** und **Zeitstempel (UTC)**.  
- Der Dateiname spielt keine Rolle – wichtig ist nur, dass die Daten korrekt formatiert sind.  
- Für jedes Gerät muss **eine separate CSV-Datei** angelegt werden.  
- Die App erzeugt daraus automatisch Sensoren für „heute“ und „morgen“.
- zb. die geschirrspueler.csv erzeugt sensor.spotty_optimaler_geschirrspueler_**start** und sensor.spotty_optimaler_geschirrspueler_**start_morgen**

- Wird sie richtig erkannt, sollte folgendes in den Logs erscheinen.

Bitte nicht von dem wert Kosten verwirren lassen, das sind interne Bewertungsgröße um den günstigsten Startzeitpunkt zu bestimmen. Sie entsprechen nicht direkt die Kosten, aber sie helfen der App, die preisoptimale Zeit zu finden.

```
2025-10-28 12:57:41.314262 INFO stromoptimierung: Stromoptimierung App gestartet
2025-10-28 12:57:41.332928 INFO stromoptimierung: [CSV] geschirrspueler: Muster erkannt [(3, 14), (20, 11)]
2025-10-28 12:57:41.334196 INFO stromoptimierung: [CSV] geschirrspueler: Muster geladen
2025-10-28 12:57:41.343611 INFO stromoptimierung: [CSV] waschmaschine_60C: Muster erkannt [(7, 26)]
2025-10-28 12:57:41.344276 INFO stromoptimierung: [CSV] waschmaschine_60C: Muster geladen
2025-10-28 12:57:41.344898 INFO stromoptimierung: Geraete-Muster geladen: ['geschirrspueler', 'waschmaschine_60C']
2025-10-28 12:57:43.357110 INFO stromoptimierung: Starte Initialauswertung: heute + morgen
2025-10-28 12:57:43.359602 INFO stromoptimierung: Auswertung gestartet (heute)
2025-10-28 12:57:43.552600 INFO stromoptimierung: geschirrspueler: optimaler Start 2025-10-28 03:57:00+00:00, Kosten 202.00
2025-10-28 12:57:43.644734 WARNING stromoptimierung: Entity sensor.spotty_optimaler_waschmaschine_60C_start not found in the default namespace
2025-10-28 12:57:43.644972 INFO AppDaemon: stromoptimierung: Entity sensor.spotty_optimaler_waschmaschine_60C_start created in namespace: default
2025-10-28 12:57:43.653867 INFO stromoptimierung: waschmaschine_60C: optimaler Start 2025-10-28 03:42:00+00:00, Kosten 207.00
2025-10-28 12:57:43.654775 INFO stromoptimierung: Auswertung gestartet (morgen)
2025-10-28 12:57:43.663169 INFO stromoptimierung: Keine morgigen Forecast-Daten verf��gbar (noch nicht bereitgestellt).
2025-10-28 12:57:43.668819 WARNING stromoptimierung: Entity sensor.spotty_optimaler_waschmaschine_60C_start_morgen not found in the default namespace
2025-10-28 12:57:43.669105 INFO AppDaemon: stromoptimierung: Entity sensor.spotty_optimaler_waschmaschine_60C_start_morgen created in namespace: default
```

---

## 💡 Tipp

Je genauer der aufgezeichnete Verbrauchsverlauf ist, desto präziser kann die App den optimalen Startzeitpunkt berechnen.
