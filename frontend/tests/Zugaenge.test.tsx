import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, test } from "vitest";

import { ZugangFeld } from "../src/zugaenge/ZugangFeld";
import { Zugaenge } from "../src/zugaenge/Zugaenge";
import type { Zugang } from "../src/zugaenge/zugaenge";
import { backend, TestFehler, zeige } from "./hilfen";

const GEHEIM = "sk-geheimer-api-key-9f8e7d6c5b4a";

function zugang(teil: Partial<Zugang>): Zugang {
  return {
    id: 1,
    name: "Wetter-API",
    typ: "api_key",
    typ_name: "API-Key",
    benutzer: null,
    maske: "••••5b4a",
    lesbar: true,
    notiz: "",
    erstellt: "2026-01-15T12:00:00+00:00",
    geaendert: "2026-01-15T12:00:00+00:00",
    ...teil,
  };
}

test("Liste zeigt nur maskierte Werte", async () => {
  backend({
    "GET /api/zugaenge": [
      zugang({}),
      zugang({ id: 2, name: "Nextcloud", typ: "benutzer_passwort", typ_name: "Benutzer + Passwort", benutzer: "missa", maske: "••••ort!" }),
    ],
  });
  zeige(<Zugaenge />);

  const zeile = (await screen.findByText("Wetter-API")).closest("tr")!;
  expect(within(zeile).getByText("••••5b4a")).toBeInTheDocument();
  expect(screen.getByText("Nextcloud").closest("tr")).toHaveTextContent("missa · ••••ort!");
});

test("leere Liste erklärt, was zu tun ist", async () => {
  backend({ "GET /api/zugaenge": [] });
  zeige(<Zugaenge />);
  expect(await screen.findByText("Noch keine Zugänge")).toBeInTheDocument();
});

