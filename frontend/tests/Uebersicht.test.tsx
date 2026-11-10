import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, expect, test, vi } from "vitest";

import { Uebersicht } from "../src/uebersicht/Uebersicht";
import { anordnen, funktionsId, type Kante, type Knoten, type Uebersicht as Daten } from "../src/uebersicht/uebersicht";
import { backend, TestFehler, zeige } from "./hilfen";

function knoten(teil: Partial<Knoten> & Pick<Knoten, "id" | "art" | "name">): Knoten {
  return { untertitel: "", status: "ok", status_text: "", details: [], link: null, ...teil };
}

function kante(von: string, nach: string, art: Kante["art"] = "nutzt", ordnet = true): Kante {
  return { id: `${von}>${nach}:${art}`, von, nach, art, ordnet };
}

const NOTIZEN = knoten({
  id: "integration:3",
  art: "integration",
  name: "Notizen",
  symbol: "🔌",
  untertitel: "MCP-Server",
  status_text: "Verbunden mit Notizen – 2 Funktion(en) gefunden.",
  details: [
    { titel: "Art", wert: "MCP-Server", zeit: false },
    { titel: "Funktionen für Missa", wert: "2 von 2", zeit: false },
    { titel: "Zuletzt geprüft", wert: "2026-11-10T10:00:00+00:00", zeit: true },
    { titel: "Leer", wert: null, zeit: false },
  ],
  funktionen: [
    { name: "notizen_auflisten", beschreibung: "Listet alle Notizen auf.", recht: "erlaubt", recht_name: "erlaubt", schreibend: false },
    { name: "notizen_notiz_anlegen", beschreibung: "Legt eine Notiz an.", recht: "nachfragen", recht_name: "erst nachfragen", schreibend: true },
  ],
  link: { pfad: "/integrationen", titel: "Zur Integration" },
});

function daten(teil: Partial<Daten> = {}): Daten {
  const alle = [
    knoten({
      id: "missa",
      art: "missa",
      name: "Missa",
      untertitel: "missa-core",
      status: "grau",
      status_text: "Nicht eingerichtet – ohne Health-URL wird missa-core nicht abgefragt.",
      hinweis: "Das Panel fragt missa-core nur lesend ab (HTTP-GET) und verändert dort nichts.",
      link: { pfad: "/clients", titel: "Clients verwalten" },
    }),
    knoten({ id: "client:1", art: "client", name: "missa-core", untertitel: "Client", status_text: "Hat sich schon verbunden." }),
    knoten({ id: "rolle:schnell", art: "rolle", name: "Schnell", untertitel: "Rolle · missa-schnell", status: "warn", status_text: "„Klein“ ist gestört – das Ersatzmodell „Gross“ springt ein." }),
    knoten({ id: "modell:1", art: "modell", name: "Klein", untertitel: "klein-7b", status: "fehler", status_text: "Das Modell antwortet nicht." }),
    NOTIZEN,
    knoten({ id: "geraet:7", art: "geraet", name: "Wohnzimmer", untertitel: "Gerät", status: "fehler", status_text: "Offline – das Gerät meldet sich nicht mehr.", link: { pfad: "/geraete", titel: "Zum Gerät" } }),
    knoten({ id: "zugang:2", art: "zugang", name: "Notiz-Token", untertitel: "Bearer-Token", status_text: "Wird verwendet." }),
    knoten({ id: "regel:5", art: "regel", name: "Klingel", untertitel: "Regel", status: "grau", status_text: "Pausiert." }),
  ];
  return {
    knoten: alle,
    kanten: [
      kante("client:1", "missa", "verbindet"),
      kante("missa", "rolle:schnell"),
      kante("rolle:schnell", "modell:1", "haupt"),
      kante("missa", "integration:3"),
      kante("integration:3", "zugang:2", "zugang"),
      kante("missa", "geraet:7"),
      kante("geraet:7", "regel:5", "ausloeser"),
      kante("regel:5", "integration:3", "aktion", false),
    ],
    positionen: {},
    zusammenfassung: { ok: 3, warn: 1, fehler: 2, grau: 2 },
    ...teil,
  };
}

function bildschirm(schmal: boolean) {
  window.matchMedia = vi.fn().mockReturnValue({ matches: schmal, addEventListener() {}, removeEventListener() {} }) as never;
}

