import { useQuery } from "@tanstack/react-query";

import { api } from "../api";

export interface Freigabe {
  id: number;
  erstellt: string;
  laeuft_ab: string;
  client: string;
  integration: string;
  funktion: string;
  beschreibung: string;
  /** Ein Satz der Integration, was genau passieren würde (leer, wenn sie keinen liefert). */
  vorschau: string;
  argumente: Record<string, unknown>;
  status: "offen" | "erlaubt" | "abgelehnt" | "abgelaufen";
  entschieden: string | null;
}

export interface FreigabenAntwort {
  offen: Freigabe[];
  verlauf: Freigabe[];
  frist_sekunden: number;
}

export const FREIGABEN = ["freigaben"] as const;
export const FREIGABEN_ANZAHL = ["freigaben-anzahl"] as const;

/** Anzahl offener Freigaben – für den Zähler in der Navigation. */
export function useOffeneFreigaben() {
  return useQuery({
    queryKey: FREIGABEN_ANZAHL,
    queryFn: () => api.get<{ offen: number }>("/api/freigaben/anzahl"),
    refetchInterval: 5000,
  });
}
