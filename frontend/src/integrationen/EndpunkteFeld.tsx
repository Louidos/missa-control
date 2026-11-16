import { Plus, Trash2 } from "lucide-react";
import { Knopf } from "../ui/ui";
import type { Endpunkt } from "./typen";

const METHODEN: Endpunkt["methode"][] = ["GET", "POST", "PUT", "PATCH", "DELETE"];

interface Props {
  titel: string;
  hilfe: string;
  wert: Endpunkt[];
  onAendern: (liste: Endpunkt[]) => void;
}

/** „Eigene Endpunkte“: aufklappbare Liste aus Name, Methode, Pfad und Beschreibung. */
export function EndpunkteFeld({ titel, hilfe, wert, onAendern }: Props) {
  const aendern = (nummer: number, teil: Partial<Endpunkt>) =>
    onAendern(wert.map((eintrag, i) => (i === nummer ? { ...eintrag, ...teil } : eintrag)));

  return (
    <details className="feld endpunkte" open={wert.length > 0}>
      <summary>
        {titel}
        {wert.length > 0 && ` (${wert.length})`}
      </summary>
      {hilfe && <div className="feld-hilfe">{hilfe}</div>}
      <div className="stapel eng">
        {wert.map((eintrag, nummer) => (
          <div className="endpunkt-zeile" key={nummer} role="group" aria-label={`Endpunkt ${nummer + 1}`}>
            <input
              aria-label="Name der Funktion"
              placeholder="artikel_lesen"
              value={eintrag.name}
              onChange={(e) => aendern(nummer, { name: e.target.value })}
            />
            <select
              aria-label="Methode"
              value={eintrag.methode}
              onChange={(e) => aendern(nummer, { methode: e.target.value as Endpunkt["methode"] })}
            >
              {METHODEN.map((methode) => (
                <option key={methode}>{methode}</option>
              ))}
            </select>
            <input
              aria-label="Pfad"
              placeholder="/artikel/{id}"
              value={eintrag.pfad}
              onChange={(e) => aendern(nummer, { pfad: e.target.value })}
            />
            <input
              aria-label="Beschreibung"
              placeholder="Was macht dieser Endpunkt?"
              value={eintrag.beschreibung}
              onChange={(e) => aendern(nummer, { beschreibung: e.target.value })}
            />
            <Knopf
              art="still"
              klein
              aria-label={`Endpunkt ${nummer + 1} entfernen`}
              onClick={() => onAendern(wert.filter((_, i) => i !== nummer))}
            >
              <Trash2 aria-hidden />
            </Knopf>
          </div>
        ))}
        <div>
          <Knopf
            klein
            onClick={() => onAendern([...wert, { name: "", methode: "GET", pfad: "", beschreibung: "" }])}
          >
            <Plus aria-hidden />
            Endpunkt hinzufügen
          </Knopf>
        </div>
      </div>
    </details>
  );
}
