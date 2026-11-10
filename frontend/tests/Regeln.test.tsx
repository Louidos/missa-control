import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import { Regeln } from "../src/regeln/Regeln";
import type { Ausloesung, Optionen, Regel } from "../src/regeln/regeln";
import { backend, TestFehler, zeige } from "./hilfen";

const OPTIONEN: Optionen = {
  ausloeser: [
    { wert: "zeitplan", titel: "Zeitplan" },
    { wert: "messwert", titel: "Messwert über oder unter einer Schwelle" },
    { wert: "geraet", titel: "Gerät meldet etwas" },
    { wert: "webhook", titel: "Webhook geht ein" },
    { wert: "integration_ausgefallen", titel: "Integration ausgefallen" },
  ],
  aktionen: [
    { wert: "ereignis", titel: "Ereignis an Missa" },
    { wert: "funktion", titel: "Funktion einer Integration aufrufen" },
  ],
  messwerte: [
    { kennung: "cpu", titel: "CPU-Auslastung", einheit: "%", verfuegbar: true },
    { kennung: "ram", titel: "Arbeitsspeicher", einheit: "%", verfuegbar: true },
    { kennung: "gpu", titel: "GPU-Auslastung", einheit: "%", verfuegbar: false },
  ],
  integrationen: [{ id: 3, name: "Lampe" }],
  webhooks: [],
  geraete: [],
  funktionen: [
    {
      name: "lampe_schalten",
      integration: "Lampe",
      beschreibung: "Schaltet die Lampe.",
      recht: "nachfragen",
      parameter: {
        properties: {
          an: { type: "boolean", description: "Ein oder aus" },
          farbe: { type: "string", default: "weiss" },
          helligkeit: { anyOf: [{ type: "integer" }, { type: "null" }] },
          modus: { enum: ["dauer", "blinken"], type: "string" },
        },
        required: ["an"],
      },
    },
  ],
  dringlichkeiten: ["niedrig", "normal", "hoch", "dringend"],
  zeitzone: "Europe/Zurich",
  standard_ruhezeit: 30,
};

function regel(teil: Partial<Regel> = {}): Regel {
  return {
    id: 1,
    name: "CPU-Alarm",
    ausloeser: { art: "messwert", messwert: "cpu", vergleich: "ueber", schwelle: 90, dauer_minuten: 5 },
    bedingung: {},
    aktion: { art: "ereignis", nachricht: "Die CPU glüht", dringlichkeit: "hoch" },
    ruhezeit_minuten: 30,
    aktiv: true,
    quelle: "manuell",
    satz: "Wenn die CPU-Auslastung 5 Minuten lang über 90 % liegt, dann bekommt Missa die Nachricht „Die CPU glüht“ (Dringlichkeit: hoch). Danach 30 Minuten Ruhe.",
    problem: null,
    erstellt: "2026-01-15T12:00:00+00:00",
    geaendert: "2026-01-15T12:00:00+00:00",
    zuletzt_ausgeloest: null,
    naechste_ausfuehrung: null,
    ...teil,
  };
}

function ausloesung(teil: Partial<Ausloesung> = {}): Ausloesung {
  return {
    id: 1,
    regel_id: 1,
    regel: "CPU-Alarm",
    zeit: "2026-01-15T12:05:00+00:00",
    anlass: "CPU-Auslastung: 97,4 % (über 90 % seit 5 Minuten)",
    ergebnis: "ok",
    ergebnis_name: "ausgeführt",
    meldung: "Ereignis an Missa gesendet.",
    test: false,
    ...teil,
  };
}

const KATALOG_AKTIV = { eintraege: [{ id: "regeln", name: "Regeln", eingerichtet: 1 }], probleme: [] };
const VERLAUF = "GET /api/regeln/verlauf?limit=50";
const LEER = { anzahl: 0, eintraege: [] };

