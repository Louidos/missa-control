import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, NotebookPen, Pencil, Plus, Search, SearchX, Trash2 } from "lucide-react";
import { useId, useState } from "react";

import { api } from "../api";
import { Bestaetigung, Dialog } from "../ui/Dialog";
import { datum } from "../ui/format";
import { IntegrationsHinweis } from "../ui/IntegrationsHinweis";
import { FehlerMeldung, Feld, Knopf, Lade, Meldung } from "../ui/ui";
import { type Eintrag, type Filter, GEDAECHTNIS, SEITE, type Uebersicht, useGedaechtnis, useVerzoegert } from "./gedaechtnis";

type Offen = { art: "neu" } | { art: "bearbeiten"; eintrag: Eintrag } | { art: "loeschen"; eintrag: Eintrag } | null;

const KEIN_FILTER: Filter = { suche: "", kategorie: "", quelle: "" };

function gekuerzt(text: string, laenge = 120): string {
  return text.length > laenge ? `${text.slice(0, laenge).trimEnd()} …` : text;
}

interface FormularProps {
  eintrag?: Eintrag;
  kategorien: Uebersicht["kategorien"];
  maxZeichen: number;
  onFertig: (gespeichert: Eintrag & { neu?: boolean }) => void;
  onAbbrechen: () => void;
}

/** Eintrag anlegen oder korrigieren: Text und Kategorie. */
function EintragFormular({ eintrag, kategorien, maxZeichen, onFertig, onAbbrechen }: FormularProps) {
  const id = useId();
  const [text, setText] = useState(eintrag?.text ?? "");
  const [kategorie, setKategorie] = useState(eintrag?.kategorie ?? "sonstiges");
  const speichern = useMutation({
    mutationFn: () =>
      eintrag
        ? api.put<Eintrag>(`/api/gedaechtnis/${eintrag.id}`, { text, kategorie })
        : api.post<Eintrag & { neu: boolean }>("/api/gedaechtnis", { text, kategorie }),
    onSuccess: onFertig,
  });

  return (
    <form
      className="stapel"
      onSubmit={(ereignis) => {
        ereignis.preventDefault();
        speichern.mutate();
      }}
    >
      <Feld
        titel="Was soll Missa wissen?"
        fuer={`${id}-text`}
        pflicht
        hilfe={`Am besten ein vollständiger Satz, der für sich allein verständlich ist. ${text.length} von ${maxZeichen} Zeichen.`}
      >
        <textarea
          id={`${id}-text`}
          rows={4}
          value={text}
          maxLength={maxZeichen}
          required
          autoFocus
          placeholder="z. B. Trinkt morgens am liebsten Kaffee mit Hafermilch"
          onChange={(ereignis) => setText(ereignis.target.value)}
        />
      </Feld>
      <Feld titel="Kategorie" fuer={`${id}-kategorie`}>
        <select id={`${id}-kategorie`} value={kategorie} onChange={(ereignis) => setKategorie(ereignis.target.value)}>
          {kategorien.map((eine) => (
            <option key={eine.wert} value={eine.wert}>
              {eine.titel}
            </option>
          ))}
        </select>
      </Feld>
      <FehlerMeldung fehler={speichern.error} />
      <div className="dialog-fuss">
        <Knopf onClick={onAbbrechen}>Abbrechen</Knopf>
        <Knopf art="haupt" type="submit" disabled={speichern.isPending || !text.trim()}>
          {speichern.isPending ? "Speichere …" : "Speichern"}
        </Knopf>
      </div>
    </form>
  );
}

