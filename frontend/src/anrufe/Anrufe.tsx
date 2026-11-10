import { useMutation, useQueryClient } from "@tanstack/react-query";
import { PhoneIncoming, PhoneOutgoing, Plus, Trash2 } from "lucide-react";
import { type FormEvent, useId, useState } from "react";

import { api } from "../api";
import { datum } from "../ui/format";
import { IntegrationsHinweis } from "../ui/IntegrationsHinweis";
import { FehlerMeldung, Feld, Knopf, Lade, Meldung, type Status, StatusMarke } from "../ui/ui";
import {
  ANRUFE,
  type Anruf,
  dauerText,
  type Einstellungen,
  type Eintrag,
  type Richtung,
  TELEFONIE,
  type Uebersicht,
  useAnrufe,
  useTelefonie,
  werText,
} from "./anrufe";

const DRINGLICHKEITEN = ["niedrig", "normal", "hoch", "dringend"];
const STATUS_FARBE: Record<Anruf["status"], Status> = {
  wartet: "ok",
  laeuft: "ok",
  beendet: "ok",
  test: "grau",
  nicht_erreicht: "warn",
  unterdrueckt: "warn",
  abgewiesen: "fehler",
  fehler: "fehler",
};
const QUELLE: Record<string, string> = { missa: "Missa", regel: "Regel", panel: "Panel" };

/** Seite „Anrufe“: Wer Missa erreichen darf, wann sie anrufen darf – und was bisher geschah. */
export function Anrufe() {
  const daten = useTelefonie();
  if (daten.isPending) return <Lade />;
  if (daten.isError) return <FehlerMeldung fehler={daten.error} />;
  const { einstellungen, adapter, adapter_fehlt, ruhezeit_jetzt } = daten.data;
  const aktiv = adapter.find((einer) => einer.kennung === einstellungen.adapter);

  return (
    <div className="stapel">
      <IntegrationsHinweis manifestId="telefonie" wasFehlt="erst anrufen" />
      {adapter_fehlt ? (
        <Meldung art="fehler" hinweis="Unten einen anderen Adapter wählen oder die zugehörige Integration wieder aktivieren.">
          Der gewählte Telefonie-Adapter steht nicht mehr zur Verfügung – Anrufe sind gerade nicht möglich.
        </Meldung>
      ) : (
        aktiv?.test && (
          <Meldung art="info" hinweis="Alles andere ist schon echt: wer anrufen darf, Ruhezeiten, Freigaben, Regeln und der Verlauf.">
            Noch ist kein echtes Telefon angeschlossen. Der Test-Adapter ruft niemanden an – er protokolliert Anrufe nur und
            meldet sie als Ereignis.
          </Meldung>
        )
      )}
      {ruhezeit_jetzt && (
        <Meldung art="warn">
          Gerade ist Ruhezeit ({ruhezeit_jetzt.von} bis {ruhezeit_jetzt.bis} Uhr): Nur dringende Anrufe gehen durch.
        </Meldung>
      )}
      <EinstellungenKarte uebersicht={daten.data} />
      <Ausprobieren uebersicht={daten.data} />
      <Verlauf />
    </div>
  );
}

function NummernListe({
  titel,
  hilfe,
  eintraege,
  onAendern,
}: {
  titel: string;
  hilfe: string;
  eintraege: Eintrag[];
  onAendern: (eintraege: Eintrag[]) => void;
}) {
  const setze = (index: number, teil: Partial<Eintrag>) =>
    onAendern(eintraege.map((eintrag, stelle) => (stelle === index ? { ...eintrag, ...teil } : eintrag)));
  return (
    <fieldset className="liste-feld">
      <legend>{titel}</legend>
      <p className="feld-hilfe">{hilfe}</p>
      {eintraege.map((eintrag, index) => (
        <div className="reihe" key={index}>
          <input
            type="tel"
            className="fuellen"
            aria-label={`${titel}: Nummer ${index + 1}`}
            placeholder="079 123 45 67"
            value={eintrag.nummer}
            onChange={(e) => setze(index, { nummer: e.target.value })}
          />
          <input
            type="text"
            className="fuellen"
            aria-label={`${titel}: Name ${index + 1}`}
            placeholder="Name (z. B. Handy)"
            maxLength={60}
            value={eintrag.name}
            onChange={(e) => setze(index, { name: e.target.value })}
          />
          <Knopf klein art="gefahr" aria-label={`${titel}: Nummer ${index + 1} entfernen`} onClick={() => onAendern(eintraege.filter((_, stelle) => stelle !== index))}>
            <Trash2 aria-hidden />
          </Knopf>
        </div>
      ))}
      <div>
        <Knopf klein onClick={() => onAendern([...eintraege, { nummer: "", name: "" }])}>
          <Plus aria-hidden />
          Nummer hinzufügen
        </Knopf>
      </div>
    </fieldset>
  );
}

