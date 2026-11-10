import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import { Gedaechtnis } from "../src/gedaechtnis/Gedaechtnis";
import type { Eintrag, Uebersicht } from "../src/gedaechtnis/gedaechtnis";
import { backend, TestFehler, zeige } from "./hilfen";

function eintrag(teil: Partial<Eintrag> = {}): Eintrag {
  return {
    id: 1,
    text: "Trinkt morgens am liebsten Kaffee mit Hafermilch",
    kategorie: "vorlieben",
    kategorie_name: "Vorlieben",
    quelle: "missa",
    quelle_name: "Missa",
    erstellt: "2026-01-15T12:00:00+00:00",
    geaendert: "2026-01-15T12:00:00+00:00",
    ...teil,
  };
}

const OMA = eintrag({
  id: 2,
  text: "Oma Müller hat am 3. Mai Geburtstag",
  kategorie: "personen",
  kategorie_name: "Personen",
  quelle: "manuell",
  quelle_name: "manuell",
  geaendert: "2026-01-16T09:30:00+00:00",
});

function uebersicht(eintraege: Eintrag[], teil: Partial<Uebersicht> = {}): Uebersicht {
  return {
    eintraege,
    treffer: eintraege.length,
    gesamt: eintraege.length,
    kategorien: [
      { wert: "vorlieben", titel: "Vorlieben", anzahl: 1 },
      { wert: "gewohnheiten", titel: "Gewohnheiten", anzahl: 0 },
      { wert: "projektwissen", titel: "Projektwissen", anzahl: 0 },
      { wert: "personen", titel: "Personen", anzahl: 1 },
      { wert: "sonstiges", titel: "Sonstiges", anzahl: 0 },
    ],
    quellen: [
      { wert: "missa", titel: "Missa" },
      { wert: "manuell", titel: "manuell" },
    ],
    max_zeichen: 2000,
    ...teil,
  };
}

const LISTE = "GET /api/gedaechtnis?limit=100";
const KATALOG_AKTIV = { eintraege: [{ id: "gedaechtnis", name: "Gedächtnis", eingerichtet: 1 }], probleme: [] };

test("zeigt Einträge mit Kategorie und Quelle – und den Export als JSON", async () => {
  backend({ [LISTE]: uebersicht([eintrag(), OMA]), "GET /api/katalog": KATALOG_AKTIV });
  zeige(<Gedaechtnis />);

  const kaffee = (await screen.findByText("Trinkt morgens am liebsten Kaffee mit Hafermilch")).closest("li") as HTMLElement;
  expect(within(kaffee).getByText("Vorlieben")).toBeInTheDocument();
  expect(within(kaffee).getByText("von Missa gemerkt")).toBeInTheDocument();
  expect(within(kaffee).queryByText(/geändert/)).not.toBeInTheDocument();
  const oma = screen.getByText("Oma Müller hat am 3. Mai Geburtstag").closest("li") as HTMLElement;
  expect(within(oma).getByText("von Hand eingetragen")).toBeInTheDocument();
  expect(within(oma).getByText(/geändert/)).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("2 Einträge");

  const exportieren = screen.getByRole("link", { name: "Als JSON exportieren" });
  expect(exportieren).toHaveAttribute("href", "/api/gedaechtnis/export");
  expect(exportieren).toHaveAttribute("download");
  expect(screen.queryByText(/wenn die Integration/)).not.toBeInTheDocument();
});

