import { useQuery } from "@tanstack/react-query";

import { api } from "../api";

export type Zeitraum = "24h" | "7d" | "30d";

export const ZEITRAEUME: { wert: Zeitraum; titel: string }[] = [
  { wert: "24h", titel: "24 Stunden" },
  { wert: "7d", titel: "7 Tage" },
  { wert: "30d", titel: "30 Tage" },
];

export interface FunktionsZeile {
  integration: string;
  funktion: string;
  aufrufe: number;
  von_missa: number;
  fehler: number;
  fehlerquote: number;
  dauer_mittel_ms: number;
  dauer_max_ms: number;
  letzter_aufruf: string | null;
  freigaben: { erlaubt: number; abgelehnt: number; abgelaufen: number };
}

export interface NieBenutzt {
  integration: string;
  integration_id: number;
  funktion: string;
  schreibend: boolean;
  recht: string;
}

export interface StatistikDaten {
  zeitraum: Zeitraum;
  seit: string;
  bis: string;
  gesamt: { aufrufe: number; fehler: number; fehlerquote: number; funktionen: number };
  pro_tag: { tag: string; aufrufe: number; fehler: number }[];
  funktionen: FunktionsZeile[];
  nie_benutzt: NieBenutzt[];
}

export function useStatistik(zeitraum: Zeitraum) {
  return useQuery({
    queryKey: ["statistik", zeitraum],
    queryFn: () => api.get<StatistikDaten>(`/api/statistik?zeitraum=${zeitraum}`),
    refetchInterval: 60_000,
  });
}

export function prozent(anteil: number): string {
  return `${(anteil * 100).toLocaleString("de-CH", { maximumFractionDigits: 1 })} %`;
}

export function dauer(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toLocaleString("de-CH", { maximumFractionDigits: 1 })} s` : `${ms} ms`;
}
