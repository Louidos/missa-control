import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

import { Geraete } from "../src/geraete/Geraete";
import { type Faehigkeit, type Geraet, konfigDatei, type Kopplung, type Uebersicht } from "../src/geraete/geraete";
import type { KatalogEintrag } from "../src/integrationen/typen";
import { backend, TestFehler, zeige } from "./hilfen";

const KARTE: KatalogEintrag = {
  id: "geraet",
  name: "Gerät (ESP32, Pico)",
  beschreibung: "Einen Mikrocontroller per Kopplungscode anbinden.",
  symbol: "📟",
  art: "geraet",
  art_name: "Gerät",
  version: "1.0.0",
  mehrfach: true,
  hinweis: "",
  felder: [],
  eingebaut: true,
  eingerichtet: 0,
  verfuegbar: true,
  kann_hinzufuegen: true,
};
const KATALOG = { eintraege: [KARTE], probleme: [] };
const BROKER = { eingerichtet: true, verbunden: true, meldung: "Verbunden.", port: 1883 };

const KOPPLUNG: Kopplung = {
  benutzer: "geraet-0a1b2c3d",
  passwort: "pw-nur-einmal-sichtbar",
  port: 1883,
  themen: {
    basis: "missa/geraete/geraet-0a1b2c3d",
    status: "missa/geraete/geraet-0a1b2c3d/status",
    faehigkeiten: "missa/geraete/geraet-0a1b2c3d/faehigkeiten",
    wert: "missa/geraete/geraet-0a1b2c3d/wert/<fähigkeit>",
    ereignis: "missa/geraete/geraet-0a1b2c3d/ereignis/<fähigkeit>",
    zustand: "missa/geraete/geraet-0a1b2c3d/zustand/<fähigkeit>",
    befehl: "missa/geraete/geraet-0a1b2c3d/befehl/<fähigkeit>",
  },
};

function faehigkeit(teil: Partial<Faehigkeit>): Faehigkeit {
  return {
    id: "temperatur",
    art: "sensor",
    name: "Temperatur",
    typ: "zahl",
    einheit: "°C",
    wert: 21.5,
    zeit: "2026-11-10T10:00:00+00:00",
    funktion: "wohnzimmer_temperatur",
    funktion_name: "temperatur",
    recht: "erlaubt",
    ...teil,
  };
}

function geraet(teil: Partial<Geraet> = {}): Geraet {
  return {
    id: 7,
    name: "Wohnzimmer",
    aktiv: true,
    online: true,
    status_seit: "2026-11-10T09:00:00+00:00",
    zuletzt_gesehen: "2026-11-10T10:00:00+00:00",
    gekoppelt: "2026-11-09T18:00:00+00:00",
    firmware: "pico-beispiel 1.0",
    mqtt_benutzer: "geraet-0a1b2c3d",
    zugang_fehlt: false,
    problem: null,
    faehigkeiten: [
      faehigkeit({}),
      faehigkeit({ id: "knopf", art: "knopf", name: "Knopf", einheit: "", wert: "gedrueckt", funktion: null, funktion_name: null, recht: null }),
      faehigkeit({
        id: "led",
        art: "aktor",
        name: "LED",
        typ: "schalter",
        einheit: "",
        wert: 0,
        funktion: "wohnzimmer_led_schalten",
        funktion_name: "led_schalten",
        recht: "nachfragen",
      }),
    ],
    ...teil,
  };
}

function uebersicht(geraete: Geraet[], broker: Partial<Uebersicht["broker"]> = {}): Uebersicht {
  return { broker: { ...BROKER, ...broker }, geraete };
}

/** Fängt ab, was als Datei zum Speichern angeboten wird. */
function dateienAbfangen() {
  const dateien: { name: string; inhalt: Blob }[] = [];
  let letzte: Blob | null = null;
  URL.createObjectURL = vi.fn((inhalt: Blob | MediaSource) => {
    letzte = inhalt as Blob;
    return "blob:test";
  });
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    if (letzte) dateien.push({ name: this.download, inhalt: letzte });
  });
  return dateien;
}

