import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Pencil, Plus, Send, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";

import { api } from "../api";
import { Bestaetigung, Dialog } from "../ui/Dialog";
import { datum } from "../ui/format";
import { FehlerMeldung, Feld, Knopf, Lade, Meldung, StatusMarke } from "../ui/ui";
import { ZugangFeld } from "../zugaenge/ZugangFeld";

export interface Ziel {
  id: number;
  name: string;
  art: "ntfy" | "webhook";
  adresse: string;
  thema: string;
  zugang_id: number | null;
  panel_adresse: string;
  arten: string[];
  aktiv: boolean;
  letzter_fehler: string;
  letzter_fehler_zeit: string | null;
  zuletzt_gesendet: string | null;
}

interface Daten {
  ziele: Ziel[];
  arten: { wert: string; titel: string; standard: boolean }[];
}

type Entwurf = Omit<Ziel, "id" | "letzter_fehler" | "letzter_fehler_zeit" | "zuletzt_gesendet">;

const MELDUNGEN = ["meldungen"] as const;

/** Seite „Meldungen“: Wohin das Panel von sich aus eine Nachricht schickt (ntfy oder Webhook). */
export function Meldungen() {
  const queryClient = useQueryClient();
  const daten = useQuery({ queryKey: MELDUNGEN, queryFn: () => api.get<Daten>("/api/meldungen") });
  const [bearbeiten, setBearbeiten] = useState<{ ziel: Ziel | null } | null>(null);
  const [loeschen, setLoeschen] = useState<Ziel | null>(null);
  const [testErgebnis, setTestErgebnis] = useState<Record<number, { ok: boolean; meldung: string }>>({});

  const neuLaden = () => queryClient.invalidateQueries({ queryKey: MELDUNGEN });
  const testen = useMutation({
    mutationFn: (ziel: Ziel) => api.post<{ ok: boolean; meldung: string }>(`/api/meldungen/${ziel.id}/testen`),
    onSuccess: async (ergebnis, ziel) => {
      setTestErgebnis((alt) => ({ ...alt, [ziel.id]: ergebnis }));
      await neuLaden();
    },
  });
  const entfernen = useMutation({
    mutationFn: (ziel: Ziel) => api.del(`/api/meldungen/${ziel.id}`),
    onSuccess: async () => {
      setLoeschen(null);
      await neuLaden();
    },
  });

  if (daten.isPending) return <Lade />;
  if (daten.isError) return <FehlerMeldung fehler={daten.error} />;
  const artTitel = Object.fromEntries(daten.data.arten.map((art) => [art.wert, art.titel]));

  return (
    <div className="stapel">
      <div className="reihe zwischen">
        <p className="gedaempft fuellen">
          Wartet eine Freigabe oder fällt eine Integration aus, schickt das Panel von sich aus eine Nachricht – an ntfy (aufs
          Handy) oder an einen Webhook. Erlauben und Ablehnen geht weiterhin nur im Panel.
        </p>
        <Knopf art="haupt" onClick={() => setBearbeiten({ ziel: null })}>
          <Plus aria-hidden />
          Ziel hinzufügen
        </Knopf>
      </div>
      <FehlerMeldung fehler={testen.error} />

      {daten.data.ziele.length === 0 && (
        <div className="karte leer">
          <BellRing aria-hidden />
          <h2>Noch keine Ziele</h2>
          <p>Lege ein Ziel an, z. B. ein ntfy-Thema, das du in der ntfy-App abonniert hast.</p>
        </div>
      )}

      {daten.data.ziele.map((ziel) => {
        const test = testErgebnis[ziel.id];
        return (
          <section key={ziel.id} className="karte stapel eng" aria-label={ziel.name}>
            <div className="integration-kopf">
              <div className="fuellen">
                <div className="reihe" style={{ gap: "0.5rem" }}>
                  <h2>{ziel.name}</h2>
                  <StatusMarke status={!ziel.aktiv ? "grau" : ziel.letzter_fehler ? "fehler" : "ok"}>
                    {!ziel.aktiv ? "aus" : ziel.letzter_fehler ? "Fehler" : "bereit"}
                  </StatusMarke>
                </div>
                <div className="gedaempft klein">
                  {ziel.art === "ntfy" ? `ntfy · ${ziel.adresse} · Thema „${ziel.thema}“` : `Webhook · ${ziel.adresse}`}
                  {ziel.zuletzt_gesendet && ` · zuletzt gesendet ${datum(ziel.zuletzt_gesendet)}`}
                </div>
                <div className="gedaempft klein">
                  Meldet: {ziel.arten.length ? ziel.arten.map((art) => artTitel[art] ?? art).join(" · ") : "nichts ausgewählt"}
                </div>
              </div>
              <Knopf klein onClick={() => testen.mutate(ziel)} disabled={testen.isPending && testen.variables?.id === ziel.id}>
                <Send aria-hidden />
                Test-Meldung senden
              </Knopf>
              <Knopf klein aria-label={`${ziel.name} bearbeiten`} onClick={() => setBearbeiten({ ziel })}>
                <Pencil aria-hidden />
              </Knopf>
              <Knopf klein art="gefahr" aria-label={`${ziel.name} löschen`} onClick={() => setLoeschen(ziel)}>
                <Trash2 aria-hidden />
              </Knopf>
            </div>
            {test && (
              <Meldung art={test.ok ? "ok" : "fehler"}>{test.meldung}</Meldung>
            )}
            {ziel.letzter_fehler && !test && (
              <Meldung art="fehler" hinweis={ziel.letzter_fehler_zeit ? `Zuletzt ${datum(ziel.letzter_fehler_zeit)}` : undefined}>
                Senden fehlgeschlagen: {ziel.letzter_fehler}
              </Meldung>
            )}
          </section>
        );
      })}

      {bearbeiten && (
        <ZielFormular
          ziel={bearbeiten.ziel}
          arten={daten.data.arten}
          onFertig={async () => {
            setBearbeiten(null);
            await neuLaden();
          }}
          onSchliessen={() => setBearbeiten(null)}
        />
      )}
      {loeschen && (
        <Bestaetigung
          titel="Ziel löschen?"
          text={<p>An „{loeschen.name}“ gehen danach keine Meldungen mehr.</p>}
          knopf="Löschen"
          laeuft={entfernen.isPending}
          fehler={<FehlerMeldung fehler={entfernen.error} />}
          onBestaetigen={() => entfernen.mutate(loeschen)}
          onAbbrechen={() => setLoeschen(null)}
        />
      )}
    </div>
  );
}

