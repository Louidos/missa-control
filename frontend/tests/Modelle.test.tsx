import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import { Modelle } from "../src/modelle/Modelle";
import type { Modell, ModellUebersicht, Rolle } from "../src/modelle/modelle";
import { backend, TestFehler, zeige } from "./hilfen";

function modell(teil: Partial<Modell>): Modell {
  return {
    id: 1,
    name: "Klein",
    url: "http://192.168.1.30:8000/v1",
    zugang_id: null,
    modellname: "klein-7b",
    kontextlaenge: 32768,
    test: { ok: true, meldung: "Das Modell antwortet.", hinweis: "", ms: 420, tokens_pro_s: 38.5, zeit: "2026-01-15T12:00:00+00:00" },
    statistik: { anfragen: 12, fehler: 2, antwortzeit_ms: 1350, tokens_pro_s: 41.2 },
    ...teil,
  };
}

function rolle(teil: Partial<Rolle>): Rolle {
  return {
    id: 1,
    kennung: "schnell",
    modellname: "missa-schnell",
    name: "Schnell",
    beschreibung: "Für Gespräche: antwortet zügig.",
    haupt_modell_id: 1,
    ersatz_modell_id: null,
    fest: true,
    ...teil,
  };
}

const STARK = rolle({ id: 2, kennung: "stark", modellname: "missa-stark", name: "Stark", beschreibung: "Für schwierige Aufgaben – darf länger dauern.", haupt_modell_id: null });
const GROSS = modell({ id: 2, name: "Gross", modellname: "gross-70b", test: { ok: null, meldung: "", hinweis: "", ms: null, tokens_pro_s: null, zeit: null }, statistik: { anfragen: 0, fehler: 0, antwortzeit_ms: null, tokens_pro_s: null } });

test("zeigt Rollen mit festen Namen, Modelle mit Testergebnis und Statistik", async () => {
  backend({ "GET /api/modelle": { modelle: [modell({}), GROSS], rollen: [rolle({}), STARK] } });
  zeige(<Modelle />);

  const schnell = await screen.findByRole("region", { name: "Rolle Schnell" });
  expect(within(schnell).getByText("missa-schnell")).toBeInTheDocument();
  expect(within(schnell).getByLabelText("Hauptmodell für Schnell")).toHaveValue("1");
  const stark = screen.getByRole("region", { name: "Rolle Stark" });
  expect(within(stark).getByText(/Ohne Hauptmodell kann Missa diese Rolle nicht nutzen/)).toBeInTheDocument();
  expect(within(stark).queryByRole("button", { name: /löschen/ })).not.toBeInTheDocument(); // feste Rolle

  const zeile = screen.getByText("klein-7b").closest("tr")!;
  expect(within(zeile).getByText("antwortet")).toBeInTheDocument();
  expect(within(zeile).getByText("420 ms · 38.5 Tokens/s")).toBeInTheDocument();
  expect(within(zeile).getByText("12 Anfragen, davon 2 Fehler")).toBeInTheDocument();
  expect(within(zeile).getByText("⌀ 1.4 s · 41.2 Tokens/s")).toBeInTheDocument();
  expect(within(screen.getByText("gross-70b").closest("tr")!).getByText("noch nicht getestet")).toBeInTheDocument();
  expect(screen.getByText(`${window.location.origin}/v1`)).toBeInTheDocument();
  expect(screen.getByText("missa-schnell, missa-stark")).toBeInTheDocument();
});

