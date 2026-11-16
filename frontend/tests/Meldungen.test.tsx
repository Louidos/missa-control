import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import { Meldungen, type Ziel } from "../src/meldungen/Meldungen";
import { backend, zeige } from "./hilfen";

const ARTEN = [
  { wert: "freigabe", titel: "Freigabe wartet", standard: true },
  { wert: "integration", titel: "Integration ausgefallen / wieder da", standard: true },
  { wert: "geraet_offline", titel: "Gerät offline", standard: false },
  { wert: "regel_hoch", titel: "Regel ausgelöst (Dringlichkeit hoch oder dringend)", standard: false },
];

function ziel(teil: Partial<Ziel>): Ziel {
  return {
    id: 1,
    name: "Handy",
    art: "ntfy",
    adresse: "https://ntfy.sh",
    thema: "missa-louis",
    zugang_id: null,
    panel_adresse: "http://ai01:8090",
    arten: ["freigabe", "integration"],
    aktiv: true,
    letzter_fehler: "",
    letzter_fehler_zeit: null,
    zuletzt_gesendet: null,
    ...teil,
  };
}

test("Ziel anlegen: ntfy mit Thema, Standard sind Freigabe und Ausfall", async () => {
  const aufrufe = backend({
    "GET /api/meldungen": { ziele: [], arten: ARTEN },
    "GET /api/zugaenge": [],
    "POST /api/meldungen": ziel({}),
  });
  const nutzer = userEvent.setup();
  zeige(<Meldungen />, "/meldungen");
  await nutzer.click(await screen.findByRole("button", { name: /Ziel hinzufügen/ }));
  const dialog = screen.getByRole("dialog");
  await nutzer.type(within(dialog).getByLabelText(/Thema/), "missa-louis");
  expect(within(dialog).getByLabelText("Freigabe wartet")).toBeChecked();
  expect(within(dialog).getByLabelText("Integration ausgefallen / wieder da")).toBeChecked();
  expect(within(dialog).getByLabelText("Gerät offline")).not.toBeChecked();
  await nutzer.click(within(dialog).getByLabelText("Gerät offline"));
  await nutzer.click(within(dialog).getByRole("button", { name: "Speichern" }));

  const gesendet = aufrufe.find((a) => a.methode === "POST")?.koerper as Record<string, unknown>;
  expect(gesendet).toMatchObject({
    name: "Handy",
    art: "ntfy",
    adresse: "https://ntfy.sh",
    thema: "missa-louis",
    panel_adresse: window.location.origin,
    arten: ["freigabe", "integration", "geraet_offline"],
  });
});

test("Test-Meldung: Erfolg und Grund des Fehlers stehen am Ziel", async () => {
  backend({
    "GET /api/meldungen": { ziele: [ziel({}), ziel({ id: 2, name: "Hook", art: "webhook", adresse: "http://hook", letzter_fehler: "Die Gegenstelle ist nicht erreichbar." })], arten: ARTEN },
    "POST /api/meldungen/1/testen": { ok: true, meldung: "Die Test-Meldung wurde gesendet." },
  });
  const nutzer = userEvent.setup();
  zeige(<Meldungen />, "/meldungen");
  const hook = await screen.findByRole("region", { name: "Hook" });
  expect(within(hook).getByText(/Senden fehlgeschlagen: Die Gegenstelle ist nicht erreichbar/)).toBeInTheDocument();
  const handy = screen.getByRole("region", { name: "Handy" });
  expect(within(handy).getByText(/Meldet: Freigabe wartet · Integration ausgefallen/)).toBeInTheDocument();
  await nutzer.click(within(handy).getByRole("button", { name: /Test-Meldung senden/ }));
  expect(await within(handy).findByText("Die Test-Meldung wurde gesendet.")).toBeInTheDocument();
});
