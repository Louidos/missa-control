import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChartLine, Cpu, KeyRound, Plus, Table2, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link } from "react-router";

import { api } from "../api";
import { Assistent } from "../integrationen/Assistent";
import { INTEGRATIONEN, KATALOG, RECHTE, useKatalog } from "../integrationen/typen";
import { Liniendiagramm } from "../serverlast/Liniendiagramm";
import { ZEITRAEUME, type Zeitraum } from "../serverlast/serverlast";
import { Bestaetigung, Dialog } from "../ui/Dialog";
import { datum } from "../ui/format";
import { FehlerMeldung, Knopf, Lade, Meldung, type Status, StatusMarke } from "../ui/ui";
import { type Faehigkeit, GERAETE, type Geraet, type Kopplung, useGeraete, useVerlauf, wertText } from "./geraete";
import { KopplungsDaten } from "./KopplungsDaten";

type Offen =
  | { art: "koppeln"; geraet: Geraet }
  | { art: "kopplung"; geraet: Geraet; kopplung: Kopplung }
  | { art: "entfernen"; geraet: Geraet };

const ART_NAME = { sensor: "Sensor", knopf: "Knopf", aktor: "Schalten" } as const;

function zustand(geraet: Geraet): { status: Status; text: string; zusatz: string } {
  if (!geraet.aktiv) return { status: "grau", text: "deaktiviert", zusatz: "Die Integration ist ausgeschaltet – Meldungen des Geräts werden nicht beachtet." };
  if (geraet.status_seit === null) return { status: "grau", text: "wartet auf das Gerät", zusatz: `gekoppelt ${datum(geraet.gekoppelt)}` };
  if (geraet.online) return { status: "ok", text: "online", zusatz: `seit ${datum(geraet.status_seit)}` };
  return { status: "fehler", text: "offline", zusatz: `seit ${datum(geraet.status_seit)} · zuletzt gesehen ${datum(geraet.zuletzt_gesehen)}` };
}

