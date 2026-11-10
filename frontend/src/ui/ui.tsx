/** Kleine Bausteine, die überall im Panel gleich aussehen. */

import { CircleAlert, CircleCheck, Info, TriangleAlert } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { ApiFehler } from "../api";

type KnopfArt = "normal" | "haupt" | "gefahr" | "still";

interface KnopfProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  art?: KnopfArt;
  klein?: boolean;
}

export function Knopf({ art = "normal", klein, className, type = "button", ...rest }: KnopfProps) {
  const klassen = ["knopf", art !== "normal" && art, klein && "klein", className].filter(Boolean).join(" ");
  return <button type={type} className={klassen} {...rest} />;
}

type MeldungArt = "fehler" | "ok" | "warn" | "info";

const MELDUNG_SYMBOL = { fehler: CircleAlert, ok: CircleCheck, warn: TriangleAlert, info: Info };

export function Meldung({ art, hinweis, children }: { art: MeldungArt; hinweis?: string; children: ReactNode }) {
  const Symbol = MELDUNG_SYMBOL[art];
  return (
    <div className={`meldung ${art}`} role={art === "fehler" ? "alert" : "status"}>
      <Symbol aria-hidden />
      <div>
        <div>{children}</div>
        {hinweis && <div className="meldung-hinweis">{hinweis}</div>}
      </div>
    </div>
  );
}

/** Zeigt einen Fehler mit Lösungshinweis an – oder nichts, wenn es keinen gibt. */
export function FehlerMeldung({ fehler }: { fehler: unknown }) {
  if (!fehler) return null;
  if (fehler instanceof ApiFehler) {
    return (
      <Meldung art="fehler" hinweis={fehler.hinweis}>
        {fehler.message}
      </Meldung>
    );
  }
  return <Meldung art="fehler">{fehler instanceof Error ? fehler.message : "Unbekannter Fehler."}</Meldung>;
}

interface FeldProps {
  titel: string;
  fuer?: string;
  hilfe?: ReactNode;
  pflicht?: boolean;
  children: ReactNode;
}

export function Feld({ titel, fuer, hilfe, pflicht, children }: FeldProps) {
  return (
    <div className="feld">
      <label htmlFor={fuer}>
        {titel}
        {pflicht && (
          <span className="pflicht" title="Pflichtfeld">
            {" *"}
          </span>
        )}
      </label>
      {children}
      {hilfe && <div className="feld-hilfe">{hilfe}</div>}
    </div>
  );
}

export type Status = "ok" | "warn" | "fehler" | "grau";

export function StatusMarke({ status, children }: { status: Status; children: ReactNode }) {
  return <span className={`marke-status ${status}`}>{children}</span>;
}

export function Lade({ text = "Lädt …" }: { text?: string }) {
  return (
    <div className="lade" role="status">
      {text}
    </div>
  );
}
