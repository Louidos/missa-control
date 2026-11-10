import { useQuery } from "@tanstack/react-query";

import { api } from "../api";

export type ZugangTyp = "api_key" | "benutzer_passwort" | "bearer_token";

export interface Zugang {
  id: number;
  name: string;
  typ: ZugangTyp;
  typ_name: string;
  benutzer: string | null;
  /** Nur die Maske (z. B. ••••abcd) – den Wert selbst gibt das Backend nie heraus. */
  maske: string;
  lesbar: boolean;
  notiz: string;
  /** Namen der Integrationen, die diesen Zugang verwenden. */
  verwendet_von?: string[];
  erstellt: string;
  geaendert: string;
}

export const TYPEN: { wert: ZugangTyp; name: string; wertTitel: string }[] = [
  { wert: "api_key", name: "API-Key", wertTitel: "API-Key" },
  { wert: "bearer_token", name: "Bearer-Token", wertTitel: "Token" },
  { wert: "benutzer_passwort", name: "Benutzer + Passwort", wertTitel: "Passwort" },
];

export const ZUGAENGE = ["zugaenge"] as const;

export function useZugaenge() {
  return useQuery({ queryKey: ZUGAENGE, queryFn: () => api.get<Zugang[]>("/api/zugaenge") });
}
