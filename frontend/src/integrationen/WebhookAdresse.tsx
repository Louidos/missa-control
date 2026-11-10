import { useId } from "react";

import { KopierFeld } from "../ui/KopierFeld";
import { Feld } from "../ui/ui";

/** Die geheime Adresse eines Webhooks mit einem Beispiel zum Ausprobieren. */
export function WebhookAdresse({ pfad }: { pfad: string }) {
  const id = useId();
  const adresse = window.location.origin + pfad;
  const beispiel = [
    `curl -X POST "${adresse}" \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d '{"nachricht": "Die Waschmaschine ist fertig"}'`,
  ].join("\n");

  return (
    <div className="stapel eng">
      <Feld
        titel="Geheime Adresse"
        fuer={id}
        hilfe="Wer diese Adresse kennt, kann Meldungen schicken – nur an Dienste weitergeben, denen du vertraust. Das sendende Gerät muss das Panel unter dieser Adresse erreichen."
      >
        <KopierFeld id={id} wert={adresse} beschriftung="Adresse kopieren" />
      </Feld>
      <div className="feld">
        <div className="feld-titel">Zum Ausprobieren</div>
        <pre className="ergebnis" aria-label="Beispiel mit curl">
          {beispiel}
        </pre>
        <div className="feld-hilfe">
          Jede Meldung wird zum Ereignis für Missa und kann Regeln auslösen. Möglich sind JSON, Formularfelder oder
          einfacher Text – für ganz einfache Geräte auch ein Aufruf mit <code>?nachricht=…</code> am Ende der Adresse.
          Das Feld <code>dringlichkeit</code> (niedrig, normal, hoch, dringend) darf mitkommen.
        </div>
      </div>
    </div>
  );
}