/** Seite „Geräte“: Mikrocontroller koppeln, ihre Werte ansehen und ihre Ausgänge schalten. */
export function Geraete() {
  const queryClient = useQueryClient();
  const daten = useGeraete();
  const katalog = useKatalog();
  const [hinzufuegen, setHinzufuegen] = useState(false);
  const [offen, setOffen] = useState<Offen | null>(null);

  const auffrischen = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: GERAETE }),
      queryClient.invalidateQueries({ queryKey: INTEGRATIONEN }),
      queryClient.invalidateQueries({ queryKey: KATALOG }),
    ]);
  const koppeln = useMutation({
    mutationFn: (geraet: Geraet) => api.post<Kopplung>(`/api/geraete/${geraet.id}/koppeln`),
    onSuccess: async (kopplung, geraet) => {
      setOffen({ art: "kopplung", geraet, kopplung });
      await auffrischen();
    },
  });
  const entfernen = useMutation({
    mutationFn: (geraet: Geraet) => api.del(`/api/integrationen/${geraet.id}`),
    onSuccess: async () => {
      setOffen(null);
      await auffrischen();
    },
  });

  if (daten.isPending) return <Lade />;
  if (daten.isError) return <FehlerMeldung fehler={daten.error} />;
  const { broker, geraete } = daten.data;
  const karte = katalog.data?.eintraege.find((eintrag) => eintrag.id === "geraet");
  const knopfHinzufuegen = (
    <Knopf art="haupt" disabled={!broker.verbunden || !karte} onClick={() => setHinzufuegen(true)}>
      <Plus aria-hidden />
      Gerät hinzufügen
    </Knopf>
  );

  return (
    <div className="stapel">
      {!broker.eingerichtet ? (
        <Meldung art="warn" hinweis="In der Datei .env muss COMPOSE_PROFILES=geraete stehen; danach ./scripts/install.sh ausführen.">
          Der MQTT-Broker für Geräte ist nicht eingerichtet.
        </Meldung>
      ) : (
        !broker.verbunden && (
          <Meldung art="warn" hinweis="Prüfen mit: docker compose -p missa-control ps – starten mit: ./scripts/install.sh">
            {broker.meldung}
          </Meldung>
        )
      )}

      <div className="reihe zwischen">
        <p className="gedaempft fuellen" style={{ flexBasis: "22rem" }}>
          Geräte verbinden sich über den eigenen MQTT-Broker (Port {broker.port}) und sagen selbst, was sie können. Daraus
          werden Funktionen für Missa und Auslöser für Regeln.
        </p>
        {geraete.length > 0 && knopfHinzufuegen}
      </div>

      {geraete.length === 0 && (
        <div className="karte leer">
          <Cpu aria-hidden />
          <h2>Noch kein Gerät</h2>
          <p>
            Ein ESP32 oder Raspberry Pi Pico wird in drei Schritten angebunden: hinzufügen, Konfiguration herunterladen,
            aufs Gerät kopieren. Die Beispiel-Firmware dazu liegt im Repo unter <code>examples/geraete</code>.
          </p>
          {knopfHinzufuegen}
        </div>
      )}

      {geraete.map((geraet) => (
        <GeraetKarte key={geraet.id} geraet={geraet} onOeffnen={setOffen} />
      ))}

      {hinzufuegen && karte && (
        <Assistent
          eintrag={karte}
          onSchliessen={() => {
            setHinzufuegen(false);
            void auffrischen();
          }}
        />
      )}
      {offen?.art === "koppeln" && (
        <Bestaetigung
          titel="Gerät neu koppeln?"
          text={
            <p>
              „{offen.geraet.name}“ bekommt neue Zugangsdaten. Die bisherigen gelten sofort nicht mehr – das Gerät verbindet
              sich erst wieder, wenn es die neue Konfiguration bekommen hat.
            </p>
          }
          knopf="Neu koppeln"
          laeuft={koppeln.isPending}
          fehler={<FehlerMeldung fehler={koppeln.error} />}
          onBestaetigen={() => koppeln.mutate(offen.geraet)}
          onAbbrechen={() => {
            koppeln.reset();
            setOffen(null);
          }}
        />
      )}
      {offen?.art === "kopplung" && (
        <Dialog titel={`Neue Zugangsdaten für „${offen.geraet.name}“`} onSchliessen={() => setOffen(null)} breit>
          <KopplungsDaten name={offen.geraet.name} kopplung={offen.kopplung} />
          <div className="dialog-fuss">
            <Knopf art="haupt" onClick={() => setOffen(null)}>
              Fertig
            </Knopf>
          </div>
        </Dialog>
      )}
      {offen?.art === "entfernen" && (
        <Bestaetigung
          titel="Gerät entfernen?"
          text={
            <p>
              „{offen.geraet.name}“ wird entfernt: Sein Zugang zum MQTT-Broker gilt sofort nicht mehr, seine Funktionen
              und sein Verlauf verschwinden. Regeln, die sich auf das Gerät beziehen, lösen nicht mehr aus.
            </p>
          }
          knopf="Entfernen"
          laeuft={entfernen.isPending}
          fehler={<FehlerMeldung fehler={entfernen.error} />}
          onBestaetigen={() => entfernen.mutate(offen.geraet)}
          onAbbrechen={() => {
            entfernen.reset();
            setOffen(null);
          }}
        />
      )}
    </div>
  );
}

function GeraetKarte({ geraet, onOeffnen }: { geraet: Geraet; onOeffnen: (offen: Offen) => void }) {
  const { status, text, zusatz } = zustand(geraet);
  return (
    <section className="karte stapel eng" aria-label={geraet.name}>
      <div className="integration-kopf">
        <span className="symbol" aria-hidden>
          <Cpu />
        </span>
        <div className="fuellen">
          <div className="reihe" style={{ gap: "0.5rem" }}>
            <h2>{geraet.name}</h2>
            <StatusMarke status={status}>{text}</StatusMarke>
          </div>
          <div className="gedaempft klein">
            {zusatz}
            {geraet.firmware && ` · Firmware ${geraet.firmware}`}
          </div>
        </div>
        <Knopf klein onClick={() => onOeffnen({ art: "koppeln", geraet })}>
          <KeyRound aria-hidden />
          Neu koppeln
        </Knopf>
        <Knopf klein art="gefahr" aria-label={`${geraet.name} entfernen`} onClick={() => onOeffnen({ art: "entfernen", geraet })}>
          <Trash2 aria-hidden />
        </Knopf>
      </div>

      {geraet.zugang_fehlt && (
        <Meldung art="fehler" hinweis="Mit „Neu koppeln“ bekommt das Gerät neue Zugangsdaten.">
          Der Zugang dieses Geräts am MQTT-Broker fehlt – es kann sich nicht verbinden.
        </Meldung>
      )}
      {geraet.problem && <Meldung art="warn">{geraet.problem}</Meldung>}
      {geraet.aktiv && geraet.status_seit === null && !geraet.zugang_fehlt && (
        <p className="gedaempft">
          Das Gerät hat sich noch nicht gemeldet. Sobald es mit der Konfiguration aus dem Panel startet, erscheint es hier als
          online. Ist die Konfiguration verloren gegangen, hilft „Neu koppeln“.
        </p>
      )}

      {geraet.faehigkeiten.length > 0 && (
        <>
          <ul className="faehigkeiten">
            {geraet.faehigkeiten.map((faehigkeit) => (
              <FaehigkeitZeile key={faehigkeit.id} geraet={geraet} faehigkeit={faehigkeit} />
            ))}
          </ul>
          <p className="gedaempft klein">
            Was Missa damit darf, legst du unter <Link to="/integrationen">Integrationen</Link> fest. Knöpfe und „offline“
            können unter <Link to="/regeln">Regeln</Link> etwas auslösen.
          </p>
        </>
      )}
    </section>
  );
}

