import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import { Statistik } from "../src/statistik/Statistik";
import type { FunktionsZeile, StatistikDaten } from "../src/statistik/statistik";
import { backend, zeige } from "./hilfen";

function zeile(teil: Partial<FunktionsZeile>): FunktionsZeile {
  return {
    integration: "Serverlast",
    funktion: "serverlast_aktuell",
    aufrufe: 10,
    von_missa: 9,
    fehler: 1,
    fehlerquote: 0.1,
    dauer_mittel_ms: 120,
    dauer_max_ms: 1500,
    letzter_aufruf: "2026-11-16T10:00:00+00:00",
    freigaben: { erlaubt: 0, abgelehnt: 0, abgelaufen: 0 },
    ...teil,
  };
}

function daten(teil: Partial<StatistikDaten>): StatistikDaten {
  return {
    zeitraum: "7d",
    seit: "2026-11-09T12:00:00+00:00",
    bis: "2026-11-16T12:00:00+00:00",
    gesamt: { aufrufe: 13, fehler: 1, fehlerquote: 1 / 13, funktionen: 2 },
    pro_tag: [
      { tag: "2026-11-15", aufrufe: 5, fehler: 0 },
      { tag: "2026-11-16", aufrufe: 8, fehler: 1 },
    ],
    funktionen: [
      zeile({}),
      zeile({
        integration: "Kalender",
        funktion: "kalender_eintragen",
        aufrufe: 3,
        fehler: 0,
        fehlerquote: 0,
        dauer_mittel_ms: 900,
        freigaben: { erlaubt: 2, abgelehnt: 1, abgelaufen: 0 },
      }),
    ],
    nie_benutzt: [{ integration: "Gedächtnis", integration_id: 4, funktion: "gedaechtnis_vergessen", schreibend: true, recht: "nachfragen" }],
    ...teil,
  };
}

test("Statistik zeigt Zahlen pro Funktion, lässt sich sortieren und den Zeitraum wechseln", async () => {
  const aufrufe = backend({
    "GET /api/statistik?zeitraum=7d": daten({}),
    "GET /api/statistik?zeitraum=30d": daten({ zeitraum: "30d", funktionen: [], nie_benutzt: [] }),
  });
  const nutzer = userEvent.setup();
  zeige(<Statistik />, "/statistik");

  const tabelle = await screen.findByRole("table", { name: "Aufrufe pro Funktion" });
  const zeilen = () => within(tabelle).getAllByRole("row").slice(1).map((z) => within(z).getAllByRole("cell")[1].textContent);
  expect(zeilen()).toEqual(["serverlast_aktuell", "kalender_eintragen"]); // meiste Aufrufe zuerst
  expect(within(tabelle).getByText("10 %")).toBeInTheDocument();
  expect(within(tabelle).getAllByText("1.5 s")).toHaveLength(2);
  expect(within(tabelle).getByText("2 erlaubt · 1 abgelehnt · 0 abgelaufen")).toBeInTheDocument();

  await nutzer.click(within(tabelle).getByRole("button", { name: "Ø Dauer" }));
  expect(zeilen()).toEqual(["kalender_eintragen", "serverlast_aktuell"]);
  await nutzer.click(within(tabelle).getByRole("button", { name: /Ø Dauer/ }));
  expect(zeilen()).toEqual(["serverlast_aktuell", "kalender_eintragen"]);

  const nie = screen.getByRole("region", { name: "Nie benutzt" });
  expect(within(nie).getByText("gedaechtnis_vergessen")).toBeInTheDocument();
  expect(within(nie).getByRole("link", { name: "Zur Integration" })).toHaveAttribute("href", "/integrationen#integration-4");

  await nutzer.click(screen.getByRole("radio", { name: "30 Tage" }));
  expect(await screen.findByText("Keine Aufrufe in diesem Zeitraum")).toBeInTheDocument();
  expect(aufrufe.map((a) => a.pfad)).toContain("/api/statistik?zeitraum=30d");
});