test("Rolle auf ein anderes Modell umstellen und Ersatzmodell wählen", async () => {
  let rollen = [rolle({}), STARK];
  const aufrufe = backend({
    "GET /api/modelle": () => ({ modelle: [modell({}), GROSS], rollen }),
    "PUT /api/rollen/1": (koerper) => {
      rollen = [{ ...rollen[0], ...(koerper as Partial<Rolle>) }, STARK];
      return { modelle: [modell({}), GROSS], rollen } satisfies ModellUebersicht;
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Modelle />);

  await nutzer.selectOptions(await screen.findByLabelText("Hauptmodell für Schnell"), "2");
  await waitFor(() => expect(screen.getByLabelText("Hauptmodell für Schnell")).toHaveValue("2"));
  await nutzer.selectOptions(screen.getByLabelText("Ersatzmodell bei Ausfall für Schnell"), "1");
  await waitFor(() => expect(screen.getByLabelText("Ersatzmodell bei Ausfall für Schnell")).toHaveValue("1"));
  expect(aufrufe.filter((a) => a.methode === "PUT").map((a) => a.koerper)).toEqual([
    { haupt_modell_id: 2 },
    { ersatz_modell_id: 1 },
  ]);
});

test("neues Modell eintragen: wird gespeichert und sofort getestet", async () => {
  const modelle: Modell[] = [];
  const aufrufe = backend({
    "GET /api/modelle": () => ({ modelle: [...modelle], rollen: [rolle({ haupt_modell_id: null })] }),
    "GET /api/zugaenge": [],
    "POST /api/modelle": () => {
      modelle.push(modell({ id: 5, name: "Qwen", test: GROSS.test, statistik: GROSS.statistik }));
      return modelle[0];
    },
    "POST /api/modelle/5/testen": () => {
      modelle[0] = modell({ id: 5, name: "Qwen", test: { ok: false, meldung: "Die Gegenstelle ist nicht erreichbar.", hinweis: "Läuft der Dienst?", ms: null, tokens_pro_s: null, zeit: "2026-01-15T12:00:00+00:00" } });
      return modelle[0];
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Modelle />);

  expect(await screen.findByText("Noch keine Modelle")).toBeInTheDocument();
  await nutzer.click(screen.getByRole("button", { name: /Neues Modell/ }));
  const dialog = screen.getByRole("dialog");
  await nutzer.type(within(dialog).getByLabelText(/^Name/), "Qwen");
  await nutzer.type(within(dialog).getByLabelText(/URL des Endpunkts/), "http://192.168.1.30:8000/v1");
  await nutzer.type(within(dialog).getByLabelText(/Modellname/), "qwen2.5:32b");
  await nutzer.type(within(dialog).getByLabelText(/Kontextlänge/), "32768");
  await nutzer.click(within(dialog).getByRole("button", { name: "Speichern und testen" }));

  // Das Testergebnis erscheint mit Meldung und Lösungshinweis.
  expect(await screen.findByText("Die Gegenstelle ist nicht erreichbar.")).toBeInTheDocument();
  expect(screen.getByText("Läuft der Dienst?")).toBeInTheDocument();
  expect(aufrufe.find((a) => a.methode === "POST" && a.pfad === "/api/modelle")?.koerper).toEqual({
    name: "Qwen",
    url: "http://192.168.1.30:8000/v1",
    modellname: "qwen2.5:32b",
    zugang_id: null,
    kontextlaenge: 32768,
  });
  expect(aufrufe.some((a) => a.pfad === "/api/modelle/5/testen")).toBe(true);
});

test("neue Rolle anlegen zeigt den künftigen Modellnamen; verwendetes Modell lässt sich nicht löschen", async () => {
  const eigene = rolle({ id: 9, kennung: "uebersetzen", modellname: "missa-uebersetzen", name: "Übersetzen", fest: false, haupt_modell_id: null });
  let rollen = [rolle({})];
  const aufrufe = backend({
    "GET /api/modelle": () => ({ modelle: [modell({})], rollen }),
    "POST /api/rollen": () => {
      rollen = [rolle({}), eigene];
      return eigene;
    },
    "DELETE /api/modelle/1": new TestFehler(409, "Das Modell wird noch verwendet von: „Schnell“.", "Zuerst bei diesen Rollen ein anderes Modell auswählen."),
  });
  const nutzer = userEvent.setup();
  zeige(<Modelle />);

  await nutzer.click(await screen.findByRole("button", { name: /Neue Rolle/ }));
  await nutzer.type(screen.getByLabelText(/Kurzname/), "Uebersetzen");
  expect(screen.getByText(/missa-uebersetzen/)).toBeInTheDocument();
  await nutzer.click(screen.getByRole("button", { name: "Rolle anlegen" }));
  const neu = await screen.findByRole("region", { name: "Rolle Übersetzen" });
  expect(within(neu).getByRole("button", { name: "Rolle Übersetzen löschen" })).toBeInTheDocument();
  expect(aufrufe.find((a) => a.pfad === "/api/rollen")?.koerper).toEqual({ kennung: "uebersetzen", name: "", beschreibung: "" });

  await nutzer.click(screen.getByRole("button", { name: "Klein löschen" }));
  await nutzer.click(screen.getByRole("button", { name: "Löschen" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Zuerst bei diesen Rollen ein anderes Modell auswählen.");
});