test("zeigt Regeln als lesbare Sätze – mit Herkunft, Zustand, Problem und Verlauf", async () => {
  const morgens = regel({
    id: 2,
    name: "Guten Morgen",
    quelle: "missa",
    aktiv: false,
    satz: "Montags bis freitags um 07:30 Uhr bekommt Missa die Nachricht „Guten Morgen“.",
    naechste_ausfuehrung: null,
  });
  const licht = regel({
    id: 3,
    name: "Licht",
    satz: "Wenn ein Webhook etwas empfängt, dann wird die Funktion „lampe_schalten“ aufgerufen (an = ja). Danach 30 Minuten Ruhe.",
    problem: "Die Funktion „lampe_schalten“ gibt es nicht oder sie ist gesperrt.",
    zuletzt_ausgeloest: "2026-01-15T12:05:00+00:00",
  });
  backend({
    "GET /api/regeln": { regeln: [regel(), morgens, licht], optionen: OPTIONEN },
    [VERLAUF]: {
      anzahl: 2,
      eintraege: [ausloesung({ id: 2, regel: "Licht", regel_id: 3, ergebnis: "fehler", ergebnis_name: "fehlgeschlagen", meldung: "Die Lampe antwortet nicht.", anlass: "Test im Panel", test: true }), ausloesung()],
    },
    "GET /api/katalog": KATALOG_AKTIV,
  });
  zeige(<Regeln />);

  const cpu = await screen.findByRole("region", { name: "Regel CPU-Alarm" });
  expect(within(cpu).getByText(/Wenn die CPU-Auslastung 5 Minuten lang über 90 % liegt, dann bekommt Missa/)).toBeInTheDocument();
  expect(within(cpu).getByText(/Zuletzt ausgelöst: noch nie/)).toBeInTheDocument();
  expect(within(cpu).getByRole("checkbox", { name: "CPU-Alarm aktiv" })).toBeChecked();
  expect(within(cpu).queryByText("von Missa angelegt")).not.toBeInTheDocument();

  const vonMissa = screen.getByRole("region", { name: "Regel Guten Morgen" });
  expect(within(vonMissa).getByText("von Missa angelegt")).toBeInTheDocument();
  expect(within(vonMissa).getByText("pausiert")).toBeInTheDocument();
  expect(within(vonMissa).getByRole("checkbox", { name: "Guten Morgen aktiv" })).not.toBeChecked();

  const kaputt = screen.getByRole("region", { name: "Regel Licht" });
  expect(within(kaputt).getByText("Die Funktion „lampe_schalten“ gibt es nicht oder sie ist gesperrt.")).toBeInTheDocument();

  // Verlauf der Auslösungen
  const tabelle = await screen.findByRole("table");
  expect(within(tabelle).getByText("CPU-Auslastung: 97,4 % (über 90 % seit 5 Minuten)")).toBeInTheDocument();
  expect(within(tabelle).getByText("ausgeführt")).toBeInTheDocument();
  expect(within(tabelle).getByText("fehlgeschlagen")).toBeInTheDocument();
  expect(within(tabelle).getByText("Die Lampe antwortet nicht.")).toBeInTheDocument();
  expect(within(tabelle).getByText("Test")).toBeInTheDocument();
});

