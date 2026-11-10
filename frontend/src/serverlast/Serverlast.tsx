import { CircleAlert, Table2, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { datum } from "../ui/format";
import { IntegrationsHinweis } from "../ui/IntegrationsHinweis";
import { FehlerMeldung, Knopf, Lade } from "../ui/ui";
import { Liniendiagramm } from "./Liniendiagramm";
import { type Aktuell, type Kennung, mitEinheit, useServerlast, ZEITRAEUME, type Zeitraum } from "./serverlast";

const AB_HOCH = 75;
const AB_KRITISCH = 90;

interface KachelProps {
  titel: string;
  wert: number | null;
  einheit: string;
  zusatz?: string;
}

/** Ein aktueller Wert. Prozentwerte bekommen einen Balken; ab 75 % bzw. 90 % kommt ein Hinweis dazu. */
function Kachel({ titel, wert, einheit, zusatz }: KachelProps) {
  const prozent = einheit === "%" && wert !== null;
  const stufe = !prozent ? "normal" : wert >= AB_KRITISCH ? "kritisch" : wert >= AB_HOCH ? "hoch" : "normal";
  return (
    <div className={`karte kachel ${stufe}`}>
      <div className="kachel-titel">{titel}</div>
      <div className="kachel-wert">{mitEinheit(wert, einheit)}</div>
      {prozent && (
        <div className="meter" role="meter" aria-label={titel} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(wert)}>
          <div className="meter-fuellung" style={{ width: `${Math.min(Math.max(wert, 0), 100)}%` }} />
        </div>
      )}
      <div className="kachel-zusatz gedaempft klein">
        {stufe !== "normal" && (
          <span className="kachel-stufe">
            {stufe === "kritisch" ? <CircleAlert aria-hidden /> : <TriangleAlert aria-hidden />}
            {stufe === "kritisch" ? "kritisch" : "hoch"}
            {zusatz ? " · " : ""}
          </span>
        )}
        {zusatz}
      </div>
    </div>
  );
}

function gb(wert: number): string {
  return `${wert.toLocaleString("de-CH", { maximumFractionDigits: 1 })} GB`;
}

function kacheln(aktuell: Aktuell): KachelProps[] {
  const liste: KachelProps[] = [
    {
      titel: "CPU-Auslastung",
      wert: aktuell.cpu,
      einheit: "%",
      zusatz: `${aktuell.cpu_kerne} Kerne${aktuell.last !== null ? ` · Last ${aktuell.last.toFixed(2)}` : ""}`,
    },
    { titel: "Arbeitsspeicher", wert: aktuell.ram, einheit: "%", zusatz: `${gb(aktuell.ram_belegt_gb)} von ${gb(aktuell.ram_gesamt_gb)}` },
    { titel: "Speicherplatz", wert: aktuell.speicher, einheit: "%", zusatz: `${gb(aktuell.speicher_frei_gb)} frei von ${gb(aktuell.speicher_gesamt_gb)}` },
  ];
  if (aktuell.cpu_temp !== null) liste.push({ titel: "CPU-Temperatur", wert: aktuell.cpu_temp, einheit: "°C" });
  if (aktuell.gpu_vorhanden) {
    const namen = aktuell.gpus.map((gpu) => gpu.name).join(", ");
    liste.push({ titel: "GPU-Auslastung", wert: aktuell.gpu, einheit: "%", zusatz: namen });
    liste.push({ titel: "GPU-Speicher", wert: aktuell.gpu_speicher, einheit: "%" });
    if (aktuell.gpu_temp !== null) liste.push({ titel: "GPU-Temperatur", wert: aktuell.gpu_temp, einheit: "°C" });
  }
  return liste;
}