function FaehigkeitZeile({ geraet, faehigkeit }: { geraet: Geraet; faehigkeit: Faehigkeit }) {
  const [verlauf, setVerlauf] = useState(false);
  const mitVerlauf = faehigkeit.art === "sensor" && faehigkeit.typ !== "text";
  const recht = RECHTE.find((eintrag) => eintrag.wert === faehigkeit.recht)?.name;
  return (
    <li className="faehigkeit">
      <div className="faehigkeit-zeile">
        <div className="fuellen">
          <div className="reihe" style={{ gap: "0.5rem" }}>
            <strong>{faehigkeit.name}</strong>
            <span className="etikett">{ART_NAME[faehigkeit.art]}</span>
          </div>
          <div className="gedaempft klein">
            {faehigkeit.funktion ? (
              <>
                Für Missa: <code>{faehigkeit.funktion}</code>
                {recht && ` · ${recht}`}
              </>
            ) : (
              "Jeder Druck wird zum Ereignis für Missa."
            )}
          </div>
        </div>
        <div className="faehigkeit-wert">
          <div className="wert">{faehigkeit.art === "knopf" ? (faehigkeit.zeit ? "gedrückt" : "–") : wertText(faehigkeit, faehigkeit.wert)}</div>
          <div className="gedaempft klein">{faehigkeit.zeit ? datum(faehigkeit.zeit) : "noch nichts gemeldet"}</div>
        </div>
        {mitVerlauf && (
          <Knopf klein aria-expanded={verlauf} aria-label={`Verlauf von ${faehigkeit.name}`} onClick={() => setVerlauf(!verlauf)}>
            <ChartLine aria-hidden />
            Verlauf
          </Knopf>
        )}
      </div>
      {faehigkeit.art === "aktor" && faehigkeit.funktion_name && <Steuerung geraet={geraet} faehigkeit={faehigkeit} />}
      {mitVerlauf && verlauf && <Verlauf geraet={geraet} faehigkeit={faehigkeit} />}
    </li>
  );
}

type Antwort = { ok: true; ergebnis: string } | { ok: false; meldung?: string; hinweis?: string | null; ergebnis?: string };

/** Einen Ausgang des Geräts vom Panel aus schalten (unabhängig davon, was Missa darf). */
function Steuerung({ geraet, faehigkeit }: { geraet: Geraet; faehigkeit: Faehigkeit }) {
  const queryClient = useQueryClient();
  const [eingabe, setEingabe] = useState("");
  const senden = useMutation({
    mutationFn: (argumente: Record<string, unknown>) =>
      api.post<Antwort>(`/api/integrationen/${geraet.id}/aufrufen`, { funktion: faehigkeit.funktion_name, argumente }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: GERAETE }),
  });
  const gesperrt = !geraet.online || senden.isPending;
  const grund = geraet.online ? undefined : "Das Gerät ist offline.";

  return (
    <div className="stapel eng">
      {faehigkeit.typ === "schalter" ? (
        <div className="reihe" role="group" aria-label={`${faehigkeit.name} schalten`}>
          <Knopf klein disabled={gesperrt} title={grund} aria-pressed={faehigkeit.wert === 1} onClick={() => senden.mutate({ an: true })}>
            Einschalten
          </Knopf>
          <Knopf klein disabled={gesperrt} title={grund} aria-pressed={faehigkeit.wert === 0} onClick={() => senden.mutate({ an: false })}>
            Ausschalten
          </Knopf>
        </div>
      ) : (
        <form
          className="reihe"
          onSubmit={(ereignis: FormEvent) => {
            ereignis.preventDefault();
            senden.mutate(faehigkeit.typ === "zahl" ? { wert: Number(eingabe.replace(",", ".")) } : { text: eingabe });
          }}
        >
          <input
            type={faehigkeit.typ === "zahl" ? "number" : "text"}
            step="any"
            min={faehigkeit.min}
            max={faehigkeit.max}
            required
            style={{ width: "12rem" }}
            aria-label={faehigkeit.typ === "zahl" ? `Neuer Wert für ${faehigkeit.name}` : `Text für ${faehigkeit.name}`}
            value={eingabe}
            onChange={(e) => setEingabe(e.target.value)}
          />
          <Knopf klein type="submit" disabled={gesperrt} title={grund}>
            {faehigkeit.typ === "zahl" ? "Setzen" : "Senden"}
          </Knopf>
        </form>
      )}
      <FehlerMeldung fehler={senden.error} />
      {senden.data &&
        (senden.data.ok ? (
          <p className="gedaempft klein" role="status">
            {senden.data.ergebnis}
          </p>
        ) : (
          <Meldung art="fehler" hinweis={senden.data.hinweis ?? undefined}>
            {senden.data.meldung ?? senden.data.ergebnis ?? "Das hat nicht geklappt."}
          </Meldung>
        ))}
    </div>
  );
}

