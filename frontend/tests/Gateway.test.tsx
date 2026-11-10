import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import { Seiten } from "../src/App";
import { type Client, Clients } from "../src/gateway/Clients";
import { Freigaben } from "../src/gateway/Freigaben";
import type { Freigabe } from "../src/gateway/freigaben";
import { Protokoll } from "../src/gateway/Protokoll";
import { backend, TestFehler, zeige } from "./hilfen";

const TOKEN = "mc_geheimer-client-token-0123456789abcdef";

function client(teil: Partial<Client>): Client {
  return {
    id: 1,
    name: "missa-core",
    token_anfang: "mc_gehe…",
    erstellt: "2026-01-15T12:00:00+00:00",
    zuletzt_gesehen: null,
    widerrufen: null,
    aktiv: true,
    ...teil,
  };
}

function freigabe(teil: Partial<Freigabe>): Freigabe {
  return {
    id: 7,
    erstellt: new Date(Date.now() - 20_000).toISOString(),
    laeuft_ab: new Date(Date.now() + 280_000).toISOString(),
    client: "missa-core",
    integration: "Kalender",
    funktion: "kalender_termin_eintragen",
    beschreibung: "Trägt einen Termin ein.",
    vorschau: "",
    argumente: { titel: "Zahnarzt", beginn: "2026-02-03T09:00", teilnehmer: ["Louis"] },
    status: "offen",
    entschieden: null,
    ...teil,
  };
}

// ---------------------------------------------------------------- Clients