/** Seite „Serverlast“: aktuelle Werte und Verlauf von CPU, Arbeitsspeicher, Speicherplatz und GPU. */
export function Serverlast() {
  const [zeitraum, setZeitraum] = useState<Zeitraum>("1h");
  const [tabelle, setTabelle] = useState(false);
  const [zeiger, setZeiger] = useState<number | null>(null);
  const daten = useServerlast(zeitraum);

  if (daten.isPending) return <Lade />;
  if (daten.isError) return <FehlerMeldung fehler={daten.error} />;
  const { aktuell, verlauf, messwerte } = daten.data;
  const auswahl = ZEITRAEUME.find((eintrag) => eintrag.wert === daten.data.zeitraum) ?? ZEITRAEUME[0];
  // Rechter Rand der Diagramme: der Zeitpunkt, zu dem die Daten zuletzt geholt wurden.
  const bis = daten.dataUpdatedAt;
  const von = bis - auswahl.ms;

  // Nur Messwerte zeigen, die es auf diesem Server gibt (ohne GPU keine GPU-Diagramme).
  const vorhanden = messwerte.filter(
    (messwert) => messwert.kennung !== "last" && (aktuell[messwert.kennung] !== null || verlauf.some((punkt) => punkt[messwert.kennung] !== null)),
  );
  const reihe = (kennung: Kennung) => verlauf.map((punkt) => ({ t: new Date(punkt.zeit).getTime(), w: punkt[kennung] }));

  return (
    <div className="stapel">
      <IntegrationsHinweis manifestId="serverlast" wasFehlt="die Serverlast erst abfragen" />

      <div className="reihe zwischen">
        <div className="auswahl" role="radiogroup" aria-label="Zeitraum">
          {ZEITRAEUME.map((eintrag) => (
            <button key={eintrag.wert} type="button" role="radio" aria-checked={zeitraum === eintrag.wert} onClick={() => setZeitraum(eintrag.wert)}>
              {eintrag.titel}
            </button>
          ))}
        </div>
        <Knopf klein aria-pressed={tabelle} onClick={() => setTabelle(!tabelle)}>
          <Table2 aria-hidden />
          {tabelle ? "Als Diagramme anzeigen" : "Als Tabelle anzeigen"}
        </Knopf>
      </div>

      <div className="kacheln">
        {kacheln(aktuell).map((kachel) => (
          <Kachel key={kachel.titel} {...kachel} />
        ))}
      </div>

      <div className={daten.isPlaceholderData ? "viz wartet" : "viz"}>
        {tabelle ? (
          <div className="karte ohne-rand tabelle-huelle">
            <table className="tabelle zahlen">
              <thead>
                <tr>
                  <th>Zeit</th>
                  {vorhanden.map((messwert) => (
                    <th key={messwert.kennung}>{messwert.titel}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...verlauf].reverse().map((punkt) => (
                  <tr key={punkt.zeit}>
                    <td>{datum(punkt.zeit)}</td>
                    {vorhanden.map((messwert) => (
                      <td key={messwert.kennung}>{mitEinheit(punkt[messwert.kennung], messwert.einheit)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {verlauf.length === 0 && <p className="leer">Noch keine Messwerte in diesem Zeitraum.</p>}
          </div>
        ) : (
          <div className="diagramme">
            {vorhanden.map((messwert) => (
              <div className="karte" key={messwert.kennung}>
                <Liniendiagramm
                  titel={messwert.titel}
                  einheit={messwert.einheit}
                  punkte={reihe(messwert.kennung)}
                  von={von}
                  bis={bis}
                  max={messwert.einheit === "%" ? 100 : undefined}
                  rasterMs={auswahl.rasterMs}
                  zeiger={zeiger}
                  onZeiger={setZeiger}
                />
              </div>
            ))}
          </div>
        )}
      </div>
      <p className="gedaempft klein">
        Gemessen wird alle {daten.data.intervall_sekunden || 30} Sekunden, nur lesend. Die Werte bleiben 7 Tage gespeichert;
        für 24 Stunden und 7 Tage zeigen die Diagramme Mittelwerte.
      </p>
    </div>
  );
}
