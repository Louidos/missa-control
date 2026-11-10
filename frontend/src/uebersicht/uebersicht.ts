import dagre from "@dagrejs/dagre";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api";
import type { Status } from "../ui/ui";

export type KnotenArt = "missa" | "client" | "rolle" | "modell" | "integration" | "geraet" | "zugang" | "regel";

export interface Detail {
  titel: string;
  wert: string | number | null;
  /** Der Wert ist ein Zeitpunkt (ISO) und wird in Ortszeit angezeigt. */
  zeit: boolean;
}

export interface FunktionsAngabe {
  name: string;
  beschreibung: string;
  recht: "erlaubt" | "nachfragen" | "gesperrt";
  recht_name: string;
  schreibend: boolean;
}

export interface Knoten {
  id: string;
  art: KnotenArt;
  name: string;
  untertitel: string;
  symbol?: string;
  status: Status;
  status_text: string;
  details: Detail[];
  hinweis?: string | null;
  funktionen?: FunktionsAngabe[];
  link: { pfad: string; titel: string } | null;
}

export interface Kante {
  id: string;
  von: string;
  nach: string;
  art: "nutzt" | "verbindet" | "haupt" | "ersatz" | "zugang" | "ausloeser" | "aktion";
  /** Zählt für die automatische Anordnung. */
  ordnet: boolean;
}

export interface Ort {
  x: number;
  y: number;
}

export interface Uebersicht {
  knoten: Knoten[];
  kanten: Kante[];
  positionen: Record<string, Ort>;
  zusammenfassung: Record<Status, number>;
}

export const STATUS = ["status"] as const;

export function useStatus() {
  // Alle 30 Sekunden nachsehen: Neues erscheint von selbst, Ausfälle werden ohne Neuladen sichtbar.
  return useQuery({ queryKey: STATUS, queryFn: () => api.get<Uebersicht>("/api/status"), refetchInterval: 30_000 });
}

export const STATUS_NAME: Record<Status, string> = { ok: "in Ordnung", warn: "Warnung", fehler: "Fehler", grau: "aus" };

/** Die Arten, nach denen sich filtern lässt (Missa selbst ist immer zu sehen). */
export const FILTER: { wert: string; titel: string; arten: KnotenArt[] }[] = [
  { wert: "integrationen", titel: "Integrationen", arten: ["integration"] },
  { wert: "geraete", titel: "Geräte", arten: ["geraet"] },
  { wert: "modelle", titel: "Modelle", arten: ["rolle", "modell"] },
  { wert: "zugaenge", titel: "Zugänge", arten: ["zugang"] },
  { wert: "clients", titel: "Clients", arten: ["client"] },
  { wert: "regeln", titel: "Regeln", arten: ["regel"] },
];

export const ART_NAME: Record<KnotenArt, string> = {
  missa: "Missa",
  client: "Clients",
  rolle: "Rollen",
  modell: "Modelle",
  integration: "Integrationen",
  geraet: "Geräte",
  zugang: "Zugänge",
  regel: "Regeln",
};

export interface Gezeichnet {
  id: string;
  /** „funktion“ für die aufgeklappten Funktionen einer Integration. */
  art: KnotenArt | "funktion";
  ort: Ort;
  breite: number;
  hoehe: number;
  knoten?: Knoten;
  funktion?: FunktionsAngabe;
  /** Bei Funktionen: die Integration, zu der sie gehören. */
  elternteil?: string;
}

export const GROESSE: Record<Gezeichnet["art"], { breite: number; hoehe: number }> = {
  missa: { breite: 190, hoehe: 76 },
  client: { breite: 210, hoehe: 60 },
  rolle: { breite: 210, hoehe: 60 },
  modell: { breite: 210, hoehe: 60 },
  integration: { breite: 230, hoehe: 76 },
  geraet: { breite: 230, hoehe: 76 },
  zugang: { breite: 210, hoehe: 60 },
  regel: { breite: 210, hoehe: 60 },
  funktion: { breite: 250, hoehe: 40 },
};

export function funktionsId(knotenId: string, name: string): string {
  return `${knotenId}/${name}`;
}

/**
 * Ordnet die sichtbaren Knoten an: von links nach rechts entlang der Verbindungen (dagre). Knoten, die von
 * Hand verschoben wurden, behalten ihren Platz; ihre aufgeklappten Funktionen wandern mit.
 */
export function anordnen(
  uebersicht: Pick<Uebersicht, "knoten" | "kanten">,
  optionen: { ausgeblendet?: ReadonlySet<KnotenArt>; aufgeklappt?: ReadonlySet<string>; positionen?: Record<string, Ort> } = {},
): { knoten: Gezeichnet[]; kanten: Kante[] } {
  const { ausgeblendet = new Set(), aufgeklappt = new Set(), positionen = {} } = optionen;
  const sichtbar = uebersicht.knoten.filter((knoten) => knoten.art === "missa" || !ausgeblendet.has(knoten.art));
  const vorhanden = new Set(sichtbar.map((knoten) => knoten.id));
  const kanten = uebersicht.kanten.filter((kante) => vorhanden.has(kante.von) && vorhanden.has(kante.nach));

  const graph = new dagre.graphlib.Graph();
  graph.setGraph({ rankdir: "LR", nodesep: 18, ranksep: 80, marginx: 20, marginy: 20 });
  graph.setDefaultEdgeLabel(() => ({}));
  const gezeichnet: Gezeichnet[] = [];
  for (const knoten of sichtbar) {
    const groesse = GROESSE[knoten.art];
    graph.setNode(knoten.id, { width: groesse.breite, height: groesse.hoehe });
    gezeichnet.push({ id: knoten.id, art: knoten.art, ort: { x: 0, y: 0 }, ...groesse, knoten });
    if (!aufgeklappt.has(knoten.id)) continue;
    for (const funktion of knoten.funktionen ?? []) {
      const id = funktionsId(knoten.id, funktion.name);
      graph.setNode(id, { width: GROESSE.funktion.breite, height: GROESSE.funktion.hoehe });
      graph.setEdge(knoten.id, id);
      gezeichnet.push({ id, art: "funktion", ort: { x: 0, y: 0 }, ...GROESSE.funktion, funktion, elternteil: knoten.id });
      kanten.push({ id: `${knoten.id}>${id}`, von: knoten.id, nach: id, art: "nutzt", ordnet: true });
    }
  }
  for (const kante of kanten) if (kante.ordnet && !graph.hasEdge(kante.von, kante.nach)) graph.setEdge(kante.von, kante.nach);
  dagre.layout(graph);

  const automatisch = new Map<string, Ort>();
  for (const eintrag of gezeichnet) {
    const ort = graph.node(eintrag.id);
    // dagre nennt die Mitte, gezeichnet wird ab der linken oberen Ecke.
    automatisch.set(eintrag.id, { x: Math.round(ort.x - eintrag.breite / 2), y: Math.round(ort.y - eintrag.hoehe / 2) });
  }
  for (const eintrag of gezeichnet) {
    const auto = automatisch.get(eintrag.id) ?? { x: 0, y: 0 };
    if (eintrag.elternteil) {
      // Funktionen bleiben bei ihrer Integration, auch wenn diese verschoben wurde.
      const eltern = positionen[eintrag.elternteil];
      const elternAuto = automatisch.get(eintrag.elternteil);
      eintrag.ort = eltern && elternAuto ? { x: auto.x + eltern.x - elternAuto.x, y: auto.y + eltern.y - elternAuto.y } : auto;
    } else {
      eintrag.ort = positionen[eintrag.id] ?? auto;
    }
  }
  return { knoten: gezeichnet, kanten };
}
