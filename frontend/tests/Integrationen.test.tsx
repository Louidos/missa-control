import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import { Integrationen } from "../src/integrationen/Integrationen";
import { Katalog } from "../src/integrationen/Katalog";
import type { Feld, Integration, Katalog as KatalogDaten, KatalogEintrag } from "../src/integrationen/typen";
import { backend, TestFehler, zeige } from "./hilfen";

function feld(teil: Partial<Feld> & Pick<Feld, "name" | "titel">): Feld {
  return {
    typ: "text",
    pflicht: false,
    hilfe: "",
    platzhalter: "",
    standard: null,
    optionen: [],
    zugang_typen: [],
    endungen: [],
    nach_test: false,
    ...teil,
  };
}

function karte(teil: Partial<KatalogEintrag>): KatalogEintrag {
  return {
    id: "mcp-server",
    name: "MCP-Server",
    beschreibung: "Einen beliebigen MCP-Server per URL anbinden.",
    symbol: "🔌",
    art: "mcp",
    art_name: "MCP-Server",
    version: "1.0.0",
    mehrfach: true,
    hinweis: "",
    felder: [
      feld({ name: "url", titel: "URL des MCP-Servers", typ: "url", pflicht: true }),
      feld({ name: "zugang", titel: "Zugang (optional)", typ: "zugang", zugang_typen: ["bearer_token"] }),
    ],
    eingebaut: true,
    eingerichtet: 0,
    verfuegbar: true,
    kann_hinzufuegen: true,
    ...teil,
  };
}

const REST = karte({
  id: "rest-api",
  name: "REST-API (OpenAPI)",
  beschreibung: "Eine beliebige REST-API anbinden.",
  symbol: "🌐",
  art: "openapi",
  art_name: "REST-API",
  felder: [feld({ name: "spec_datei", titel: "OpenAPI-Datei hochladen", typ: "datei", endungen: [".json"] })],
});

const KATALOG: KatalogDaten = { eintraege: [karte({}), REST], probleme: [] };

function integration(teil: Partial<Integration>): Integration {
  return {
    id: 1,
    manifest_id: "mcp-server",
    manifest: karte({}),
    name: "Notizen",
    kennung: "notizen",
    symbol: "🔌",
    art: "mcp",
    art_name: "MCP-Server",
    konfig: { url: "http://server:8000/mcp" },
    aktiv: true,
    status: "ok",
    status_meldung: "",
    status_hinweis: "",
    geprueft: "2026-01-15T12:00:00+00:00",
    funktionen: [
      {
        id: 1,
        name: "notizen_auflisten",
        gateway_name: "notizen_auflisten",
        beschreibung: "Listet alle Notizen auf.",
        schreibend: false,
        recht: "erlaubt",
        vorhanden: true,
        parameter: { properties: {} },
      },
      {
        id: 2,
        name: "notiz_anlegen",
        gateway_name: "notizen_notiz_anlegen",
        beschreibung: "Legt eine neue Notiz an.",
        schreibend: true,
        recht: "nachfragen",
        vorhanden: true,
        parameter: { properties: { text: { type: "string" } }, required: ["text"] },
      },
    ],
    ...teil,
  };
}

const TEST_OK = {
  ok: true,
  test_id: "test-1",
  meldung: "Verbunden mit Notizen – 2 Funktion(en) gefunden.",
  details: ["Verbindungsart: Streamable HTTP"],
  optionen: {},
  viele_funktionen: false,
  funktionen: [
    { name: "notizen_auflisten", beschreibung: "Listet alle Notizen auf.", schreibend: false, recht: "erlaubt" },
    { name: "notiz_anlegen", beschreibung: "Legt eine neue Notiz an.", schreibend: true, recht: "nachfragen" },
  ],
};

// ---------------------------------------------------------------- Katalog

