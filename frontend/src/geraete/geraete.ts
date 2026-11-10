import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "../api";
import type { Recht } from "../integrationen/typen";
import type { Zeitraum } from "../serverlast/serverlast";

/** Die Zugangsdaten eines Geräts. Das Passwort gibt es nur ein einziges Mal: direkt nach dem Koppeln. */
export interface Kopplung {
  benutzer: string;
  passwort: string;
  port: number;
  themen: Record<"basis" | "status" | "faehigkeiten" | "wert" | "ereignis" | "zustand" | "befehl", string>;
}

export interface Faehigkeit {
  id: string;
  art: "sensor" | "knopf" | "aktor";
  name: string;
  typ: "zahl" | "schalter" | "text";
  einheit: string;
  min?: number;
  max?: number;
  wert: number | string | null;
  zeit: string | null;
  /** Name der Funktion, unter dem Missa sie sieht – Knöpfe haben keine. */
  funktion: string | null;
  funktion_name: string | null;
  recht: Recht | null;
}

export interface Geraet {
  id: number;
  name: string;
  aktiv: boolean;
  online: boolean;
  status_seit: string | null;
  zuletzt_gesehen: string | null;
  gekoppelt: string | null;
  firmware: string;
  mqtt_benutzer: string;
  /** Der Zugang am Broker fehlt (z. B. nach dem Zurücksetzen des Brokers): neu koppeln. */
  zugang_fehlt: boolean;
  problem: string | null;
  faehigkeiten: Faehigkeit[];
}

export interface Uebersicht {
  broker: { eingerichtet: boolean; verbunden: boolean; meldung: string; port: number };
  geraete: Geraet[];
}

export interface Messpunkt {
  zeit: string;
  wert: number;
}

export const GERAETE = ["geraete"] as const;

export function useGeraete() {
  // Alle 5 Sekunden nachsehen: So erscheint ein Gerät von selbst als online bzw. offline.
  return useQuery({ queryKey: GERAETE, queryFn: () => api.get<Uebersicht>("/api/geraete"), refetchInterval: 5_000 });
}

export function useVerlauf(geraetId: number, faehigkeit: string, zeitraum: Zeitraum) {
  return useQuery({
    queryKey: [...GERAETE, geraetId, "verlauf", faehigkeit, zeitraum],
    queryFn: () =>
      api.get<{ verlauf: Messpunkt[]; zeitraum: Zeitraum }>(
        `/api/geraete/${geraetId}/verlauf?faehigkeit=${encodeURIComponent(faehigkeit)}&zeitraum=${zeitraum}`,
      ),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
}

/** „21,5 °C“, „an“/„aus“ bei Schaltern, „–“ ohne Wert. */
export function wertText(faehigkeit: Pick<Faehigkeit, "typ" | "einheit">, wert: number | string | null | undefined): string {
  if (wert === null || wert === undefined) return "–";
  if (typeof wert === "string") return wert;
  if (faehigkeit.typ === "schalter") return wert ? "an" : "aus";
  const zahl = wert.toLocaleString("de-CH", { maximumFractionDigits: 2 });
  return faehigkeit.einheit ? `${zahl} ${faehigkeit.einheit}` : zahl;
}

export type Board = "pico" | "esp32";

export const BOARDS: { wert: Board; titel: string; datei: string; ordner: string; ablegen: string }[] = [
  {
    wert: "pico",
    titel: "Raspberry Pi Pico 2 W (MicroPython)",
    datei: "config.py",
    ordner: "examples/geraete/pico-micropython",
    ablegen: "Kopiere config.py zusammen mit main.py auf den Pico.",
  },
  {
    wert: "esp32",
    titel: "ESP32 (Arduino)",
    datei: "config.h",
    ordner: "examples/geraete/esp32-arduino",
    ablegen: "Lege config.h neben esp32-arduino.ino und lade den Sketch auf den ESP32.",
  },
];

/** Ein Text als Zeichenkette für Python bzw. C – auch wenn im WLAN-Passwort Anführungszeichen stecken. */
function zeichenkette(wert: string, sprache: "python" | "c"): string {
  let ergebnis = '"';
  for (const zeichen of wert) {
    const code = zeichen.codePointAt(0) ?? 0;
    if (zeichen === "\\" || zeichen === '"') ergebnis += `\\${zeichen}`;
    else if (code < 0x20 || code === 0x7f) {
      ergebnis += sprache === "python" ? `\\x${code.toString(16).padStart(2, "0")}` : `\\${code.toString(8).padStart(3, "0")}`;
    } else ergebnis += zeichen;
  }
  return `${ergebnis}"`;
}

export interface KonfigEingabe {
  /** Adresse von ai01, wie das Gerät sie im WLAN erreicht. */
  host: string;
  wlanName: string;
  wlanPasswort: string;
}

/**
 * Die fertig ausgefüllte Konfigurationsdatei für die Beispiel-Firmware (config.py bzw. config.h).
 * Sie entsteht im Browser: WLAN-Name und -Passwort verlassen ihn nicht.
 */
export function konfigDatei(board: Board, geraetName: string, kopplung: Kopplung, eingabe: KonfigEingabe): string {
  const name = geraetName.replace(/\s+/g, " ").trim();
  if (board === "pico") {
    const text = (wert: string) => zeichenkette(wert, "python");
    return [
      `# Konfiguration für das Gerät „${name}“ – erzeugt von Missa Control.`,
      "# Enthält Passwörter: nicht weitergeben und nicht ins Repo legen.",
      "",
      `WLAN_NAME = ${text(eingabe.wlanName)}`,
      `WLAN_PASSWORT = ${text(eingabe.wlanPasswort)}`,
      "",
      `MQTT_HOST = ${text(eingabe.host)}  # Adresse von ai01 im Geräte-Netz`,
      `MQTT_PORT = ${kopplung.port}`,
      `MQTT_BENUTZER = ${text(kopplung.benutzer)}`,
      `MQTT_PASSWORT = ${text(kopplung.passwort)}`,
      "",
      "KNOPF_PIN = 15  # Taster zwischen GP15 und GND",
      "",
    ].join("\n");
  }
  const text = (wert: string) => zeichenkette(wert, "c");
  return [
    `// Konfiguration für das Gerät „${name}“ – erzeugt von Missa Control.`,
    "// Enthält Passwörter: nicht weitergeben und nicht ins Repo legen.",
    "",
    `#define WLAN_NAME ${text(eingabe.wlanName)}`,
    `#define WLAN_PASSWORT ${text(eingabe.wlanPasswort)}`,
    "",
    `#define MQTT_HOST ${text(eingabe.host)}  // Adresse von ai01 im Geräte-Netz`,
    `#define MQTT_PORT ${kopplung.port}`,
    `#define MQTT_BENUTZER ${text(kopplung.benutzer)}`,
    `#define MQTT_PASSWORT ${text(kopplung.passwort)}`,
    "",
    "#define KNOPF_PIN 0  // BOOT-Taste der meisten ESP32-Boards",
    "#define LED_PIN 2    // eingebaute LED vieler ESP32-Boards",
    "",
  ].join("\n");
}

/** Bietet einen Text als Datei zum Speichern an. */
export function herunterladen(dateiname: string, inhalt: string): void {
  const adresse = URL.createObjectURL(new Blob([inhalt], { type: "text/plain;charset=utf-8" }));
  const verweis = document.createElement("a");
  verweis.href = adresse;
  verweis.download = dateiname;
  document.body.appendChild(verweis);
  verweis.click();
  verweis.remove();
  URL.revokeObjectURL(adresse);
}
