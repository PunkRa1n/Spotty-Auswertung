import appdaemon.plugins.hass.hassapi as hass
import os
import pandas as pd
from datetime import datetime, timedelta

class Stromoptimierung(hass.Hass):

    def initialize(self):
        # CSV-Ordner relativ zum Skript
        self.csv_patterns_folder = os.path.join(os.path.dirname(__file__), "csv_patterns")
        self.csv_forecast_folder = os.path.join(os.path.dirname(__file__), "csv_forecast")
        self.forecast_csv_file = os.path.join(self.csv_forecast_folder, "strompreise.csv")

        self.log("Stromoptimierung App gestartet")

        # Muster laden
        self.patterns = {}
        for file in os.listdir(self.csv_patterns_folder):
            if file.endswith(".csv"):
                name = file.replace(".csv", "")
                path = os.path.join(self.csv_patterns_folder, file)
                pattern = self.csv_to_pattern(path)
                if pattern:
                    self.patterns[name] = pattern
                    self.log(f"[CSV] {name}: Muster geladen")
        self.log(f"Geraete-Muster geladen: {list(self.patterns.keys())}")

        # Erste Auswertungen direkt nach dem Start
        self.run_in(self.initial_auswertungen, 2)

        # Tägliche Auswertung um Mitternacht (heute)
        self.run_daily(self.auswerten, "00:00:30")

        # Um Mitternacht alle morgigen Sensoren zurücksetzen
        self.run_daily(self.reset_morgen_sensors, "00:00:00")


        # Prüfung zwischen 13–15 Uhr, wenn neue Börsendaten für morgen kommen
        for stunde in [13, 14, 15]:
            zeit = f"{stunde:02d}:01:00"
            self.run_daily(self.auswerten_morgen, zeit)
            self.log(f"Plane tägliche Prüfung für morgige Preise um {zeit}")


    # --------- Initial beide Auswertungen ---------
    def initial_auswertungen(self, kwargs):
        self.log("Starte Initialauswertung: heute + morgen")
        self.auswerten({})
        self.auswerten_morgen({})


    # --------- CSV Verarbeitung ---------
    def csv_to_pattern(self, file_path):
        df = pd.read_csv(file_path)

        if "last_changed" not in df.columns or "state" not in df.columns:
            self.log(f"CSV {file_path} hat falsche Spalten!", level="ERROR")
            return None

        df["time"] = pd.to_datetime(df["last_changed"])
        df["state"] = pd.to_numeric(df["state"], errors="coerce").fillna(0)

        df_resampled = df.set_index("time").resample("1min")["state"].mean().fillna(0)

        mean = df_resampled.mean()
        std = df_resampled.std()
        threshold = mean + std if std > 1 else 10

        pattern = []
        in_block = False
        block_start = None

        for i, (ts, value) in enumerate(df_resampled.items()):
            if value > threshold and not in_block:
                in_block = True
                block_start = i
            elif value <= threshold and in_block:
                in_block = False
                duration = i - block_start
                pattern.append((block_start, duration))

        if in_block:
            duration = len(df_resampled) - block_start
            pattern.append((block_start, duration))

        self.log(f"[CSV] {os.path.basename(file_path).replace('.csv','')}: Muster erkannt {pattern}")
        return {"pattern": pattern, "length": len(df_resampled)}


    def lade_forecast(self):
        try:
            df = pd.read_csv(self.forecast_csv_file)
            if "datetime" not in df.columns or "price" not in df.columns:
                self.log(f"Forecast {self.forecast_csv_file} falsche Spalten!", level="ERROR")
                return None

            # Datetime richtig parsen (inkl. Zeitzone falls vorhanden)
            df["time"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")

            # Ungültige Zeitstempel rausschmeißen
            df = df.dropna(subset=["time"])

            df["price"] = pd.to_numeric(df["price"], errors="coerce")
            df = df.dropna(subset=["price"])

            # Jetzt sicherstellen, dass der Index datetime ist
            df = df.set_index("time")

            # Danach darf resample endlich laufen
            df = df.resample("1min").ffill()

            return df["price"]

        except Exception as e:
            self.log(f"Fehler beim Laden des Forecast: {e}", level="ERROR")
            return None



    # --------- Optimierung ---------
    def berechne_optimalen_start(self, forecast, pattern):
        total_duration = max([start + duration for start, duration in pattern["pattern"]])
        best_start = None
        best_cost = float("inf")

        for t0 in range(len(forecast) - total_duration):
            cost = 0
            for offset, duration in pattern["pattern"]:
                window = forecast.iloc[t0 + offset : t0 + offset + duration]
                cost += window.sum()
            if cost < best_cost:
                best_cost = cost
                best_start = forecast.index[t0]

        return best_start, best_cost


    # --------- Hauptauswertung (heute) ---------
    def auswerten(self, kwargs):
        self.log("Auswertung gestartet (heute)")

        forecast = self.lade_forecast()
        if forecast is None:
            self.log("Kein Forecast verfügbar")
            return

        for name, pattern in self.patterns.items():
            best_start, best_cost = self.berechne_optimalen_start(forecast, pattern)
            sensor_name = f"sensor.spotty_optimaler_{name}_start"

            if best_start:
                self.set_state(sensor_name, state=best_start.isoformat(),
                                attributes={
                                    "device_class": "timestamp",
                                    "friendly_name": f"Optimaler Start {name}",
                                    "cost": round(best_cost, 2)
                                })
                self.log(f"{name}: optimaler Start {best_start}, Kosten {best_cost:.2f}")
            else:
                self.set_state(sensor_name, state="unknown")
                self.log(f"{name}: kein optimaler Start gefunden")


    # --------- Auswertung für morgen ---------
    def auswerten_morgen(self, kwargs):
        self.log("Auswertung gestartet (morgen)")

        forecast = self.lade_forecast()
        if forecast is None:
            self.log("Kein Forecast verfügbar (morgen)")
            return

        tzinfo = forecast.index.tz or "UTC"
        jetzt = pd.Timestamp.now(tz=tzinfo)
        morgen_start = (jetzt + pd.Timedelta(days=1)).floor("D")
        uebermorgen_start = (jetzt + pd.Timedelta(days=2)).floor("D")

        forecast_morgen = forecast[(forecast.index >= morgen_start) & (forecast.index < uebermorgen_start)]

        if forecast_morgen.empty:
            self.log("Keine morgigen Forecast-Daten verfügbar (noch nicht bereitgestellt).")
            # Sensors trotzdem auf "unknown" setzen
            for name in self.patterns.keys():
                sensor_morgen = f"sensor.spotty_optimaler_{name}_start_morgen"
                self.set_state(sensor_morgen, state="unknown",
                                attributes={
                                    "device_class": "timestamp",
                                    "friendly_name": f"Optimaler Start {name} (morgen)",
                                    "icon": "mdi:update"
                                })
            return

        for name, pattern in self.patterns.items():
            best_start_morgen, best_cost_morgen = self.berechne_optimalen_start(forecast_morgen, pattern)
            sensor_morgen = f"sensor.spotty_optimaler_{name}_start_morgen"

            if best_start_morgen:
                self.set_state(sensor_morgen, state=best_start_morgen.isoformat(),
                                attributes={
                                    "device_class": "timestamp",
                                    "friendly_name": f"Optimaler Start {name} (morgen)",
                                    "icon": "mdi:update",
                                    "cost": round(best_cost_morgen, 2)
                                })
                self.log(f"{name} (morgen): optimaler Start {best_start_morgen}, Kosten {best_cost_morgen:.2f}")
            else:
                self.set_state(sensor_morgen, state="unknown")
                self.log(f"{name}: Kein optimaler Start (morgen) gefunden")

    # --------- sensoren auf unbekannt setzen --------- 
    def reset_morgen_sensors(self, kwargs):
        self.log("Mitternacht: Setze morgige Sensoren auf 'unknown'")
        for name in self.patterns.keys():
            sensor_morgen = f"sensor.spotty_optimaler_{name}_start_morgen"
            self.set_state(sensor_morgen, state="unknown",
                            attributes={
                                "device_class": "timestamp",
                                "friendly_name": f"Optimaler Start {name} (morgen)",
                                "icon": "mdi:update"
                            })
