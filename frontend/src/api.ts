/** Zugriff auf das Backend. Fehler kommen immer als `ApiFehler` mit verständlicher Meldung. */

export class ApiFehler extends Error {
  readonly status: number;
  readonly hinweis?: string;

  constructor(status: number, meldung: string, hinweis?: string) {
    super(meldung);
    this.name = "ApiFehler";
    this.status = status;
    this.hinweis = hinweis;
  }
}

/** Wird ausgelöst, wenn das Backend eine Anfrage wegen fehlender Anmeldung ablehnt. */
export const ABGEMELDET_EREIGNIS = "missa-control:abgemeldet";

type Methode = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

async function anfrage<T>(methode: Methode, pfad: string, daten?: unknown): Promise<T> {
  const istFormular = daten instanceof FormData;
  let antwort: Response;
  try {
    antwort = await fetch(pfad, {
      method: methode,
      credentials: "same-origin",
      headers: daten !== undefined && !istFormular ? { "Content-Type": "application/json" } : undefined,
      body: daten === undefined ? undefined : istFormular ? daten : JSON.stringify(daten),
    });
  } catch {
    throw new ApiFehler(
      0,
      "Das Panel ist nicht erreichbar.",
      "Läuft der Container noch? Bitte Verbindung prüfen und erneut versuchen.",
    );
  }

  const istJson = (antwort.headers.get("content-type") ?? "").includes("application/json");
  const inhalt: unknown = istJson ? await antwort.json().catch(() => null) : null;

  if (!antwort.ok) {
    if (antwort.status === 401 && !pfad.startsWith("/api/auth/")) {
      window.dispatchEvent(new Event(ABGEMELDET_EREIGNIS));
    }
    const fehler = (inhalt ?? {}) as { meldung?: string; hinweis?: string };
    throw new ApiFehler(
      antwort.status,
      fehler.meldung ?? `Unerwarteter Fehler (${antwort.status}).`,
      fehler.hinweis,
    );
  }
  return inhalt as T;
}

export const api = {
  get: <T>(pfad: string) => anfrage<T>("GET", pfad),
  post: <T>(pfad: string, daten?: unknown) => anfrage<T>("POST", pfad, daten ?? {}),
  put: <T>(pfad: string, daten?: unknown) => anfrage<T>("PUT", pfad, daten ?? {}),
  patch: <T>(pfad: string, daten?: unknown) => anfrage<T>("PATCH", pfad, daten ?? {}),
  del: <T>(pfad: string) => anfrage<T>("DELETE", pfad),
};