test("Client anlegen zeigt den Token genau einmal, mit den Adressen zum Verbinden", async () => {
  const liste: Client[] = [];
  const aufrufe = backend({
    "GET /api/clients": () => [...liste],
    "POST /api/clients": () => {
      liste.push(client({}));
      return client({ token: TOKEN });
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Clients />);

  expect(await screen.findByText("Noch keine Clients")).toBeInTheDocument();
  await nutzer.click(screen.getByRole("button", { name: /Neuer Client/ }));
  await nutzer.type(screen.getByLabelText(/Name/), "missa-core");
  await nutzer.click(screen.getByRole("button", { name: "Client anlegen" }));

  const dialog = await screen.findByRole("dialog", { name: "Token für „missa-core“" });
  expect(within(dialog).getByLabelText("Token")).toHaveValue(TOKEN);
  expect(within(dialog).getByText(/nur jetzt angezeigt/)).toBeInTheDocument();
  expect(within(dialog).getByText(`${window.location.origin}/mcp`)).toBeInTheDocument();
  expect(within(dialog).getByText(`${window.location.origin}/api/events/stream`)).toBeInTheDocument();
  expect(aufrufe.find((a) => a.methode === "POST")?.koerper).toEqual({ name: "missa-core" });

  await nutzer.click(within(dialog).getByRole("button", { name: "Ich habe den Token gespeichert" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  // In der Liste steht danach nur noch der Anfang des Tokens.
  expect(await screen.findByText("mc_gehe…")).toBeInTheDocument();
  expect(document.body.innerHTML).not.toContain(TOKEN);
});

test("Token widerrufen fragt nach; widerrufene Clients sind als solche erkennbar", async () => {
  let aktuell = client({ zuletzt_gesehen: "2026-01-15T13:00:00+00:00" });
  const aufrufe = backend({
    "GET /api/clients": () => [aktuell],
    "POST /api/clients/1/widerrufen": () => {
      aktuell = client({ aktiv: false, widerrufen: "2026-01-15T14:00:00+00:00" });
      return aktuell;
    },
    "DELETE /api/clients/1": { ok: true },
  });
  const nutzer = userEvent.setup();
  zeige(<Clients />);

  expect(await screen.findByText("aktiv")).toBeInTheDocument();
  await nutzer.click(screen.getByRole("button", { name: "Token von missa-core widerrufen" }));
  expect(aufrufe.some((a) => a.methode === "POST")).toBe(false);
  expect(screen.getByText(/sofort nicht mehr verbinden/)).toBeInTheDocument();
  await nutzer.click(screen.getByRole("button", { name: "Widerrufen" }));

  expect(await screen.findByText("widerrufen")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Token von missa-core widerrufen" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "missa-core löschen" })).toBeInTheDocument();
});

test("doppelter Client-Name zeigt die Meldung des Backends", async () => {
  backend({
    "GET /api/clients": [client({})],
    "POST /api/clients": new TestFehler(409, "Es gibt bereits einen Client mit dem Namen „missa-core“.", "Bitte einen anderen Namen wählen."),
  });
  const nutzer = userEvent.setup();
  zeige(<Clients />);
  await nutzer.click(await screen.findByRole("button", { name: /Neuer Client/ }));
  await nutzer.type(screen.getByLabelText(/Name/), "missa-core");
  await nutzer.click(screen.getByRole("button", { name: "Client anlegen" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Bitte einen anderen Namen wählen.");
});

// ---------------------------------------------------------------- Freigaben

test("offene Freigabe zeigt Funktion und Parameter; Erlauben schickt die Entscheidung", async () => {
  let offen = [freigabe({})];
  const aufrufe = backend({
    "GET /api/freigaben": () => ({ offen, verlauf: [], frist_sekunden: 300 }),
    "POST /api/freigaben/7": () => {
      offen = [];
      return freigabe({ status: "erlaubt" });
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Freigaben />);

  const karte = await screen.findByRole("region", { name: "Freigabe für kalender_termin_eintragen" });
  expect(within(karte).getByText(/„missa-core“ möchte über „Kalender“ ausführen/)).toBeInTheDocument();
  expect(within(karte).getByText("Trägt einen Termin ein.")).toBeInTheDocument();
  expect(within(karte).getByText("titel")).toBeInTheDocument();
  expect(within(karte).getByText("Zahnarzt")).toBeInTheDocument();
  expect(within(karte).getByText(/"Louis"/)).toBeInTheDocument(); // auch Listen sind lesbar
  expect(within(karte).getByText(/wartet noch 4:[34]\d/)).toBeInTheDocument();
  expect(screen.getByText(/innerhalb von 5 Minuten/)).toBeInTheDocument();

  await nutzer.click(within(karte).getByRole("button", { name: "Erlauben" }));
  expect(await screen.findByText("Nichts zu entscheiden")).toBeInTheDocument();
  expect(aufrufe.find((a) => a.methode === "POST")?.koerper).toEqual({ erlauben: true });
});

test("Freigabe zeigt die Vorschau der Integration: was genau passieren würde", async () => {
  backend({
    "GET /api/freigaben": {
      offen: [
        freigabe({
          funktion: "gedaechtnis_vergessen",
          integration: "Gedächtnis",
          argumente: { id: 12 },
          vorschau: "Löscht aus dem Gedächtnis (Vorlieben): „Mag keine Oliven“",
        }),
      ],
      verlauf: [],
      frist_sekunden: 300,
    },
  });
  zeige(<Freigaben />);

  const karte = await screen.findByRole("region", { name: "Freigabe für gedaechtnis_vergessen" });
  expect(within(karte).getByText("Löscht aus dem Gedächtnis (Vorlieben): „Mag keine Oliven“")).toBeInTheDocument();
  expect(within(karte).getByText("12")).toBeInTheDocument(); // die Parameter stehen weiterhin da
});

test("Ablehnen und Verlauf; abgelaufene Anfrage zeigt verständliche Meldung", async () => {
  const aufrufe = backend({
    "GET /api/freigaben": {
      offen: [freigabe({ argumente: {} })],
      verlauf: [freigabe({ id: 3, status: "abgelaufen", funktion: "licht_schalten" }), freigabe({ id: 2, status: "abgelehnt" })],
      frist_sekunden: 300,
    },
    "POST /api/freigaben/7": new TestFehler(409, "Diese Anfrage wartet nicht mehr auf eine Entscheidung.", "Missa muss die Aktion erneut anstossen."),
  });
  const nutzer = userEvent.setup();
  zeige(<Freigaben />);

  expect(await screen.findByText("Ohne Parameter.")).toBeInTheDocument();
  expect(screen.getByText("abgelaufen")).toBeInTheDocument();
  expect(screen.getByText("abgelehnt")).toBeInTheDocument();
  await nutzer.click(screen.getByRole("button", { name: "Ablehnen" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Missa muss die Aktion erneut anstossen.");
  expect(aufrufe.find((a) => a.methode === "POST")?.koerper).toEqual({ erlauben: false });
});

test("Navigation zeigt den Zähler offener Freigaben", async () => {
  backend({
    "GET /api/auth/status": { eingerichtet: true, angemeldet: true, version: "1.2.3" },
    "GET /api/freigaben/anzahl": { offen: 2 },
    "GET /api/freigaben": { offen: [], verlauf: [], frist_sekunden: 300 },
  });
  zeige(<Seiten />, "/freigaben");
  const zaehler = await screen.findByLabelText("2 offene Freigaben");
  expect(zaehler).toHaveTextContent("2");
  expect(zaehler.closest("a")).toHaveAttribute("href", "/freigaben");
});

test("ohne offene Freigaben gibt es keinen Zähler", async () => {
  backend({
    "GET /api/auth/status": { eingerichtet: true, angemeldet: true, version: "1.2.3" },
    "GET /api/freigaben": { offen: [], verlauf: [], frist_sekunden: 300 },
  });
  zeige(<Seiten />, "/freigaben");
  await screen.findByText("Nichts zu entscheiden");
  expect(screen.queryByLabelText(/offene Freigaben/)).not.toBeInTheDocument();
});

// ---------------------------------------------------------------- Protokoll

const AUFRUFE = {
  anzahl: 2,
  clients: ["Overlay-App", "missa-core"],
  integrationen: ["Kalender"],
  eintraege: [
    { id: 2, zeit: "2026-01-15T12:05:00+00:00", quelle: "gateway", client: "missa-core", integration: "Kalender", funktion: "kalender_termin_eintragen", ok: false, fehler: "Die Aktion wurde im Panel abgelehnt.", dauer_ms: 12400, freigabe: "abgelehnt" },
    { id: 1, zeit: "2026-01-15T12:00:00+00:00", quelle: "gateway", client: "missa-core", integration: "Kalender", funktion: "kalender_termine_anzeigen", ok: true, fehler: "", dauer_ms: 85, freigabe: "ohne" },
  ],
};

test("Protokoll zeigt Aufrufe und filtert über das Backend", async () => {
  const aufrufe = backend({
    "GET /api/protokoll?limit=100": AUFRUFE,
    "GET /api/protokoll?limit=100&ergebnis=fehler": { ...AUFRUFE, anzahl: 1, eintraege: [AUFRUFE.eintraege[0]] },
    "GET /api/protokoll?limit=100&client=Overlay-App&ergebnis=fehler": { ...AUFRUFE, anzahl: 0, eintraege: [] },
  });
  const nutzer = userEvent.setup();
  zeige(<Protokoll />);

  expect(await screen.findByText("kalender_termine_anzeigen")).toBeInTheDocument();
  const fehlerZeile = screen.getByText("kalender_termin_eintragen").closest("tr")!;
  expect(within(fehlerZeile).getByText("Die Aktion wurde im Panel abgelehnt.")).toBeInTheDocument();
  expect(within(fehlerZeile).getByText("Freigabe: abgelehnt")).toBeInTheDocument();
  expect(within(fehlerZeile).getByText("12.4 s")).toBeInTheDocument();
  expect(screen.getByText("85 ms")).toBeInTheDocument();
  expect(screen.getByText("2 von 2 Einträgen")).toBeInTheDocument();

  await nutzer.selectOptions(screen.getByLabelText("Ergebnis"), "fehler");
  await waitFor(() => expect(screen.queryByText("kalender_termine_anzeigen")).not.toBeInTheDocument());
  await nutzer.selectOptions(screen.getByLabelText("Client"), "Overlay-App");
  expect(await screen.findByText("Zu diesem Filter gibt es keine Einträge.")).toBeInTheDocument();
  expect(aufrufe.map((a) => a.pfad)).toContain("/api/protokoll?limit=100&client=Overlay-App&ergebnis=fehler");
});

test("Reiter Ereignisse: Liste und Test-Ereignis senden", async () => {
  const ereignisse = [
    { id: 1, zeit: "2026-01-15T12:00:00+00:00", art: "integration_ausgefallen", quelle: "Notizen", titel: "Integration „Notizen“ ist ausgefallen", nachricht: "Die Gegenstelle ist nicht erreichbar.", dringlichkeit: "hoch", daten: {} },
  ];
  const aufrufe = backend({
    "GET /api/protokoll?limit=100": { anzahl: 0, eintraege: [], clients: [], integrationen: [] },
    "GET /api/ereignisse": () => [...ereignisse],
    "POST /api/ereignisse/test": () => {
      ereignisse.unshift({ id: 2, zeit: "2026-01-15T12:01:00+00:00", art: "test", quelle: "panel", titel: "Test-Ereignis", nachricht: "Das ist ein Test-Ereignis aus dem Panel.", dringlichkeit: "normal", daten: {} });
      return ereignisse[0];
    },
  });
  const nutzer = userEvent.setup();
  zeige(<Protokoll />);

  expect(await screen.findByText("Noch hat niemand eine Funktion aufgerufen.")).toBeInTheDocument();
  await nutzer.click(screen.getByRole("tab", { name: "Ereignisse" }));
  expect(await screen.findByText("Integration „Notizen“ ist ausgefallen")).toBeInTheDocument();
  expect(screen.getByText("hoch")).toBeInTheDocument();

  await nutzer.click(screen.getByRole("button", { name: /Test-Ereignis senden/ }));
  expect(await screen.findByText("Das ist ein Test-Ereignis aus dem Panel.")).toBeInTheDocument();
  expect(aufrufe.some((a) => a.methode === "POST" && a.pfad === "/api/ereignisse/test")).toBe(true);
});
