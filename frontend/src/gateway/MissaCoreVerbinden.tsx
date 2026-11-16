import { useQuery } from "@tanstack/react-query";
import { CircleCheck, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../api";
import { Dialog } from "../ui/Dialog";
import { KopierFeld } from "../ui/KopierFeld";
import { Feld, Knopf, Meldung } from "../ui/ui";
import type { Client } from "./Clients";
import { CLIENTS } from "./clients";

export type NeuerMissaCore = Client & { token: string; port: number };

/** Sekunden seit einem Zeitpunkt (nie negativ). */
function sekundenSeit(iso: string, jetzt: number): number {
  return Math.max(0, Math.round((jetzt - new Date(iso).getTime()) / 1000));
}

function vorZeit(sekunden: number): string {
  if (sekunden < 90)
    return `vor ${sekunden} Sekunde${sekunden === 1 ? "" : "n"}`;
  const minuten = Math.round(sekunden / 60);
  return `vor ${minuten} Minute${minuten === 1 ? "" : "n"}`;
}

/**
 * „Missa-Core verbinden“: legt einen Client an und zeigt genau zwei Zeilen für /etc/missa/missa.env
 * plus den Neustart-Befehl. Danach wartet der Dialog sichtbar, bis Missa-Core sich meldet.
 * Das Panel schreibt nichts nach missa-core – die Zeilen trägt der Besitzer selbst ein.
 */
export function MissaCoreVerbinden({
  neu,
  onSchliessen,
}: {
  neu: NeuerMissaCore;
  onSchliessen: () => void;
}) {
  const [jetzt, setJetzt] = useState(() => Date.now());

  // Solange der Dialog offen ist: alle 2 Sekunden nachsehen, ob sich Missa-Core gemeldet hat.
  const clients = useQuery({
    queryKey: CLIENTS,
    queryFn: () => api.get<Client[]>("/api/clients"),
    refetchInterval: 2000,
  });
  useEffect(() => {
    const uhr = setInterval(() => setJetzt(Date.now()), 1000);
    return () => clearInterval(uhr);
  }, []);

  const stand = clients.data?.find((client) => client.id === neu.id);
  const gesehen = stand?.zuletzt_gesehen ?? null;
  const host = window.location.hostname;
  const lokal = ["localhost", "127.0.0.1", "::1", "[::1]", ""].includes(host);

  return (
    <Dialog titel="Missa-Core verbinden" onSchliessen={onSchliessen} breit>
      <div className="stapel">
        <p>
          Diese zwei Zeilen in <code>/etc/missa/missa.env</code> auf ai01
          eintragen (Datei mit <code>sudo nano /etc/missa/missa.env</code>{" "}
          öffnen):
        </p>
        <Feld
          titel="1 · Adresse des Panels"
          fuer="missa-url"
          hilfe="Läuft Missa-Core auf ai01 – also auf demselben Rechner wie das Panel."
        >
          <KopierFeld
            id="missa-url"
            wert={`MISSA_CONTROL_URL=http://127.0.0.1:${neu.port}`}
            beschriftung="Adresse kopieren"
          />
        </Feld>
        {!lokal && (
          <details className="feld">
            <summary className="klein">
              Missa-Core läuft auf einem anderen Rechner?
            </summary>
            <KopierFeld
              wert={`MISSA_CONTROL_URL=http://${host}:${neu.port}`}
              beschriftung="Adresse für einen anderen Rechner kopieren"
            />
          </details>
        )}
        <Feld titel="2 · Token" fuer="missa-token">
          <KopierFeld
            id="missa-token"
            wert={`MISSA_CONTROL_TOKEN=${neu.token}`}
            beschriftung="Token kopieren"
          />
        </Feld>
        <Meldung art="warn">
          Der Token wird nur jetzt angezeigt – nach dem Schliessen ist er nicht
          mehr sichtbar.
        </Meldung>
        <Feld titel="Danach Missa-Core neu starten" fuer="missa-neustart">
          <KopierFeld
            id="missa-neustart"
            wert="sudo systemctl restart missa-core"
            beschriftung="Befehl kopieren"
          />
        </Feld>
        <p className="gedaempft klein">
          Setzt eine Missa-Core-Version mit eingebauter Anbindung voraus. Das
          Panel schreibt nichts nach missa-core.
        </p>

        <div role="status" aria-live="polite" aria-label="Verbindung" className="karte">
          {gesehen ? (
            <div className="reihe" style={{ gap: "0.5rem" }}>
              <CircleCheck aria-hidden style={{ color: "var(--ok)" }} />
              <span>
                <strong>Verbunden</strong> – zuletzt gesehen{" "}
                {vorZeit(sekundenSeit(gesehen, jetzt))}
                {stand?.zuletzt_abgeholt &&
                  ` · Funktionen abgeholt ${vorZeit(sekundenSeit(stand.zuletzt_abgeholt, jetzt))}`}
              </span>
            </div>
          ) : (
            <div className="reihe" style={{ gap: "0.5rem" }}>
              <LoaderCircle aria-hidden className="dreht" />
              <span>
                Warte auf Missa-Core … (sobald Missa-Core neu gestartet ist und
                sich meldet, steht hier „Verbunden“)
              </span>
            </div>
          )}
        </div>
      </div>
      <div className="dialog-fuss">
        <Knopf art="haupt" onClick={onSchliessen}>
          {gesehen ? "Fertig" : "Schliessen"}
        </Knopf>
      </div>
    </Dialog>
  );
}