beforeAll(() => {
  // Was React Flow vom Browser braucht und jsdom nicht mitbringt.
  class Beobachter {
    constructor(private readonly rueckruf: ResizeObserverCallback) {}
    observe(ziel: Element) {
      this.rueckruf([{ target: ziel } as ResizeObserverEntry], this as unknown as ResizeObserver);
    }
    unobserve() {}
    disconnect() {}
  }
  class Matrix {
    m22: number;
    constructor(transform?: string) {
      const zoom = transform?.match(/scale\(([0-9.]+)\)/)?.[1];
      this.m22 = zoom !== undefined ? Number(zoom) : 1;
    }
  }
  globalThis.ResizeObserver = Beobachter as unknown as typeof ResizeObserver;
  globalThis.DOMMatrixReadOnly = Matrix as unknown as typeof DOMMatrixReadOnly;
  Object.defineProperties(HTMLElement.prototype, {
    offsetHeight: { get(this: HTMLElement) { return parseFloat(this.style.height) || 1; } },
    offsetWidth: { get(this: HTMLElement) { return parseFloat(this.style.width) || 1; } },
  });
  (SVGElement.prototype as unknown as { getBBox: () => DOMRect }).getBBox = () => ({ x: 0, y: 0, width: 0, height: 0 }) as DOMRect;
});

beforeEach(() => bildschirm(true)); // die meisten Tests nutzen die Liste (auf dem Handy der Anfang)

test("Liste: alles Eingerichtete mit Status; ein Klick zeigt Details und den Link zur Bearbeitung", async () => {
  backend({ "GET /api/status": daten() });
  const nutzer = userEvent.setup();
  zeige(<Uebersicht />);

  const integrationen = await screen.findByRole("region", { name: "Integrationen" });
  expect(within(integrationen).getByRole("button", { name: /Notizen/ })).toHaveTextContent("Verbunden mit Notizen – 2 Funktion(en) gefunden.");
  expect(within(within(integrationen).getByRole("button", { name: /Notizen/ })).getByRole("img", { name: "in Ordnung" })).toBeInTheDocument();
  const geraete = screen.getByRole("region", { name: "Geräte" });
  expect(within(geraete).getByRole("img", { name: "Fehler" })).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "Rollen" })).getByRole("img", { name: "Warnung" })).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "Missa" })).getByRole("img", { name: "aus" })).toBeInTheDocument();
  expect(screen.getByRole("status", { name: "Zusammenfassung" })).toHaveTextContent("2 Fehler1 Warnung3 in Ordnung2 aus");
  expect(screen.queryByRole("complementary", { name: "Details" })).not.toBeInTheDocument();

  await nutzer.click(within(integrationen).getByRole("button", { name: /Notizen/ }));
  const leiste = screen.getByRole("complementary", { name: "Details" });
  expect(within(leiste).getByRole("heading", { name: "🔌 Notizen" })).toBeInTheDocument();
  expect(within(leiste).getByText("in Ordnung")).toBeInTheDocument();
  expect(within(leiste).getByText("2 von 2")).toBeInTheDocument();
  expect(within(leiste).queryByText("Leer")).not.toBeInTheDocument(); // Angaben ohne Wert bleiben weg
  expect(within(leiste).queryByText("2026-11-10T10:00:00+00:00")).not.toBeInTheDocument(); // Zeitpunkte in Ortszeit
  expect(within(leiste).getByText("notizen_notiz_anlegen")).toBeInTheDocument();
  expect(within(leiste).getByText("erst nachfragen")).toBeInTheDocument();
  expect(within(leiste).getByRole("link", { name: "Zur Integration" })).toHaveAttribute("href", "/integrationen");

  await nutzer.click(within(screen.getByRole("region", { name: "Missa" })).getByRole("button", { name: /Missa/ }));
  expect(within(leiste).getByText(/Nicht eingerichtet – ohne Health-URL/)).toBeInTheDocument();
  expect(within(leiste).getByText(/fragt missa-core nur lesend ab/)).toBeInTheDocument();
  await nutzer.click(within(leiste).getByRole("button", { name: "Details schliessen" }));
  expect(screen.queryByRole("complementary", { name: "Details" })).not.toBeInTheDocument();
});

