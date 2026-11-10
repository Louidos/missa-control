import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import { Anrufe } from "../src/anrufe/Anrufe";
import { type Anruf, dauerText, type Uebersicht } from "../src/anrufe/anrufe";
import { backend, TestFehler, zeige } from "./hilfen";

const KATALOG_AKTIV = { eintraege: [{ id: "telefonie", name: "Telefonie", eingerichtet: 1 }], probleme: [] };
const KATALOG_OFFEN = { eintraege: [{ id: "telefonie", name: "Telefonie", eingerichtet: 0 }], probleme: [] };
const ALLE = "GET /api/telefonie/anrufe";

function uebersicht(teil: Partial<Uebersicht> = {}, einstellungen: Partial<Uebersicht["einstellungen"]> = {}): Uebersicht {
  return {
    einstellungen: {
      adapter: "test",
      landesvorwahl: "+41",
      eigene_nummern: [{ nummer: "+41791234567", name: "Louis" }],
      erlaubte_anrufer: [{ nummer: "+41445556677", name: "Oma" }],
      ruhezeiten: [{ von: "22:00", bis: "07:00" }],
      nur_bekannte: true,
      ...einstellungen,
    },
    adapter: [{ kennung: "test", name: "Test-Adapter", beschreibung: "Ruft niemanden an – Anrufe werden nur protokolliert.", test: true }],
    adapter_fehlt: false,
    ruhezeit_jetzt: null,
    zeitzone: "Europe/Zurich",
    ...teil,
  };
}

function anruf(teil: Partial<Anruf> = {}): Anruf {
  return {
    id: 1,
    zeit: "2026-11-10T10:00:00+00:00",
    richtung: "ausgehend",
    nummer: "+41791234567",
    name: "Louis",
    status: "test",
    status_text: "Test – nur protokolliert",
    dauer_sekunden: 0,
    grund: "Die CPU von ai01 glüht: 97 %",
    dringlichkeit: "hoch",
    quelle: "regel",
    quelle_name: "CPU-Alarm",
    adapter: "test",
    meldung: "Test-Adapter: Es wurde niemand wirklich angerufen.",
    ...teil,
  };
}

