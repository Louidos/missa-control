import { useQuery } from "@tanstack/react-query";

import { api } from "../api";

export interface Modell {
  id: number;
  name: string;
  url: string;
  zugang_id: number | null;
  modellname: string;
  kontextlaenge: number | null;
  test: {
    ok: boolean | null;
    meldung: string;
    hinweis: string;
    ms: number | null;
    tokens_pro_s: number | null;
    zeit: string | null;
  };
  statistik: {
    anfragen: number;
    fehler: number;
    antwortzeit_ms: number | null;
    tokens_pro_s: number | null;
  };
}

export interface Rolle {
  id: number;
  kennung: string;
  /** Der feste Name, den Clients verwenden, z. B. missa-schnell. */
  modellname: string;
  name: string;
  beschreibung: string;
  haupt_modell_id: number | null;
  ersatz_modell_id: number | null;
  fest: boolean;
}

export interface ModellUebersicht {
  modelle: Modell[];
  rollen: Rolle[];
}

export const MODELLE = ["modelle"] as const;

export function useModelle(aktualisieren = true) {
  return useQuery({
    queryKey: MODELLE,
    queryFn: () => api.get<ModellUebersicht>("/api/modelle"),
    refetchInterval: aktualisieren ? 30_000 : false,
  });
}

export function zeitspanne(ms: number | null): string {
  if (ms === null) return "–";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;
}
