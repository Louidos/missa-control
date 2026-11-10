/** Anzeige von Zeitpunkten und Zahlen, überall im Panel gleich. */

const DATUM = new Intl.DateTimeFormat("de-CH", { dateStyle: "medium", timeStyle: "short" });

export function datum(iso: string | null | undefined): string {
  if (!iso) return "–";
  const zeitpunkt = new Date(iso);
  return Number.isNaN(zeitpunkt.getTime()) ? "–" : DATUM.format(zeitpunkt);
}
