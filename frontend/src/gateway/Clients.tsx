import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Copy, MonitorSmartphone, Plus, Trash2 } from "lucide-react";
import { type FormEvent, useRef, useState } from "react";

import { api } from "../api";
import { Bestaetigung, Dialog } from "../ui/Dialog";
import { datum } from "../ui/format";
import { FehlerMeldung, Feld, Knopf, Lade, Meldung, StatusMarke } from "../ui/ui";

export interface Client {
  id: number;
  name: string;
  token_anfang: string;
  erstellt: string;
  zuletzt_gesehen: string | null;
  widerrufen: string | null;
  aktiv: boolean;
  /** Nur in der Antwort direkt nach dem Anlegen enthalten. */
  token?: string;
}

const CLIENTS = ["clients"] as const;

type Offen = { art: "neu" } | { art: "token"; client: Client } | { art: "widerrufen" | "loeschen"; client: Client } | null;

/** Seite „Clients“: wer sich mit dem Panel verbinden darf – jeder mit eigenem Token. */
export function Clients() {
  const queryClient = useQueryClient();
  const clients = useQuery({ queryKey: CLIENTS, queryFn: () => api.get<Client[]>("/api/clients") });
  const [offen, setOffen] = useState<Offen>(null);
  const [name, setName] = useState("");

  const neuLaden = () => queryClient.invalidateQueries({ queryKey: CLIENTS });
  const anlegen = useMutation({
    mutationFn: () => api.post<Client>("/api/clients", { name }),
    onSuccess: async (client) => {
      setName("");
      setOffen({ art: "token", client });
      await neuLaden();
    },
  });
  const aendern = useMutation({
    mutationFn: ({ client, art }: { client: Client; art: "widerrufen" | "loeschen" }) =>
      art === "widerrufen" ? api.post(`/api/clients/${client.id}/widerrufen`) : api.del(`/api/clients/${client.id}`),
    onSuccess: async () => {
      setOffen(null);
      await neuLaden();
    },
  });
  const schliessen = () => {
    anlegen.reset();
    aendern.reset();
    setOffen(null);
  };

  return (
    <div className="stapel">
      <div className="reihe zwischen">
        <p className="gedaempft fuellen">
          Clients sind Programme, die sich mit Missa Control verbinden dürfen – zum Beispiel missa-core oder eine App.
          Jeder bekommt einen eigenen Token, der sich einzeln widerrufen lässt.
        </p>
        <Knopf art="haupt" onClick={() => setOffen({ art: "neu" })}>
          <Plus aria-hidden />
          Neuer Client
        </Knopf>
      </div>
      <FehlerMeldung fehler={clients.error} />
      {clients.isPending && <Lade />}

      {clients.data?.length === 0 && (
        <div className="karte leer">
          <MonitorSmartphone aria-hidden />
          <h2>Noch keine Clients</h2>
          <p>Lege einen Client für missa-core an, um Missa mit dem Panel zu verbinden.</p>
        </div>
      )}

      {!!clients.data?.length && (
        <div className="karte ohne-rand tabelle-huelle">
          <table className="tabelle">
            <thead>
              <tr>
                <th>Name</th>
                <th>Token</th>
                <th>Status</th>
                <th>Angelegt</th>
                <th>Zuletzt gesehen</th>
                <th>
                  <span className="sr-only">Aktionen</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {clients.data.map((client) => (
                <tr key={client.id}>
                  <td>
                    <strong>{client.name}</strong>
                  </td>
                  <td className="mono">{client.token_anfang}</td>
                  <td>
                    <StatusMarke status={client.aktiv ? "ok" : "grau"}>{client.aktiv ? "aktiv" : "widerrufen"}</StatusMarke>
                  </td>
                  <td className="gedaempft klein">{datum(client.erstellt)}</td>
                  <td className="gedaempft klein">{client.zuletzt_gesehen ? datum(client.zuletzt_gesehen) : "noch nie"}</td>
                  <td className="aktionen">
                    {client.aktiv && (
                      <Knopf art="still" aria-label={`Token von ${client.name} widerrufen`} title="Token widerrufen" onClick={() => setOffen({ art: "widerrufen", client })}>
                        <Ban aria-hidden />
                      </Knopf>
                    )}
                    <Knopf art="still" aria-label={`${client.name} löschen`} title="Löschen" onClick={() => setOffen({ art: "loeschen", client })}>
                      <Trash2 aria-hidden />
                    </Knopf>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {offen?.art === "neu" && (
        <Dialog titel="Neuer Client" onSchliessen={schliessen}>
          <form
            className="stapel"
            onSubmit={(ereignis: FormEvent) => {
              ereignis.preventDefault();
              anlegen.mutate();
            }}
          >
            <Feld titel="Name" fuer="client-name" pflicht hilfe="Zum Beispiel „missa-core“ oder „Overlay-App“.">
              <input id="client-name" type="text" required autoFocus maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
            </Feld>
            <FehlerMeldung fehler={anlegen.error} />
            <div className="dialog-fuss">
              <Knopf onClick={schliessen}>Abbrechen</Knopf>
              <Knopf art="haupt" type="submit" disabled={anlegen.isPending}>
                Client anlegen
              </Knopf>
            </div>
          </form>
        </Dialog>
      )}
      {offen?.art === "token" && <TokenAnzeige client={offen.client} onSchliessen={schliessen} />}
      {(offen?.art === "widerrufen" || offen?.art === "loeschen") && (
        <Bestaetigung
          titel={offen.art === "widerrufen" ? "Token widerrufen?" : "Client löschen?"}
          text={
            <p>
              „{offen.client.name}“ kann sich danach sofort nicht mehr verbinden.
              {offen.art === "widerrufen" ? " Der Eintrag bleibt zur Nachvollziehbarkeit sichtbar." : ""}
            </p>
          }
          knopf={offen.art === "widerrufen" ? "Widerrufen" : "Löschen"}
          laeuft={aendern.isPending}
          fehler={<FehlerMeldung fehler={aendern.error} />}
          onBestaetigen={() => aendern.mutate({ client: offen.client, art: offen.art })}
          onAbbrechen={schliessen}
        />
      )}
    </div>
  );
}

/** Zeigt den Token genau einmal – mit allem, was man zum Anbinden braucht. */
function TokenAnzeige({ client, onSchliessen }: { client: Client; onSchliessen: () => void }) {
  const feld = useRef<HTMLInputElement>(null);
  const [kopiert, setKopiert] = useState(false);
  const adresse = window.location.origin;

  const kopieren = async () => {
    feld.current?.select();
    try {
      // Die Zwischenablage gibt es nur über HTTPS oder localhost – sonst hilft das markierte Feld.
      await navigator.clipboard.writeText(client.token ?? "");
      setKopiert(true);
    } catch {
      setKopiert(document.execCommand?.("copy") ?? false);
    }
  };

  return (
    <Dialog titel={`Token für „${client.name}“`} onSchliessen={onSchliessen} breit>
      <Meldung art="warn">Dieser Token wird nur jetzt angezeigt. Bitte gleich kopieren und sicher ablegen.</Meldung>
      <Feld titel="Token" fuer="client-token">
        <div className="reihe">
          <input id="client-token" ref={feld} className="mono fuellen" style={{ width: "auto" }} type="text" readOnly value={client.token ?? ""} onFocus={(e) => e.target.select()} />
          <Knopf onClick={() => void kopieren()}>
            <Copy aria-hidden />
            {kopiert ? "Kopiert" : "Kopieren"}
          </Knopf>
        </div>
      </Feld>
      <div className="stapel eng">
        <h3>So verbindet sich der Client</h3>
        <p className="gedaempft klein">
          Bei jeder Anfrage den Token als Header <code>Authorization: Bearer &lt;Token&gt;</code> mitsenden.
        </p>
        <table className="tabelle">
          <tbody>
            <tr>
              <td>Funktionen (MCP, Streamable HTTP)</td>
              <td className="mono">{adresse}/mcp</td>
            </tr>
            <tr>
              <td>Ereignisse (Server-Sent Events)</td>
              <td className="mono">{adresse}/api/events/stream</td>
            </tr>
            <tr>
              <td>Ereignisse abholen</td>
              <td className="mono">{adresse}/api/events?seit=…</td>
            </tr>
            <tr>
              <td>Konfiguration (nur lesend)</td>
              <td className="mono">{adresse}/api/config/integrations</td>
            </tr>
          </tbody>
        </table>
        <p className="gedaempft klein">Die ganze Anleitung steht in docs/anbindung-missa-core.md.</p>
      </div>
      <div className="dialog-fuss">
        <Knopf art="haupt" onClick={onSchliessen}>
          Ich habe den Token gespeichert
        </Knopf>
      </div>
    </Dialog>
  );
}