test("Filter blenden Arten aus; „Jetzt prüfen“ holt den neuen Stand", async () => {
  const geprueft = daten({ zusammenfassung: { ok: 2, warn: 1, fehler: 3, grau: 2 } });
  geprueft.knoten = geprueft.knoten.map((eintrag) => (eintrag.id === "integration:3" ? { ...eintrag, status: "fehler", status_text: "Die Gegenstelle ist nicht erreichbar." } : eintrag));
  const aufrufe = backend({ "GET /api/status": daten(), "POST /api/status/pruefen": geprueft });
  const nutzer = userEvent.setup();
  zeige(<Uebersicht />);

  const filter = await screen.findByRole("group", { name: "Anzeigen" });
  expect(within(filter).getAllByRole("button").map((knopf) => knopf.textContent)).toEqual([
    "Integrationen 1",
    "Geräte 1",
    "Modelle 2",
    "Zugänge 1",
    "Clients 1",
    "Regeln 1",
  ]);
  await nutzer.click(within(filter).getByRole("button", { name: /Modelle/ }));
  expect(within(filter).getByRole("button", { name: /Modelle/ })).toHaveAttribute("aria-pressed", "false");
  expect(screen.queryByRole("region", { name: "Rollen" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Modelle" })).not.toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Missa" })).toBeInTheDocument(); // Missa bleibt immer
  await nutzer.click(within(filter).getByRole("button", { name: /Modelle/ }));
  expect(screen.getByRole("region", { name: "Rollen" })).toBeInTheDocument();

  await nutzer.click(screen.getByRole("button", { name: "Jetzt prüfen" }));
  expect(await screen.findByText("Die Gegenstelle ist nicht erreichbar.")).toBeInTheDocument();
  expect(screen.getByRole("status", { name: "Zusammenfassung" })).toHaveTextContent("3 Fehler");
  expect(aufrufe.some((aufruf) => aufruf.methode === "POST" && aufruf.pfad === "/api/status/pruefen")).toBe(true);
});

