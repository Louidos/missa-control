import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

import App, { Seiten } from "../src/App";
import { ALLE_EINTRAEGE } from "../src/layout/navigation";
import { backend, TestFehler, zeige } from "./hilfen";

const QR = "data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%27http%3A//www.w3.org/2000/svg%27/%3E";

test("erster Aufruf zeigt die Einrichtung: Passwort, QR-Code, Code bestätigen", async () => {
  let eingerichtet = false;
  const aufrufe = backend({
    "GET /api/auth/status": () => ({ eingerichtet, angemeldet: eingerichtet, version: "1.2.3" }),
    "POST /api/auth/einrichten": { geheimnis: "ABCDEFGH", otpauth_url: "otpauth://totp/x", qr_svg: QR },
    "POST /api/auth/einrichten/bestaetigen": () => {
      eingerichtet = true;
      return { ok: true };
    },
  });
  const nutzer = userEvent.setup();
  render(<App />);

  await nutzer.type(await screen.findByLabelText("Neues Passwort"), "sehr-langes-passwort");
  await nutzer.type(screen.getByLabelText("Passwort wiederholen"), "sehr-langes-passwort");
  await nutzer.click(screen.getByRole("button", { name: "Weiter" }));

  expect(await screen.findByAltText(/QR-Code/)).toHaveAttribute("src", QR);
  expect(screen.getByText("ABCDEFGH")).toBeInTheDocument();
  await nutzer.type(screen.getByLabelText(/Code aus der App/), "123456");
  await nutzer.click(screen.getByRole("button", { name: /Bestätigen/ }));

  // Danach ist man im Panel.
  expect(await screen.findByRole("navigation", { name: "Hauptnavigation" })).toBeInTheDocument();
  expect(aufrufe.find((a) => a.pfad === "/api/auth/einrichten")?.koerper).toEqual({
    passwort: "sehr-langes-passwort",
  });
  expect(aufrufe.find((a) => a.pfad === "/api/auth/einrichten/bestaetigen")?.koerper).toEqual({ code: "123456" });
});

test("Einrichtung lässt zu kurze oder ungleiche Passwörter nicht zu", async () => {
  backend({ "GET /api/auth/status": { eingerichtet: false, angemeldet: false, version: "1.2.3" } });
  const nutzer = userEvent.setup();
  render(<App />);

  await nutzer.type(await screen.findByLabelText("Neues Passwort"), "kurz");
  expect(screen.getByText(/Noch 6 Zeichen/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Weiter" })).toBeDisabled();

  await nutzer.clear(screen.getByLabelText("Neues Passwort"));
  await nutzer.type(screen.getByLabelText("Neues Passwort"), "sehr-langes-passwort");
  await nutzer.type(screen.getByLabelText("Passwort wiederholen"), "anderes-passwort");
  expect(screen.getByText(/stimmen nicht überein/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Weiter" })).toBeDisabled();
});

test("Login zeigt Fehlermeldung mit Hinweis und lässt danach ins Panel", async () => {
  let angemeldet = false;
  let versuche = 0;
  backend({
    "GET /api/auth/status": () => ({ eingerichtet: true, angemeldet, version: "1.2.3" }),
    "POST /api/auth/anmelden": () => {
      versuche += 1;
      if (versuche === 1) return new TestFehler(401, "Passwort oder Code falsch.", "Noch 4 Versuch(e).");
      angemeldet = true;
      return { ok: true };
    },
  });
  const nutzer = userEvent.setup();
  render(<App />);

  await nutzer.type(await screen.findByLabelText("Passwort"), "falsch");
  await nutzer.type(screen.getByLabelText(/Code/), "000000");
  await nutzer.click(screen.getByRole("button", { name: "Anmelden" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Passwort oder Code falsch.");
  expect(screen.getByRole("alert")).toHaveTextContent("Noch 4 Versuch(e).");

  await nutzer.type(screen.getByLabelText(/Code/), "123456");
  await nutzer.click(screen.getByRole("button", { name: "Anmelden" }));
  expect(await screen.findByRole("navigation", { name: "Hauptnavigation" })).toBeInTheDocument();
  expect(screen.getByText("Version 1.2.3")).toBeInTheDocument();
});

test("nicht erreichbares Panel zeigt verständliche Meldung", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("offline"));
  render(<App />);
  expect(await screen.findByRole("alert", {}, { timeout: 4000 })).toHaveTextContent(
    "Das Panel ist nicht erreichbar.",
  );
});

test("Navigation enthält alle Bereiche, jeder hat eine Seite oder einen Platzhalter", async () => {
  backend({ "GET /api/auth/status": { eingerichtet: true, angemeldet: true, version: "1.2.3" } });
  const nutzer = userEvent.setup();
  zeige(<Seiten />);

  const erwartet = [
    "Übersicht",
    "Katalog",
    "Integrationen",
    "Zugänge",
    "Geräte",
    "Charakter",
    "Modelle",
    "Gedächtnis",
    "Regeln",
    "Anrufe",
    "Freigaben",
    "Clients",
    "Protokoll",
    "Serverlast",
  ];
  expect(ALLE_EINTRAEGE.map((eintrag) => eintrag.titel)).toEqual(erwartet);

  for (const titel of erwartet) {
    await nutzer.click(screen.getByRole("link", { name: titel }));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(titel);
  }
});

test("Abmelden ruft das Backend und zeigt wieder den Login", async () => {
  let angemeldet = true;
  const aufrufe = backend({
    "GET /api/auth/status": () => ({ eingerichtet: true, angemeldet, version: "1.2.3" }),
    "POST /api/auth/abmelden": () => {
      angemeldet = false;
      return { ok: true };
    },
  });
  const nutzer = userEvent.setup();
  render(<App />);

  await nutzer.click(await screen.findByRole("button", { name: "Abmelden" }));
  expect(await screen.findByRole("heading", { name: "Anmelden" })).toBeInTheDocument();
  expect(aufrufe.some((a) => a.methode === "POST" && a.pfad === "/api/auth/abmelden")).toBe(true);
});
