import { useState } from "react";

import { Knopf } from "../ui/ui";
import { type Recht, RECHTE, type TestFunktion } from "./typen";

interface Props {
  funktionen: (TestFunktion & { anzeigeName?: string; vorhanden?: boolean })[];
  rechte: Record<string, Recht>;
  onAendern: (rechte: Record<string, Recht>) => void;
  /** Zusätzliche Spalte am Ende jeder Zeile (z. B. „Ausprobieren“). */
  aktion?: (funktion: TestFunktion) => React.ReactNode;
}

const AB_SUCHE = 8;

/** Liste der Funktionen einer Integration mit dem Recht pro Funktion. */
export function RechteListe({ funktionen, rechte, onAendern, aktion }: Props) {
  const [suche, setSuche] = useState("");
  const begriff = suche.trim().toLowerCase();
  const sichtbar = funktionen.filter(
    (funktion) =>
      !begriff ||
      funktion.name.toLowerCase().includes(begriff) ||
      funktion.beschreibung.toLowerCase().includes(begriff),
  );
  const setzeAlle = (regel: (funktion: TestFunktion) => Recht) =>
    onAendern({ ...rechte, ...Object.fromEntries(sichtbar.map((funktion) => [funktion.name, regel(funktion)])) });

  if (funktionen.length === 0) {
    return <p className="gedaempft">Diese Integration bietet (noch) keine Funktionen an.</p>;
  }

  return (
    <div className="stapel eng">
      {funktionen.length >= AB_SUCHE && (
        <div className="reihe">
          <input
            type="search"
            className="fuellen"
            style={{ width: "auto" }}
            placeholder="Funktionen durchsuchen …"
            aria-label="Funktionen durchsuchen"
            value={suche}
            onChange={(e) => setSuche(e.target.value)}
          />
          <Knopf klein onClick={() => setzeAlle((f) => (f.schreibend ? "nachfragen" : "erlaubt"))}>
            Empfehlung für alle
          </Knopf>
          <Knopf klein onClick={() => setzeAlle(() => "gesperrt")}>
            Alle sperren
          </Knopf>
        </div>
      )}
      <ul className="funktionen">
        {sichtbar.map((funktion) => (
          <li key={funktion.name} className={funktion.vorhanden === false ? "fehlt" : undefined}>
            <div className="funktion-text">
              <div className="reihe" style={{ gap: "0.4rem" }}>
                <code>{funktion.anzeigeName ?? funktion.name}</code>
                <span className={`etikett ${funktion.schreibend ? "schreibend" : "lesend"}`}>
                  {funktion.schreibend ? "schreibend" : "lesend"}
                </span>
                {funktion.vorhanden === false && <span className="etikett fehlt">nicht mehr vorhanden</span>}
              </div>
              <div className="gedaempft klein">{funktion.beschreibung}</div>
            </div>
            <select
              aria-label={`Recht für ${funktion.name}`}
              value={rechte[funktion.name] ?? funktion.recht}
              onChange={(e) => onAendern({ ...rechte, [funktion.name]: e.target.value as Recht })}
            >
              {RECHTE.map((recht) => (
                <option key={recht.wert} value={recht.wert}>
                  {recht.name}
                </option>
              ))}
            </select>
            {aktion?.(funktion)}
          </li>
        ))}
      </ul>
      {sichtbar.length === 0 && <p className="gedaempft">Keine Funktion passt zur Suche.</p>}
    </div>
  );
}
