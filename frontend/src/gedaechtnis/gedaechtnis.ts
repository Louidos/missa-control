import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api";

export interface Eintrag {
  id: number;
  text: string;
  kategorie: string;
  kategorie_name: string;
  quelle: "missa" | "manuell";
  quelle_name: string;
  erstellt: string;
  geaendert: string;
}

export interface Uebersicht {
  eintraege: Eintrag[];
  /** Wie viele Einträge zur Suche passen (auch wenn nicht alle angezeigt werden). */
  treffer: number;
  /** Wie viele Einträge es insgesamt gibt. */
  gesamt: number;
  kategorien: { wert: string; titel: string; anzahl: number }[];
  quellen: { wert: string; titel: string }[];
  max_zeichen: number;
}

export interface Filter {
  suche: string;
  kategorie: string;
  quelle: string;
}

export const GEDAECHTNIS = ["gedaechtnis"] as const;
export const SEITE = 100;

export function useGedaechtnis(filter: Filter, limit: number) {
  const parameter = new URLSearchParams({ limit: String(limit) });
  for (const [name, wert] of Object.entries(filter)) if (wert) parameter.set(name, wert);
  return useQuery({
    queryKey: [...GEDAECHTNIS, filter, limit],
    queryFn: () => api.get<Uebersicht>(`/api/gedaechtnis?${parameter}`),
    placeholderData: keepPreviousData,
    // Was Missa sich gerade merkt, erscheint ohne Neuladen.
    refetchInterval: 15_000,
  });
}

/** Gibt den Wert erst weiter, wenn er sich kurz nicht geändert hat (damit nicht jeder Tastendruck sucht). */
export function useVerzoegert<T>(wert: T, millisekunden = 250): T {
  const [verzoegert, setVerzoegert] = useState(wert);
  useEffect(() => {
    const warten = window.setTimeout(() => setVerzoegert(wert), millisekunden);
    return () => window.clearTimeout(warten);
  }, [wert, millisekunden]);
  return verzoegert;
}
