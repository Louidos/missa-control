import { X } from "lucide-react";
import { type ReactNode, useEffect, useId } from "react";

import { Knopf } from "./ui";

interface DialogProps {
  titel: string;
  onSchliessen: () => void;
  breit?: boolean;
  children: ReactNode;
}

/** Ein Fenster über der Seite. Schliesst mit Escape, dem Kreuz oder einem Klick daneben. */
export function Dialog({ titel, onSchliessen, breit, children }: DialogProps) {
  const titelId = useId();

  useEffect(() => {
    const taste = (ereignis: KeyboardEvent) => {
      if (ereignis.key === "Escape") onSchliessen();
    };
    document.addEventListener("keydown", taste);
    return () => document.removeEventListener("keydown", taste);
  }, [onSchliessen]);

  return (
    <div
      className="dialog-schleier"
      onMouseDown={(ereignis) => {
        if (ereignis.target === ereignis.currentTarget) onSchliessen();
      }}
    >
      <div className={`karte dialog stapel${breit ? " breit" : ""}`} role="dialog" aria-modal="true" aria-labelledby={titelId}>
        <div className="dialog-kopf">
          <h2 id={titelId}>{titel}</h2>
          <Knopf art="still" klein aria-label="Schliessen" onClick={onSchliessen}>
            <X aria-hidden />
          </Knopf>
        </div>
        {children}
      </div>
    </div>
  );
}

interface BestaetigungProps {
  titel: string;
  text: ReactNode;
  knopf: string;
  laeuft?: boolean;
  fehler?: ReactNode;
  onBestaetigen: () => void;
  onAbbrechen: () => void;
}

/** Rückfrage vor Aktionen, die sich nicht rückgängig machen lassen. */
export function Bestaetigung({ titel, text, knopf, laeuft, fehler, onBestaetigen, onAbbrechen }: BestaetigungProps) {
  return (
    <Dialog titel={titel} onSchliessen={onAbbrechen}>
      <div>{text}</div>
      {fehler}
      <div className="dialog-fuss">
        <Knopf onClick={onAbbrechen}>Abbrechen</Knopf>
        <Knopf art="gefahr" onClick={onBestaetigen} disabled={laeuft}>
          {knopf}
        </Knopf>
      </div>
    </Dialog>
  );
}
