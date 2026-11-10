import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "../api";

export type Zeitraum = "1h" | "24h" | "7t";
export type Kennung = "cpu" | "ram" | "speicher" | "last" | "cpu_temp" | "gpu" | "gpu_speicher" | "gpu_temp";

export type Messpunkt = { zeit: string } & Record<Kennung, number | null>;

export interface Gpu {
  name: string;
  auslastung: number | null;
  speicher_belegt_mb: number | null;
  speicher_gesamt_mb: number | null;
  temperatur: number | null;
}

export interface Aktuell extends Record<Kennung, number | null> {
  cpu_kerne: number;
  ram_gesamt_gb: number;
  ram_belegt_gb: number;
  speicher_gesamt_gb: number;
  speicher_frei_gb: number;
  gpus: Gpu[];
  gpu_vorhanden: boolean;
}

export interface Uebersicht {
  aktuell: Aktuell;
  verlauf: Messpunkt[];
  zeitraum: Zeitraum;
  intervall_sekunden: number;
  messwerte: { kennung: Kennung; titel: string; einheit: string }[];
}

export const ZEITRAEUME: { wert: Zeitraum; titel: string; ms: number; rasterMs: number }[] = [
  { wert: "1h", titel: "1 Stunde", ms: 3_600_000, rasterMs: 30_000 },
  { wert: "24h", titel: "24 Stunden", ms: 86_400_000, rasterMs: 300_000 },
  { wert: "7t", titel: "7 Tage", ms: 604_800_000, rasterMs: 1_800_000 },
];

export function useServerlast(zeitraum: Zeitraum) {
  return useQuery({
    queryKey: ["serverlast", zeitraum],
    queryFn: () => api.get<Uebersicht>(`/api/serverlast?zeitraum=${zeitraum}`),
    // Beim Wechsel des Zeitraums bleibt die alte Ansicht stehen, bis die neue da ist – kein Flackern.
    placeholderData: keepPreviousData,
    refetchInterval: 15_000,
  });
}

/** Zahl mit Einheit, z. B. „42 %“ oder „61 °C“. */
export function mitEinheit(wert: number | null | undefined, einheit: string): string {
  if (wert === null || wert === undefined) return "–";
  const zahl = einheit === "" ? wert.toFixed(2) : String(Math.round(wert));
  return einheit ? `${zahl} ${einheit}` : zahl;
}
