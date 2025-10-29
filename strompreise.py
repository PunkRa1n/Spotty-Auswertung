import appdaemon.plugins.hass.hassapi as hass
import json
import requests
from datetime import datetime, timedelta, timezone
import csv
import os


class Strompreise(hass.Hass):

    def initialize(self):
        self.log("Strompreis App gestartet")
        self.url = self.args.get("url", "http://localhost:8000/")
        self.report_time = self.args["report_time"]



        # Wenn der Schwellenwert in HA geändert wird → neu auswerten
        self.listen_state(self.schwelle_geaendert, "input_number.spotty_strompreis_schwelle_prozent")

        # Erste Auswertung sofort starten
        self.auswerten({})
        #self.tagesbericht({})

        # Alle 15 Minuten neu auswerten
        jetzt = datetime.now()
        minuten = ((jetzt.minute // 15) + 1) * 15
        stunde = jetzt.hour
        tag = jetzt.date()

        if minuten >= 60:
            minuten = 0
            stunde += 1
            if stunde >= 24:
                stunde = 0
                tag += timedelta(days=1)

        startzeit = datetime.combine(tag, datetime.min.time()).replace(hour=stunde, minute=minuten, second=5)
        self.run_every(self.auswerten, startzeit, 15 * 60)

        # Täglicher Bericht
        report_time = datetime.strptime(self.report_time, "%H:%M").time()
        self.run_daily(self.tagesbericht, report_time)
        


    def schwelle_geaendert(self, entity, attribute, old, new, kwargs):
        self.auswerten({})


    def auswerten(self, kwargs):
        self.log("Spotty wird abgefragt...")
        try:
            headers = {
                "User-Agent":   "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
                                "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
            }
            response = requests.get(self.url, timeout=5, headers=headers)
            response.raise_for_status()
            data = response.json()

            if not data:
                self.log("Keine Daten empfangen", level="WARNING")
                return

            now = datetime.now(timezone.utc).astimezone()
            heute = now.date()
            morgen = heute + timedelta(days=1)

            # ✅ Daten für heute UND morgen
            daten_von_heute_und_morgen = [
                eintrag for eintrag in data
                if datetime.fromisoformat(eintrag["from"]).astimezone().date() in (heute, morgen)
            ]

            if not daten_von_heute_und_morgen:
                self.log("Keine Preisdaten für heute oder morgen gefunden", level="WARNING")
                return

            # --- CSV exportieren für andere App (nur bei Änderungen) ---
            forecast_csv_folder = os.path.join(os.path.dirname(__file__), "csv_forecast")
            os.makedirs(forecast_csv_folder, exist_ok=True)
            forecast_csv_file = os.path.join(forecast_csv_folder, "strompreise.csv")
            
            # Neue CSV-Daten aufbereiten (sortiert, rund auf 2 Dezimalstellen)
            neue_daten = [
                (
                    datetime.fromisoformat(e["from"]).astimezone().replace(second=0, microsecond=0).isoformat(),
                    round(e["price"], 2),
                )
                for e in daten_von_heute_und_morgen
            ]
            neue_daten.sort()
            
            # Alte CSV lesen, falls vorhanden
            alte_daten = []
            if os.path.exists(forecast_csv_file):
                with open(forecast_csv_file, "r", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    next(reader, None)  # Header überspringen
                    for row in reader:
                        if len(row) == 2:
                            alte_daten.append((row[0], float(row[1])))
            
            # Prüfen, ob sich was geändert hat
            if neue_daten != alte_daten:
                with open(forecast_csv_file, "w", newline="", encoding="utf-8") as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow(["datetime", "price"])
                    writer.writerows(neue_daten)
                self.log(f"Forecast CSV aktualisiert: {forecast_csv_file} ({len(neue_daten)} Einträge)")
            else:
                self.log("Forecast CSV unverändert – kein Schreibvorgang nötig.")



            # Filtere nur heutige Daten für HA-Sensoren
            daten_von_heute = [
                e for e in daten_von_heute_und_morgen
                if datetime.fromisoformat(e["from"]).astimezone().date() == heute
            ]

            if not daten_von_heute:
                self.log("Keine heutigen Preisdaten gefunden – Sensoren werden nicht aktualisiert", level="WARNING")
                return

            # Niedrigster & Höchster Preis
            niedrigster = min(daten_von_heute, key=lambda x: x["price"])
            hoechster = max(daten_von_heute, key=lambda x: x["price"])

            # Aktuelles und nächstes Intervall bestimmen
            minute = (now.minute // 15) * 15
            aktuelles_intervall = now.replace(minute=minute, second=0, microsecond=0)
            naechstes_intervall = aktuelles_intervall + timedelta(minutes=15)

            aktueller_preis = None
            naechster_preis = None
            for e in daten_von_heute:
                zeitpunkt = datetime.fromisoformat(e["from"]).astimezone()
                if zeitpunkt == aktuelles_intervall:
                    aktueller_preis = e["price"]
                if zeitpunkt == naechstes_intervall:
                    naechster_preis = e["price"]

            # Sensoren aktualisieren
            if aktueller_preis is not None:
                self.set_state("sensor.spotty_aktueller_strompreis", state=round(aktueller_preis, 2),
                                attributes={"unit_of_measurement": "ct/kWh"})
                self.set_state("sensor.spotty_aktueller_strompreis_eur", state=round(aktueller_preis / 100, 4),
                                attributes={"unit_of_measurement": "EUR/kWh","icon": "mdi:set-none"})

            if naechster_preis is not None:
                self.set_state("sensor.spotty_naechster_strompreis", state=round(naechster_preis, 2),
                                attributes={"unit_of_measurement": "ct/kWh"})

            # Extremwerte
            self.set_state("sensor.spotty_niedrigster_strompreis_wert", state=round(niedrigster["price"], 2),
                            attributes={"unit_of_measurement": "ct/kWh"})
            self.set_state("sensor.spotty_niedrigster_strompreis_zeit", state=niedrigster["from"],
                            attributes={"device_class": "timestamp"})
            self.set_state("sensor.spotty_hoechster_strompreis_wert", state=round(hoechster["price"], 2),
                            attributes={"unit_of_measurement": "ct/kWh"})
            self.set_state("sensor.spotty_hoechster_strompreis_zeit", state=hoechster["from"],
                            attributes={"device_class": "timestamp"})

            # Binärsensor für günstigstes Intervall
            guenstigste_zeit = datetime.fromisoformat(niedrigster["from"]).replace(second=0, microsecond=0)
            ist_jetzt = aktuelles_intervall == guenstigste_zeit
            self.set_state("binary_sensor.spotty_guenstigstes_stromintervall",
                            state="on" if ist_jetzt else "off",
                            attributes={"friendly_name": "Günstigstes Stromintervall", "icon": "mdi:clock-check-outline"})

            # Dynamischer Schwellenwert
            preise = [e["price"] for e in daten_von_heute]
            prozentschwelle = self.get_state("input_number.spotty_strompreis_schwelle_prozent")
            try:
                prozentschwelle = float(prozentschwelle)
            except (TypeError, ValueError):
                self.log("Ungültiger Schwellenwert, benutze 25%", level="WARNING")
                prozentschwelle = 25.0

            preise_sortiert = sorted(preise)
            index = int(len(preise_sortiert) * prozentschwelle / 100)
            index = min(index, len(preise_sortiert) - 1)
            schwelle = preise_sortiert[index]

            self.set_state("sensor.spotty_schwelle", state=round(schwelle, 2),
                            attributes={"unit_of_measurement": "ct/kWh"})

            # Längster günstiger Zeitraum
            aktueller_block = []
            bester_block = []

            for e in daten_von_heute:
                if e["price"] <= schwelle:
                    aktueller_block.append(e)
                else:
                    if len(aktueller_block) > len(bester_block):
                        bester_block = aktueller_block
                    elif len(aktueller_block) == len(bester_block) and len(aktueller_block) > 0:
                        avg_curr = sum(x["price"] for x in aktueller_block) / len(aktueller_block)
                        avg_best = sum(x["price"] for x in bester_block) / len(bester_block)
                        if avg_curr < avg_best:
                            bester_block = aktueller_block
                    aktueller_block = []

            if len(aktueller_block) > len(bester_block):
                bester_block = aktueller_block

            if bester_block:
                best_start = datetime.fromisoformat(bester_block[0]["from"]).astimezone()
                best_end = best_start + timedelta(minutes=15 * len(bester_block))
                avg_block = sum(e["price"] for e in bester_block) / len(bester_block)

                self.set_state("sensor.spotty_laengster_guenstiger_zeitraum_start", state=best_start.isoformat(), attributes={"device_class": "timestamp"})
                self.set_state("sensor.spotty_laengster_guenstiger_zeitraum_ende", state=best_end.isoformat(), attributes={"device_class": "timestamp"})
                self.set_state("sensor.spotty_laengster_guenstiger_zeitraum_dauer", state=len(bester_block) * 15,
                                attributes={"unit_of_measurement": "min"})
                self.set_state("sensor.spotty_guenstigster_durchschnittspreis", state=round(avg_block, 2),
                                attributes={"unit_of_measurement": "ct/kWh"})

                self.set_state("binary_sensor.spotty_guenstiger_zeitraum_aktiv",
                                state="on" if best_start <= now < best_end else "off")
            else:
                self.set_state("binary_sensor.spotty_guenstiger_zeitraum_aktiv", state="off")

            # Forecast-Sensor (Plotly-Card)
            forecast_data = [
                {
                    "datetime": datetime.fromisoformat(e["from"]).astimezone().isoformat(),
                    "price": round(e["price"], 2)
                }
                for e in daten_von_heute
                if datetime.fromisoformat(e["from"]).astimezone() >= now
            ]
            forecast_state = forecast_data[0]["price"] if forecast_data else None

            self.set_state("sensor.spotty_forecast",
                            state=forecast_state,
                            attributes={"unit_of_measurement": "ct/kWh", "forecast": forecast_data})

            self.log("Abfrage abgeschlossen.")

        except Exception as e:
            self.log(f"Fehler beim Abrufen/Auswerten: {e}", level="ERROR")

    # TODO: notwendig?
    def benachrichtigen_vorwarnung(self, eintrag, typ, jetzt):
        """Sendet 15 Minuten vor günstigstem/teuerstem Preis eine Benachrichtigung."""
        zeitpunkt = datetime.fromisoformat(eintrag["from"]).astimezone()
        zielzeit = zeitpunkt - timedelta(minutes=15)
        if abs((jetzt - zielzeit).total_seconds()) < 60:
            preis = round(eintrag["price"], 2)
            if typ == "günstig":
                self.call_service("notify/notify", title="⚡ Bald günstigster Strompreis",
                                    message=f"In 15 Minuten ist der günstigste Preis: {preis} ct/kWh",
                                    data={"tag": "spotty-soon-cheap"}
                                    )
            else:
                self.call_service("notify/notify", title="⚠️ Bald teuerster Strompreis",
                                    message=f"In 15 Minuten ist der höchste Preis: {preis} ct/kWh",
                                    data={"tag": "spotty-soon-expensive"}
                                    )


    def tagesbericht(self, kwargs):
        """Tägliche Übersicht der Strompreise versenden."""
        niedrig = self.get_state("sensor.spotty_niedrigster_strompreis_wert")
        tiefzeit = self.get_state("sensor.spotty_niedrigster_strompreis_zeit")
        hoch = self.get_state("sensor.spotty_hoechster_strompreis_wert")
        hochzeit = self.get_state("sensor.spotty_hoechster_strompreis_zeit")

        if not (niedrig and hoch and tiefzeit and hochzeit):
            self.log("Kein vollständiger Tagesbericht möglich (fehlende Daten)", level="WARNING")
            return

        nachricht = (
            f"• Tief: {niedrig} ct/kWh um {tiefzeit[11:16]} Uhr\n"
            f"• Hoch: {hoch} ct/kWh um {hochzeit[11:16]} Uhr"
        )
        self.log("Sende Benachrichtugung mittels dienst Notify.Notify")

# https://companion.home-assistant.io/docs/notifications/notifications-basic/#replacing
        self.call_service("notify/notify",  title="🔎 Strompreis-Übersicht",
                                            message=nachricht,
                                            data={"tag": "spotty-daily-report"}
                                            )
