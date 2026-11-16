import { ArrowDown, ArrowUp, BarChart3 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { Liniendiagramm } from "../serverlast/Liniendiagramm";
import { datum } from "../ui/format";
import { FehlerMeldung, Lade } from "../ui/ui";
import { dauer, type FunktionsZeile, prozent, useStatistik, type Zeitraum, ZEITRAEUME } from "./statistik";

type Spalte = "integration" | "funktion" | "aufrufe" | "fehlerquote" | "dauer_mittel_ms" | "dauer_max_ms" | "letzter_aufruf";

const SPALTEN: { wert: Spalte; titel: string; zahl?: boolean }[] = [
  { wert: "integration", titel: "Integration" },
  { wert: "funktion", titel: "Funktion" },
  { wert: "aufrufe", titel: "Aufrufe", zahl: true },
  { wert: "fehlerquote", titel: "Fehlerquote", zahl: true },
  { wert: "dauer_mittel_ms", titel: "Ø Dauer", zahl: true },
  { wert: "dauer_max_ms", titel: "Längste", zahl: true },
  { wert: "letzter_aufruf", titel: "Letzter Aufruf" },
];
const TAG_MS = 24 * 60 * 60 * 1000;

function vergleichen(a: FunktionsZeile, b: FunktionsZeile, spalte: Spalte): number {
  const x = a[spalte] ?? "";
  const y = b[spalte] ?? "";
  return typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "de");
}

/**
 * Seite „Statistik“: welche Funktionen Missa wie oft benutzt, wie oft sie scheitern und wie schnell sie
 * sind – berechnet aus dem Protokoll. Die Statistik der Sprachmodelle steht auf der Seite „Modelle“.
 */
