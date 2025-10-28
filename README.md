# ⚡ Home Assistant - Spotty Stromoptimierung (AppDaemon)

Zwei aufeinander abgestimmte AppDaemon-Apps, die automatisch **Strompreise auswerten** und **optimale Startzeitpunkte für Geräte** berechnen.
---
⚠️ Zugegeben, das meiste ist KI erstellter Code und bedarf noch sehr viel Optimierung.

---


## 🧩 Komponenten

| App | Beschreibung |
|------|---------------|
| **Strompreise** | Holt Strompreise (heute + morgen), erstellt Sensoren. |
| **Stromoptimierung** | Liest Forecast + Geräte-Muster (z. B. Geschirrspüler), berechnet günstigsten Startzeitpunkt. |

---

## ⚙️ Installation

1. Kopiere die Datein in den AppDaemon-Ordner:

   ```bash
   (config/)appdaemon/apps/
   ├── strompreise.py
   ├── stromoptimierung.py
   ├── csv_forecast/
      └── strompreise.csv (wird angelegt)
   └── csv_patterns/
      └── geschirrspueler.csv (muss vom User hinzugefügt werden)
   ```

2. Füge in `apps.yaml` folgende Konfiguration hinzu:

   ```yaml
   strompreise:
     module: strompreise
     class: Strompreise
     url: "https://i.spottyenergie.at/api/prices/CONSUMPTION/AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE?timezone=at"  # <-------- Deine CONSUMPTION Spotty-API

   stromoptimierung:
     module: stromoptimierung
     class: Stromoptimierung
   ```

3. Installiere das "pandas" Python-Package in AppDaemon:

   a. Einstellungen -> Addons -> Appdeamon
   
   b. Reiter: Konfiguration
   
   c. In das Feld "Python package" "pandas" eintragen
   
   d. Auswählen und bestätigen.

5. Starte AppDaemon neu.

---

## 💾 Forecast-CSV

Die Datei `strompreise.csv` wird automatisch in `apps/csv_forecast` angelegt.

---
## 🧰 Lizenz

MIT License  
Autor: PunkRa1n