/** Abstand, in dem das Gerät üblicherweise misst (Median) – daran wird erkannt, wo eine echte Lücke ist. */
function ueblicherAbstand(zeiten: number[]): number {
  const abstaende = zeiten.slice(1).map((zeit, index) => zeit - zeiten[index]).sort((a, b) => a - b);
  return abstaende.length > 0 ? abstaende[Math.floor(abstaende.length / 2)] : 0;
}

function Verlauf({ geraet, faehigkeit }: { geraet: Geraet; faehigkeit: Faehigkeit }) {
  const [zeitraum, setZeitraum] = useState<Zeitraum>("7t");
  const [tabelle, setTabelle] = useState(false);
  const [zeiger, setZeiger] = useState<number | null>(null);
  const daten = useVerlauf(geraet.id, faehigkeit.id, zeitraum);

  if (daten.isPending) return <Lade />;
  if (daten.isError) return <FehlerMeldung fehler={daten.error} />;
  const auswahl = ZEITRAEUME.find((eintrag) => eintrag.wert === daten.data.zeitraum) ?? ZEITRAEUME[2];
  const punkte = daten.data.verlauf.map((punkt) => ({ t: new Date(punkt.zeit).getTime(), w: punkt.wert }));
  const bis = daten.dataUpdatedAt;

  return (
    <div className={daten.isPlaceholderData ? "viz wartet stapel eng" : "viz stapel eng"}>
      <div className="reihe zwischen">
        <div className="auswahl" role="radiogroup" aria-label={`Zeitraum für ${faehigkeit.name}`}>
          {ZEITRAEUME.map((eintrag) => (
            <button key={eintrag.wert} type="button" role="radio" aria-checked={zeitraum === eintrag.wert} onClick={() => setZeitraum(eintrag.wert)}>
              {eintrag.titel}
            </button>
          ))}
        </div>
        <Knopf klein aria-pressed={tabelle} onClick={() => setTabelle(!tabelle)}>
          <Table2 aria-hidden />
          {tabelle ? "Als Diagramm anzeigen" : "Als Tabelle anzeigen"}
        </Knopf>
      </div>
      {tabelle ? (
        <div className="tabelle-huelle verlauf-tabelle">
          <table className="tabelle zahlen">
            <thead>
              <tr>
                <th>Zeit</th>
                <th>{faehigkeit.name}</th>
              </tr>
            </thead>
            <tbody>
              {[...daten.data.verlauf].reverse().map((punkt) => (
                <tr key={punkt.zeit}>
                  <td>{datum(punkt.zeit)}</td>
                  <td>{wertText(faehigkeit, punkt.wert)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {punkte.length === 0 && <p className="leer">Noch keine Messwerte in diesem Zeitraum.</p>}
        </div>
      ) : (
        <Liniendiagramm
          titel={faehigkeit.name}
          einheit={faehigkeit.einheit}
          punkte={punkte}
          von={bis - auswahl.ms}
          bis={bis}
          angepasst={faehigkeit.typ !== "schalter"}
          max={faehigkeit.typ === "schalter" ? 1 : undefined}
          wertText={(wert) => wertText(faehigkeit, faehigkeit.typ === "schalter" ? Math.round(wert) : wert)}
          rasterMs={Math.max(auswahl.rasterMs, ueblicherAbstand(punkte.map((punkt) => punkt.t)))}
          zeiger={zeiger}
          onZeiger={setZeiger}
        />
      )}
      <p className="gedaempft klein">
        Gespeichert wird höchstens ein Wert pro halbe Minute, für 7 Tage. Für 24 Stunden und 7 Tage zeigt der Verlauf
        Mittelwerte.
      </p>
    </div>
  );
}