test("Katalog zeigt Karten und lässt sich durchsuchen", async () => {
  backend({ "GET /api/katalog": KATALOG });
  const nutzer = userEvent.setup();
  zeige(<Katalog />, "/katalog");

  expect(await screen.findByRole("heading", { name: "MCP-Server" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "REST-API (OpenAPI)" })).toBeInTheDocument();

  await nutzer.type(screen.getByLabelText("Katalog durchsuchen"), "openapi");
  expect(screen.queryByRole("heading", { name: "MCP-Server" })).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "REST-API (OpenAPI)" })).toBeInTheDocument();

  await nutzer.clear(screen.getByLabelText("Katalog durchsuchen"));
  await nutzer.type(screen.getByLabelText("Katalog durchsuchen"), "gibt es nicht");
  expect(screen.getByText(/Keine Integration passt/)).toBeInTheDocument();
});

test("Katalog meldet Integrationen mit kaputtem Manifest verständlich", async () => {
  backend({
    "GET /api/katalog": { eintraege: [karte({})], probleme: [{ ordner: "wetter", meldungen: ["„beschreibung“ fehlt (Pflichtangabe)"] }] },
  });
  zeige(<Katalog />, "/katalog");
  const meldung = (await screen.findByText(/konnte nicht geladen werden/)).closest(".meldung")!;
  expect(meldung).toHaveTextContent("Ordner „wetter“ konnte nicht geladen werden");
  expect(meldung).toHaveTextContent("„beschreibung“ fehlt (Pflichtangabe)");
  expect(meldung).toHaveTextContent("integrations/_vorlage/");
});

