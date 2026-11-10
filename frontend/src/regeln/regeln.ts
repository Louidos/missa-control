import { useQuery } from "@tanstack/react-query";

import { api } from "../api";

export interface Ausloeser {
  art: string;
  modus?: "uhrzeit" | "intervall";
  uhrzeit?: string;
  intervall_minuten?: number | string;
  messwert?: string;
  vergleich?: "ueber" | "unter";
  schwelle?: number | string;
  dauer_minuten?: number | string;
  geraet_id?: number | null;
  faehigkeit?: string;
  integration_id?: number | null;
}

export interface Bedingung {
  /** 0 = Montag … 6 = Sonntag; leer = jeden Tag */
  tage?: number[];
  von?: string;
  bis?: string;
}

export interface Aktion {
  art: string;
  nachricht?: string;
  dringlichkeit?: string;
  funktion?: string;
  argumente?: Record<string, unknown>;
  [feld: string]: unknown;
}

/** Die Angaben einer Regel, so wie sie der Editor bearbeitet und das Backend speichert. */
export interface Entwurf {
  name: string;
  ausloeser: Ausloeser;
  bedingung: Bedingung;
  aktion: Aktion;
  ruhezeit_minuten: number | string;
  aktiv: boolean;
}

export interface Regel extends Entwurf {
  id: number;
  quelle: "missa" | "manuell";
  /** Die Regel als lesbarer Satz. */
  satz: string;
  /** Gesetzt, wenn etwas fehlt, worauf sich die Regel bezieht (z. B. eine entfernte Funktion). */
  problem: string | null;
  erstellt: string;
  geaendert: string;
  zuletzt_ausgeloest: string | null;
  naechste_ausfuehrung: string | null;
}

export interface Parameter {
  properties?: Record<string, Record<string, unknown>>;
  required?: string[];
}

export interface FunktionsOption {
  name: string;
  integration: string;
  beschreibung: string;
  parameter: Parameter;
  recht: string;
}

export interface Optionen {
  ausloeser: { wert: string; titel: string }[];
  aktionen: { wert: string; titel: string }[];
  messwerte: { kennung: string; titel: string; einheit: string; verfuegbar: boolean }[];
  integrationen: { id: number; name: string }[];
  webhooks: { id: number; name: string }[];
  geraete: { id: number; name: string }[];
  funktionen: FunktionsOption[];
  dringlichkeiten: string[];
  zeitzone: string;
  standard_ruhezeit: number;
}

export interface Uebersicht {
  regeln: Regel[];
  optionen: Optionen;
}

export interface Ausloesung {
  id: number;
  regel_id: number;
  regel: string;
  zeit: string;
  anlass: string;
  ergebnis: "ok" | "fehler" | "ruhezeit" | "bedingung";
  ergebnis_name: string;
  meldung: string;
  test: boolean;
}

export interface Verlauf {
  anzahl: number;
  eintraege: Ausloesung[];
}

export const REGELN = ["regeln"] as const;
export const REGEL_VERLAUF = ["regeln-verlauf"] as const;

export function useRegeln() {
  // Regelmässig nachfragen: Regeln, die Missa anlegt, und „zuletzt ausgelöst“ erscheinen ohne Neuladen.
  return useQuery({ queryKey: REGELN, queryFn: () => api.get<Uebersicht>("/api/regeln"), refetchInterval: 15_000 });
}

export function neuerEntwurf(optionen: Optionen): Entwurf {
  return {
    name: "",
    ausloeser: { art: "messwert", messwert: "cpu", vergleich: "ueber", schwelle: 90, dauer_minuten: 5 },
    bedingung: {},
    aktion: { art: "ereignis", nachricht: "", dringlichkeit: "normal" },
    ruhezeit_minuten: optionen.standard_ruhezeit,
    aktiv: true,
  };
}

/** Startwerte, wenn im Editor eine andere Art von Auslöser gewählt wird. */
export function ausloeserStart(art: string): Ausloeser {
  if (art === "zeitplan") return { art, modus: "uhrzeit", uhrzeit: "07:30" };
  if (art === "messwert") return { art, messwert: "cpu", vergleich: "ueber", schwelle: 90, dauer_minuten: 5 };
  if (art === "geraet") return { art, geraet_id: null, faehigkeit: "" };
  return { art, integration_id: null };
}

export function aktionStart(art: string): Aktion {
  if (art === "funktion") return { art, funktion: "", argumente: {} };
  if (art === "ereignis") return { art, nachricht: "", dringlichkeit: "normal" };
  return { art };
}
