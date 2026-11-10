import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Pencil, Play, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { api } from "../api";
import { Bestaetigung, Dialog } from "../ui/Dialog";
import { datum } from "../ui/format";
import { IntegrationsHinweis } from "../ui/IntegrationsHinweis";
import { FehlerMeldung, Knopf, Lade, Meldung, type Status, StatusMarke } from "../ui/ui";
import { RegelEditor } from "./RegelEditor";
import { type Ausloesung, type Regel, REGEL_VERLAUF, REGELN, useRegeln, type Verlauf } from "./regeln";

type Offen = { art: "neu" } | { art: "bearbeiten"; regel: Regel } | { art: "loeschen"; regel: Regel } | null;

const ERGEBNIS: Record<Ausloesung["ergebnis"], Status> = { ok: "ok", fehler: "fehler", ruhezeit: "grau", bedingung: "grau" };
const SEITE = 50;

/** Seite „Regeln“: Regeln als lesbare Sätze, Editor, „Jetzt testen“ und der Verlauf der Auslösungen. */
export function Regeln() {
  const queryClient = useQueryClient();
  const regeln = useRegeln();
  const [offen, setOffen] = useState<Offen>(null);
  const [tests, setTests] = useState<Record<number, { ok: boolean; meldung: string }>>({});
  const [nurRegel, setNurRegel] = useState("");
  const [limit, setLimit] = useState(SEITE);
  const verlauf = useQuery({
    queryKey: [...REGEL_VERLAUF, nurRegel, limit],
    queryFn: () => api.get<Verlauf>(`/api/regeln/verlauf?limit=${limit}${nurRegel ? `&regel_id=${nurRegel}` : ""}`),
    placeholderData: keepPreviousData,
    refetchInterval: 15_000,
  });

  const neuLaden = () =>
    Promise.all([queryClient.invalidateQueries({ queryKey: REGELN }), queryClient.invalidateQueries({ queryKey: REGEL_VERLAUF })]);
  const schalten = useMutation({
    mutationFn: ({ regel, aktiv }: { regel: Regel; aktiv: boolean }) => api.patch<Regel>(`/api/regeln/${regel.id}`, { aktiv }),
    onSettled: neuLaden,
  });
  const testen = useMutation({
    mutationFn: (regel: Regel) => api.post<{ ok: boolean; meldung: string }>(`/api/regeln/${regel.id}/testen`),
    onSuccess: (ergebnis, regel) => setTests((bisher) => ({ ...bisher, [regel.id]: ergebnis })),
    onSettled: neuLaden,
  });
  const loeschen = useMutation({
    mutationFn: (regel: Regel) => api.del(`/api/regeln/${regel.id}`),
    onSuccess: async () => {
      await neuLaden();
      setOffen(null);
    },
  });
  const schliessen = () => {
    loeschen.reset();
    setOffen(null);
  };
  const gespeichert = async () => {
    await neuLaden();
    setOffen(null);
  };

  if (regeln.isPending) return <Lade />;
  if (regeln.isError) return <FehlerMeldung fehler={regeln.error} />;
  const { regeln: liste, optionen } = regeln.data;

  return (
    <div className="stapel">
      <div className="reihe zwischen">
        <p className="gedaempft fuellen">
          Regeln verbinden einen Auslöser mit einer Aktion – zum Beispiel „Wenn die CPU länger als 5 Minuten über 90 %
          liegt, bekommt Missa eine Nachricht“. Missa kann Regeln auch selbst anlegen; sie erscheinen dann hier.
        </p>
        <Knopf art="haupt" onClick={() => setOffen({ art: "neu" })}>
          <Plus aria-hidden />
          Neue Regel
        </Knopf>
      </div>

      <IntegrationsHinweis manifestId="regeln" wasFehlt="Regeln erst selbst anlegen und ändern" />
      <FehlerMeldung fehler={schalten.error ?? testen.error} />

      {liste.length === 0 && (
        <div className="karte leer">
          <BellRing aria-hidden />
          <h2>Noch keine Regeln</h2>
          <p>Lege die erste Regel an – oder bitte Missa darum.</p>
        </div>
      )}

      {liste.map((regel) => (
        <section className={`karte stapel eng regel${regel.aktiv ? "" : " pausiert"}`} key={regel.id} aria-label={`Regel ${regel.name}`}>
          <div className="reihe zwischen">
            <div className="reihe">
              <h2>{regel.name}</h2>
              {regel.quelle === "missa" && <span className="etikett aktiv">von Missa angelegt</span>}
            </div>
            <label className="schalter" title="Regel einschalten oder pausieren">
              <input type="checkbox" checked={regel.aktiv} aria-label={`${regel.name} aktiv`} onChange={(e) => schalten.mutate({ regel, aktiv: e.target.checked })} />
              <span>{regel.aktiv ? "aktiv" : "pausiert"}</span>
            </label>
          </div>
          <p className="regel-satz">{regel.satz}</p>
          {regel.problem && (
            <Meldung art="warn" hinweis="Die Regel bearbeiten – oder das Fehlende wieder einrichten.">
              {regel.problem}
            </Meldung>
          )}
          <div className="reihe zwischen">
            <span className="gedaempft klein">
              Zuletzt ausgelöst: {regel.zuletzt_ausgeloest ? datum(regel.zuletzt_ausgeloest) : "noch nie"}
              {regel.naechste_ausfuehrung && ` · Nächste Ausführung: ${datum(regel.naechste_ausfuehrung)}`}
            </span>
            <div className="reihe">
              <Knopf klein onClick={() => testen.mutate(regel)} disabled={testen.isPending && testen.variables?.id === regel.id} title="Führt die Aktion sofort aus – ohne auf den Auslöser zu warten">
                <Play aria-hidden />
                {testen.isPending && testen.variables?.id === regel.id ? "Teste …" : "Jetzt testen"}
              </Knopf>
              <Knopf art="still" klein aria-label={`${regel.name} bearbeiten`} onClick={() => setOffen({ art: "bearbeiten", regel })}>
                <Pencil aria-hidden />
              </Knopf>
              <Knopf art="still" klein aria-label={`${regel.name} löschen`} onClick={() => setOffen({ art: "loeschen", regel })}>
                <Trash2 aria-hidden />
              </Knopf>
            </div>
          </div>
          {tests[regel.id] && <Meldung art={tests[regel.id].ok ? "ok" : "fehler"}>Test: {tests[regel.id].meldung}</Meldung>}
        </section>
      ))}

      {(verlauf.data?.anzahl ?? 0) > 0 || nurRegel ? (
        <>
          <div className="reihe zwischen">
            <h2>Verlauf der Auslösungen</h2>
            <select aria-label="Verlauf filtern" value={nurRegel} style={{ width: "auto" }} onChange={(e) => { setNurRegel(e.target.value); setLimit(SEITE); }}>
              <option value="">Alle Regeln</option>
              {liste.map((regel) => (
                <option key={regel.id} value={regel.id}>
                  {regel.name}
                </option>
              ))}
            </select>
          </div>
          <div className="karte ohne-rand tabelle-huelle">
            <table className="tabelle">
              <thead>
                <tr>
                  <th>Zeit</th>
                  <th>Regel</th>
                  <th>Anlass</th>
                  <th>Ergebnis</th>
                </tr>
              </thead>
              <tbody>
                {verlauf.data?.eintraege.map((eintrag) => (
                  <tr key={eintrag.id}>
                    <td className="gedaempft klein">{datum(eintrag.zeit)}</td>
                    <td>{eintrag.regel}</td>
                    <td>{eintrag.anlass}</td>
                    <td>
                      <StatusMarke status={ERGEBNIS[eintrag.ergebnis] ?? "grau"}>{eintrag.ergebnis_name}</StatusMarke>
                      {eintrag.test && <span className="etikett"> Test</span>}
                      {eintrag.meldung && <div className="gedaempft klein">{eintrag.meldung}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {verlauf.data?.eintraege.length === 0 && <p className="leer">Diese Regel hat noch nicht ausgelöst.</p>}
          </div>
          {(verlauf.data?.anzahl ?? 0) > (verlauf.data?.eintraege.length ?? 0) && (
            <div className="reihe">
              <span className="gedaempft klein">
                {verlauf.data?.eintraege.length} von {verlauf.data?.anzahl} angezeigt
              </span>
              <Knopf klein onClick={() => setLimit(limit + SEITE)}>
                Weitere anzeigen
              </Knopf>
            </div>
          )}
          <p className="gedaempft klein">Einträge im Verlauf werden nach 30 Tagen gelöscht.</p>
        </>
      ) : null}

      {offen?.art === "neu" && (
        <Dialog titel="Neue Regel" breit onSchliessen={schliessen}>
          <RegelEditor optionen={optionen} onFertig={gespeichert} onAbbrechen={schliessen} />
        </Dialog>
      )}
      {offen?.art === "bearbeiten" && (
        <Dialog titel={`Regel „${offen.regel.name}“ bearbeiten`} breit onSchliessen={schliessen}>
          <RegelEditor regel={offen.regel} optionen={optionen} onFertig={gespeichert} onAbbrechen={schliessen} />
        </Dialog>
      )}
      {offen?.art === "loeschen" && (
        <Bestaetigung
          titel="Regel löschen?"
          text={<p>„{offen.regel.name}“ wird samt ihrem Verlauf endgültig gelöscht. Zum vorübergehenden Abschalten genügt „pausiert“.</p>}
          knopf="Endgültig löschen"
          laeuft={loeschen.isPending}
          fehler={<FehlerMeldung fehler={loeschen.error} />}
          onBestaetigen={() => loeschen.mutate(offen.regel)}
          onAbbrechen={schliessen}
        />
      )}
    </div>
  );
}