test("bereits eingerichtete Einzel-Integration und spätere Arten lassen sich nicht starten", async () => {
  backend({
    "GET /api/katalog": {
      eintraege: [
        karte({ id: "serverlast", name: "Serverlast", mehrfach: false, eingerichtet: 1, kann_hinzufuegen: false }),
        karte({ id: "geraet", name: "Gerät", verfuegbar: false, kann_hinzufuegen: false }),
      ],
      probleme: [],
    },
  });
  zeige(<Katalog />, "/katalog");
  expect(await screen.findByRole("button", { name: "Bereits eingerichtet" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Kommt mit einer späteren Version" })).toBeDisabled();
  expect(screen.getByRole("link", { name: "1× eingerichtet" })).toHaveAttribute("href", "/integrationen");
});

// ---------------------------------------------------------------- Assistent

test("MCP-Server in drei Schritten: Karte wählen, URL eintragen und testen, aktivieren", async () => {
  const aufrufe = backend({
    "GET /api/katalog": KATALOG,
    "GET /api/zugaenge": [],
    "POST /api/integrationen/testen": TEST_OK,
    "POST /api/integrationen": integration({}),
  });
  const nutzer = userEvent.setup();
  zeige(<Katalog />, "/katalog");
  let klicks = 0;
  const klicke = async (element: HTMLElement) => {
    klicks += 1;
    await nutzer.click(element);
  };

  // Schritt 1: Karte wählen
  const mcpKarte = (await screen.findByRole("heading", { name: "MCP-Server" })).closest("article")!;
  await klicke(within(mcpKarte).getByRole("button", { name: "Einrichten" }));

  // Schritt 2: Formular ausfüllen (nur die URL ist Pflicht) und testen
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByLabelText("Name")).toHaveValue("MCP-Server");
  await nutzer.type(within(dialog).getByLabelText(/URL des MCP-Servers/), "http://server:8000/mcp");
  await klicke(within(dialog).getByRole("button", { name: "Verbindung testen" }));

  expect(await within(dialog).findByText(/2 Funktion\(en\) gefunden/)).toBeInTheDocument();
  expect(within(dialog).getByText("notizen_auflisten")).toBeInTheDocument();
  expect(within(dialog).getByLabelText("Recht für notizen_auflisten")).toHaveValue("erlaubt");
  expect(within(dialog).getByLabelText("Recht für notiz_anlegen")).toHaveValue("nachfragen");

  // Schritt 3: aktivieren
  await klicke(within(dialog).getByRole("button", { name: "Aktivieren" }));
  expect(await within(dialog).findByText("„Notizen“ ist aktiv")).toBeInTheDocument();
  expect(within(dialog).getByText(/Missa kann jetzt 2 Funktionen nutzen/)).toBeInTheDocument();

  expect(klicks).toBe(3);
  expect(aufrufe.find((a) => a.pfad === "/api/integrationen/testen")?.koerper).toEqual({
    manifest_id: "mcp-server",
    konfig: { url: "http://server:8000/mcp" },
  });
  expect(aufrufe.find((a) => a.methode === "POST" && a.pfad === "/api/integrationen")?.koerper).toEqual({
    manifest_id: "mcp-server",
    name: "MCP-Server",
    konfig: { url: "http://server:8000/mcp" },
    rechte: { notizen_auflisten: "erlaubt", notiz_anlegen: "nachfragen" },
    test_id: "test-1",
  });
});

test("fehlgeschlagener Test zeigt Meldung mit Lösungshinweis und bleibt beim Formular", async () => {
  backend({
    "GET /api/katalog": KATALOG,
    "GET /api/zugaenge": [],
    "POST /api/integrationen/testen": {
      ok: false,
      meldung: "Die Gegenstelle ist nicht erreichbar.",
      hinweis: "Läuft der Dienst und stimmen Adresse und Port?",
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Katalog />, "/katalog?neu=mcp-server"); // direkter Einstieg in den Assistenten

  const dialog = await screen.findByRole("dialog");
  await nutzer.type(within(dialog).getByLabelText(/URL des MCP-Servers/), "http://falsch:1/mcp");
  await nutzer.click(within(dialog).getByRole("button", { name: "Verbindung testen" }));

  const meldung = await within(dialog).findByRole("alert");
  expect(meldung).toHaveTextContent("Die Gegenstelle ist nicht erreichbar.");
  expect(meldung).toHaveTextContent("Läuft der Dienst und stimmen Adresse und Port?");
  expect(within(dialog).getByRole("button", { name: "Verbindung testen" })).toBeEnabled();
  expect(within(dialog).queryByRole("button", { name: "Aktivieren" })).not.toBeInTheDocument();
});

test("Rechte lassen sich vor dem Aktivieren ändern; Felder nach dem Test erscheinen mit Auswahl", async () => {
  const kalender = karte({
    id: "kalender",
    name: "Kalender",
    felder: [
      feld({ name: "url", titel: "Adresse", typ: "url", pflicht: true }),
      feld({ name: "laut", titel: "Ausführlich", typ: "schalter" }),
      feld({ name: "anzahl", titel: "Anzahl", typ: "zahl", standard: 5 }),
      feld({ name: "kalender", titel: "Kalender", typ: "auswahl", pflicht: true, nach_test: true }),
    ],
  });
  const aufrufe = backend({
    "GET /api/katalog": { eintraege: [kalender], probleme: [] },
    "POST /api/integrationen/testen": {
      ...TEST_OK,
      optionen: { kalender: [{ wert: "privat", titel: "Privat" }, { wert: "arbeit", titel: "Arbeit" }] },
    },
    "POST /api/integrationen": integration({ name: "Kalender" }),
  });
  const nutzer = userEvent.setup();
  zeige(<Katalog />, "/katalog?neu=kalender");

  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).queryByLabelText(/^Kalender/)).not.toBeInTheDocument(); // erst nach dem Test
  expect(within(dialog).getByLabelText("Anzahl")).toHaveValue(5); // Standardwert aus dem Manifest
  await nutzer.type(within(dialog).getByLabelText(/Adresse/), "https://cloud.example.ch");
  await nutzer.click(within(dialog).getByLabelText("Ausführlich"));
  await nutzer.click(within(dialog).getByRole("button", { name: "Verbindung testen" }));

  await nutzer.selectOptions(await within(dialog).findByLabelText(/^Kalender/), "arbeit");
  await nutzer.selectOptions(within(dialog).getByLabelText("Recht für notiz_anlegen"), "gesperrt");
  await nutzer.click(within(dialog).getByRole("button", { name: "Aktivieren" }));

  await within(dialog).findByText(/Missa kann jetzt 1 Funktion nutzen/);
  expect(aufrufe.find((a) => a.methode === "POST" && a.pfad === "/api/integrationen")?.koerper).toMatchObject({
    konfig: { url: "https://cloud.example.ch", laut: true, anzahl: 5, kalender: "arbeit" },
    rechte: { notizen_auflisten: "erlaubt", notiz_anlegen: "gesperrt" },
  });
});

test("OpenAPI-Datei hochladen: Inhalt geht ans Backend, bei grossen APIs ist zunächst alles gesperrt", async () => {
  const funktionen = Array.from({ length: 12 }, (_, nummer) => ({
    name: `ding_${nummer}`,
    beschreibung: `GET /dinge/${nummer}`,
    schreibend: nummer % 2 === 1,
    recht: "gesperrt",
  }));
  const aufrufe = backend({
    "GET /api/katalog": KATALOG,
    "POST /api/integrationen/testen": { ...TEST_OK, viele_funktionen: true, funktionen },
    "POST /api/integrationen": integration({ name: "REST" }),
  });
  const nutzer = userEvent.setup();
  zeige(<Katalog />, "/katalog?neu=rest-api");

  const dialog = await screen.findByRole("dialog");
  const datei = new File(['{"openapi": "3.0.0", "paths": {}}'], "api.json", { type: "application/json" });
  await nutzer.upload(within(dialog).getByLabelText(/OpenAPI-Datei hochladen/), datei);
  expect(await within(dialog).findByText(/Datei geladen/)).toBeInTheDocument();
  await nutzer.click(within(dialog).getByRole("button", { name: "Verbindung testen" }));

  expect(await within(dialog).findByText(/Zunächst ist alles gesperrt/)).toBeInTheDocument();
  expect(aufrufe.find((a) => a.pfad === "/api/integrationen/testen")?.koerper).toEqual({
    manifest_id: "rest-api",
    konfig: { spec_datei: '{"openapi": "3.0.0", "paths": {}}' },
  });

  // Auswahl: suchen, dann die Empfehlung nur für die Treffer übernehmen.
  await nutzer.type(within(dialog).getByLabelText("Funktionen durchsuchen"), "ding_1");
  expect(within(dialog).getAllByRole("combobox", { name: /Recht für/ })).toHaveLength(3); // ding_1, ding_10, ding_11
  await nutzer.click(within(dialog).getByRole("button", { name: "Empfehlung für alle" }));
  expect(within(dialog).getByLabelText("Recht für ding_1")).toHaveValue("nachfragen");
  expect(within(dialog).getByLabelText("Recht für ding_10")).toHaveValue("erlaubt");
  await nutzer.click(within(dialog).getByRole("button", { name: "Aktivieren" }));

  await within(dialog).findByText(/Missa kann jetzt 3 Funktionen nutzen/);
  const rechte = (aufrufe.find((a) => a.methode === "POST" && a.pfad === "/api/integrationen")?.koerper as { rechte: Record<string, string> }).rechte;
  expect(rechte.ding_0).toBe("gesperrt");
  expect(rechte.ding_10).toBe("erlaubt");
});

test("ZIP hochladen: Fehler wird erklärt, vorhandene Integration nur nach Rückfrage ersetzt", async () => {
  let versuch = 0;
  const aufrufe = backend({
    "GET /api/katalog": KATALOG,
    "POST /api/katalog/hochladen": () => {
      versuch += 1;
      if (versuch === 1) return new TestFehler(422, "integration.yaml ist ungültig: „beschreibung“ fehlt (Pflichtangabe)", "Die Vorlage zeigt den richtigen Aufbau.");
      if (versuch === 2) return new TestFehler(409, "Eine eigene Integration mit der id „wetter“ gibt es schon.");
      return { id: "wetter", name: "Wetter", ersetzt: true };
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Katalog />, "/katalog");
  const zip = new File(["PK"], "wetter.zip", { type: "application/zip" });

  await nutzer.upload(await screen.findByLabelText("ZIP-Datei auswählen"), zip);
  expect(await screen.findByRole("alert")).toHaveTextContent("„beschreibung“ fehlt (Pflichtangabe)");

  await nutzer.upload(screen.getByLabelText("ZIP-Datei auswählen"), zip);
  const rueckfrage = await screen.findByRole("dialog", { name: "Vorhandene Integration ersetzen?" });
  await nutzer.click(within(rueckfrage).getByRole("button", { name: "Ersetzen" }));

  await waitFor(() => expect(versuch).toBe(3));
  const formulare = aufrufe.filter((a) => a.pfad === "/api/katalog/hochladen").map((a) => a.koerper as FormData);
  expect(formulare.map((formular) => formular.get("ersetzen"))).toEqual(["false", "false", "true"]);
  expect((formulare[2].get("datei") as File).name).toBe("wetter.zip");
});

// ---------------------------------------------------------------- Integrationen

test("leere Seite verweist auf den Katalog", async () => {
  backend({ "GET /api/integrationen": [] });
  zeige(<Integrationen />, "/integrationen");
  expect(await screen.findByText("Noch keine Integrationen")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Katalog" })).toHaveAttribute("href", "/katalog");
});

test("Integration deaktivieren, Recht ändern, erneut testen", async () => {
  let aktuell = integration({});
  const aufrufe = backend({
    "GET /api/integrationen": () => [aktuell],
    "PUT /api/integrationen/1": (koerper) => {
      const aenderung = koerper as { aktiv?: boolean; rechte?: Record<string, "erlaubt" | "nachfragen" | "gesperrt"> };
      aktuell = {
        ...aktuell,
        aktiv: aenderung.aktiv ?? aktuell.aktiv,
        funktionen: aktuell.funktionen.map((f) => ({ ...f, recht: aenderung.rechte?.[f.name] ?? f.recht })),
      };
      return aktuell;
    },
    "POST /api/integrationen/1/testen": () => {
      aktuell = { ...aktuell, status: "fehler", status_meldung: "Die Gegenstelle ist nicht erreichbar.", status_hinweis: "Läuft der Dienst?" };
      return aktuell;
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Integrationen />, "/integrationen");

  const bereich = await screen.findByRole("region", { name: "Notizen" });
  expect(within(bereich).getByText("in Ordnung")).toBeInTheDocument();
  expect(within(bereich).getByText(/2 von 2 Funktionen für Missa sichtbar/)).toBeInTheDocument();

  await nutzer.click(within(bereich).getByRole("button", { name: /Funktionen und Rechte/ }));
  expect(within(bereich).getByText("notizen_notiz_anlegen")).toBeInTheDocument(); // Name am Gateway
  await nutzer.selectOptions(within(bereich).getByLabelText("Recht für notiz_anlegen"), "gesperrt");
  await waitFor(() => expect(within(bereich).getByText(/1 von 2 Funktionen/)).toBeInTheDocument());
  expect(aufrufe.find((a) => a.methode === "PUT")?.koerper).toEqual({
    rechte: { notizen_auflisten: "erlaubt", notiz_anlegen: "gesperrt" },
  });

  await nutzer.click(within(bereich).getByLabelText("Notizen aktiv"));
  expect(await within(bereich).findByText("deaktiviert")).toBeInTheDocument();
  await nutzer.click(within(bereich).getByLabelText("Notizen aktiv"));

  await nutzer.click(within(bereich).getByRole("button", { name: "Testen" }));
  const meldung = await within(bereich).findByRole("alert");
  expect(meldung).toHaveTextContent("Die Gegenstelle ist nicht erreichbar.");
  expect(meldung).toHaveTextContent("Läuft der Dienst?");
});

test("Bearbeiten speichert Name und Formular, Entfernen fragt nach", async () => {
  let vorhanden = true;
  const aufrufe = backend({
    "GET /api/integrationen": () => (vorhanden ? [integration({})] : []),
    "GET /api/zugaenge": [],
    "PUT /api/integrationen/1": integration({ name: "Meine Notizen", konfig: { url: "http://neu:9000/mcp" } }),
    "DELETE /api/integrationen/1": () => {
      vorhanden = false;
      return { ok: true };
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Integrationen />, "/integrationen");

  await nutzer.click(await screen.findByRole("button", { name: "Notizen bearbeiten" }));
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByLabelText(/URL des MCP-Servers/)).toHaveValue("http://server:8000/mcp");
  await nutzer.clear(within(dialog).getByLabelText("Name"));
  await nutzer.type(within(dialog).getByLabelText("Name"), "Meine Notizen");
  await nutzer.clear(within(dialog).getByLabelText(/URL des MCP-Servers/));
  await nutzer.type(within(dialog).getByLabelText(/URL des MCP-Servers/), "http://neu:9000/mcp");
  await nutzer.click(within(dialog).getByRole("button", { name: "Speichern und testen" }));

  expect(await screen.findByRole("region", { name: "Meine Notizen" })).toBeInTheDocument();
  expect(aufrufe.find((a) => a.methode === "PUT")?.koerper).toEqual({
    name: "Meine Notizen",
    konfig: { url: "http://neu:9000/mcp" },
  });

  await nutzer.click(screen.getByRole("button", { name: "Meine Notizen entfernen" }));
  expect(aufrufe.some((a) => a.methode === "DELETE")).toBe(false);
  await nutzer.click(screen.getByRole("button", { name: "Entfernen" }));
  expect(await screen.findByText("Noch keine Integrationen")).toBeInTheDocument();
});

test("Funktion ausprobieren zeigt Ergebnis oder Fehler mit Hinweis", async () => {
  let versuch = 0;
  const aufrufe = backend({
    "GET /api/integrationen": [integration({})],
    "POST /api/integrationen/1/aufrufen": () => {
      versuch += 1;
      return versuch === 1
        ? { ok: true, ergebnis: "Notiz 2 gespeichert" }
        : { ok: false, meldung: "Ungültige Parameter für „notiz_anlegen“", hinweis: "Die erwarteten Parameter stehen in der Beschreibung." };
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Integrationen />, "/integrationen");

  await nutzer.click(await screen.findByRole("button", { name: /Funktionen und Rechte/ }));
  await nutzer.click(screen.getByRole("button", { name: "notiz_anlegen ausprobieren" }));
  const dialog = screen.getByRole("dialog");
  const eingabe = within(dialog).getByLabelText("Parameter (JSON)");
  expect(eingabe).toHaveValue('{\n  "text": ""\n}'); // Pflichtparameter sind vorbereitet
  expect(within(dialog).getByText(/kann etwas verändern/)).toBeInTheDocument();

  await nutzer.clear(eingabe);
  await nutzer.type(eingabe, "kein json");
  await nutzer.click(within(dialog).getByRole("button", { name: "Aufrufen" }));
  expect(within(dialog).getByText(/müssen gültiges JSON sein/)).toBeInTheDocument();
  expect(versuch).toBe(0);

  await nutzer.clear(eingabe);
  await nutzer.type(eingabe, '{{"text": "Brot"}');
  await nutzer.click(within(dialog).getByRole("button", { name: "Aufrufen" }));
  expect(await within(dialog).findByText("Notiz 2 gespeichert")).toBeInTheDocument();
  expect(aufrufe.find((a) => a.pfad.endsWith("/aufrufen"))?.koerper).toEqual({
    funktion: "notiz_anlegen",
    argumente: { text: "Brot" },
  });

  await nutzer.click(within(dialog).getByRole("button", { name: "Aufrufen" }));
  const fehler = await within(dialog).findByRole("alert");
  expect(fehler).toHaveTextContent("Ungültige Parameter");
  expect(fehler).toHaveTextContent("Die erwarteten Parameter stehen in der Beschreibung.");
});

test("Integration, deren Katalog-Eintrag fehlt, zeigt den Fehler und lässt sich entfernen", async () => {
  backend({
    "GET /api/integrationen": [
      integration({
        manifest: null,
        status: "fehler",
        status_meldung: "Diese Integration ist nicht mehr im Katalog vorhanden.",
        status_hinweis: "Wurde der Ordner der Integration gelöscht?",
      }),
    ],
  });
  zeige(<Integrationen />, "/integrationen");
  expect(await screen.findByRole("alert")).toHaveTextContent("nicht mehr im Katalog vorhanden");
  expect(screen.getByRole("button", { name: "Notizen bearbeiten" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Notizen entfernen" })).toBeEnabled();
});