test("ohne Regeln: Hinweis, kein Verlauf – und Missa kann mit einem Klick Regeln verwalten", async () => {
  let eingerichtet = 0;
  const aufrufe = backend({
    "GET /api/regeln": { regeln: [], optionen: OPTIONEN },
    [VERLAUF]: LEER,
    "GET /api/katalog": () => ({ eintraege: [{ id: "regeln", name: "Regeln", eingerichtet }], probleme: [] }),
    "POST /api/integrationen": () => {
      eingerichtet = 1;
      return { id: 9 };
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Regeln />);

  expect(await screen.findByText("Noch keine Regeln")).toBeInTheDocument();
  expect(screen.queryByText("Verlauf der Auslösungen")).not.toBeInTheDocument();
  expect(await screen.findByText(/Missa kann Regeln erst selbst anlegen und ändern, wenn die Integration „Regeln“ aktiv ist/)).toBeInTheDocument();
  await nutzer.click(screen.getByRole("button", { name: "Für Missa aktivieren" }));
  await waitFor(() => expect(screen.queryByText(/wenn die Integration/)).not.toBeInTheDocument());
  expect(aufrufe.find((a) => a.methode === "POST")?.koerper).toEqual({ manifest_id: "regeln", konfig: {} });
});

test("pausieren, wieder einschalten und „Jetzt testen“", async () => {
  let aktiv = true;
  const aufrufe = backend({
    "GET /api/regeln": () => ({ regeln: [regel({ aktiv })], optionen: OPTIONEN }),
    [VERLAUF]: LEER,
    "GET /api/katalog": KATALOG_AKTIV,
    "PATCH /api/regeln/1": (koerper) => {
      aktiv = (koerper as { aktiv: boolean }).aktiv;
      return regel({ aktiv });
    },
    "POST /api/regeln/1/testen": { ok: true, meldung: "Ereignis an Missa gesendet." },
  });
  const nutzer = userEvent.setup();
  zeige(<Regeln />);

  await nutzer.click(await screen.findByRole("checkbox", { name: "CPU-Alarm aktiv" }));
  expect(await screen.findByText("pausiert")).toBeInTheDocument();
  expect(aufrufe.find((a) => a.methode === "PATCH")?.koerper).toEqual({ aktiv: false });

  await nutzer.click(screen.getByRole("button", { name: "Jetzt testen" }));
  expect(await screen.findByText("Test: Ereignis an Missa gesendet.")).toBeInTheDocument();
});

test("fehlgeschlagener Test zeigt die Meldung der Aktion", async () => {
  backend({
    "GET /api/regeln": { regeln: [regel()], optionen: OPTIONEN },
    [VERLAUF]: LEER,
    "GET /api/katalog": KATALOG_AKTIV,
    "POST /api/regeln/1/testen": { ok: false, meldung: "Die Lampe antwortet nicht. Hinweis: Steckt der Stecker?" },
  });
  const nutzer = userEvent.setup();
  zeige(<Regeln />);
  await nutzer.click(await screen.findByRole("button", { name: "Jetzt testen" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Test: Die Lampe antwortet nicht. Hinweis: Steckt der Stecker?");
});

test("neue Schwellwert-Regel im Editor: Auswahlfelder, Vorschau als Satz, speichern", async () => {
  let gespeichert: Regel[] = [];
  const aufrufe = backend({
    "GET /api/regeln": () => ({ regeln: gespeichert, optionen: OPTIONEN }),
    [VERLAUF]: LEER,
    "GET /api/katalog": KATALOG_AKTIV,
    "POST /api/regeln/satz": (koerper) => {
      const entwurf = koerper as Regel;
      if (!entwurf.name) return { ok: false, meldung: "Bitte der Regel einen Namen geben." };
      if (!entwurf.aktion.nachricht) return { ok: false, meldung: "Bitte eine Nachricht für Missa angeben." };
      return { ok: true, satz: `Wenn die Auslastung des Arbeitsspeichers ${entwurf.ausloeser.dauer_minuten} Minuten lang über ${entwurf.ausloeser.schwelle} % liegt, dann …` };
    },
    "POST /api/regeln": (koerper) => {
      gespeichert = [regel({ ...(koerper as Regel), id: 5, satz: "Gespeicherter Satz." })];
      return gespeichert[0];
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Regeln />);

  await nutzer.click(await screen.findByRole("button", { name: "Neue Regel" }));
  const dialog = screen.getByRole("dialog", { name: "Neue Regel" });
  expect(await within(dialog).findByText("Noch nicht vollständig: Bitte der Regel einen Namen geben.")).toBeInTheDocument();

  await nutzer.type(within(dialog).getByLabelText(/^Name/), "RAM-Alarm");
  expect(within(dialog).getByLabelText("Auslöser")).toHaveValue("messwert"); // Vorschlag: Messwert
  expect(within(dialog).getByRole("option", { name: "GPU-Auslastung (hier nicht vorhanden)" })).toBeInTheDocument();
  await nutzer.selectOptions(within(dialog).getByLabelText("Messwert"), "Arbeitsspeicher");
  const schwelle = within(dialog).getByLabelText("Schwelle (%)");
  await nutzer.clear(schwelle);
  await nutzer.type(schwelle, "85");
  await nutzer.type(within(dialog).getByLabelText(/Nachricht an Missa/), "Der Arbeitsspeicher wird knapp");
  await nutzer.selectOptions(within(dialog).getByLabelText("Dringlichkeit"), "hoch");

  expect(await within(dialog).findByText("Wenn die Auslastung des Arbeitsspeichers 5 Minuten lang über 85 % liegt, dann …")).toBeInTheDocument();
  await nutzer.click(within(dialog).getByRole("button", { name: "Speichern" }));

  expect(await screen.findByText("Gespeicherter Satz.")).toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(aufrufe.find((a) => a.methode === "POST" && a.pfad === "/api/regeln")?.koerper).toEqual({
    name: "RAM-Alarm",
    ausloeser: { art: "messwert", messwert: "ram", vergleich: "ueber", schwelle: "85", dauer_minuten: 5 },
    bedingung: {},
    aktion: { art: "ereignis", nachricht: "Der Arbeitsspeicher wird knapp", dringlichkeit: "hoch" },
    ruhezeit_minuten: 30,
    aktiv: true,
  });
});

test("Zeitplan mit Wochentagen und einer Funktion als Aktion: Parameter kommen als passende Felder", async () => {
  const aufrufe = backend({
    "GET /api/regeln": { regeln: [], optionen: OPTIONEN },
    [VERLAUF]: LEER,
    "GET /api/katalog": KATALOG_AKTIV,
    "POST /api/regeln/satz": { ok: true, satz: "Montags und dienstags um 18:15 Uhr wird die Funktion „lampe_schalten“ aufgerufen." },
    "POST /api/regeln": (koerper) => regel({ ...(koerper as Regel), id: 6 }),
  });
  const nutzer = userEvent.setup();
  zeige(<Regeln />);

  await nutzer.click(await screen.findByRole("button", { name: "Neue Regel" }));
  const dialog = screen.getByRole("dialog");
  await nutzer.type(within(dialog).getByLabelText(/^Name/), "Abendlicht");
  await nutzer.selectOptions(within(dialog).getByLabelText("Auslöser"), "Zeitplan");
  expect(within(dialog).getByRole("radio", { name: "Zu einer Uhrzeit" })).toBeChecked();
  expect(within(dialog).queryByLabelText(/Ruhezeit/)).not.toBeInTheDocument(); // beim Zeitplan ohne Bedeutung
  expect(within(dialog).getByText(/Zeitzone: Europe\/Zurich/)).toBeInTheDocument();
  const uhrzeit = within(dialog).getByLabelText("Uhrzeit");
  await nutzer.clear(uhrzeit);
  await nutzer.type(uhrzeit, "18:15");
  await nutzer.click(within(dialog).getByRole("button", { name: "Montag" }));
  await nutzer.click(within(dialog).getByRole("button", { name: "Dienstag" }));
  expect(within(dialog).getByRole("button", { name: "Montag" })).toHaveAttribute("aria-pressed", "true");

  await nutzer.selectOptions(within(dialog).getByLabelText("Aktion"), "Funktion einer Integration aufrufen");
  await nutzer.selectOptions(within(dialog).getByLabelText(/^Funktion/), "lampe_schalten");
  expect(within(dialog).getByText("Schaltet die Lampe.")).toBeInTheDocument();
  expect(within(dialog).getByText(/Die Regel führt sie ohne Nachfrage aus/)).toBeInTheDocument();
  // Ja/Nein, Text, Zahl und Auswahl – je nach Typ des Parameters:
  await nutzer.selectOptions(within(dialog).getByLabelText(/^an/), "Ja");
  await nutzer.type(within(dialog).getByLabelText("farbe"), "rot");
  await nutzer.type(within(dialog).getByLabelText("helligkeit"), "80");
  await nutzer.selectOptions(within(dialog).getByLabelText("modus"), "blinken");
  await nutzer.click(within(dialog).getByRole("button", { name: "Speichern" }));

  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(aufrufe.find((a) => a.methode === "POST" && a.pfad === "/api/regeln")?.koerper).toEqual({
    name: "Abendlicht",
    ausloeser: { art: "zeitplan", modus: "uhrzeit", uhrzeit: "18:15" },
    bedingung: { tage: [0, 1] },
    aktion: { art: "funktion", funktion: "lampe_schalten", argumente: { an: true, farbe: "rot", helligkeit: 80, modus: "blinken" } },
    ruhezeit_minuten: 30,
    aktiv: true,
  });
});

test("Intervall, Webhook und Integration ausgefallen bieten die passenden Felder", async () => {
  backend({
    "GET /api/regeln": { regeln: [], optionen: OPTIONEN },
    [VERLAUF]: LEER,
    "GET /api/katalog": KATALOG_AKTIV,
    "POST /api/regeln/satz": { ok: true, satz: "…" },
  });
  const nutzer = userEvent.setup();
  zeige(<Regeln />);
  await nutzer.click(await screen.findByRole("button", { name: "Neue Regel" }));
  const dialog = screen.getByRole("dialog");

  await nutzer.selectOptions(within(dialog).getByLabelText("Auslöser"), "Zeitplan");
  await nutzer.click(within(dialog).getByRole("radio", { name: "In einem festen Abstand" }));
  expect(within(dialog).getByLabelText("Abstand in Minuten")).toHaveValue(60);

  await nutzer.selectOptions(within(dialog).getByLabelText("Auslöser"), "Webhook geht ein");
  expect(within(dialog).getByText(/Noch kein Webhook eingerichtet/)).toBeInTheDocument();
  expect(within(dialog).getByRole("link", { name: "Katalog" })).toHaveAttribute("href", "/katalog");
  expect(within(dialog).getByLabelText(/Ruhezeit/)).toHaveValue(30);

  await nutzer.selectOptions(within(dialog).getByLabelText("Auslöser"), "Integration ausgefallen");
  expect(within(dialog).getByRole("option", { name: "Jede Integration" })).toBeInTheDocument();
  expect(within(dialog).getByRole("option", { name: "Lampe" })).toBeInTheDocument();

  await nutzer.selectOptions(within(dialog).getByLabelText("Auslöser"), "Gerät meldet etwas");
  expect(within(dialog).getByText(/Noch kein Gerät eingerichtet/)).toBeInTheDocument();
  // Auch ohne Gerät lässt sich schon auf „offline“ reagieren.
  expect(within(within(dialog).getByLabelText("Was es meldet")).getAllByRole("option").map((option) => option.textContent)).toEqual([
    "Alles (jede Meldung)",
    "geht offline",
    "kommt online",
  ]);
});

test("Auslöser „Gerät meldet etwas“: Auswahl aus dem, was das Gerät melden kann", async () => {
  const meldung = (wert: string, titel: string) => ({ wert, titel });
  const status = [meldung("offline", "geht offline"), meldung("online", "kommt online")];
  const optionen: Optionen = {
    ...OPTIONEN,
    geraete: [
      { id: 7, name: "Wohnzimmer", meldungen: [meldung("knopf", "Knopf"), ...status] },
      { id: 8, name: "Haustür", meldungen: [meldung("klingel", "Klingel"), ...status] },
    ],
  };
  const aufrufe = backend({
    "GET /api/regeln": { regeln: [], optionen },
    [VERLAUF]: LEER,
    "GET /api/katalog": KATALOG_AKTIV,
    "POST /api/regeln/satz": { ok: true, satz: "Wenn das Gerät „Wohnzimmer“ „Knopf“ meldet, dann …" },
    "POST /api/regeln": (koerper) => regel({ ...(koerper as Regel), id: 2 }),
  });
  const nutzer = userEvent.setup();
  zeige(<Regeln />);
  await nutzer.click(await screen.findByRole("button", { name: "Neue Regel" }));
  const dialog = screen.getByRole("dialog");
  await nutzer.selectOptions(within(dialog).getByLabelText("Auslöser"), "Gerät meldet etwas");
  const was = within(dialog).getByLabelText("Was es meldet");
  const namen = () => within(was).getAllByRole("option").map((option) => option.textContent);

  // „Jedes Gerät“: die Knöpfe aller Geräte.
  expect(namen()).toEqual(["Alles (jede Meldung)", "Knopf", "Klingel", "geht offline", "kommt online"]);
  await nutzer.selectOptions(within(dialog).getByLabelText("Gerät"), "Wohnzimmer");
  expect(namen()).toEqual(["Alles (jede Meldung)", "Knopf", "geht offline", "kommt online"]);
  await nutzer.selectOptions(was, "Knopf");

  // Was das andere Gerät nicht melden kann, wird beim Wechsel nicht mitgenommen – „offline“ schon.
  await nutzer.selectOptions(within(dialog).getByLabelText("Gerät"), "Haustür");
  expect(was).toHaveValue("");
  await nutzer.selectOptions(was, "geht offline");
  await nutzer.selectOptions(within(dialog).getByLabelText("Gerät"), "Wohnzimmer");
  expect(was).toHaveValue("offline");
  await nutzer.selectOptions(was, "Knopf");

  await nutzer.type(within(dialog).getByLabelText(/^Name/), "Klingel");
  await nutzer.type(within(dialog).getByLabelText(/Nachricht an Missa/), "Es hat geklingelt");
  await nutzer.click(within(dialog).getByRole("button", { name: "Speichern" }));
  await waitFor(() => expect(aufrufe.some((aufruf) => aufruf.methode === "POST" && aufruf.pfad === "/api/regeln")).toBe(true));
  expect(aufrufe.find((aufruf) => aufruf.methode === "POST" && aufruf.pfad === "/api/regeln")?.koerper).toMatchObject({
    ausloeser: { art: "geraet", geraet_id: 7, faehigkeit: "knopf" },
  });
});

test("Aktion „Anrufen“: Nummer, Dringlichkeit und was Missa sagt", async () => {
  const optionen: Optionen = { ...OPTIONEN, aktionen: [...OPTIONEN.aktionen, { wert: "anruf", titel: "Anrufen" }] };
  const aufrufe = backend({
    "GET /api/regeln": { regeln: [], optionen },
    [VERLAUF]: LEER,
    "GET /api/katalog": KATALOG_AKTIV,
    "POST /api/regeln/satz": { ok: true, satz: "Wenn …, dann ruft Missa dich an und sagt: „Die CPU glüht“." },
    "POST /api/regeln": (koerper) => regel({ ...(koerper as Regel), id: 2 }),
  });
  const nutzer = userEvent.setup();
  zeige(<Regeln />);
  await nutzer.click(await screen.findByRole("button", { name: "Neue Regel" }));
  const dialog = screen.getByRole("dialog");
  await nutzer.type(within(dialog).getByLabelText(/^Name/), "CPU-Anruf");
  await nutzer.selectOptions(within(dialog).getByLabelText("Aktion"), "Anrufen");

  expect(within(dialog).getByLabelText("Nummer")).toHaveAttribute("placeholder", "deine eigene Nummer");
  expect(within(dialog).getByRole("link", { name: "Anrufe" })).toHaveAttribute("href", "/anrufe");
  expect(within(dialog).getByText("In der Ruhezeit gehen nur dringende Anrufe durch.")).toBeInTheDocument();
  await nutzer.type(within(dialog).getByLabelText(/Was Missa am Telefon sagt/), "Die CPU glüht");
  await nutzer.selectOptions(within(dialog).getByLabelText("Dringlichkeit"), "dringend");
  await nutzer.click(within(dialog).getByRole("button", { name: "Speichern" }));

  await waitFor(() => expect(aufrufe.some((aufruf) => aufruf.methode === "POST" && aufruf.pfad === "/api/regeln")).toBe(true));
  expect(aufrufe.find((aufruf) => aufruf.methode === "POST" && aufruf.pfad === "/api/regeln")?.koerper).toMatchObject({
    aktion: { art: "anruf", nachricht: "Die CPU glüht", dringlichkeit: "dringend", nummer: "" },
  });
});

test("Regel bearbeiten, Fehler beim Speichern anzeigen und Regel löschen", async () => {
  let liste = [regel()];
  let ablehnen = true;
  const aufrufe = backend({
    "GET /api/regeln": () => ({ regeln: liste, optionen: OPTIONEN }),
    [VERLAUF]: LEER,
    "GET /api/katalog": KATALOG_AKTIV,
    "POST /api/regeln/satz": { ok: true, satz: "…" },
    "PUT /api/regeln/1": (koerper) => {
      if (ablehnen) return new TestFehler(422, "„Schwelle“ muss zwischen -1e+06 und 1e+06 liegen.");
      liste = [regel({ ...(koerper as Regel), satz: "Geänderter Satz." })];
      return liste[0];
    },
    "DELETE /api/regeln/1": () => {
      liste = [];
      return null;
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Regeln />);

  await nutzer.click(await screen.findByRole("button", { name: "CPU-Alarm bearbeiten" }));
  const dialog = screen.getByRole("dialog", { name: "Regel „CPU-Alarm“ bearbeiten" });
  expect(within(dialog).getByLabelText(/^Name/)).toHaveValue("CPU-Alarm");
  expect(within(dialog).getByLabelText("Schwelle (%)")).toHaveValue(90);
  expect(within(dialog).getByLabelText(/Nachricht an Missa/)).toHaveValue("Die CPU glüht");
  await nutzer.clear(within(dialog).getByLabelText("Mindestdauer (Minuten)"));
  await nutzer.type(within(dialog).getByLabelText("Mindestdauer (Minuten)"), "10");
  await nutzer.click(within(dialog).getByRole("button", { name: "Speichern" }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent("„Schwelle“ muss zwischen");

  ablehnen = false;
  await nutzer.click(within(dialog).getByRole("button", { name: "Speichern" }));
  expect(await screen.findByText("Geänderter Satz.")).toBeInTheDocument();
  expect((aufrufe.filter((a) => a.methode === "PUT").at(-1)?.koerper as Regel).ausloeser.dauer_minuten).toBe("10");

  await nutzer.click(screen.getByRole("button", { name: "CPU-Alarm löschen" }));
  await nutzer.click(within(screen.getByRole("dialog", { name: "Regel löschen?" })).getByRole("button", { name: "Endgültig löschen" }));
  expect(await screen.findByText("Noch keine Regeln")).toBeInTheDocument();
});

test("Verlauf lässt sich auf eine Regel eingrenzen", async () => {
  const aufrufe = backend({
    "GET /api/regeln": { regeln: [regel(), regel({ id: 2, name: "Licht" })], optionen: OPTIONEN },
    [VERLAUF]: { anzahl: 2, eintraege: [ausloesung(), ausloesung({ id: 2, regel_id: 2, regel: "Licht", anlass: "Zeitplan (18:00 Uhr)" })] },
    "GET /api/regeln/verlauf?limit=50&regel_id=2": { anzahl: 1, eintraege: [ausloesung({ id: 2, regel_id: 2, regel: "Licht", anlass: "Zeitplan (18:00 Uhr)" })] },
    "GET /api/katalog": KATALOG_AKTIV,
  });
  const nutzer = userEvent.setup();
  zeige(<Regeln />);

  expect(await screen.findByText("CPU-Auslastung: 97,4 % (über 90 % seit 5 Minuten)")).toBeInTheDocument();
  await nutzer.selectOptions(screen.getByRole("combobox", { name: "Verlauf filtern" }), "Licht");
  await waitFor(() => expect(screen.queryByText("CPU-Auslastung: 97,4 % (über 90 % seit 5 Minuten)")).not.toBeInTheDocument());
  expect(screen.getByText("Zeitplan (18:00 Uhr)")).toBeInTheDocument();
  expect(aufrufe.some((a) => a.pfad === "/api/regeln/verlauf?limit=50&regel_id=2")).toBe(true);
});