test("leeres Gedächtnis: Hinweis statt Liste, und die Integration lässt sich mit einem Klick aktivieren", async () => {
  let eingerichtet = 0;
  const aufrufe = backend({
    [LISTE]: uebersicht([], { gesamt: 0 }),
    "GET /api/katalog": () => ({ eintraege: [{ id: "gedaechtnis", name: "Gedächtnis", eingerichtet }], probleme: [] }),
    "POST /api/integrationen": () => {
      eingerichtet = 1;
      return { id: 5 };
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Gedaechtnis />);

  expect(await screen.findByText("Noch nichts gemerkt")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Als JSON exportieren" })).not.toBeInTheDocument();
  expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
  expect(await screen.findByText(/Missa kann sich erst etwas merken, wenn die Integration „Gedächtnis“ aktiv ist/)).toBeInTheDocument();
  await nutzer.click(screen.getByRole("button", { name: "Für Missa aktivieren" }));
  await waitFor(() => expect(screen.queryByText(/wenn die Integration/)).not.toBeInTheDocument());
  expect(aufrufe.find((a) => a.methode === "POST")?.koerper).toEqual({ manifest_id: "gedaechtnis", konfig: {} });
});

test("Suche und Filter fragen das Backend; ohne Treffer lässt sich der Filter zurücksetzen", async () => {
  const aufrufe = backend({
    [LISTE]: uebersicht([eintrag(), OMA]),
    "GET /api/gedaechtnis?limit=100&suche=geburtstag": uebersicht([OMA], { treffer: 1, gesamt: 2 }),
    "GET /api/gedaechtnis?limit=100&suche=geburtstag&kategorie=vorlieben": uebersicht([], { treffer: 0, gesamt: 2 }),
    "GET /api/katalog": KATALOG_AKTIV,
  });
  const nutzer = userEvent.setup();
  zeige(<Gedaechtnis />);

  await nutzer.type(await screen.findByRole("searchbox", { name: "Gedächtnis durchsuchen" }), "geburtstag");
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("1 von 2 Einträgen"));
  expect(screen.queryByText(/Kaffee/)).not.toBeInTheDocument();
  // Nicht jeder Tastendruck sucht: es gab nur die Anfrage mit dem ganzen Wort.
  expect(aufrufe.filter((a) => a.pfad.includes("suche=")).map((a) => a.pfad)).toEqual(["/api/gedaechtnis?limit=100&suche=geburtstag"]);

  await nutzer.selectOptions(screen.getByRole("combobox", { name: "Kategorie" }), "Vorlieben (1)");
  expect(await screen.findByText("Nichts gefunden")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("0 von 2 Einträgen");
  await nutzer.click(screen.getByRole("button", { name: "Filter zurücksetzen" }));
  expect(await screen.findByText(/Kaffee/)).toBeInTheDocument();
  expect(screen.getByRole("searchbox")).toHaveValue("");
});

test("Eintrag von Hand anlegen; steht der Text schon da, gibt es einen Hinweis statt einer Dublette", async () => {
  let liste = [eintrag()];
  const aufrufe = backend({
    [LISTE]: () => uebersicht(liste),
    "GET /api/katalog": KATALOG_AKTIV,
    "POST /api/gedaechtnis": (koerper) => {
      const { text, kategorie } = koerper as { text: string; kategorie: string };
      if (liste.some((einer) => einer.text === text)) return { ...liste[0], neu: false };
      const neu = eintrag({ id: 9, text, kategorie, kategorie_name: "Gewohnheiten", quelle: "manuell" });
      liste = [neu, ...liste];
      return { ...neu, neu: true };
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Gedaechtnis />);

  await nutzer.click(await screen.findByRole("button", { name: "Neuer Eintrag" }));
  const dialog = screen.getByRole("dialog", { name: "Neuer Eintrag" });
  expect(within(dialog).getByRole("button", { name: "Speichern" })).toBeDisabled(); // leer geht nicht
  await nutzer.type(within(dialog).getByLabelText(/Was soll Missa wissen/), "Geht montags zum Sport");
  expect(within(dialog).getByText(/22 von 2000 Zeichen/)).toBeInTheDocument();
  await nutzer.selectOptions(within(dialog).getByLabelText("Kategorie"), "Gewohnheiten");
  await nutzer.click(within(dialog).getByRole("button", { name: "Speichern" }));

  expect(await screen.findByText("Geht montags zum Sport")).toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(aufrufe.find((a) => a.methode === "POST")?.koerper).toEqual({ text: "Geht montags zum Sport", kategorie: "gewohnheiten" });
  expect(screen.queryByText(/steht schon im Gedächtnis/)).not.toBeInTheDocument();

  await nutzer.click(screen.getByRole("button", { name: "Neuer Eintrag" }));
  await nutzer.type(screen.getByLabelText(/Was soll Missa wissen/), "Geht montags zum Sport");
  await nutzer.click(screen.getByRole("button", { name: "Speichern" }));
  expect(await screen.findByText(/steht schon im Gedächtnis – es wurde kein zweiter Eintrag angelegt/)).toBeInTheDocument();
});

test("Eintrag korrigieren und löschen", async () => {
  let liste = [eintrag(), OMA];
  const aufrufe = backend({
    [LISTE]: () => uebersicht(liste),
    "GET /api/katalog": KATALOG_AKTIV,
    "PUT /api/gedaechtnis/1": (koerper) => {
      liste = [{ ...liste[0], ...(koerper as Partial<Eintrag>) }, OMA];
      return liste[0];
    },
    "DELETE /api/gedaechtnis/2": () => {
      liste = liste.filter((einer) => einer.id !== 2);
      return null;
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Gedaechtnis />);

  await nutzer.click(await screen.findByRole("button", { name: /Eintrag bearbeiten: Trinkt morgens/ }));
  const feld = within(screen.getByRole("dialog", { name: "Eintrag bearbeiten" })).getByLabelText(/Was soll Missa wissen/);
  expect(feld).toHaveValue("Trinkt morgens am liebsten Kaffee mit Hafermilch");
  await nutzer.clear(feld);
  await nutzer.type(feld, "Trinkt morgens Grüntee");
  await nutzer.click(screen.getByRole("button", { name: "Speichern" }));
  expect(await screen.findByText("Trinkt morgens Grüntee")).toBeInTheDocument();
  expect(aufrufe.find((a) => a.methode === "PUT")?.koerper).toEqual({ text: "Trinkt morgens Grüntee", kategorie: "vorlieben" });

  await nutzer.click(screen.getByRole("button", { name: /Eintrag löschen: Oma Müller/ }));
  const rueckfrage = screen.getByRole("dialog", { name: "Eintrag löschen?" });
  expect(within(rueckfrage).getByText(/„Oma Müller hat am 3. Mai Geburtstag“ wird endgültig aus dem Gedächtnis gelöscht/)).toBeInTheDocument();
  await nutzer.click(within(rueckfrage).getByRole("button", { name: "Endgültig löschen" }));
  await waitFor(() => expect(screen.queryByText("Oma Müller hat am 3. Mai Geburtstag")).not.toBeInTheDocument());
  expect(aufrufe.some((a) => a.methode === "DELETE" && a.pfad === "/api/gedaechtnis/2")).toBe(true);
});

test("Fehler beim Speichern zeigt Meldung und Hinweis; weitere Einträge lassen sich nachladen", async () => {
  backend({
    [LISTE]: uebersicht([eintrag()], { treffer: 250, gesamt: 250 }),
    "GET /api/gedaechtnis?limit=200": uebersicht([eintrag(), OMA], { treffer: 250, gesamt: 250 }),
    "GET /api/katalog": KATALOG_AKTIV,
    "POST /api/gedaechtnis": new TestFehler(422, "Der Eintrag ist zu lang (2500 Zeichen).", "Höchstens 2000 Zeichen – lieber mehrere kurze Einträge anlegen."),
  });
  const nutzer = userEvent.setup();
  zeige(<Gedaechtnis />);

  expect(await screen.findByText("1 von 250 angezeigt")).toBeInTheDocument();
  await nutzer.click(screen.getByRole("button", { name: "Weitere anzeigen" }));
  expect(await screen.findByText("2 von 250 angezeigt")).toBeInTheDocument();

  await nutzer.click(screen.getByRole("button", { name: "Neuer Eintrag" }));
  await nutzer.type(screen.getByLabelText(/Was soll Missa wissen/), "x");
  await nutzer.click(screen.getByRole("button", { name: "Speichern" }));
  const meldung = await screen.findByRole("alert");
  expect(meldung).toHaveTextContent("Der Eintrag ist zu lang (2500 Zeichen).");
  expect(meldung).toHaveTextContent("lieber mehrere kurze Einträge anlegen");
  expect(screen.getByRole("dialog")).toBeInTheDocument(); // der Dialog bleibt offen, nichts geht verloren
});