test("neuen Zugang anlegen: Wert wird gesendet, danach aber nirgends angezeigt", async () => {
  const gespeichert: Zugang[] = [];
  const aufrufe = backend({
    "GET /api/zugaenge": () => [...gespeichert],
    "POST /api/zugaenge": () => {
      gespeichert.push(zugang({ notiz: "für Wetter" }));
      return gespeichert[0];
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Zugaenge />);

  await nutzer.click(await screen.findByRole("button", { name: /Neuer Zugang/ }));
  const dialog = screen.getByRole("dialog", { name: "Neuer Zugang" });
  await nutzer.type(within(dialog).getByLabelText(/Name/), "Wetter-API");
  const wertFeld = within(dialog).getByLabelText(/API-Key/);
  expect(wertFeld).toHaveAttribute("type", "password");
  await nutzer.type(wertFeld, GEHEIM);
  await nutzer.type(within(dialog).getByLabelText("Notiz"), "für Wetter");
  await nutzer.click(within(dialog).getByRole("button", { name: "Zugang anlegen" }));

  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(await screen.findByText("••••5b4a")).toBeInTheDocument();
  expect(aufrufe.find((a) => a.methode === "POST")?.koerper).toEqual({
    name: "Wetter-API",
    typ: "api_key",
    wert: GEHEIM,
    notiz: "für Wetter",
  });
  expect(document.body.innerHTML).not.toContain(GEHEIM);
});

test("Benutzer + Passwort verlangt einen Benutzernamen", async () => {
  const aufrufe = backend({
    "GET /api/zugaenge": [],
    "POST /api/zugaenge": zugang({ id: 3, typ: "benutzer_passwort", benutzer: "missa" }),
  });
  const nutzer = userEvent.setup();
  zeige(<Zugaenge />);

  await nutzer.click(await screen.findByRole("button", { name: /Neuer Zugang/ }));
  await nutzer.type(screen.getByLabelText(/Name/), "Nextcloud");
  await nutzer.selectOptions(screen.getByLabelText("Typ"), "benutzer_passwort");
  await nutzer.type(screen.getByLabelText(/Benutzername/), "missa");
  await nutzer.type(screen.getByLabelText(/Passwort/), "geheimes-passwort");
  await nutzer.click(screen.getByRole("button", { name: "Zugang anlegen" }));

  await waitFor(() => expect(aufrufe.some((a) => a.methode === "POST")).toBe(true));
  expect(aufrufe.find((a) => a.methode === "POST")?.koerper).toMatchObject({
    typ: "benutzer_passwort",
    benutzer: "missa",
    wert: "geheimes-passwort",
  });
});

test("Bearbeiten zeigt den Wert nicht und lässt ihn ohne Eingabe unverändert", async () => {
  const aufrufe = backend({
    "GET /api/zugaenge": [zugang({})],
    "PUT /api/zugaenge/1": zugang({ name: "Wetter" }),
  });
  const nutzer = userEvent.setup();
  zeige(<Zugaenge />);

  await nutzer.click(await screen.findByRole("button", { name: "Wetter-API bearbeiten" }));
  const wertFeld = screen.getByLabelText(/API-Key/);
  expect(wertFeld).toHaveValue("");
  expect(screen.getByText(/Gespeichert: ••••5b4a/)).toBeInTheDocument();
  await nutzer.clear(screen.getByLabelText(/Name/));
  await nutzer.type(screen.getByLabelText(/Name/), "Wetter");
  await nutzer.click(screen.getByRole("button", { name: "Speichern" }));

  await waitFor(() => expect(aufrufe.some((a) => a.methode === "PUT")).toBe(true));
  expect(aufrufe.find((a) => a.methode === "PUT")?.koerper).toEqual({ name: "Wetter", notiz: "" });
});

test("Fehler vom Backend erscheint mit Lösungshinweis", async () => {
  backend({
    "GET /api/zugaenge": [],
    "POST /api/zugaenge": new TestFehler(409, "Es gibt bereits einen Zugang mit dem Namen „A“.", "Bitte einen anderen Namen wählen."),
  });
  const nutzer = userEvent.setup();
  zeige(<Zugaenge />);

  await nutzer.click(await screen.findByRole("button", { name: /Neuer Zugang/ }));
  await nutzer.type(screen.getByLabelText(/Name/), "A");
  await nutzer.type(screen.getByLabelText(/API-Key/), "irgendein-wert");
  await nutzer.click(screen.getByRole("button", { name: "Zugang anlegen" }));

  const meldung = await screen.findByRole("alert");
  expect(meldung).toHaveTextContent("Es gibt bereits einen Zugang");
  expect(meldung).toHaveTextContent("Bitte einen anderen Namen wählen.");
});

test("Löschen fragt nach und ruft dann das Backend", async () => {
  let vorhanden = true;
  const aufrufe = backend({
    "GET /api/zugaenge": () => (vorhanden ? [zugang({})] : []),
    "DELETE /api/zugaenge/1": () => {
      vorhanden = false;
      return { ok: true };
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Zugaenge />);

  await nutzer.click(await screen.findByRole("button", { name: "Wetter-API löschen" }));
  expect(aufrufe.some((a) => a.methode === "DELETE")).toBe(false); // erst nach der Rückfrage
  await nutzer.click(screen.getByRole("button", { name: "Endgültig löschen" }));
  expect(await screen.findByText("Noch keine Zugänge")).toBeInTheDocument();
});

function FeldMitZustand({ typen }: { typen?: Zugang["typ"][] }) {
  const [wert, setWert] = useState<number | null>(null);
  return (
    <>
      <label htmlFor="feld">Zugang</label>
      <ZugangFeld id="feld" wert={wert} onAendern={setWert} typen={typen} vorschlagName="Mein Server" />
      <output>gewählt: {wert ?? "nichts"}</output>
    </>
  );
}

test("Baustein für Formulare: bestehenden Zugang wählen, nach Typ gefiltert", async () => {
  backend({
    "GET /api/zugaenge": [zugang({}), zugang({ id: 2, name: "HA-Token", typ: "bearer_token", typ_name: "Bearer-Token" })],
  });
  const nutzer = userEvent.setup();
  zeige(<FeldMitZustand typen={["bearer_token"]} />);

  const auswahl = await screen.findByLabelText("Zugang");
  expect(within(auswahl).queryByText(/Wetter-API/)).not.toBeInTheDocument();
  await nutzer.selectOptions(auswahl, "2");
  expect(screen.getByText("gewählt: 2")).toBeInTheDocument();
});

test("Baustein für Formulare: neuen Zugang direkt im Formular anlegen", async () => {
  const gespeichert: Zugang[] = [];
  backend({
    "GET /api/zugaenge": () => [...gespeichert],
    "POST /api/zugaenge": (koerper) => {
      const neu = zugang({ id: 7, name: (koerper as { name: string }).name, typ: "bearer_token", typ_name: "Bearer-Token" });
      gespeichert.push(neu);
      return neu;
    },
  });
  const nutzer = userEvent.setup();
  zeige(<FeldMitZustand typen={["bearer_token"]} />);

  await nutzer.click(await screen.findByRole("button", { name: /Neuer Zugang/ }));
  expect(screen.getByLabelText(/Name/)).toHaveValue("Mein Server"); // Vorschlag aus dem Formular
  expect(screen.queryByLabelText("Typ")).not.toBeInTheDocument(); // nur ein Typ möglich
  await nutzer.type(screen.getByLabelText(/Token/), "geheimer-token-abcdef");
  await nutzer.click(screen.getByRole("button", { name: "Zugang anlegen" }));

  expect(await screen.findByText("gewählt: 7")).toBeInTheDocument();
  expect(await screen.findByLabelText("Zugang")).toHaveValue("7");
});
