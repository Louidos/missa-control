import { type KeyboardEvent, type PointerEvent, useEffect, useMemo, useRef, useState } from "react";

import { mitEinheit } from "./serverlast";

export interface Punkt {
  /** Zeitpunkt in Millisekunden. */
  t: number;
  w: number | null;
}

interface Props {
  titel: string;
  einheit: string;
  punkte: Punkt[];
  /** Sichtbarer Zeitraum (Millisekunden). */
  von: number;
  bis: number;
  /** Obergrenze der Y-Achse; ohne Angabe richtet sie sich nach den Werten. */
  max?: number;
  /** Abstand zweier Messungen: grössere Lücken werden nicht überbrückt. */
  rasterMs: number;
  /** Gemeinsamer Zeiger aller Diagramme (Zeitpunkt unter der Maus) – oder null. */
  zeiger: number | null;
  onZeiger: (t: number | null) => void;
}

const HOEHE = 168;
const RAND = { links: 38, rechts: 14, oben: 10, unten: 24 };
const UHRZEIT = new Intl.DateTimeFormat("de-CH", { hour: "2-digit", minute: "2-digit" });
const TAG = new Intl.DateTimeFormat("de-CH", { weekday: "short", day: "numeric", month: "numeric" });
const GENAU = new Intl.DateTimeFormat("de-CH", { weekday: "short", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" });
const SCHRITTE_MIN = [5, 10, 15, 30, 60, 120, 180, 360, 720, 1440, 2880];

function schoeneObergrenze(wert: number): number {
  if (wert <= 0) return 1;
  const stufe = 10 ** Math.floor(Math.log10(wert));
  for (const faktor of [1, 2, 5, 10]) if (wert <= faktor * stufe) return faktor * stufe;
  return 10 * stufe;
}

function zeitMarken(von: number, bis: number): number[] {
  const schritt = (SCHRITTE_MIN.find((minuten) => (bis - von) / (minuten * 60_000) <= 6) ?? 2880) * 60_000;
  // An der Ortszeit ausrichten, damit die Marken auf vollen Stunden bzw. Mitternacht liegen.
  const versatz = new Date(von).getTimezoneOffset() * 60_000;
  const marken = [];
  for (let t = Math.ceil((von - versatz) / schritt) * schritt + versatz; t <= bis; t += schritt) marken.push(t);
  return marken;
}

/**
 * Liniendiagramm für einen Messwert über die Zeit.
 * Eine Reihe pro Diagramm (der Titel sagt, was gezeigt wird), dünne Linie mit zarter Fläche,
 * zurückhaltende Hilfslinien, Fadenkreuz mit Wert beim Überfahren oder mit den Pfeiltasten.
 */
export function Liniendiagramm({ titel, einheit, punkte, von, bis, max, rasterMs, zeiger, onZeiger }: Props) {
  const huelle = useRef<HTMLDivElement>(null);
  const [breite, setBreite] = useState(480);
  useEffect(() => {
    const element = huelle.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const beobachter = new ResizeObserver(([eintrag]) => setBreite(Math.max(Math.round(eintrag.contentRect.width), 240)));
    beobachter.observe(element);
    return () => beobachter.disconnect();
  }, []);

  const gueltig = useMemo(() => punkte.filter((punkt): punkt is { t: number; w: number } => punkt.w !== null), [punkte]);
  const obergrenze = max ?? schoeneObergrenze(Math.max(...gueltig.map((punkt) => punkt.w), 0));
  const innenBreite = breite - RAND.links - RAND.rechts;
  const innenHoehe = HOEHE - RAND.oben - RAND.unten;
  const x = (t: number) => RAND.links + ((t - von) / (bis - von || 1)) * innenBreite;
  const y = (w: number) => RAND.oben + (1 - Math.min(w, obergrenze) / obergrenze) * innenHoehe;
  const grundlinie = RAND.oben + innenHoehe;

  // Linie und Fläche in Abschnitten: über Lücken (Panel war aus) wird nicht hinweg gezeichnet.
  const abschnitte: { t: number; w: number }[][] = [];
  for (const punkt of gueltig) {
    const letzter = abschnitte.at(-1);
    if (letzter && punkt.t - letzter[letzter.length - 1].t <= rasterMs * 2.5) letzter.push(punkt);
    else abschnitte.push([punkt]);
  }
  const linie = (abschnitt: { t: number; w: number }[]) =>
    abschnitt.map((punkt, index) => `${index ? "L" : "M"}${x(punkt.t).toFixed(1)},${y(punkt.w).toFixed(1)}`).join("");

  const letzter = gueltig.at(-1);
  const gezeigt =
    zeiger === null || gueltig.length === 0
      ? null
      : gueltig.reduce((naechster, punkt) => (Math.abs(punkt.t - zeiger) < Math.abs(naechster.t - zeiger) ? punkt : naechster));
  // Der gemeinsame Zeiger gilt nur, wenn dieses Diagramm in der Nähe auch einen Messwert hat.
  const aktiv = gezeigt && zeiger !== null && Math.abs(gezeigt.t - zeiger) <= Math.max(rasterMs * 2.5, (bis - von) / 40) ? gezeigt : null;

  const beiZeiger = (ereignis: PointerEvent<SVGSVGElement>) => {
    const flaeche = ereignis.currentTarget.getBoundingClientRect();
    const anteil = (ereignis.clientX - flaeche.left - RAND.links) / (innenBreite || 1);
    onZeiger(von + Math.min(Math.max(anteil, 0), 1) * (bis - von));
  };
  const beiTaste = (ereignis: KeyboardEvent<SVGSVGElement>) => {
    if (gueltig.length === 0) return;
    if (ereignis.key === "Escape") return onZeiger(null);
    if (ereignis.key !== "ArrowLeft" && ereignis.key !== "ArrowRight") return;
    ereignis.preventDefault();
    const stelle = aktiv ? gueltig.indexOf(aktiv) : gueltig.length - 1;
    const neu = Math.min(Math.max(stelle + (ereignis.key === "ArrowLeft" ? -1 : 1), 0), gueltig.length - 1);
    onZeiger(gueltig[neu].t);
  };

  const mehrTage = bis - von > 86_400_000 * 1.5;
  const yMarken = [0, obergrenze / 2, obergrenze];
  const beschreibung = letzter
    ? `${titel}: Verlauf, zuletzt ${mitEinheit(letzter.w, einheit)}. Mit den Pfeiltasten lassen sich einzelne Werte ablesen.`
    : `${titel}: noch keine Messwerte.`;

  return (
    <figure className="diagramm">
      <figcaption>
        <span className="diagramm-titel">{titel}</span>
        {einheit && <span className="gedaempft klein"> in {einheit}</span>}
      </figcaption>
      <div className="diagramm-flaeche" ref={huelle}>
        <svg
          width={breite}
          height={HOEHE}
          role="img"
          aria-label={beschreibung}
          tabIndex={0}
          onPointerMove={beiZeiger}
          onPointerLeave={() => onZeiger(null)}
          onFocus={() => letzter && zeiger === null && onZeiger(letzter.t)}
          onBlur={() => onZeiger(null)}
          onKeyDown={beiTaste}
        >
          {yMarken.map((marke) => (
            <g key={marke}>
              <line className={marke === 0 ? "viz-achse" : "viz-gitter"} x1={RAND.links} x2={breite - RAND.rechts} y1={y(marke)} y2={y(marke)} />
              <text className="viz-marke" x={RAND.links - 6} y={y(marke)} textAnchor="end" dominantBaseline="middle">
                {Number.isInteger(marke) ? marke : marke.toFixed(1)}
              </text>
            </g>
          ))}
          {zeitMarken(von, bis).map((marke) => (
            <text key={marke} className="viz-marke" x={x(marke)} y={HOEHE - 6} textAnchor="middle">
              {mehrTage ? TAG.format(marke) : UHRZEIT.format(marke)}
            </text>
          ))}
          {abschnitte.map((abschnitt, index) => (
            <g key={index}>
              {abschnitt.length > 1 && (
                <path className="viz-flaeche" d={`${linie(abschnitt)}L${x(abschnitt[abschnitt.length - 1].t).toFixed(1)},${grundlinie}L${x(abschnitt[0].t).toFixed(1)},${grundlinie}Z`} />
              )}
              <path className="viz-linie" d={linie(abschnitt)} />
            </g>
          ))}
          {letzter && !aktiv && <circle className="viz-punkt" cx={x(letzter.t)} cy={y(letzter.w)} r={4} />}
          {aktiv && (
            <>
              <line className="viz-faden" x1={x(aktiv.t)} x2={x(aktiv.t)} y1={RAND.oben} y2={grundlinie} />
              <circle className="viz-punkt" cx={x(aktiv.t)} cy={y(aktiv.w)} r={4} />
            </>
          )}
        </svg>
        {aktiv && (
          <div
            className="viz-tipp"
            role="status"
            style={x(aktiv.t) > breite * 0.6 ? { right: breite - x(aktiv.t) + 10 } : { left: x(aktiv.t) + 10 }}
          >
            <span className="viz-schluessel" aria-hidden />
            <strong>{mitEinheit(aktiv.w, einheit)}</strong>
            <span className="gedaempft">{GENAU.format(aktiv.t)}</span>
          </div>
        )}
        {gueltig.length === 0 && <div className="diagramm-leer gedaempft klein">Noch keine Messwerte in diesem Zeitraum.</div>}
      </div>
    </figure>
  );
}
