import { Construction } from "lucide-react";

import type { NavEintrag } from "../layout/navigation";

/** Steht für einen Bereich, der mit einer späteren Version dazukommt. */
export function Platzhalter({ eintrag }: { eintrag: NavEintrag }) {
  return (
    <div className="karte leer">
      <Construction aria-hidden />
      <h2>{eintrag.titel} kommt mit einer späteren Version</h2>
      <p>{eintrag.beschreibung}</p>
    </div>
  );
}
