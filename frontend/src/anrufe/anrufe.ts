import { useQuery } from "@tanstack/react-query";

import { api } from "../api";

export interface Eintrag {
  nummer: string;
  name: string;
}

export interface Ruhezeit {
  von: string;
  bis: string;
}

export interface Einstellungen {
  /** „test“ oder „integration:<id>“. */
  adapter: string;
  landesvorwahl: string;
  eigene_nummern: Eintrag[];
  erlaubte_anrufer: Eintrag[];
  ruhezeiten: Ruhezeit[];
  nur_bekannte: boolean;
}

export interface AdapterInfo {
  kennung: string;
  name: string;
  beschreibung: string;
  test: boolean;
}

export interface Uebersicht {
  einstellungen: Einstellungen;
  adapter: AdapterInfo[];
  /** Der gewählte Adapter gehört zu einer Integration, die es nicht mehr gibt oder die ausgeschaltet ist. */
  adapter_fehlt: boolean;
  ruhezeit_jetzt: Ruhezeit | null;
  zeitzone: string;
}

export type Richtung = "ausgehend" | "eingehend";

export interface Anruf {
  id: number;
  zeit: string;
  richtung: Richtung;
  nummer: string;
  name: string;
  status: "wartet" | "laeuft" | "beendet" | "nicht_erreicht" | "abgewiesen" | "unterdrueckt" | "fehler" | "test";
  status_text: string;
  dauer_sekunden: number | null;
  /** Ausgehend: was gesagt werden soll. Abgewiesen: warum. */
  grund: string;
  dringlichkeit: string;
  quelle: "missa" | "regel" | "panel" | "anrufer" | "";
  quelle_name: string;
  adapter: string;
  meldung: string;
}

export const TELEFONIE = ["telefonie"] as const;
export const ANRUFE = ["telefonie", "anrufe"] as const;

export function useTelefonie() {
  return useQuery({ queryKey: TELEFONIE, queryFn: () => api.get<Uebersicht>("/api/telefonie") });
}

export function useAnrufe(richtung: Richtung | "") {
  return useQuery({
    queryKey: [...ANRUFE, richtung],
    queryFn: () => api.get<{ anrufe: Anruf[] }>(`/api/telefonie/anrufe${richtung ? `?richtung=${richtung}` : ""}`),
    refetchInterval: 10_000,
  });
}

/** 75 → „1:15 min“, 12 → „12 s“, ohne Angabe „–“. */
export function dauerText(sekunden: number | null): string {
  if (sekunden === null) return "–";
  if (sekunden < 60) return `${sekunden} s`;
  return `${Math.floor(sekunden / 60)}:${String(sekunden % 60).padStart(2, "0")} min`;
}

export function werText(anruf: Pick<Anruf, "nummer" | "name">): string {
  return anruf.name ? `${anruf.name} (${anruf.nummer})` : anruf.nummer;
}