function EinstellungenKarte({ uebersicht }: { uebersicht: Uebersicht }) {
  const id = useId();
  const queryClient = useQueryClient();
  const [werte, setWerte] = useState<Einstellungen>(uebersicht.einstellungen);
  const speichern = useMutation({
    mutationFn: () => api.put<Uebersicht>("/api/telefonie/einstellungen", werte),
    onSuccess: (neu) => {
      // Das Panel schreibt Nummern einheitlich (079 … → +41 79 …): so stehen sie danach auch im Formular.
      queryClient.setQueryData(TELEFONIE, neu);
      setWerte(neu.einstellungen);
    },
  });
  const geaendert = JSON.stringify(werte) !== JSON.stringify(uebersicht.einstellungen);
  const setze = (teil: Partial<Einstellungen>) => {
    speichern.reset();
    setWerte({ ...werte, ...teil });
  };

  return (
    <form
      className="karte stapel"
      aria-label="Einstellungen"
      onSubmit={(ereignis: FormEvent) => {
        ereignis.preventDefault();
        speichern.mutate();
      }}
    >
      <h2>Einstellungen</h2>
      <NummernListe
        titel="Eigene Nummern"
        hilfe="Unter diesen Nummern erreicht Missa dich. Die erste wird angerufen, wenn Missa oder eine Regel ohne Nummer anruft. Eigene Nummern dürfen Missa immer anrufen."
        eintraege={werte.eigene_nummern}
        onAendern={(eigene_nummern) => setze({ eigene_nummern })}
      />
      <NummernListe
        titel="Erlaubte Anrufer"
        hilfe="Nur diese Nummern (und deine eigenen) dürfen Missa erreichen. Alle anderen Anrufe werden abgewiesen und stehen im Verlauf."
        eintraege={werte.erlaubte_anrufer}
        onAendern={(erlaubte_anrufer) => setze({ erlaubte_anrufer })}
      />
      <fieldset className="liste-feld">
        <legend>Ruhezeiten</legend>
        <p className="feld-hilfe">
          In dieser Zeit ruft Missa nur an, wenn es dringend ist (Zeitzone {uebersicht.zeitzone}). Alles andere erfährt sie als
          Ereignis und kann es später ausrichten.
        </p>
        {werte.ruhezeiten.map((ruhezeit, index) => (
          <div className="reihe" key={index}>
            <input
              type="time"
              aria-label={`Ruhezeit ${index + 1} von`}
              value={ruhezeit.von}
              onChange={(e) => setze({ ruhezeiten: werte.ruhezeiten.map((eine, stelle) => (stelle === index ? { ...eine, von: e.target.value } : eine)) })}
            />
            <span>bis</span>
            <input
              type="time"
              aria-label={`Ruhezeit ${index + 1} bis`}
              value={ruhezeit.bis}
              onChange={(e) => setze({ ruhezeiten: werte.ruhezeiten.map((eine, stelle) => (stelle === index ? { ...eine, bis: e.target.value } : eine)) })}
            />
            <span>Uhr</span>
            <Knopf klein art="gefahr" aria-label={`Ruhezeit ${index + 1} entfernen`} onClick={() => setze({ ruhezeiten: werte.ruhezeiten.filter((_, stelle) => stelle !== index) })}>
              <Trash2 aria-hidden />
            </Knopf>
          </div>
        ))}
        <div>
          <Knopf klein onClick={() => setze({ ruhezeiten: [...werte.ruhezeiten, { von: "22:00", bis: "07:00" }] })}>
            <Plus aria-hidden />
            Ruhezeit hinzufügen
          </Knopf>
        </div>
      </fieldset>

      <div className="felder-reihe">
        <Feld titel="Telefonie-Adapter" fuer={`${id}-adapter`} hilfe={uebersicht.adapter.find((einer) => einer.kennung === werte.adapter)?.beschreibung ?? "Weitere Adapter (SIP, App) kommen als Integration dazu."}>
          <select id={`${id}-adapter`} value={werte.adapter} onChange={(e) => setze({ adapter: e.target.value })}>
            {uebersicht.adapter_fehlt && <option value={uebersicht.einstellungen.adapter}>(nicht mehr vorhanden)</option>}
            {uebersicht.adapter.map((einer) => (
              <option key={einer.kennung} value={einer.kennung}>
                {einer.name}
              </option>
            ))}
          </select>
        </Feld>
        <Feld titel="Landesvorwahl" fuer={`${id}-vorwahl`} hilfe="Wird Nummern ohne Vorwahl vorangestellt: 079 … wird zu +41 79 …">
          <input id={`${id}-vorwahl`} type="text" value={werte.landesvorwahl} onChange={(e) => setze({ landesvorwahl: e.target.value })} />
        </Feld>
      </div>
      <label className="schalter">
        <input type="checkbox" checked={werte.nur_bekannte} onChange={(e) => setze({ nur_bekannte: e.target.checked })} />
        <span>Missa ruft nur eigene Nummern und erlaubte Anrufer an</span>
      </label>

      <FehlerMeldung fehler={speichern.error} />
      <div className="reihe">
        <Knopf art="haupt" type="submit" disabled={!geaendert || speichern.isPending}>
          {speichern.isPending ? "Speichere …" : "Speichern"}
        </Knopf>
        {speichern.isSuccess && !geaendert && (
          <span className="gedaempft klein" role="status">
            Gespeichert.
          </span>
        )}
      </div>
    </form>
  );
}