test("Liste zeigt Status, letzte Werte und die Funktionen für Missa; ein Ausgang lässt sich schalten", async () => {
  let led = 0;
  const aufrufe = backend({
    "GET /api/geraete": () =>
      uebersicht([
        geraet({ faehigkeiten: geraet().faehigkeiten.map((f) => (f.id === "led" ? { ...f, wert: led } : f)) }),
        geraet({ id: 8, name: "Keller", online: false, status_seit: "2026-11-10T08:30:00+00:00", firmware: "", faehigkeiten: [faehigkeit({ funktion: "keller_temperatur" })] }),
        geraet({ id: 9, name: "Neu", online: false, status_seit: null, zuletzt_gesehen: null, firmware: "", faehigkeiten: [] }),
      ]),
    "GET /api/katalog": KATALOG,
    "POST /api/integrationen/7/aufrufen": () => {
      led = 1;
      return { ok: true, ergebnis: "„LED“ ist jetzt an." };
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Geraete />);

  const wohnzimmer = await screen.findByRole("region", { name: "Wohnzimmer" });
  expect(within(wohnzimmer).getByText("online")).toBeInTheDocument();
  expect(within(wohnzimmer).getByText(/Firmware pico-beispiel 1.0/)).toBeInTheDocument();
  expect(within(wohnzimmer).getByText("21.5 °C")).toBeInTheDocument();
  expect(within(wohnzimmer).getByText("wohnzimmer_temperatur")).toBeInTheDocument();
  expect(within(wohnzimmer).getByText(/· erlaubt/)).toBeInTheDocument();
  expect(within(wohnzimmer).getByText("wohnzimmer_led_schalten")).toBeInTheDocument();
  expect(within(wohnzimmer).getByText(/· erst nachfragen/)).toBeInTheDocument();
  expect(within(wohnzimmer).getByText("Jeder Druck wird zum Ereignis für Missa.")).toBeInTheDocument();
  expect(within(wohnzimmer).getByText("aus")).toBeInTheDocument();

  const keller = screen.getByRole("region", { name: "Keller" });
  expect(within(keller).getByText("offline")).toBeInTheDocument();
  expect(within(keller).getByText(/zuletzt gesehen/)).toBeInTheDocument();
  const neu = screen.getByRole("region", { name: "Neu" });
  expect(within(neu).getByText("wartet auf das Gerät")).toBeInTheDocument();
  expect(within(neu).getByText(/hat sich noch nicht gemeldet/)).toBeInTheDocument();

  await nutzer.click(within(wohnzimmer).getByRole("button", { name: "Einschalten" }));
  expect(await within(wohnzimmer).findByText("„LED“ ist jetzt an.")).toBeInTheDocument();
  expect(aufrufe.find((aufruf) => aufruf.methode === "POST")?.koerper).toEqual({ funktion: "led_schalten", argumente: { an: true } });
  await waitFor(() => expect(within(wohnzimmer).getByRole("button", { name: "Einschalten" })).toHaveAttribute("aria-pressed", "true"));
});

test("Ist ein Gerät offline, lässt sich nichts schalten; Fehler des Geräts werden gezeigt", async () => {
  backend({
    "GET /api/geraete": uebersicht([
      geraet({ online: false, zugang_fehlt: true, problem: "Das Gerät meldet seine Fähigkeiten in einer ungültigen Form: Die Meldung ist kein gültiges JSON." }),
    ]),
    "GET /api/katalog": KATALOG,
  });
  zeige(<Geraete />);

  const karte = await screen.findByRole("region", { name: "Wohnzimmer" });
  expect(within(karte).getByRole("button", { name: "Einschalten" })).toBeDisabled();
  expect(within(karte).getByRole("button", { name: "Einschalten" })).toHaveAttribute("title", "Das Gerät ist offline.");
  expect(within(karte).getByText(/Der Zugang dieses Geräts am MQTT-Broker fehlt/)).toBeInTheDocument();
  expect(within(karte).getByText(/kein gültiges JSON/)).toBeInTheDocument();
});

test("Verlauf eines Sensors: 7 Tage als Diagramm, anderer Zeitraum und Tabelle", async () => {
  const jetzt = Date.now();
  const punkte = [20.4, 21, 23.6].map((wert, index) => ({ zeit: new Date(jetzt - (3 - index) * 1_800_000).toISOString(), wert }));
  const aufrufe = backend({
    "GET /api/geraete": uebersicht([geraet()]),
    "GET /api/katalog": KATALOG,
    "GET /api/geraete/7/verlauf?faehigkeit=temperatur&zeitraum=7t": { verlauf: punkte, zeitraum: "7t" },
    "GET /api/geraete/7/verlauf?faehigkeit=temperatur&zeitraum=1h": { verlauf: [], zeitraum: "1h" },
  });
  const nutzer = userEvent.setup();
  zeige(<Geraete />);

  const knopf = await screen.findByRole("button", { name: "Verlauf von Temperatur" });
  expect(screen.queryByRole("button", { name: "Verlauf von Knopf" })).not.toBeInTheDocument();
  await nutzer.click(knopf);
  const diagramm = await screen.findByRole("img", { name: /Temperatur: Verlauf, zuletzt 23.6 °C/ });
  expect(screen.getByRole("radio", { name: "7 Tage" })).toBeChecked();
  // Die Achse richtet sich nach den Werten (20 … 24) statt bei 0 zu beginnen.
  expect(within(diagramm).getByText("20")).toBeInTheDocument();
  expect(within(diagramm).getByText("24")).toBeInTheDocument();
  expect(within(diagramm).queryByText("0")).not.toBeInTheDocument();

  await nutzer.click(screen.getByRole("button", { name: "Als Tabelle anzeigen" }));
  expect(screen.getAllByRole("row")).toHaveLength(4);
  expect(screen.getByRole("cell", { name: "23.6 °C" })).toBeInTheDocument();

  await nutzer.click(screen.getByRole("radio", { name: "1 Stunde" }));
  expect(await screen.findByText("Noch keine Messwerte in diesem Zeitraum.")).toBeInTheDocument();
  expect(aufrufe.some((aufruf) => aufruf.pfad.endsWith("zeitraum=1h"))).toBe(true);
});

test("Gerät hinzufügen: Name, testen, aktivieren – danach die fertige Konfiguration herunterladen", async () => {
  const dateien = dateienAbfangen();
  let geraete: Geraet[] = [];
  const aufrufe = backend({
    "GET /api/geraete": () => uebersicht(geraete),
    "GET /api/katalog": KATALOG,
    "GET /api/integrationen": [],
    "POST /api/integrationen/testen": {
      ok: true,
      test_id: "t1",
      meldung: "Der MQTT-Broker ist bereit.",
      details: [],
      optionen: {},
      viele_funktionen: false,
      funktionen: [],
    },
    "POST /api/integrationen": (koerper) => {
      const name = (koerper as { name: string }).name;
      geraete = [geraet({ name, online: false, status_seit: null, zuletzt_gesehen: null, firmware: "", faehigkeiten: [] })];
      return { id: 7, manifest_id: "geraet", name, kennung: "wohnzimmer", symbol: "📟", funktionen: [], kopplung: KOPPLUNG };
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Geraete />);

  expect(await screen.findByText("Noch kein Gerät")).toBeInTheDocument();
  await nutzer.click(screen.getByRole("button", { name: "Gerät hinzufügen" }));
  const dialog = screen.getByRole("dialog");
  await nutzer.clear(within(dialog).getByLabelText("Name"));
  await nutzer.type(within(dialog).getByLabelText("Name"), "Wohnzimmer");
  await nutzer.click(within(dialog).getByRole("button", { name: "Verbindung testen" }));
  expect(await within(dialog).findByText(/Ein Gerät sagt beim ersten Verbinden selbst, was es kann/)).toBeInTheDocument();
  await nutzer.click(within(dialog).getByRole("button", { name: "Aktivieren" }));

  expect(await within(dialog).findByText("„Wohnzimmer“ ist angelegt")).toBeInTheDocument();
  expect(within(dialog).getByText(/Das Passwort des Geräts ist nur jetzt zu sehen/)).toBeInTheDocument();
  expect(within(dialog).getByRole("link", { name: "Zu den Geräten" })).toHaveAttribute("href", "/geraete");
  expect(aufrufe.find((aufruf) => aufruf.methode === "POST" && aufruf.pfad === "/api/integrationen")?.koerper).toMatchObject({
    manifest_id: "geraet",
    name: "Wohnzimmer",
    test_id: "t1",
  });

  // Ohne Adresse und WLAN-Name gibt es noch nichts herunterzuladen (im Test läuft das Panel auf „localhost“).
  const laden = within(dialog).getByRole("button", { name: "config.py herunterladen" });
  expect(laden).toBeDisabled();
  await nutzer.type(within(dialog).getByLabelText("Adresse dieses Servers im WLAN"), "192.168.1.10");
  await nutzer.type(within(dialog).getByLabelText("WLAN-Name"), "Heimnetz");
  await nutzer.type(within(dialog).getByLabelText("WLAN-Passwort"), 'geheim"1');
  await nutzer.click(laden);
  expect(dateien).toHaveLength(1);
  expect(dateien[0].name).toBe("config.py");
  const python = await dateien[0].inhalt.text();
  expect(python).toContain('WLAN_NAME = "Heimnetz"');
  expect(python).toContain('WLAN_PASSWORT = "geheim\\"1"');
  expect(python).toContain('MQTT_HOST = "192.168.1.10"');
  expect(python).toContain("MQTT_PORT = 1883");
  expect(python).toContain('MQTT_BENUTZER = "geraet-0a1b2c3d"');
  expect(python).toContain('MQTT_PASSWORT = "pw-nur-einmal-sichtbar"');
  expect(python).toContain("KNOPF_PIN = 15");
  expect(within(dialog).getByText(/Heruntergeladen\. Kopiere config\.py zusammen mit main\.py auf den Pico\./)).toBeInTheDocument();

  await nutzer.selectOptions(within(dialog).getByLabelText("Board"), "ESP32 (Arduino)");
  await nutzer.click(within(dialog).getByRole("button", { name: "config.h herunterladen" }));
  expect(dateien[1].name).toBe("config.h");
  const c = await dateien[1].inhalt.text();
  expect(c).toContain('#define WLAN_PASSWORT "geheim\\"1"');
  expect(c).toContain('#define MQTT_BENUTZER "geraet-0a1b2c3d"');
  expect(c).toContain("#define LED_PIN 2");

  // Für eigene Firmware stehen die Zugangsdaten und Themen einzeln da.
  expect(within(dialog).getByLabelText("Passwort")).toHaveValue("pw-nur-einmal-sichtbar");
  expect(dialog).toHaveTextContent("missa/geraete/geraet-0a1b2c3d/befehl/<fähigkeit> ← Befehl an einen Aktor");

  await nutzer.click(within(dialog).getByRole("button", { name: "Fertig" }));
  expect(await screen.findByRole("region", { name: "Wohnzimmer" })).toBeInTheDocument();
});

test("Neu koppeln zeigt neue Zugangsdaten; Entfernen fragt nach", async () => {
  let geraete = [geraet()];
  const aufrufe = backend({
    "GET /api/geraete": () => uebersicht(geraete),
    "GET /api/katalog": KATALOG,
    "POST /api/geraete/7/koppeln": { ...KOPPLUNG, passwort: "neues-passwort" },
    "DELETE /api/integrationen/7": () => {
      geraete = [];
      return { ok: true };
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Geraete />);

  await nutzer.click(await screen.findByRole("button", { name: "Neu koppeln" }));
  let dialog = screen.getByRole("dialog", { name: "Gerät neu koppeln?" });
  expect(within(dialog).getByText(/Die bisherigen gelten sofort nicht mehr/)).toBeInTheDocument();
  await nutzer.click(within(dialog).getByRole("button", { name: "Neu koppeln" }));
  dialog = await screen.findByRole("dialog", { name: "Neue Zugangsdaten für „Wohnzimmer“" });
  expect(within(dialog).getByLabelText("Passwort")).toHaveValue("neues-passwort");
  await nutzer.click(within(dialog).getByRole("button", { name: "Fertig" }));

  await nutzer.click(screen.getByRole("button", { name: "Wohnzimmer entfernen" }));
  dialog = screen.getByRole("dialog", { name: "Gerät entfernen?" });
  await nutzer.click(within(dialog).getByRole("button", { name: "Entfernen" }));
  expect(await screen.findByText("Noch kein Gerät")).toBeInTheDocument();
  expect(aufrufe.some((aufruf) => aufruf.methode === "DELETE" && aufruf.pfad === "/api/integrationen/7")).toBe(true);
});

test("Ohne MQTT-Broker: verständlicher Hinweis, Hinzufügen ist gesperrt", async () => {
  let broker: Partial<Uebersicht["broker"]> = { eingerichtet: false, verbunden: false, meldung: "Der MQTT-Broker für Geräte ist nicht eingerichtet." };
  backend({ "GET /api/geraete": () => uebersicht([], broker), "GET /api/katalog": KATALOG });
  const { unmount } = zeige(<Geraete />);

  expect(await screen.findByText("Der MQTT-Broker für Geräte ist nicht eingerichtet.")).toBeInTheDocument();
  expect(screen.getByText(/COMPOSE_PROFILES=geraete/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Gerät hinzufügen" })).toBeDisabled();
  unmount();

  broker = { eingerichtet: true, verbunden: false, meldung: "Die Verbindung zum MQTT-Broker ist unterbrochen und wird neu aufgebaut." };
  zeige(<Geraete />);
  expect(await screen.findByText(/ist unterbrochen und wird neu aufgebaut/)).toBeInTheDocument();
  expect(screen.getByText("Prüfen mit: docker compose -p missa-control ps – starten mit: ./scripts/install.sh")).toBeInTheDocument();
});

test("Fehler beim Laden werden angezeigt", async () => {
  backend({ "GET /api/geraete": new TestFehler(500, "Die Geräte lassen sich nicht laden."), "GET /api/katalog": KATALOG });
  zeige(<Geraete />);
  expect(await screen.findByText("Die Geräte lassen sich nicht laden.")).toBeInTheDocument();
});

test("Konfigurationsdatei: Sonderzeichen im WLAN-Passwort bleiben gültiger Python- bzw. C-Text", () => {
  const eingabe = { host: "ai01.lan", wlanName: "Café \\ Netz", wlanPasswort: 'a"b\\c\td' };
  const python = konfigDatei("pico", "Wohn\nzimmer", KOPPLUNG, eingabe);
  expect(python.split("\n")[0]).toBe("# Konfiguration für das Gerät „Wohn zimmer“ – erzeugt von Missa Control.");
  expect(python).toContain('WLAN_NAME = "Café \\\\ Netz"');
  expect(python).toContain('WLAN_PASSWORT = "a\\"b\\\\c\\x09d"');
  const c = konfigDatei("esp32", "Wohnzimmer", KOPPLUNG, eingabe);
  expect(c).toContain('#define WLAN_PASSWORT "a\\"b\\\\c\\011d"');
  expect(c).toContain('#define MQTT_HOST "ai01.lan"');
  expect(c).toContain("#define MQTT_PORT 1883");
});