export function Statistik() {
  const [zeitraum, setZeitraum] = useState<Zeitraum>("7d");
  const [sortierung, setSortierung] = useState<{ spalte: Spalte; ab: boolean }>({ spalte: "aufrufe", ab: true });
  const [zeiger, setZeiger] = useState<number | null>(null);
  const statistik = useStatistik(zeitraum);

  const sortieren = (spalte: Spalte) =>
    setSortierung((alt) => ({ spalte, ab: alt.spalte === spalte ? !alt.ab : spalte !== "integration" && spalte !== "funktion" }));

  const daten = statistik.data;
  const zeilen = daten
    ? [...daten.funktionen].sort((a, b) => vergleichen(a, b, sortierung.spalte) * (sortierung.ab ? -1 : 1))
    : [];
  const punkte = (daten?.pro_tag ?? []).map((tag) => ({ t: new Date(`${tag.tag}T12:00:00`).getTime(), w: tag.aufrufe }));
  const von = punkte.length ? punkte[0].t - TAG_MS / 2 : 0;
  const bis = punkte.length ? punkte[punkte.length - 1].t + TAG_MS / 2 : 1;

  return (
    <div className="stapel">
      <p className="gedaempft">
        Welche Funktionen Missa wie oft benutzt, wie oft sie scheitern und wie schnell sie sind – aus dem Protokoll (wird 30 Tage
        aufbewahrt). Die Statistik der Sprachmodelle steht unter <Link to="/modelle">Modelle</Link>.
      </p>
      <div className="auswahl" role="radiogroup" aria-label="Zeitraum">
        {ZEITRAEUME.map((eintrag) => (
          <button key={eintrag.wert} type="button" role="radio" aria-checked={zeitraum === eintrag.wert} onClick={() => setZeitraum(eintrag.wert)}>
            {eintrag.titel}
          </button>
        ))}
      </div>

      <FehlerMeldung fehler={statistik.error} />
      {statistik.isPending && <Lade />}

      {daten && (
        <>
          <div className="kacheln">
            <div className="karte kachel">
              <div className="kachel-titel">Aufrufe</div>
              <div className="kachel-wert">{daten.gesamt.aufrufe}</div>
            </div>
            <div className="karte kachel">
              <div className="kachel-titel">Fehlerquote</div>
              <div className="kachel-wert">{prozent(daten.gesamt.fehlerquote)}</div>
            </div>
            <div className="karte kachel">
              <div className="kachel-titel">Benutzte Funktionen</div>
              <div className="kachel-wert">{daten.gesamt.funktionen}</div>
            </div>
          </div>

          <div className="karte">
            <Liniendiagramm
              titel="Aufrufe pro Tag"
              einheit=""
              punkte={punkte}
              von={von}
              bis={bis}
              rasterMs={TAG_MS}
              wertText={(wert) => `${Math.round(wert)} Aufrufe`}
              zeiger={zeiger}
              onZeiger={setZeiger}
            />
          </div>

          {zeilen.length === 0 ? (
            <div className="karte leer">
              <BarChart3 aria-hidden />
              <h2>Keine Aufrufe in diesem Zeitraum</h2>
              <p>Sobald Missa Funktionen benutzt, steht hier, welche wie oft.</p>
            </div>
          ) : (
            <div className="karte ohne-rand tabelle-huelle">
              <table className="tabelle zahlen" aria-label="Aufrufe pro Funktion">
                <thead>
                  <tr>
                    {SPALTEN.map((spalte) => (
                      <th
                        key={spalte.wert}
                        aria-sort={sortierung.spalte === spalte.wert ? (sortierung.ab ? "descending" : "ascending") : "none"}
                      >
                        <button type="button" className="sortierknopf" onClick={() => sortieren(spalte.wert)}>
                          {spalte.titel}
                          {sortierung.spalte === spalte.wert &&
                            (sortierung.ab ? <ArrowDown aria-hidden /> : <ArrowUp aria-hidden />)}
                        </button>
                      </th>
                    ))}
                    <th>Freigaben</th>
                  </tr>
                </thead>
                <tbody>
                  {zeilen.map((zeile) => (
                    <tr key={`${zeile.integration}/${zeile.funktion}`}>
                      <td>{zeile.integration || "–"}</td>
                      <td className="mono">{zeile.funktion}</td>
                      <td title={`davon von Missa: ${zeile.von_missa}`}>{zeile.aufrufe}</td>
                      <td className={zeile.fehler > 0 ? "fehlertext" : undefined}>{prozent(zeile.fehlerquote)}</td>
                      <td>{dauer(zeile.dauer_mittel_ms)}</td>
                      <td>{dauer(zeile.dauer_max_ms)}</td>
                      <td className="gedaempft klein">{zeile.letzter_aufruf ? datum(zeile.letzter_aufruf) : "–"}</td>
                      <td className="gedaempft klein">
                        {zeile.freigaben.erlaubt + zeile.freigaben.abgelehnt + zeile.freigaben.abgelaufen === 0
                          ? "–"
                          : `${zeile.freigaben.erlaubt} erlaubt · ${zeile.freigaben.abgelehnt} abgelehnt · ${zeile.freigaben.abgelaufen} abgelaufen`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <section className="stapel eng" aria-label="Nie benutzt">
            <h2>Nie benutzt</h2>
            {daten.nie_benutzt.length === 0 ? (
              <p className="gedaempft">Missa hat im Zeitraum jede sichtbare Funktion mindestens einmal benutzt.</p>
            ) : (
              <>
                <p className="gedaempft klein">
                  Aktive Funktionen ohne einen einzigen Aufruf im Zeitraum. Braucht Missa sie nicht, lassen sie sich sperren – das
                  hält die Liste der Funktionen kurz.
                </p>
                <ul className="funktionen">
                  {daten.nie_benutzt.map((eintrag) => (
                    <li key={eintrag.funktion}>
                      <div className="funktion-text">
                        <code>{eintrag.funktion}</code>
                        <div className="gedaempft klein">
                          {eintrag.integration} · {eintrag.schreibend ? "schreibend" : "lesend"}
                        </div>
                      </div>
                      <Link className="knopf klein" to={`/integrationen#integration-${eintrag.integration_id}`}>
                        Zur Integration
                      </Link>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        </>
      )}
    </div>
  );
}