type AnrufAntwort = { ok: true; meldung: string } | { ok: false; meldung: string; hinweis?: string | null };
interface Entscheidung {
  annehmen: boolean;
  nummer: string;
  name: string;
  grund: string;
}

/** Ohne Telefon ausprobieren, was passieren würde: ein Anruf hinaus, ein Anruf herein. */
function Ausprobieren({ uebersicht }: { uebersicht: Uebersicht }) {
  const id = useId();
  const queryClient = useQueryClient();
  const [text, setText] = useState("Das ist ein Test-Anruf von Missa.");
  const [nummer, setNummer] = useState("");
  const [dringlichkeit, setDringlichkeit] = useState("normal");
  const [anrufer, setAnrufer] = useState("");
  const auffrischen = () => queryClient.invalidateQueries({ queryKey: ANRUFE });
  const anrufen = useMutation({
    mutationFn: () => api.post<AnrufAntwort>("/api/telefonie/anrufen", { text, nummer: nummer || null, dringlichkeit }),
    onSuccess: auffrischen,
  });
  const eingehend = useMutation({
    mutationFn: () => api.post<Entscheidung>("/api/telefonie/eingehend-simulieren", { nummer: anrufer }),
    onSuccess: auffrischen,
  });
  const test = uebersicht.adapter.find((einer) => einer.kennung === uebersicht.einstellungen.adapter)?.test ?? false;

  return (
    <section className="karte stapel" aria-label="Ausprobieren">
      <h2>Ausprobieren</h2>
      <div className="zwei-spalten">
        <form
          className="stapel eng"
          onSubmit={(ereignis: FormEvent) => {
            ereignis.preventDefault();
            anrufen.mutate();
          }}
        >
          <h3>Missa ruft an</h3>
          <Feld titel="Was Missa sagen soll" fuer={`${id}-text`}>
            <input id={`${id}-text`} type="text" required maxLength={500} value={text} onChange={(e) => setText(e.target.value)} />
          </Feld>
          <div className="felder-reihe">
            <Feld titel="Nummer" fuer={`${id}-nummer`} hilfe="Leer: deine erste eigene Nummer.">
              <input id={`${id}-nummer`} type="tel" value={nummer} onChange={(e) => setNummer(e.target.value)} />
            </Feld>
            <Feld titel="Dringlichkeit" fuer={`${id}-dringlichkeit`}>
              <select id={`${id}-dringlichkeit`} value={dringlichkeit} onChange={(e) => setDringlichkeit(e.target.value)}>
                {DRINGLICHKEITEN.map((eine) => (
                  <option key={eine}>{eine}</option>
                ))}
              </select>
            </Feld>
          </div>
          <div>
            <Knopf type="submit" disabled={anrufen.isPending}>
              <PhoneOutgoing aria-hidden />
              {test ? "Test-Anruf auslösen" : "Jetzt anrufen"}
            </Knopf>
          </div>
          <FehlerMeldung fehler={anrufen.error} />
          {anrufen.data && (
            <Meldung art={anrufen.data.ok ? "ok" : "warn"} hinweis={(!anrufen.data.ok && anrufen.data.hinweis) || undefined}>
              {anrufen.data.meldung}
            </Meldung>
          )}
        </form>

        <form
          className="stapel eng"
          onSubmit={(ereignis: FormEvent) => {
            ereignis.preventDefault();
            eingehend.mutate();
          }}
        >
          <h3>Jemand ruft Missa an</h3>
          <Feld titel="Nummer des Anrufers" fuer={`${id}-anrufer`} hilfe="Es klingelt nirgends – das Panel zeigt nur, ob diese Nummer durchkäme.">
            <input id={`${id}-anrufer`} type="tel" placeholder="078 000 00 00" value={anrufer} onChange={(e) => setAnrufer(e.target.value)} />
          </Feld>
          <div>
            <Knopf type="submit" disabled={eingehend.isPending}>
              <PhoneIncoming aria-hidden />
              Anruf simulieren
            </Knopf>
          </div>
          <FehlerMeldung fehler={eingehend.error} />
          {eingehend.data &&
            (eingehend.data.annehmen ? (
              <Meldung art="ok">Angenommen: {werText(eingehend.data)} darf Missa erreichen.</Meldung>
            ) : (
              <Meldung art="warn" hinweis="Der Versuch steht im Verlauf.">
                Abgewiesen: {eingehend.data.grund}
              </Meldung>
            ))}
        </form>
      </div>
    </section>
  );
}