/** Seite „Gedächtnis“: was Missa sich gemerkt hat – ansehen, suchen, korrigieren, löschen, exportieren. */
export function Gedaechtnis() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<Filter>(KEIN_FILTER);
  const [limit, setLimit] = useState(SEITE);
  const [offen, setOffen] = useState<Offen>(null);
  const [schonDa, setSchonDa] = useState(false);
  const suche = useVerzoegert(filter.suche);
  const gedaechtnis = useGedaechtnis({ ...filter, suche }, limit);

  const setze = (teil: Partial<Filter>) => {
    setFilter({ ...filter, ...teil });
    setLimit(SEITE);
  };
  const neuLaden = () => queryClient.invalidateQueries({ queryKey: GEDAECHTNIS });

  const loeschen = useMutation({
    mutationFn: (eintrag: Eintrag) => api.del(`/api/gedaechtnis/${eintrag.id}`),
    onSuccess: async () => {
      await neuLaden();
      setOffen(null);
    },
  });
  const schliessen = () => {
    loeschen.reset();
    setOffen(null);
  };
  const gespeichert = async (eintrag: Eintrag & { neu?: boolean }) => {
    setSchonDa(eintrag.neu === false);
    await neuLaden();
    setOffen(null);
  };

  if (gedaechtnis.isPending) return <Lade />;
  if (gedaechtnis.isError) return <FehlerMeldung fehler={gedaechtnis.error} />;
  const { eintraege, treffer, gesamt, kategorien, quellen, max_zeichen } = gedaechtnis.data;
  const gefiltert = Object.values(filter).some(Boolean);

  return (
    <div className="stapel">
      <div className="reihe zwischen">
        <p className="gedaempft fuellen">
          Alles, was Missa sich gemerkt hat. Hier lässt sich jeder Eintrag ansehen, korrigieren und löschen – und
          eigenes Wissen von Hand ergänzen.
        </p>
        {gesamt > 0 && (
          <a className="knopf" href="/api/gedaechtnis/export" download>
            <Download aria-hidden />
            Als JSON exportieren
          </a>
        )}
        <Knopf art="haupt" onClick={() => setOffen({ art: "neu" })}>
          <Plus aria-hidden />
          Neuer Eintrag
        </Knopf>
      </div>

      <IntegrationsHinweis manifestId="gedaechtnis" wasFehlt="sich erst etwas merken" />
      {schonDa && <Meldung art="info">Das steht schon im Gedächtnis – es wurde kein zweiter Eintrag angelegt.</Meldung>}

      {gesamt === 0 ? (
        <div className="karte leer">
          <NotebookPen aria-hidden />
          <h2>Noch nichts gemerkt</h2>
          <p>Sobald Missa sich etwas merkt, erscheint es hier. Du kannst auch selbst Einträge anlegen.</p>
        </div>
      ) : (
        <>
          <div className="reihe">
            <div className="suchfeld fuellen">
              <Search aria-hidden />
              <input
                type="search"
                placeholder="Gedächtnis durchsuchen – auch Wortteile …"
                aria-label="Gedächtnis durchsuchen"
                value={filter.suche}
                onChange={(ereignis) => setze({ suche: ereignis.target.value })}
              />
            </div>
            <select aria-label="Kategorie" value={filter.kategorie} onChange={(ereignis) => setze({ kategorie: ereignis.target.value })} style={{ width: "auto" }}>
              <option value="">Alle Kategorien</option>
              {kategorien.map((eine) => (
                <option key={eine.wert} value={eine.wert}>
                  {eine.titel} ({eine.anzahl})
                </option>
              ))}
            </select>
            <select aria-label="Quelle" value={filter.quelle} onChange={(ereignis) => setze({ quelle: ereignis.target.value })} style={{ width: "auto" }}>
              <option value="">Alle Quellen</option>
              {quellen.map((eine) => (
                <option key={eine.wert} value={eine.wert}>
                  {eine.wert === "missa" ? "Von Missa gemerkt" : "Von Hand eingetragen"}
                </option>
              ))}
            </select>
          </div>

          <p className="gedaempft klein" role="status">
            {gefiltert ? `${treffer} von ${gesamt} Einträgen` : `${gesamt} ${gesamt === 1 ? "Eintrag" : "Einträge"}`}
          </p>

          {eintraege.length === 0 ? (
            <div className="karte leer">
              <SearchX aria-hidden />
              <h2>Nichts gefunden</h2>
              <p>Zu dieser Suche gibt es keine Einträge.</p>
              <Knopf klein onClick={() => setze(KEIN_FILTER)}>
                Filter zurücksetzen
              </Knopf>
            </div>
          ) : (
            <ul className="karte erinnerungen">
              {eintraege.map((eintrag) => (
                <li key={eintrag.id}>
                  <div className="erinnerung-text">{eintrag.text}</div>
                  <div className="erinnerung-fuss">
                    <span className="etikett">{eintrag.kategorie_name}</span>
                    <span className={`etikett ${eintrag.quelle === "missa" ? "aktiv" : ""}`}>
                      {eintrag.quelle === "missa" ? "von Missa gemerkt" : "von Hand eingetragen"}
                    </span>
                    <span className="gedaempft klein fuellen">
                      {datum(eintrag.erstellt)}
                      {eintrag.geaendert !== eintrag.erstellt && ` · geändert ${datum(eintrag.geaendert)}`}
                    </span>
                    <Knopf art="still" klein aria-label={`Eintrag bearbeiten: ${gekuerzt(eintrag.text, 60)}`} onClick={() => setOffen({ art: "bearbeiten", eintrag })}>
                      <Pencil aria-hidden />
                    </Knopf>
                    <Knopf art="still" klein aria-label={`Eintrag löschen: ${gekuerzt(eintrag.text, 60)}`} onClick={() => setOffen({ art: "loeschen", eintrag })}>
                      <Trash2 aria-hidden />
                    </Knopf>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {treffer > eintraege.length && (
            <div className="reihe">
              <span className="gedaempft klein">
                {eintraege.length} von {treffer} angezeigt
              </span>
              <Knopf klein onClick={() => setLimit(limit + SEITE)}>
                Weitere anzeigen
              </Knopf>
            </div>
          )}
        </>
      )}

      {offen?.art === "neu" && (
        <Dialog titel="Neuer Eintrag" onSchliessen={schliessen}>
          <EintragFormular kategorien={kategorien} maxZeichen={max_zeichen} onFertig={gespeichert} onAbbrechen={schliessen} />
        </Dialog>
      )}
      {offen?.art === "bearbeiten" && (
        <Dialog titel="Eintrag bearbeiten" onSchliessen={schliessen}>
          <EintragFormular eintrag={offen.eintrag} kategorien={kategorien} maxZeichen={max_zeichen} onFertig={gespeichert} onAbbrechen={schliessen} />
        </Dialog>
      )}
      {offen?.art === "loeschen" && (
        <Bestaetigung
          titel="Eintrag löschen?"
          text={
            <p>
              „{gekuerzt(offen.eintrag.text)}“ wird endgültig aus dem Gedächtnis gelöscht. Missa weiss das danach nicht
              mehr.
            </p>
          }
          knopf="Endgültig löschen"
          laeuft={loeschen.isPending}
          fehler={<FehlerMeldung fehler={loeschen.error} />}
          onBestaetigen={() => loeschen.mutate(offen.eintrag)}
          onAbbrechen={schliessen}
        />
      )}
    </div>
  );
}