test("Die Übersicht fragt alle 30 Sekunden nach: Neues erscheint ohne Neuladen", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    let stand = daten();
    stand.knoten = stand.knoten.filter((eintrag) => eintrag.id !== "integration:3");
    const aufrufe = backend({ "GET /api/status": () => stand });
    zeige(<Uebersicht />);
    expect(await screen.findByRole("region", { name: "Geräte" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Integrationen" })).not.toBeInTheDocument();

    stand = daten(); // inzwischen wurde eine Integration eingerichtet
    await act(() => vi.advanceTimersByTimeAsync(29_000));
    expect(aufrufe).toHaveLength(1);
    await act(() => vi.advanceTimersByTimeAsync(1_500));
    expect(await screen.findByRole("region", { name: "Integrationen" })).toBeInTheDocument();
    expect(aufrufe).toHaveLength(2);
  } finally {
    vi.useRealTimers();
  }
});

test("Ohne Eingerichtetes weist die Seite den Weg zum Katalog; Fehler beim Laden werden gezeigt", async () => {
  const leer = daten({ kanten: [], zusammenfassung: { ok: 0, warn: 0, fehler: 0, grau: 2 } });
  leer.knoten = leer.knoten.filter((eintrag) => eintrag.art === "missa" || eintrag.art === "rolle");
  backend({ "GET /api/status": leer });
  const { unmount } = zeige(<Uebersicht />);
  expect(await screen.findByText(/Noch ist nichts eingerichtet/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Zum Katalog" })).toHaveAttribute("href", "/katalog");
  unmount();

  backend({ "GET /api/status": new TestFehler(500, "Die Übersicht lässt sich nicht laden.") });
  zeige(<Uebersicht />);
  expect(await screen.findByText("Die Übersicht lässt sich nicht laden.")).toBeInTheDocument();
});

test("Graph: Knoten mit Status, „+“ öffnet den Katalog, Funktionen lassen sich aufklappen", async () => {
  bildschirm(false);
  const aufrufe = backend({ "GET /api/status": daten({ positionen: { "regel:5": { x: 900, y: 40 } } }), "DELETE /api/status/positionen": { gespeichert: 0 } });
  const nutzer = userEvent.setup();
  zeige(<Uebersicht />);

  const graph = await screen.findByLabelText("Verbindungsbaum");
  await waitFor(() => expect(graph.querySelectorAll(".react-flow__node")).toHaveLength(8));
  expect(graph.querySelectorAll(".react-flow__node .graph-knoten.fehler")).toHaveLength(2);
  expect(within(graph).getByText("Wohnzimmer")).toBeInTheDocument();
  expect(within(graph).getAllByRole("img", { name: "Fehler" })).toHaveLength(2);
  expect(within(graph).getByRole("link", { name: /Integration hinzufügen/ })).toHaveAttribute("href", "/katalog");
  // (Die Kanten zeichnet React Flow erst, wenn der Browser die Knoten vermessen hat – das prüft der Test im echten Browser.)

  // Funktionen aufklappen: zwei weitere Knoten mit Namen und Recht.
  await nutzer.click(within(graph).getByRole("button", { name: /2 Funktionen/ }));
  await waitFor(() => expect(graph.querySelectorAll(".graph-knoten.funktion")).toHaveLength(2));
  expect(within(graph).getByText("notizen_notiz_anlegen")).toBeInTheDocument();
  expect(within(graph).getByText("erst nachfragen")).toBeInTheDocument();
  expect(within(graph).getByRole("button", { name: /2 Funktionen/ })).toHaveAttribute("aria-expanded", "true");

  // Ein Knoten wird gewählt (Klick oder Eingabetaste): rechts erscheinen die Details.
  const wohnzimmer = within(graph).getByText("Wohnzimmer").closest(".react-flow__node") as HTMLElement;
  fireEvent.click(wohnzimmer);
  const leiste = await screen.findByRole("complementary", { name: "Details" });
  expect(within(leiste).getByText("Offline – das Gerät meldet sich nicht mehr.")).toBeInTheDocument();
  expect(within(leiste).getByRole("link", { name: "Zum Gerät" })).toHaveAttribute("href", "/geraete");

  // Eine eigene Anordnung lässt sich verwerfen.
  await nutzer.click(screen.getByRole("button", { name: "Automatisch anordnen" }));
  await waitFor(() => expect(aufrufe.some((aufruf) => aufruf.methode === "DELETE" && aufruf.pfad === "/api/status/positionen")).toBe(true));

  // Liste und Graph lassen sich umschalten.
  await nutzer.click(screen.getByRole("button", { name: "Als Liste anzeigen" }));
  expect(screen.getByRole("region", { name: "Geräte" })).toBeInTheDocument();
  expect(screen.queryByLabelText("Verbindungsbaum")).not.toBeInTheDocument();
});

test("Anordnung: von links nach rechts entlang der Verbindungen; Filter, Aufklappen und eigene Positionen", () => {
  const { knoten: gezeichnet, kanten } = anordnen(daten());
  const ort = (id: string) => gezeichnet.find((eintrag) => eintrag.id === id)!.ort;
  expect(gezeichnet).toHaveLength(8);
  expect(kanten).toHaveLength(8);
  // Client → Missa → Integration → Zugang; Rolle → Modell; Gerät → Regel
  expect(ort("client:1").x).toBeLessThan(ort("missa").x);
  expect(ort("missa").x).toBeLessThan(ort("integration:3").x);
  expect(ort("integration:3").x).toBeLessThan(ort("zugang:2").x);
  expect(ort("rolle:schnell").x).toBeLessThan(ort("modell:1").x);
  expect(ort("geraet:7").x).toBeLessThan(ort("regel:5").x);
  // Nichts liegt übereinander.
  const belegt = new Set(gezeichnet.map((eintrag) => `${eintrag.ort.x}/${eintrag.ort.y}`));
  expect(belegt.size).toBe(gezeichnet.length);

  // Ausgeblendete Arten verschwinden samt ihren Kanten; Missa bleibt.
  const ohne = anordnen(daten(), { ausgeblendet: new Set(["integration", "missa"] as const) });
  expect(ohne.knoten.map((eintrag) => eintrag.id)).not.toContain("integration:3");
  expect(ohne.knoten.map((eintrag) => eintrag.id)).toContain("missa");
  expect(ohne.kanten.every((eine) => eine.von !== "integration:3" && eine.nach !== "integration:3")).toBe(true);

  // Aufgeklappt: die Funktionen stehen rechts von ihrer Integration.
  const offen = anordnen(daten(), { aufgeklappt: new Set(["integration:3"]) });
  const funktion = offen.knoten.find((eintrag) => eintrag.id === funktionsId("integration:3", "notizen_auflisten"))!;
  const integration = offen.knoten.find((eintrag) => eintrag.id === "integration:3")!;
  expect(funktion.art).toBe("funktion");
  expect(funktion.elternteil).toBe("integration:3");
  expect(funktion.ort.x).toBeGreaterThan(integration.ort.x);
  expect(offen.kanten).toHaveLength(10);

  // Von Hand verschoben: der Knoten bleibt, wo er hingezogen wurde – seine Funktionen wandern mit.
  const verschoben = anordnen(daten(), { aufgeklappt: new Set(["integration:3"]), positionen: { "integration:3": { x: integration.ort.x + 500, y: integration.ort.y - 300 } } });
  const neu = verschoben.knoten.find((eintrag) => eintrag.id === "integration:3")!;
  const mit = verschoben.knoten.find((eintrag) => eintrag.id === funktion.id)!;
  expect(neu.ort).toEqual({ x: integration.ort.x + 500, y: integration.ort.y - 300 });
  expect(mit.ort).toEqual({ x: funktion.ort.x + 500, y: funktion.ort.y - 300 });
  // Alle anderen bleiben, wo die automatische Anordnung sie hingestellt hat.
  expect(verschoben.knoten.find((eintrag) => eintrag.id === "missa")!.ort).toEqual(offen.knoten.find((eintrag) => eintrag.id === "missa")!.ort);
});