test("Einstellungen: Nummern, Ruhezeiten und Schalter ändern und speichern", async () => {
  let stand = uebersicht();
  let ablehnen = true;
  const aufrufe = backend({
    "GET /api/telefonie": () => stand,
    [ALLE]: { anrufe: [] },
    "GET /api/katalog": KATALOG_AKTIV,
    "PUT /api/telefonie/einstellungen": (koerper) => {
      if (ablehnen) return new TestFehler(422, "„keine“ ist keine gültige Telefonnummer.", "Erlaubt sind Ziffern.");
      stand = uebersicht({}, { ...(koerper as Uebersicht["einstellungen"]), erlaubte_anrufer: [{ nummer: "+41445556677", name: "Oma" }, { nummer: "+41780000000", name: "Nachbar" }] });
      return stand;
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Anrufe />);

  const formular = await screen.findByRole("form", { name: "Einstellungen" });
  expect(within(formular).getByLabelText("Eigene Nummern: Nummer 1")).toHaveValue("+41791234567");
  expect(within(formular).getByLabelText("Erlaubte Anrufer: Name 1")).toHaveValue("Oma");
  expect(within(formular).getByLabelText("Ruhezeit 1 von")).toHaveValue("22:00");
  expect(within(formular).getByLabelText("Missa ruft nur eigene Nummern und erlaubte Anrufer an")).toBeChecked();
  expect(within(formular).getByText(/Zeitzone Europe\/Zurich/)).toBeInTheDocument();
  expect(within(formular).getByRole("button", { name: "Speichern" })).toBeDisabled(); // noch nichts geändert
  expect(screen.getByText(/Noch ist kein echtes Telefon angeschlossen/)).toBeInTheDocument();

  const erlaubte = within(formular).getByRole("group", { name: "Erlaubte Anrufer" });
  await nutzer.click(within(erlaubte).getByRole("button", { name: "Nummer hinzufügen" }));
  await nutzer.type(within(formular).getByLabelText("Erlaubte Anrufer: Nummer 2"), "keine");
  await nutzer.type(within(formular).getByLabelText("Erlaubte Anrufer: Name 2"), "Nachbar");
  await nutzer.click(within(formular).getByRole("button", { name: "Ruhezeit 1 entfernen" }));
  await nutzer.click(within(formular).getByRole("button", { name: "Speichern" }));
  expect(await within(formular).findByText("„keine“ ist keine gültige Telefonnummer.")).toBeInTheDocument();

  ablehnen = false;
  await nutzer.clear(within(formular).getByLabelText("Erlaubte Anrufer: Nummer 2"));
  await nutzer.type(within(formular).getByLabelText("Erlaubte Anrufer: Nummer 2"), "078 000 00 00");
  await nutzer.click(within(formular).getByRole("button", { name: "Speichern" }));
  // Nach dem Speichern steht die Nummer so da, wie das Panel sie schreibt.
  await waitFor(() => expect(screen.getByLabelText("Erlaubte Anrufer: Nummer 2")).toHaveValue("+41780000000"));
  expect(screen.getByText("Gespeichert.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Speichern" })).toBeDisabled();
  expect(aufrufe.filter((aufruf) => aufruf.methode === "PUT").at(-1)?.koerper).toEqual({
    adapter: "test",
    landesvorwahl: "+41",
    eigene_nummern: [{ nummer: "+41791234567", name: "Louis" }],
    erlaubte_anrufer: [
      { nummer: "+41445556677", name: "Oma" },
      { nummer: "078 000 00 00", name: "Nachbar" },
    ],
    ruhezeiten: [],
    nur_bekannte: true,
  });
});

test("Hinweise: Integration fehlt, Ruhezeit läuft, Adapter verschwunden", async () => {
  backend({
    "GET /api/telefonie": uebersicht(
      {
        adapter_fehlt: true,
        ruhezeit_jetzt: { von: "22:00", bis: "07:00" },
      },
      { adapter: "integration:9" },
    ),
    [ALLE]: { anrufe: [] },
    "GET /api/katalog": KATALOG_OFFEN,
  });
  zeige(<Anrufe />);

  expect(await screen.findByText(/Der gewählte Telefonie-Adapter steht nicht mehr zur Verfügung/)).toBeInTheDocument();
  expect(screen.getByText("Gerade ist Ruhezeit (22:00 bis 07:00 Uhr): Nur dringende Anrufe gehen durch.")).toBeInTheDocument();
  expect(await screen.findByText(/Missa kann erst anrufen, wenn die Integration „Telefonie“ aktiv ist/)).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "(nicht mehr vorhanden)" })).toBeInTheDocument();
  expect(screen.queryByText(/Noch ist kein echtes Telefon angeschlossen/)).not.toBeInTheDocument();
});

test("Ausprobieren: Test-Anruf hinaus und simulierter Anruf herein", async () => {
  const aufrufe = backend({
    "GET /api/telefonie": uebersicht(),
    [ALLE]: { anrufe: [] },
    "GET /api/katalog": KATALOG_AKTIV,
    "POST /api/telefonie/anrufen": (koerper) =>
      (koerper as { dringlichkeit: string }).dringlichkeit === "dringend"
        ? { ok: true, meldung: "Test-Adapter: Der Anruf an Louis (+41791234567) wurde nur protokolliert – es hat nirgends geklingelt." }
        : { ok: false, meldung: "Nicht angerufen: Es ist Ruhezeit (22:00 bis 07:00 Uhr).", hinweis: "In der Ruhezeit gehen nur Anrufe mit der Dringlichkeit „dringend“ durch." },
    "POST /api/telefonie/eingehend-simulieren": (koerper) =>
      (koerper as { nummer: string }).nummer.startsWith("044")
        ? { annehmen: true, nummer: "+41445556677", name: "Oma", grund: "" }
        : { annehmen: false, nummer: "+41780000000", name: "", grund: "Die Nummer steht nicht in der Liste erlaubter Anrufer." },
  });
  const nutzer = userEvent.setup();
  zeige(<Anrufe />);

  const bereich = await screen.findByRole("region", { name: "Ausprobieren" });
  await nutzer.click(within(bereich).getByRole("button", { name: "Test-Anruf auslösen" }));
  expect(await within(bereich).findByText("Nicht angerufen: Es ist Ruhezeit (22:00 bis 07:00 Uhr).")).toBeInTheDocument();
  expect(aufrufe.find((aufruf) => aufruf.pfad === "/api/telefonie/anrufen")?.koerper).toEqual({
    text: "Das ist ein Test-Anruf von Missa.",
    nummer: null,
    dringlichkeit: "normal",
  });
  await nutzer.selectOptions(within(bereich).getByLabelText("Dringlichkeit"), "dringend");
  await nutzer.click(within(bereich).getByRole("button", { name: "Test-Anruf auslösen" }));
  expect(await within(bereich).findByText(/wurde nur protokolliert/)).toBeInTheDocument();

  await nutzer.type(within(bereich).getByLabelText("Nummer des Anrufers"), "078 000 00 00");
  await nutzer.click(within(bereich).getByRole("button", { name: "Anruf simulieren" }));
  expect(await within(bereich).findByText("Abgewiesen: Die Nummer steht nicht in der Liste erlaubter Anrufer.")).toBeInTheDocument();
  await nutzer.clear(within(bereich).getByLabelText("Nummer des Anrufers"));
  await nutzer.type(within(bereich).getByLabelText("Nummer des Anrufers"), "044 555 66 77");
  await nutzer.click(within(bereich).getByRole("button", { name: "Anruf simulieren" }));
  expect(await within(bereich).findByText("Angenommen: Oma (+41445556677) darf Missa erreichen.")).toBeInTheDocument();
  // Nach jedem Versuch wird der Verlauf neu geholt.
  expect(aufrufe.filter((aufruf) => aufruf.pfad === "/api/telefonie/anrufe").length).toBeGreaterThan(2);
});

