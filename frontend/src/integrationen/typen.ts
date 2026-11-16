import { useQuery } from "@tanstack/react-query";

import { api } from "../api";
import type { Kopplung } from "../geraete/geraete";
import type { ZugangTyp } from "../zugaenge/zugaenge";

export type Recht = "erlaubt" | "nachfragen" | "gesperrt";

export const RECHTE: { wert: Recht; name: string }[] = [
  { wert: "erlaubt", name: "erlaubt" },
  { wert: "nachfragen", name: "erst nachfragen" },
  { wert: "gesperrt", name: "gesperrt" },
];

export interface Option {
  wert: string;
  titel: string;
}

export interface Feld {
  name: string;
  titel: string;
  typ: "text" | "zahl" | "url" | "auswahl" | "zugang" | "schalter" | "datei" | "endpunkte";
  pflicht: boolean;
  hilfe: string;
  platzhalter: string;
  standard: string | number | boolean | null;
  optionen: Option[];
  zugang_typen: ZugangTyp[];
  endungen: string[];
  nach_test: boolean;
  /** Feld erscheint nur, wenn ein anderes Feld einen dieser Werte hat. */
  sichtbar_wenn?: Record<string, string[]>;
}

/** Ein eigener Endpunkt einer API (Feldtyp „endpunkte“): wird zu einer eigenen Funktion. */
export interface Endpunkt {
  name: string;
  methode: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  pfad: string;
  beschreibung: string;
}

export interface Manifest {
  id: string;
  name: string;
  beschreibung: string;
  symbol: string;
  art: string;
  art_name: string;
  version: string;
  mehrfach: boolean;
  hinweis: string;
  /** Karte steht im Katalog ganz vorne und ist hervorgehoben. */
  hervorgehoben?: boolean;
  felder: Feld[];
}

export interface KatalogEintrag extends Manifest {
  eingebaut: boolean;
  eingerichtet: number;
  verfuegbar: boolean;
  kann_hinzufuegen: boolean;
}

export interface Katalog {
  eintraege: KatalogEintrag[];
  probleme: { ordner: string; meldungen: string[] }[];
}

export interface TestFunktion {
  name: string;
  beschreibung: string;
  schreibend: boolean;
  recht: Recht;
}

export type TestErgebnis =
  | { ok: false; meldung: string; hinweis?: string | null }
  | {
      ok: true;
      test_id: string;
      meldung: string;
      details: string[];
      optionen: Record<string, Option[]>;
      viele_funktionen: boolean;
      funktionen: TestFunktion[];
    };

export interface Funktion extends TestFunktion {
  id: number;
  gateway_name: string;
  vorhanden: boolean;
  parameter: { properties?: Record<string, unknown>; required?: string[] };
}

export type Wert = string | number | boolean | null | { datei: true; zeichen: number } | Endpunkt[];
export type Konfig = Record<string, Wert>;

export interface Integration {
  id: number;
  manifest_id: string;
  manifest: Manifest | null;
  name: string;
  kennung: string;
  symbol: string;
  art: string | null;
  art_name: string;
  konfig: Konfig;
  aktiv: boolean;
  status: "ok" | "fehler" | "ungetestet";
  status_meldung: string;
  status_hinweis: string;
  geprueft: string | null;
  funktionen: Funktion[];
  /** Nur bei Webhooks: der Pfad der geheimen Adresse, an die andere Dienste senden. */
  webhook?: { pfad: string | null };
  /** Nur bei Geräten und nur direkt nach dem Anlegen: die Zugangsdaten (das Passwort gibt es nur dieses eine Mal). */
  kopplung?: Kopplung;
}

export const KATALOG = ["katalog"] as const;
export const INTEGRATIONEN = ["integrationen"] as const;

export function useKatalog() {
  return useQuery({ queryKey: KATALOG, queryFn: () => api.get<Katalog>("/api/katalog") });
}

export function useIntegrationen() {
  return useQuery({ queryKey: INTEGRATIONEN, queryFn: () => api.get<Integration[]>("/api/integrationen") });
}

/** Ist das Feld bei diesen Werten sichtbar? (`sichtbar_wenn` im Manifest) */
export function feldSichtbar(feld: Feld, werte: Konfig): boolean {
  return Object.entries(feld.sichtbar_wenn ?? {}).every(([name, erlaubt]) => erlaubt.includes(String(werte[name] ?? "")));
}

/** Startwerte eines Formulars: die Standardwerte aus dem Manifest. */
export function standardwerte(felder: Feld[]): Konfig {
  const werte: Konfig = {};
  for (const feld of felder) {
    if (feld.standard !== null && feld.standard !== undefined) werte[feld.name] = feld.standard;
    else if (feld.typ === "schalter") werte[feld.name] = false;
  }
  return werte;
}
