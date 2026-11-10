/** Helfer für Tests: ein Backend-Ersatz für `fetch` und ein Rahmen mit allen nötigen Providern. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";

type Antwort = unknown | ((koerper: unknown) => unknown);

export interface Aufruf {
  methode: string;
  pfad: string;
  koerper: unknown;
}

export class TestFehler {
  constructor(
    readonly status: number,
    readonly meldung: string,
    readonly hinweis?: string,
  ) {}
}

/**
 * Ersetzt `fetch`. Schlüssel sind "METHODE /pfad"; der Wert ist die JSON-Antwort,
 * eine Funktion (bekommt den gesendeten Körper) oder ein `TestFehler`.
 */
export function backend(routen: Record<string, Antwort>) {
  const aufrufe: Aufruf[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (eingabe, init) => {
    const methode = (init?.method ?? "GET").toUpperCase();
    const pfad = String(eingabe);
    const koerper = typeof init?.body === "string" ? JSON.parse(init.body) : init?.body;
    aufrufe.push({ methode, pfad, koerper });
    const schluessel = `${methode} ${pfad}`;
    if (!(schluessel in routen)) {
      return json({ meldung: `Im Test nicht vorgesehen: ${schluessel}` }, 500);
    }
    let antwort = routen[schluessel];
    if (typeof antwort === "function") antwort = (antwort as (k: unknown) => unknown)(koerper);
    if (antwort instanceof TestFehler) {
      return json({ meldung: antwort.meldung, hinweis: antwort.hinweis }, antwort.status);
    }
    return json(antwort, 200);
  });
  return aufrufe;
}

function json(inhalt: unknown, status: number) {
  return new Response(JSON.stringify(inhalt), { status, headers: { "Content-Type": "application/json" } });
}

export function testQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

/** Rendert ein Element mit Datenabruf und Router, wie es im Panel läuft. */
export function zeige(element: ReactElement, pfad = "/") {
  return render(
    <QueryClientProvider client={testQueryClient()}>
      <MemoryRouter initialEntries={[pfad]}>{element}</MemoryRouter>
    </QueryClientProvider>,
  );
}
