import { useId } from "react";

import { Feld as FeldRahmen } from "../ui/ui";
import { ZugangFeld } from "../zugaenge/ZugangFeld";
import type { Feld, Konfig, Option, Wert } from "./typen";

interface Props {
  felder: Feld[];
  werte: Konfig;
  onAendern: (werte: Konfig) => void;
  /** Auswahlmöglichkeiten aus dem Verbindungstest (für Felder, die erst danach erscheinen). */
  optionen?: Record<string, Option[]>;
  /** Vorschlag für den Namen eines neuen Zugangs, der direkt im Formular angelegt wird. */
  zugangName?: string;
}

/** Baut aus den Feldern eines Manifests automatisch die Eingabemaske. */
export function Formular({ felder, werte, onAendern, optionen, zugangName }: Props) {
  const basis = useId();
  const setze = (name: string, wert: Wert) => onAendern({ ...werte, [name]: wert });

  return (
    <>
      {felder.map((feld) => {
        const id = `${basis}-${feld.name}`;
        const wert = werte[feld.name];
        const text = typeof wert === "string" || typeof wert === "number" ? String(wert) : "";

        if (feld.typ === "schalter") {
          return (
            <div className="feld" key={feld.name}>
              <label className="schalter">
                <input type="checkbox" checked={wert === true} onChange={(e) => setze(feld.name, e.target.checked)} />
                <span>{feld.titel}</span>
              </label>
              {feld.hilfe && <div className="feld-hilfe">{feld.hilfe}</div>}
            </div>
          );
        }

        let eingabe;
        if (feld.typ === "zugang") {
          eingabe = (
            <ZugangFeld
              id={id}
              wert={typeof wert === "number" ? wert : null}
              onAendern={(zugangId) => setze(feld.name, zugangId)}
              typen={feld.zugang_typen}
              pflicht={feld.pflicht}
              vorschlagName={zugangName}
            />
          );
        } else if (feld.typ === "auswahl") {
          const auswahl = feld.optionen.length ? feld.optionen : (optionen?.[feld.name] ?? []);
          eingabe = auswahl.length ? (
            <select id={id} required={feld.pflicht} value={text} onChange={(e) => setze(feld.name, e.target.value)}>
              {(!feld.pflicht || !text) && <option value="">{feld.pflicht ? "Bitte wählen …" : "–"}</option>}
              {auswahl.map((option) => (
                <option key={option.wert} value={option.wert}>
                  {option.titel}
                </option>
              ))}
            </select>
          ) : (
            <input id={id} type="text" required={feld.pflicht} value={text} onChange={(e) => setze(feld.name, e.target.value)} />
          );
        } else if (feld.typ === "datei") {
          const gespeichert = typeof wert === "object" && wert !== null;
          const geladen = typeof wert === "string" && wert.length > 0;
          eingabe = (
            <>
              <input
                id={id}
                type="file"
                accept={feld.endungen.join(",") || undefined}
                required={feld.pflicht && !gespeichert && !geladen}
                onChange={async (e) => {
                  const datei = e.target.files?.[0];
                  setze(feld.name, datei ? await datei.text() : null);
                }}
              />
              {gespeichert && <div className="feld-hilfe">Eine Datei ist gespeichert – nur auswählen, um sie zu ersetzen.</div>}
              {geladen && <div className="feld-hilfe">Datei geladen ({Math.ceil((wert as string).length / 1024)} kB).</div>}
            </>
          );
        } else {
          eingabe = (
            <input
              id={id}
              type={feld.typ === "zahl" ? "number" : feld.typ === "url" ? "url" : "text"}
              step={feld.typ === "zahl" ? "any" : undefined}
              required={feld.pflicht}
              placeholder={feld.platzhalter || undefined}
              value={text}
              onChange={(e) => setze(feld.name, e.target.value)}
            />
          );
        }

        return (
          <FeldRahmen key={feld.name} titel={feld.titel} fuer={id} pflicht={feld.pflicht} hilfe={feld.hilfe || undefined}>
            {eingabe}
          </FeldRahmen>
        );
      })}
    </>
  );
}