function ZielFormular({
  ziel,
  arten,
  onFertig,
  onSchliessen,
}: {
  ziel: Ziel | null;
  arten: Daten["arten"];
  onFertig: () => void;
  onSchliessen: () => void;
}) {
  const [entwurf, setEntwurf] = useState<Entwurf>(
    () =>
      ziel ?? {
        name: "Handy",
        art: "ntfy",
        adresse: "https://ntfy.sh",
        thema: "",
        zugang_id: null,
        panel_adresse: window.location.origin,
        arten: arten.filter((art) => art.standard).map((art) => art.wert),
        aktiv: true,
      },
  );
  const speichern = useMutation({
    mutationFn: () => (ziel ? api.put(`/api/meldungen/${ziel.id}`, entwurf) : api.post("/api/meldungen", entwurf)),
    onSuccess: onFertig,
  });
  const setze = (teil: Partial<Entwurf>) => setEntwurf({ ...entwurf, ...teil });

  return (
    <Dialog titel={ziel ? `„${ziel.name}“ bearbeiten` : "Ziel hinzufügen"} onSchliessen={onSchliessen} breit>
      <form
        className="stapel"
        onSubmit={(ereignis: FormEvent) => {
          ereignis.preventDefault();
          speichern.mutate();
        }}
      >
        <Feld titel="Name" fuer="ziel-name" pflicht>
          <input id="ziel-name" required maxLength={80} value={entwurf.name} onChange={(e) => setze({ name: e.target.value })} />
        </Feld>
        <div className="auswahl" role="radiogroup" aria-label="Art">
          {(["ntfy", "webhook"] as const).map((art) => (
            <button key={art} type="button" role="radio" aria-checked={entwurf.art === art} onClick={() => setze({ art })}>
              {art === "ntfy" ? "ntfy" : "Webhook"}
            </button>
          ))}
        </div>
        <Feld
          titel={entwurf.art === "ntfy" ? "Adresse des ntfy-Servers" : "Adresse des Webhooks"}
          fuer="ziel-adresse"
          pflicht
          hilfe={entwurf.art === "webhook" ? "Das Panel sendet die Meldung als JSON per POST an diese Adresse." : undefined}
        >
          <input id="ziel-adresse" type="url" required value={entwurf.adresse} onChange={(e) => setze({ adresse: e.target.value })} />
        </Feld>
        {entwurf.art === "ntfy" && (
          <Feld titel="Thema" fuer="ziel-thema" pflicht hilfe="Das Thema, das du in der ntfy-App abonniert hast – auf ntfy.sh schwer zu erraten wählen.">
            <input id="ziel-thema" required value={entwurf.thema} onChange={(e) => setze({ thema: e.target.value })} />
          </Feld>
        )}
        <Feld titel="Zugang (optional)" fuer="ziel-zugang" hilfe="Token oder Benutzer + Passwort, falls das Ziel eine Anmeldung verlangt.">
          <ZugangFeld
            id="ziel-zugang"
            wert={entwurf.zugang_id}
            onAendern={(zugangId) => setze({ zugang_id: zugangId })}
            typen={["bearer_token", "api_key", "benutzer_passwort"]}
            pflicht={false}
            vorschlagName={entwurf.name}
          />
        </Feld>
        <Feld titel="Adresse des Panels (für den Link in der Meldung)" fuer="ziel-panel">
          <input id="ziel-panel" type="url" value={entwurf.panel_adresse} onChange={(e) => setze({ panel_adresse: e.target.value })} />
        </Feld>
        <fieldset className="stapel eng">
          <legend>Was wird gemeldet?</legend>
          {arten.map((art) => (
            <label key={art.wert} className="schalter">
              <input
                type="checkbox"
                checked={entwurf.arten.includes(art.wert)}
                onChange={(e) =>
                  setze({ arten: e.target.checked ? [...entwurf.arten, art.wert] : entwurf.arten.filter((a) => a !== art.wert) })
                }
              />
              <span>{art.titel}</span>
            </label>
          ))}
        </fieldset>
        <label className="schalter">
          <input type="checkbox" checked={entwurf.aktiv} onChange={(e) => setze({ aktiv: e.target.checked })} />
          <span>aktiv</span>
        </label>
        <FehlerMeldung fehler={speichern.error} />
        <div className="dialog-fuss">
          <Knopf onClick={onSchliessen}>Abbrechen</Knopf>
          <Knopf art="haupt" type="submit" disabled={speichern.isPending}>
            Speichern
          </Knopf>
        </div>
      </form>
    </Dialog>
  );
}
