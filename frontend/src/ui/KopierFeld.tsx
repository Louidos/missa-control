import { Copy } from "lucide-react";
import { useRef, useState } from "react";

import { Knopf } from "./ui";

interface Props {
  id?: string;
  wert: string;
  /** Beschriftung für Vorleseprogramme, z. B. „Adresse kopieren“. */
  beschriftung?: string;
}

/** Ein Wert zum Mitnehmen: nur lesbares Feld mit Knopf „Kopieren“. */
export function KopierFeld({ id, wert, beschriftung = "Kopieren" }: Props) {
  const feld = useRef<HTMLInputElement>(null);
  const [kopiert, setKopiert] = useState(false);

  const kopieren = async () => {
    feld.current?.select();
    try {
      // Die Zwischenablage gibt es nur über HTTPS oder localhost – sonst hilft das markierte Feld.
      await navigator.clipboard.writeText(wert);
      setKopiert(true);
    } catch {
      setKopiert(document.execCommand?.("copy") ?? false);
    }
  };

  return (
    <div className="reihe">
      <input id={id} ref={feld} className="mono fuellen" style={{ width: "auto" }} type="text" readOnly value={wert} onFocus={(e) => e.target.select()} />
      <Knopf aria-label={beschriftung} onClick={() => void kopieren()}>
        <Copy aria-hidden />
        {kopiert ? "Kopiert" : "Kopieren"}
      </Knopf>
    </div>
  );
}