const FILTER: { wert: Richtung | ""; titel: string }[] = [
  { wert: "", titel: "Alle" },
  { wert: "ausgehend", titel: "Ausgehend" },
  { wert: "eingehend", titel: "Eingehend" },
];

function Verlauf() {
  const [richtung, setRichtung] = useState<Richtung | "">("");
  const daten = useAnrufe(richtung);

  return (
    <section className="stapel eng" aria-label="Anrufverlauf">
      <div className="reihe zwischen">
        <h2>Verlauf</h2>
        <div className="auswahl" role="radiogroup" aria-label="Richtung">
          {FILTER.map((eintrag) => (
            <button key={eintrag.wert} type="button" role="radio" aria-checked={richtung === eintrag.wert} onClick={() => setRichtung(eintrag.wert)}>
              {eintrag.titel}
            </button>
          ))}
        </div>
      </div>
      {daten.isPending ? (
        <Lade />
      ) : daten.isError ? (
        <FehlerMeldung fehler={daten.error} />
      ) : (
        <div className="karte ohne-rand tabelle-huelle">
          <table className="tabelle">
            <thead>
              <tr>
                <th>Zeit</th>
                <th>Richtung</th>
                <th>Nummer</th>
                <th>Dauer</th>
                <th>Grund</th>
                <th>Ergebnis</th>
              </tr>
            </thead>
            <tbody>
              {daten.data.anrufe.map((anruf) => (
                <tr key={anruf.id}>
                  <td>{datum(anruf.zeit)}</td>
                  <td>
                    <span className="reihe" style={{ gap: "0.35rem", flexWrap: "nowrap" }}>
                      {anruf.richtung === "ausgehend" ? <PhoneOutgoing aria-hidden className="symbol-klein" /> : <PhoneIncoming aria-hidden className="symbol-klein" />}
                      {anruf.richtung}
                    </span>
                  </td>
                  <td>
                    {anruf.name && <div>{anruf.name}</div>}
                    <div className={anruf.name ? "gedaempft klein" : undefined}>{anruf.nummer}</div>
                  </td>
                  <td>{dauerText(anruf.dauer_sekunden)}</td>
                  <td>
                    <div>{anruf.grund || "–"}</div>
                    {QUELLE[anruf.quelle] && (
                      <div className="gedaempft klein">
                        ausgelöst von {QUELLE[anruf.quelle]}
                        {anruf.quelle === "regel" && anruf.quelle_name ? ` „${anruf.quelle_name}“` : ""}
                        {anruf.dringlichkeit !== "normal" ? ` · ${anruf.dringlichkeit}` : ""}
                      </div>
                    )}
                  </td>
                  <td>
                    <StatusMarke status={STATUS_FARBE[anruf.status] ?? "grau"}>{anruf.status_text}</StatusMarke>
                    {anruf.meldung && anruf.status !== "test" && <div className="gedaempft klein">{anruf.meldung}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {daten.data.anrufe.length === 0 && <p className="leer">Noch keine Anrufe.</p>}
        </div>
      )}
    </section>
  );
}
