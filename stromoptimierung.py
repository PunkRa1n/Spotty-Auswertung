import appdaemon.plugins.hass.hassapi as hass
import os
import pandas as pd
from datetime import timedelta


class Stromoptimierung(hass.Hass):

    def initialize(self):
        # Zeitzone: aus apps.yaml lesbar, sonst Default. Eine ECHTE IANA-Zone,
        # damit Sommer-/Winterzeit korrekt behandelt wird (kein fester Offset!).
        self.tz = self.args.get("timezone", "Europe/Berlin")

        # CSV-Ordner relativ zum Skript
        self.csv_patterns_folder = os.path.join(os.path.dirname(__file__), "csv_patterns")
        self.csv_forecast_folder = os.path.join(os.path.dirname(__file__), "csv_forecast")
        self.forecast_csv_file = os.path.join(self.csv_forecast_folder, "strompreise.csv")

        self.log(f"Stromoptimierung App gestartet (Zeitzone: {self.tz})")

        # --------- Muster (Leistungsprofile) initial laden ---------
        self.patterns = {}
        if not self.lade_muster():
            self.log("Keine gueltigen Muster beim Start. App wird beendet.", level="WARNING")
            self.stop_app(self.name)
            return

        # Erste Auswertungen direkt nach dem Start
        self.initial_auswertungen({})

        # --------- Scheduler NUR EINMAL registrieren ---------
        # Taegliche Auswertung kurz nach Mitternacht (heute)
        self.run_daily(self.auswerten, "00:00:30")
        # Um Mitternacht alle morgigen Sensoren zuruecksetzen
        self.run_daily(self.reset_morgen_sensors, "00:00:00")
        # Pruefung zwischen 13-15 Uhr, wenn neue Boersendaten fuer morgen kommen
        for stunde in [13, 14, 15]:
            self.run_daily(self.auswerten_morgen, f"{stunde:02d}:00:30")

        # --------- Knopf zum Neu-Einlesen der CSVs ---------
        # Lege in HA einen Helfer vom Typ "Knopf" mit dieser Entity-ID an:
        #   input_button.spotty_muster_neu_laden
        # Jeder Druck loest muster_neu_laden() aus (Timer bleiben unberuehrt).
        self.listen_state(self.muster_neu_laden, "input_button.spotty_muster_neu_laden")
        self.log("Bereit. Knopf 'input_button.spotty_muster_neu_laden' liest die CSVs neu ein.")

    # --------- Muster laden (von initialize UND vom Knopf genutzt) ---------
    def lade_muster(self):
        """Liest alle CSV-Profile neu ein. Registriert KEINE Scheduler.
        Gibt True zurueck, wenn mindestens ein gueltiges Muster geladen wurde.
        Bei Misserfolg bleiben die bisherigen Muster unveraendert."""
        if not os.path.exists(self.csv_patterns_folder):
            os.makedirs(self.csv_patterns_folder, exist_ok=True)
            self.log(f"Ordner {self.csv_patterns_folder} wurde erstellt.", level="INFO")

        csv_files = [f for f in os.listdir(self.csv_patterns_folder) if f.endswith(".csv")]
        if not csv_files:
            self.log(f"Keine CSV-Musterdateien im Ordner {self.csv_patterns_folder} gefunden.", level="WARNING")
            return False

        # In ein temporaeres Dict laden und erst bei Erfolg uebernehmen,
        # damit ein fehlgeschlagenes Neu-Einlesen die laufenden Muster nicht zerstoert.
        neue_patterns = {}
        for file in csv_files:
            name = file.replace(".csv", "")
            path = os.path.join(self.csv_patterns_folder, file)
            pattern = self.csv_to_pattern(path)
            if pattern:
                neue_patterns[name] = pattern
                self.log(f"[CSV] {name}: Profil geladen "
                         f"({pattern['length']} min, {pattern['energy_kwh']:.3f} kWh, "
                         f"Peak {max(pattern['profile']):.0f} W)")

        if not neue_patterns:
            self.log("Keine gueltigen Muster erkannt.", level="WARNING")
            return False

        self.patterns = neue_patterns
        self.log(f"Geraete-Muster geladen: {list(self.patterns.keys())}")
        return True

    # --------- Knopf-Callback: CSVs neu einlesen ---------
    def muster_neu_laden(self, entity, attribute, old, new, kwargs):
        self.log("Knopfdruck: CSV-Muster werden neu eingelesen ...")
        if self.lade_muster():
            self.initial_auswertungen({})
            self.log("Muster neu eingelesen und Auswertung aktualisiert.")
        else:
            self.log("Neu-Einlesen fehlgeschlagen - bisherige Muster bleiben aktiv.", level="WARNING")

    # --------- Initial beide Auswertungen ---------
    def initial_auswertungen(self, kwargs):
        self.log("Starte Initialauswertung: heute + morgen")
        self.auswerten({})
        self.auswerten_morgen({})

    # --------- CSV -> Leistungsprofil ---------
    def csv_to_pattern(self, file_path, idle_w=3.0):
        """Liest einen HA-Verlaufsexport und baut die echte Leistungskurve
        (W je Minute) ueber den aktiven Zeitraum. Behaelt die tatsaechliche
        Leistung pro Phase - keine Reduktion auf an/aus."""
        try:
            df = pd.read_csv(file_path)
        except Exception as e:
            self.log(f"CSV {file_path} nicht lesbar: {e}", level="ERROR")
            return None

        if "last_changed" not in df.columns or "state" not in df.columns:
            self.log(f"CSV {file_path} hat falsche Spalten!", level="ERROR")
            return None

        # HA-Exporte stehen in UTC (...Z). utc=True macht das Parsen robust,
        # auch wenn mal gemischte Offsets auftauchen.
        df["time"] = pd.to_datetime(df["last_changed"], utc=True, errors="coerce")
        df = df.dropna(subset=["time"])
        df["state"] = pd.to_numeric(df["state"], errors="coerce").fillna(0)

        if df.empty:
            self.log(f"[CSV] {os.path.basename(file_path)}: keine gueltigen Datenpunkte", level="WARNING")
            return None

        # Auf 1-Minuten-Raster mitteln -> Leistungskurve in W
        series = df.set_index("time").resample("1min")["state"].mean().fillna(0)

        # Aktiven Bereich zuschneiden: erster bis letzter Punkt ueber Standby.
        # Das macht das Profil unabhaengig davon, wann die Aufnahme gestartet
        # wurde (loest das Offset-Problem an der Wurzel).
        active = series[series > idle_w]
        if active.empty:
            self.log(f"[CSV] {os.path.basename(file_path)}: nie ueber {idle_w} W - verworfen", level="WARNING")
            return None

        # Echte Leistungskurve als reine Python-Liste (kein numpy noetig).
        profile = series.loc[active.index[0]:active.index[-1]].round(3).tolist()
        energy_kwh = sum(profile) / 1000.0 / 60.0  # W * min -> kWh

        name = os.path.basename(file_path).replace(".csv", "")
        self.log(f"[CSV] {name}: Profil {len(profile)} min erkannt")
        return {"profile": profile, "length": len(profile), "energy_kwh": energy_kwh}

    # --------- Forecast laden (DST-sicher) ---------
    def lade_forecast(self):
        try:
            df = pd.read_csv(self.forecast_csv_file)
            if "datetime" not in df.columns or "price" not in df.columns:
                self.log(f"Forecast {self.forecast_csv_file} falsche Spalten!", level="ERROR")
                return None

            # KERN-FIX: erst nach UTC (eindeutig, ueberlebt den Umstellungstag),
            # dann in die echte lokale Zeitzone. Damit stimmen Tagesgrenzen
            # ganzjaehrig, und gemischte Offsets crashen nicht mehr.
            df["time"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
            df = df.dropna(subset=["time"])
            df["time"] = df["time"].dt.tz_convert(self.tz)

            df["price"] = pd.to_numeric(df["price"], errors="coerce")
            df = df.dropna(subset=["price"])
            if df.empty:
                self.log("Forecast enthaelt keine gueltigen Zeilen", level="WARNING")
                return None

            df = df.set_index("time").sort_index()

            # Preis ist je 15-Min-Block konstant und springt an der Grenze.
            # ffill auf 1-Min bildet genau das ab: innerhalb des Blocks gleicher
            # Preis, an der Grenze sauberer Sprung.
            return df["price"].resample("1min").ffill()

        except Exception as e:
            self.log(f"Fehler beim Laden des Forecast: {e}", level="ERROR")
            return None

    # --------- Optimierung (leistungsgewichtet, ohne numpy) ---------
    def berechne_optimalen_start(self, forecast, pattern):
        """Sucht die Startminute mit den geringsten echten Kosten.
        cost(t0) = Summe ueber Profil-Minuten ( Leistung_i * Preis(t0+i) ).
        Rueckgabe: (Zeitstempel, Kosten in ct fuer einen Lauf)."""
        profile = pattern["profile"]
        prices = forecast.tolist()
        L = len(profile)
        N = len(prices)

        if L == 0 or L > N:
            return None, None

        # Gleitendes Skalarprodukt ueber alle gueltigen Startfenster.
        # range(N - L + 1) liefert genau alle Fenster -> kein off-by-one.
        best_cost = None
        best_k = 0
        for t0 in range(N - L + 1):
            cost = sum(w * p for w, p in zip(profile, prices[t0:t0 + L]))
            if best_cost is None or cost < best_cost:
                best_cost = cost
                best_k = t0

        cost_ct = best_cost / 1000.0 / 60.0  # W * ct/kWh -> ct fuer einen Lauf
        return forecast.index[best_k], cost_ct

    # --------- Hauptauswertung (heute) ---------
    def auswerten(self, kwargs):
        self.log("Auswertung gestartet (heute)")

        forecast = self.lade_forecast()
        if forecast is None or forecast.empty:
            self.log("Kein Forecast verfuegbar")
            return

        jetzt = pd.Timestamp.now(forecast.index.tz)
        heute_start = jetzt.normalize()
        morgen_start = heute_start + pd.Timedelta(days=1)

        forecast_heute = forecast[(forecast.index >= heute_start) & (forecast.index < morgen_start)]
        if forecast_heute.empty:
            self.log("Keine heutigen Forecast-Daten verfuegbar")
            return

        future_forecast = forecast_heute[forecast_heute.index > jetzt]

        for name, pattern in self.patterns.items():
            best_start, best_cost = self.berechne_optimalen_start(forecast_heute, pattern)

            next_start, next_cost = (None, None)
            if not future_forecast.empty:
                next_start, next_cost = self.berechne_optimalen_start(future_forecast, pattern)

            sensor_name = f"sensor.spotty_optimaler_{name}_start"

            if best_start is not None:
                attributes = {
                    "device_class": "timestamp",
                    "friendly_name": f"Optimaler Start {name}",
                    "energy_kwh": round(pattern["energy_kwh"], 3),
                    "duration_min": pattern["length"],
                    "cost_ct": round(best_cost, 2),
                }
                if next_start is not None:
                    attributes["next_start"] = next_start.isoformat()
                    attributes["next_cost_ct"] = round(next_cost, 2)

                self.set_state(sensor_name, state=best_start.isoformat(), attributes=attributes)
                self.log(f"{name}: optimaler Start (heute) {best_start}, Kosten: {best_cost:.2f} ct")
                if next_start is not None:
                    self.log(f"{name}: naechstmoeglicher Start {next_start}, Kosten: {next_cost:.2f} ct")
            else:
                self.set_state(sensor_name, state="unknown")
                self.log(f"{name}: kein optimaler Start gefunden")

    # --------- Auswertung fuer morgen ---------
    def auswerten_morgen(self, kwargs):
        self.log("Auswertung gestartet (morgen)")

        forecast = self.lade_forecast()
        if forecast is None or forecast.empty:
            self.log("Kein Forecast verfuegbar (morgen)")
            return

        jetzt = pd.Timestamp.now(forecast.index.tz)
        morgen_start = (jetzt + pd.Timedelta(days=1)).normalize()
        uebermorgen_start = morgen_start + pd.Timedelta(days=1)

        forecast_morgen = forecast[(forecast.index >= morgen_start) & (forecast.index < uebermorgen_start)]

        if forecast_morgen.empty:
            # Morgige Preise noch nicht bereitgestellt -> Sensoren auf unknown.
            self.log("Keine morgigen Forecast-Daten verfuegbar (noch nicht bereitgestellt).")
            self.reset_morgen_sensors({})
            return

        for name, pattern in self.patterns.items():
            best_start_morgen, best_cost_morgen = self.berechne_optimalen_start(forecast_morgen, pattern)
            sensor_morgen = f"sensor.spotty_optimaler_{name}_start_morgen"

            if best_start_morgen is not None:
                self.set_state(sensor_morgen, state=best_start_morgen.isoformat(),
                               attributes={
                                   "device_class": "timestamp",
                                   "friendly_name": f"Optimaler Start {name} (morgen)",
                                   "icon": "mdi:update",
                                   "energy_kwh": round(pattern["energy_kwh"], 3),
                                   "duration_min": pattern["length"],
                                   "cost_ct": round(best_cost_morgen, 2),
                               })
                self.log(f"{name} (morgen): optimaler Start {best_start_morgen}, Kosten: {best_cost_morgen:.2f} ct")
            else:
                self.set_state(sensor_morgen, state="unknown")
                self.log(f"{name}: Kein optimaler Start (morgen) gefunden")

    # --------- Morgige Sensoren auf unbekannt setzen ---------
    def reset_morgen_sensors(self, kwargs):
        self.log("Setze morgige Sensoren auf 'unknown'")
        for name in self.patterns.keys():
            sensor_morgen = f"sensor.spotty_optimaler_{name}_start_morgen"
            self.set_state(sensor_morgen, state="unknown",
                           attributes={
                               "device_class": "timestamp",
                               "friendly_name": f"Optimaler Start {name} (morgen)",
                               "icon": "mdi:update",
                               "cost_ct": "unknown",
                           })