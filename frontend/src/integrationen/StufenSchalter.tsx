import { useState } from "react";

import { Bestaetigung } from "../ui/Dialog";
import { ZUGRIFFE, type Zugriff } from "./typen";

interface Props {
  wert: Zugriff;
  /** Einzelne Rechte weichen von der Stufe ab → „angepasst“. */
  angepasst: boolean;
  /** Die schreibenden Funktionen – „Voller Zugriff“ nennt sie in der Rückfrage. */
  schreibende: string[];
  onWaehlen: (stufe: Zugriff) => void;
  laeuft?: boolean;
}

/** Dreier-Schalter über der Rechte-Liste: wie viel Missa bei dieser Integration darf. */
export function StufenSchalter({ wert, angepasst, schreibende, onWaehlen, laeuft }: Props) {
  const [nachfrage, setNachfrage] = useState(false);
  const beschreibung = ZUGRIFFE.find((stufe) => stufe.wert === wert)?.text;

  return (
    <div className="stapel eng">
      <div className="reihe" style={{ gap: "0.5rem" }}>
        <div className="auswahl" role="radiogroup" aria-label="Zugriffsstufe">
          {ZUGRIFFE.map((stufe) => (
            <button
              key={stufe.wert}
              type="button"
              role="radio"
              aria-checked={wert === stufe.wert}
              disabled={laeuft}
              title={stufe.text}
              onClick={() => {
                if (stufe.wert === wert && !angepasst) return;
                if (stufe.wert === "voll" && schreibende.length > 0) setNachfrage(true);
                else onWaehlen(stufe.wert);
              }}
            >
              {stufe.name}
            </button>
          ))}
        </div>
        {angepasst && (
          <span className="etikett" title="Einzelne Rechte weichen von der Stufe ab">
            angepasst
          </span>
        )}
      </div>
      {beschreibung && <p className="gedaempft klein">{beschreibung}</p>}
      {nachfrage && (
        <Bestaetigung
          titel="Voller Zugriff?"
          text={
            <div className="stapel eng">
              <p>
                <strong>Missa darf dann ohne Nachfrage auch ändern und löschen.</strong> Das betrifft diese schreibenden
                Funktionen:
              </p>
              <ul aria-label="Betroffene Funktionen">
                {schreibende.map((name) => (
                  <li key={name}>
                    <code>{name}</code>
                  </li>
                ))}
              </ul>
            </div>
          }
          knopf="Voller Zugriff"
          onBestaetigen={() => {
            setNachfrage(false);
            onWaehlen("voll");
          }}
          onAbbrechen={() => setNachfrage(false)}
        />
      )}
    </div>
  );
}
