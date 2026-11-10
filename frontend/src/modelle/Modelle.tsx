import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Brain, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";

import { api } from "../api";
import { Bestaetigung, Dialog } from "../ui/Dialog";
import { FehlerMeldung, Feld, Knopf, Lade, Meldung, StatusMarke } from "../ui/ui";
import { ZugangFeld } from "../zugaenge/ZugangFeld";
import { type Modell, MODELLE, type ModellUebersicht, type Rolle, useModelle, zeitspanne } from "./modelle";

type Offen =
  | { art: "modell"; modell?: Modell }
  | { art: "modell-loeschen"; modell: Modell }
  | { art: "rolle" }
  | { art: "rolle-loeschen"; rolle: Rolle }
  | null;

/** Seite „Modelle“: Modell-Endpunkte und Rollen mit Haupt- und Ersatzmodell. */
export function Modelle() {
  const queryClient = useQueryClient();
  const uebersicht = useModelle();
  const [offen, setOffen] = useState<Offen>(null);
  const neuLaden = () => queryClient.invalidateQueries({ queryKey: MODELLE });

  const zuweisen = useMutation({
    mutationFn: ({ rolle, ...daten }: { rolle: Rolle; haupt_modell_id?: number | null; ersatz_modell_id?: number | null }) =>
      api.put<ModellUebersicht>(`/api/rollen/${rolle.id}`, daten),
    onSuccess: (daten) => queryClient.setQueryData(MODELLE, daten),
  });
  const testen = useMutation({
    mutationFn: (modell: Modell) => api.post<Modell>(`/api/modelle/${modell.id}/testen`),
    onSuccess: neuLaden,
  });
  const loeschen = useMutation({
    mutationFn: (pfad: string) => api.del(pfad),
    onSuccess: async () => {
      setOffen(null);
      await neuLaden();
    },
  });
  const schliessen = () => {
    loeschen.reset();
    setOffen(null);
  };

  if (uebersicht.isPending) return <Lade />;
  if (uebersicht.isError) return <FehlerMeldung fehler={uebersicht.error} />;
  const { modelle, rollen } = uebersicht.data;

  const modellAuswahl = (rolle: Rolle, feld: "haupt_modell_id" | "ersatz_modell_id", titel: string) => (
    <label className="feld">
      <span className="feld-titel">{titel}</span>
      <select
        aria-label={`${titel} für ${rolle.name}`}
        value={rolle[feld] ?? ""}
        onChange={(e) => zuweisen.mutate({ rolle, [feld]: e.target.value ? Number(e.target.value) : null })}
      >
        <option value="">{feld === "haupt_modell_id" ? "Kein Modell ausgewählt" : "Kein Ersatz"}</option>
        {modelle.map((modell) => (
          <option key={modell.id} value={modell.id}>
            {modell.name}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="stapel">
      <p className="gedaempft">
        Missa verwendet feste Namen wie <code>missa-schnell</code> und <code>missa-stark</code>. Welches Modell
        dahinter steckt, legst du hier fest – ein Wechsel wirkt sofort, ohne dass sich bei Missa etwas ändert.
      </p>
      <FehlerMeldung fehler={zuweisen.error ?? testen.error} />

      <div className="reihe zwischen">
        <h2>Rollen</h2>
        <Knopf onClick={() => setOffen({ art: "rolle" })}>
          <Plus aria-hidden />
          Neue Rolle
        </Knopf>
      </div>
      <div className="karten">
        {rollen.map((rolle) => (
          <section className="karte stapel eng" key={rolle.id} aria-label={`Rolle ${rolle.name}`}>
            <div className="reihe zwischen">
              <h3>{rolle.name}</h3>
              <div className="reihe" style={{ gap: "0.3rem" }}>
                <code className="etikett">{rolle.modellname}</code>
                {!rolle.fest && (
                  <Knopf art="still" klein aria-label={`Rolle ${rolle.name} löschen`} onClick={() => setOffen({ art: "rolle-loeschen", rolle })}>
                    <Trash2 aria-hidden />
                  </Knopf>
                )}
              </div>
            </div>
            <p className="gedaempft klein fuellen">{rolle.beschreibung}</p>
            {modellAuswahl(rolle, "haupt_modell_id", "Hauptmodell")}
            {modellAuswahl(rolle, "ersatz_modell_id", "Ersatzmodell bei Ausfall")}
            {rolle.haupt_modell_id === null && <Meldung art="warn">Ohne Hauptmodell kann Missa diese Rolle nicht nutzen.</Meldung>}
          </section>
        ))}
      </div>

      <div className="reihe zwischen">
        <h2>Modelle</h2>
        <Knopf art="haupt" onClick={() => setOffen({ art: "modell" })}>
          <Plus aria-hidden />
          Neues Modell
        </Knopf>
      </div>
      {modelle.length === 0 ? (
        <div className="karte leer">
          <Brain aria-hidden />
          <h2>Noch keine Modelle</h2>
          <p>Trage einen OpenAI-kompatiblen Endpunkt ein, z. B. einen lokalen vLLM-, llama.cpp- oder Ollama-Server.</p>
        </div>
      ) : (
        <div className="karte ohne-rand tabelle-huelle">
          <table className="tabelle">
            <thead>
              <tr>
                <th>Modell</th>
                <th>Verbindungstest</th>
                <th>Letzte 7 Tage</th>
                <th>
                  <span className="sr-only">Aktionen</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {modelle.map((modell) => (
                <tr key={modell.id}>
                  <td>
                    <strong>{modell.name}</strong>
                    <div className="gedaempft klein mono">{modell.modellname}</div>
                    <div className="gedaempft klein">
                      {modell.url}
                      {modell.kontextlaenge ? ` · Kontext ${modell.kontextlaenge.toLocaleString("de-CH")}` : ""}
                    </div>
                  </td>
                  <td>
                    {modell.test.ok === null && <StatusMarke status="grau">noch nicht getestet</StatusMarke>}
                    {modell.test.ok === true && (
                      <>
                        <StatusMarke status="ok">antwortet</StatusMarke>
                        <div className="gedaempft klein">
                          {zeitspanne(modell.test.ms)}
                          {modell.test.tokens_pro_s !== null && ` · ${modell.test.tokens_pro_s} Tokens/s`}
                        </div>
                      </>
                    )}
                    {modell.test.ok === false && (
                      <>
                        <StatusMarke status="fehler">Fehler</StatusMarke>
                        <div className="klein">{modell.test.meldung}</div>
                        <div className="gedaempft klein">{modell.test.hinweis}</div>
                      </>
                    )}
                  </td>
                  <td className="klein">
                    {modell.statistik.anfragen === 0 ? (
                      <span className="gedaempft">keine Anfragen</span>
                    ) : (
                      <>
                        <div>
                          {modell.statistik.anfragen} {modell.statistik.anfragen === 1 ? "Anfrage" : "Anfragen"}
                          {modell.statistik.fehler > 0 && `, davon ${modell.statistik.fehler} Fehler`}
                        </div>
                        <div className="gedaempft">
                          ⌀ {zeitspanne(modell.statistik.antwortzeit_ms)}
                          {modell.statistik.tokens_pro_s !== null && ` · ${modell.statistik.tokens_pro_s} Tokens/s`}
                        </div>
                      </>
                    )}
                  </td>
                  <td className="aktionen">
                    <Knopf klein onClick={() => testen.mutate(modell)} disabled={testen.isPending && testen.variables?.id === modell.id}>
                      <RefreshCw aria-hidden />
                      {testen.isPending && testen.variables?.id === modell.id ? "Teste …" : "Testen"}
                    </Knopf>
                    <Knopf art="still" aria-label={`${modell.name} bearbeiten`} onClick={() => setOffen({ art: "modell", modell })}>
                      <Pencil aria-hidden />
                    </Knopf>
                    <Knopf art="still" aria-label={`${modell.name} löschen`} onClick={() => setOffen({ art: "modell-loeschen", modell })}>
                      <Trash2 aria-hidden />
                    </Knopf>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="karte stapel eng">
        <h3>So nutzt ein Client die Modelle</h3>
        <p className="gedaempft klein">
          Der Modell-Anschluss spricht die Sprache der OpenAI-API. Als API-Key dient der Token aus „Clients“.
        </p>
        <table className="tabelle">
          <tbody>
            <tr>
              <td>Basis-URL</td>
              <td className="mono">{window.location.origin}/v1</td>
            </tr>
            <tr>
              <td>API-Key</td>
              <td>Client-Token</td>
            </tr>
            <tr>
              <td>Modell</td>
              <td className="mono">{rollen.map((rolle) => rolle.modellname).join(", ")}</td>
            </tr>
          </tbody>
        </table>
      </div>

      {offen?.art === "modell" && (
        <ModellFormular
          modell={offen.modell}
          onSchliessen={schliessen}
          onGespeichert={async (modell) => {
            setOffen(null);
            await neuLaden();
            testen.mutate(modell); // gleich prüfen, ob das Modell antwortet
          }}
        />
      )}
      {offen?.art === "rolle" && (
        <RolleFormular
          onSchliessen={schliessen}
          onGespeichert={async () => {
            setOffen(null);
            await neuLaden();
          }}
        />
      )}
      {offen?.art === "modell-loeschen" && (
        <Bestaetigung
          titel="Modell löschen?"
          text={<p>„{offen.modell.name}“ wird gelöscht. Die Statistik dazu geht verloren.</p>}
          knopf="Löschen"
          laeuft={loeschen.isPending}
          fehler={<FehlerMeldung fehler={loeschen.error} />}
          onBestaetigen={() => loeschen.mutate(`/api/modelle/${offen.modell.id}`)}
          onAbbrechen={schliessen}
        />
      )}
      {offen?.art === "rolle-loeschen" && (
        <Bestaetigung
          titel="Rolle löschen?"
          text={<p>Clients können danach „{offen.rolle.modellname}“ nicht mehr verwenden.</p>}
          knopf="Löschen"
          laeuft={loeschen.isPending}
          fehler={<FehlerMeldung fehler={loeschen.error} />}
          onBestaetigen={() => loeschen.mutate(`/api/rollen/${offen.rolle.id}`)}
          onAbbrechen={schliessen}
        />
      )}
    </div>
  );
}

function ModellFormular({
  modell,
  onSchliessen,
  onGespeichert,
}: {
  modell?: Modell;
  onSchliessen: () => void;
  onGespeichert: (modell: Modell) => void;
}) {
  const [name, setName] = useState(modell?.name ?? "");
  const [url, setUrl] = useState(modell?.url ?? "");
  const [modellname, setModellname] = useState(modell?.modellname ?? "");
  const [zugang, setZugang] = useState<number | null>(modell?.zugang_id ?? null);
  const [kontext, setKontext] = useState(modell?.kontextlaenge ? String(modell.kontextlaenge) : "");

  const speichern = useMutation({
    mutationFn: () => {
      const daten = { name, url, modellname, zugang_id: zugang, kontextlaenge: kontext ? Number(kontext) : null };
      return modell ? api.put<Modell>(`/api/modelle/${modell.id}`, daten) : api.post<Modell>("/api/modelle", daten);
    },
    onSuccess: onGespeichert,
  });

  return (
    <Dialog titel={modell ? `Modell „${modell.name}“ bearbeiten` : "Neues Modell"} onSchliessen={onSchliessen} breit>
      <form
        className="stapel"
        onSubmit={(ereignis: FormEvent) => {
          ereignis.preventDefault();
          speichern.mutate();
        }}
      >
        <Feld titel="Name" fuer="modell-name" pflicht hilfe="Frei wählbar, z. B. „Qwen 32B auf der Workstation“.">
          <input id="modell-name" type="text" required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
        </Feld>
        <Feld titel="URL des Endpunkts" fuer="modell-url" pflicht hilfe="OpenAI-kompatibel, bis einschliesslich /v1 – z. B. http://192.168.1.30:8000/v1">
          <input id="modell-url" type="url" required placeholder="http://192.168.1.30:8000/v1" value={url} onChange={(e) => setUrl(e.target.value)} />
        </Feld>
        <Feld titel="Modellname" fuer="modell-modellname" pflicht hilfe="So, wie ihn der Server kennt – z. B. „qwen2.5:32b“.">
          <input id="modell-modellname" type="text" required maxLength={200} value={modellname} onChange={(e) => setModellname(e.target.value)} />
        </Feld>
        <Feld titel="Zugang (optional)" fuer="modell-zugang" hilfe="Nur nötig, wenn der Endpunkt einen API-Key verlangt.">
          <ZugangFeld id="modell-zugang" wert={zugang} onAendern={setZugang} typen={["api_key", "bearer_token"]} vorschlagName={name} />
        </Feld>
        <Feld titel="Kontextlänge (optional)" fuer="modell-kontext" hilfe="In Tokens, z. B. 32768. Nur zur Information.">
          <input id="modell-kontext" type="number" min={1} value={kontext} onChange={(e) => setKontext(e.target.value)} />
        </Feld>
        <FehlerMeldung fehler={speichern.error} />
        <div className="dialog-fuss">
          <Knopf onClick={onSchliessen}>Abbrechen</Knopf>
          <Knopf art="haupt" type="submit" disabled={speichern.isPending}>
            Speichern und testen
          </Knopf>
        </div>
      </form>
    </Dialog>
  );
}

function RolleFormular({ onSchliessen, onGespeichert }: { onSchliessen: () => void; onGespeichert: () => void }) {
  const [kennung, setKennung] = useState("");
  const [name, setName] = useState("");
  const [beschreibung, setBeschreibung] = useState("");
  const speichern = useMutation({
    mutationFn: () => api.post<Rolle>("/api/rollen", { kennung, name, beschreibung }),
    onSuccess: onGespeichert,
  });

  return (
    <Dialog titel="Neue Rolle" onSchliessen={onSchliessen}>
      <form
        className="stapel"
        onSubmit={(ereignis: FormEvent) => {
          ereignis.preventDefault();
          speichern.mutate();
        }}
      >
        <Feld titel="Kurzname" fuer="rolle-kennung" pflicht hilfe={`Clients verwenden dann den Modellnamen missa-${kennung || "…"}.`}>
          <input id="rolle-kennung" type="text" required maxLength={30} pattern="[a-z][a-z0-9\-]*" placeholder="uebersetzen" value={kennung} onChange={(e) => setKennung(e.target.value.toLowerCase())} />
        </Feld>
        <Feld titel="Name" fuer="rolle-name">
          <input id="rolle-name" type="text" maxLength={60} placeholder="Übersetzen" value={name} onChange={(e) => setName(e.target.value)} />
        </Feld>
        <Feld titel="Wofür?" fuer="rolle-beschreibung">
          <input id="rolle-beschreibung" type="text" maxLength={300} value={beschreibung} onChange={(e) => setBeschreibung(e.target.value)} />
        </Feld>
        <FehlerMeldung fehler={speichern.error} />
        <div className="dialog-fuss">
          <Knopf onClick={onSchliessen}>Abbrechen</Knopf>
          <Knopf art="haupt" type="submit" disabled={speichern.isPending}>
            Rolle anlegen
          </Knopf>
        </div>
      </form>
    </Dialog>
  );
}
