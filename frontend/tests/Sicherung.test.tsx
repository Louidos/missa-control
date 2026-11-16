import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

import { Sicherung } from "../src/sicherung/Sicherung";
import { backend, TestFehler, zeige } from "./hilfen";

const VORSCHAU = {
  panel_version: "0.1.0",
  erstellt: "2026-11-16T10:00:00+00:00",
  mit_zugaengen: true,
  bereiche: [
    { bereich: "zugaenge", titel: "Zugänge", eintraege: [{ name: "Lager-Key", status: "neu" }], nur_hier: [] },
    {
      bereich: "integrationen",
      titel: "Integrationen",
      eintraege: [
        { name: "Lager (lager)", status: "ueberschrieben" },
        { name: "Serverlast (serverlast)", status: "unveraendert" },
      ],
      nur_hier: ["Gedächtnis (gedaechtnis)"],
    },
  ],
};

test("Herunterladen ohne Passwort braucht keine Bestätigung, mit Zugängen schon", async () => {
  const speichern = vi.fn();
  globalThis.URL.createObjectURL = vi.fn(() => "blob:x");
  globalThis.URL.revokeObjectURL = speichern;
  const aufrufe = backend({ "POST /api/sicherung/export": { format: "missa-control-sicherung", version: 1 } });
  const nutzer = userEvent.setup();
  zeige(<Sicherung />, "/sicherung");
  const bereich = screen.getByRole("region", { name: "Sicherung herunterladen" });

  await nutzer.click(within(bereich).getByRole("button", { name: "Sicherung herunterladen" }));
  expect(await within(bereich).findByText("Die Sicherung wurde heruntergeladen.")).toBeInTheDocument();
  expect(aufrufe[0].koerper).toEqual({});
  expect(speichern).toHaveBeenCalled();

  await nutzer.click(within(bereich).getByLabelText(/Zugänge mitsichern/));
  await nutzer.type(within(bereich).getByLabelText("Passwort für die Sicherung"), "sicherungs-passwort");
  await nutzer.type(within(bereich).getByLabelText("Passwort wiederholen"), "sicherungs-passwort");
  await nutzer.type(within(bereich).getByLabelText("Passwort des Panels"), "panel-passwort-123");
  await nutzer.type(within(bereich).getByLabelText("Code aus der Authenticator-App"), "123456");
  await nutzer.click(within(bereich).getByRole("button", { name: "Sicherung herunterladen" }));
  await waitFor(() => expect(aufrufe).toHaveLength(2));
  expect(aufrufe[1].koerper).toEqual({ sicherungs_passwort: "sicherungs-passwort", passwort: "panel-passwort-123", code: "123456" });
});

test("Einspielen: Vorschau zeigt neu, überschrieben, unverändert – ersetzen zeigt, was entfernt würde", async () => {
  const aufrufe = backend({
    "POST /api/sicherung/vorschau": VORSCHAU,
    "POST /api/sicherung/einspielen": (koerper) =>
      (koerper as { code: string }).code === "000000"
        ? new TestFehler(403, "Passwort oder Code falsch – bitte zur Bestätigung erneut eingeben.")
        : { eingespielt: { integrationen: 2 }, zugang_fehlt: ["Lager"] },
  });
  const nutzer = userEvent.setup();
  zeige(<Sicherung />, "/sicherung");
  const bereich = screen.getByRole("region", { name: "Sicherung einspielen" });
  await nutzer.type(within(bereich).getByLabelText(/Passwort der Sicherung/), "sicherungs-passwort");
  const datei = new File(['{"format":"missa-control-sicherung","version":1}'], "sicherung.json", { type: "application/json" });
  await nutzer.upload(within(bereich).getByLabelText("Sicherungsdatei"), datei);

  expect(await within(bereich).findByText("Lager (lager)")).toBeInTheDocument();
  expect(within(bereich).getByText("würde überschrieben")).toBeInTheDocument();
  expect(within(bereich).getByText("unverändert")).toBeInTheDocument();
  expect(within(bereich).getByText("neu")).toBeInTheDocument();
  expect(within(bereich).queryByText("würde entfernt")).not.toBeInTheDocument();
  await nutzer.click(within(within(bereich).getByRole("radiogroup", { name: "Integrationen: Modus" })).getByRole("radio", { name: "ersetzen" }));
  expect(within(bereich).getByText("würde entfernt")).toBeInTheDocument();

  await nutzer.type(within(bereich).getByLabelText("Passwort des Panels"), "panel-passwort-123");
  await nutzer.type(within(bereich).getByLabelText("Code aus der Authenticator-App"), "000000");
  await nutzer.click(within(bereich).getByRole("button", { name: "Einspielen" }));
  expect(await within(bereich).findByText(/Passwort oder Code falsch/)).toBeInTheDocument();

  await nutzer.clear(within(bereich).getByLabelText("Code aus der Authenticator-App"));
  await nutzer.type(within(bereich).getByLabelText("Code aus der Authenticator-App"), "654321");
  await nutzer.click(within(bereich).getByRole("button", { name: "Einspielen" }));
  expect(await within(bereich).findByText("Die Sicherung ist eingespielt.")).toBeInTheDocument();
  expect(within(bereich).getByText(/Zugang fehlt bei: Lager/)).toBeInTheDocument();
  expect(aufrufe.at(-1)?.koerper).toEqual({
    datei: '{"format":"missa-control-sicherung","version":1}',
    sicherungs_passwort: "sicherungs-passwort",
    modi: { integrationen: "ersetzen" },
    passwort: "panel-passwort-123",
    code: "654321",
  });
});
