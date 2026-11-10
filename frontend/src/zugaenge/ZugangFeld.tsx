import { Plus } from "lucide-react";
import { useState } from "react";

import { Knopf, Lade } from "../ui/ui";
import { ZugangFormular } from "./ZugangFormular";
import { useZugaenge, type ZugangTyp } from "./zugaenge";

interface Props {
  id?: string;
  /** Gewählter Zugang (seine Nummer) oder `null`. */
  wert: number | null;
  onAendern: (zugangId: number | null) => void;
  /** Nur diese Typen anbieten (leer = alle). */
  typen?: ZugangTyp[];
  pflicht?: boolean;
  vorschlagName?: string;
}

/**
 * Baustein für Formulare: einen bestehenden Zugang auswählen oder direkt hier einen neuen anlegen.
 * So muss man ein Formular nie verlassen, nur weil der passende Zugang noch fehlt.
 */
export function ZugangFeld({ id, wert, onAendern, typen, pflicht, vorschlagName }: Props) {
  const zugaenge = useZugaenge();
  const [neu, setNeu] = useState(false);

  if (zugaenge.isPending) return <Lade text="Lade Zugänge …" />;
  const passende = (zugaenge.data ?? []).filter((zugang) => !typen?.length || typen.includes(zugang.typ));

  if (neu) {
    return (
      <div className="zugang-neu">
        <ZugangFormular
          erlaubteTypen={typen}
          vorschlagName={vorschlagName}
          onAbbrechen={() => setNeu(false)}
          onFertig={(zugang) => {
            onAendern(zugang.id);
            setNeu(false);
          }}
        />
      </div>
    );
  }

  return (
    <div className="reihe">
      <select
        id={id}
        className="fuellen"
        style={{ width: "auto" }}
        required={pflicht}
        value={wert ?? ""}
        onChange={(e) => onAendern(e.target.value ? Number(e.target.value) : null)}
      >
        <option value="">{pflicht ? "Bitte wählen …" : "Kein Zugang"}</option>
        {passende.map((zugang) => (
          <option key={zugang.id} value={zugang.id}>
            {zugang.name} ({zugang.typ_name}, {zugang.maske})
          </option>
        ))}
      </select>
      <Knopf onClick={() => setNeu(true)}>
        <Plus aria-hidden />
        Neuer Zugang
      </Knopf>
    </div>
  );
}