test("Verlauf: Zeit, Richtung, Nummer, Dauer, Grund und Ergebnis – mit Filter", async () => {
  const eingehend = anruf({
    id: 2,
    richtung: "eingehend",
    nummer: "+41780000000",
    name: "",
    status: "abgewiesen",
    status_text: "abgewiesen",
    dauer_sekunden: 0,
    grund: "Die Nummer steht nicht in der Liste erlaubter Anrufer.",
    dringlichkeit: "niedrig",
    quelle: "anrufer",
    quelle_name: "",
    meldung: "",
  });
  const gespraech = anruf({ id: 3, status: "beendet", status_text: "beendet", dauer_sekunden: 75, quelle: "missa", quelle_name: "Missa", dringlichkeit: "normal", grund: "Das Essen ist fertig.", meldung: "aufgelegt" });
  const aufrufe = backend({
    "GET /api/telefonie": uebersicht(),
    [ALLE]: { anrufe: [gespraech, eingehend, anruf()] },
    "GET /api/telefonie/anrufe?richtung=eingehend": { anrufe: [eingehend] },
    "GET /api/katalog": KATALOG_AKTIV,
  });
  const nutzer = userEvent.setup();
  zeige(<Anrufe />);

  const verlauf = await screen.findByRole("region", { name: "Anrufverlauf" });
  const zeilen = await within(verlauf).findAllByRole("row");
  expect(zeilen).toHaveLength(4);
  expect(within(zeilen[0]).getAllByRole("columnheader").map((kopf) => kopf.textContent)).toEqual(["Zeit", "Richtung", "Nummer", "Dauer", "Grund", "Ergebnis"]);
  expect(zeilen[1]).toHaveTextContent("ausgehend");
  expect(zeilen[1]).toHaveTextContent("Louis+41791234567");
  expect(zeilen[1]).toHaveTextContent("1:15 min");
  expect(zeilen[1]).toHaveTextContent("Das Essen ist fertig.ausgelöst von Missa");
  expect(zeilen[1]).toHaveTextContent("beendetaufgelegt");
  expect(zeilen[2]).toHaveTextContent("eingehend");
  expect(zeilen[2]).toHaveTextContent("Die Nummer steht nicht in der Liste erlaubter Anrufer.");
  expect(zeilen[2]).toHaveTextContent("abgewiesen");
  expect(zeilen[3]).toHaveTextContent("ausgelöst von Regel „CPU-Alarm“ · hoch");
  expect(zeilen[3]).toHaveTextContent("Test – nur protokolliert");

  await nutzer.click(within(verlauf).getByRole("radio", { name: "Eingehend" }));
  await waitFor(() => expect(within(verlauf).getAllByRole("row")).toHaveLength(2));
  expect(aufrufe.some((aufruf) => aufruf.pfad === "/api/telefonie/anrufe?richtung=eingehend")).toBe(true);
});

test("Dauer wird lesbar angezeigt", () => {
  expect(dauerText(null)).toBe("–");
  expect(dauerText(0)).toBe("0 s");
  expect(dauerText(42)).toBe("42 s");
  expect(dauerText(75)).toBe("1:15 min");
  expect(dauerText(600)).toBe("10:00 min");
});
