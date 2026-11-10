import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleCheck } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link } from "react-router";

import { api } from "../api";
import { Dialog } from "../ui/Dialog";
import { FehlerMeldung, Feld, Knopf, Meldung } from "../ui/ui";
import { Formular } from "./Formular";
import { RechteListe } from "./RechteListe";
import { WebhookAdresse } from "./WebhookAdresse";
import {
  type Integration,
  INTEGRATIONEN,
  KATALOG,
  type KatalogEintrag,
  type Konfig,
  type Recht,
  standardwerte,
  type TestErgebnis,
} from "./typen";

type Erfolg = Extract<TestErgebnis, { ok: true }>;

/**
 * Der Assistent: Formular ausfüllen → Verbindung testen → Rechte prüfen → aktivieren.
 * Zusammen mit der Wahl der Karte im Katalog sind das höchstens drei Schritte.
 */
export function Assistent({ eintrag, onSchliessen }: { eintrag: KatalogEintrag; onSchliessen: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(eintrag.name);
  const [werte, setWerte] = useState<Konfig>(() => standardwerte(eintrag.felder));
  const [test, setTest] = useState<Erfolg | null>(null);
  const [rechte, setRechte] = useState<Record<string, Recht>>({});
  const [fertig, setFertig] = useState<Integration | null>(null);

  const vorTest = eintrag.felder.filter((feld) => !feld.nach_test);
  const nachTest = eintrag.felder.filter((feld) => feld.nach_test);

  const testen = useMutation({
    mutationFn: () => api.post<TestErgebnis>("/api/integrationen/testen", { manifest_id: eintrag.id, konfig: werte }),
    onSuccess: (ergebnis) => {
      if (!ergebnis.ok) return;
      setTest(ergebnis);
      setRechte(Object.fromEntries(ergebnis.funktionen.map((funktion) => [funktion.name, funktion.recht])));
      // Auswahlfelder, die erst der Test füllt (z. B. die gefundenen Kalender): die erste Möglichkeit vorschlagen.
      const vorschlaege = Object.fromEntries(
        nachTest
          .filter((feld) => feld.typ === "auswahl" && !werte[feld.name] && ergebnis.optionen[feld.name]?.length)
          .map((feld) => [feld.name, ergebnis.optionen[feld.name][0].wert]),
      );
      if (Object.keys(vorschlaege).length > 0) setWerte({ ...werte, ...vorschlaege });
    },
  });
  const aktivieren = useMutation({
    mutationFn: () =>
      api.post<Integration>("/api/integrationen", {
        manifest_id: eintrag.id,
        name,
        konfig: werte,
        rechte,
        test_id: test?.test_id,
      }),
    onSuccess: async (integration) => {
      setFertig(integration);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: INTEGRATIONEN }),
        queryClient.invalidateQueries({ queryKey: KATALOG }),
      ]);
    },
  });

  const schritt = fertig ? 3 : test ? 2 : 1;
  const fehlgeschlagen = testen.data && !testen.data.ok ? testen.data : null;
  const sichtbar = Object.values(rechte).filter((recht) => recht !== "gesperrt").length;

  return (
    <Dialog titel={`${eintrag.symbol} ${eintrag.name} einrichten`} onSchliessen={onSchliessen} breit>
      <ol className="schritte" aria-label="Fortschritt">
        <li className={schritt === 1 ? "aktiv" : "fertig"}>1 · Formular</li>
        <li className={schritt === 2 ? "aktiv" : schritt > 2 ? "fertig" : ""}>2 · Testen und Rechte</li>
        <li className={schritt === 3 ? "fertig" : ""}>3 · Aktiv</li>
      </ol>

      {schritt === 1 && (
        <form
          className="stapel"
          onSubmit={(ereignis: FormEvent) => {
            ereignis.preventDefault();
            testen.mutate();
          }}
        >
          {eintrag.hinweis && <p className="gedaempft">{eintrag.hinweis}</p>}
          <Feld titel="Name" fuer="assistent-name" hilfe="So heisst die Integration im Panel. Daraus entsteht auch die Vorsilbe der Funktionsnamen.">
            <input id="assistent-name" type="text" required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
          </Feld>
          <Formular felder={vorTest} werte={werte} onAendern={setWerte} zugangName={name} />
          {fehlgeschlagen && (
            <Meldung art="fehler" hinweis={fehlgeschlagen.hinweis ?? undefined}>
              {fehlgeschlagen.meldung}
            </Meldung>
          )}
          <FehlerMeldung fehler={testen.error} />
          <div className="dialog-fuss">
            <Knopf onClick={onSchliessen}>Abbrechen</Knopf>
            <Knopf art="haupt" type="submit" disabled={testen.isPending}>
              {testen.isPending ? "Teste Verbindung …" : "Verbindung testen"}
            </Knopf>
          </div>
        </form>
      )}

      {schritt === 2 && test && (
        <form
          className="stapel"
          onSubmit={(ereignis: FormEvent) => {
            ereignis.preventDefault();
            aktivieren.mutate();
          }}
        >
          <Meldung art="ok" hinweis={test.details.join(" · ") || undefined}>
            {test.meldung}
          </Meldung>
          {nachTest.length > 0 && (
            <Formular felder={nachTest} werte={werte} onAendern={setWerte} optionen={test.optionen} />
          )}
          {test.funktionen.length > 0 ? (
            <div className="stapel eng">
              <h3>Was darf Missa?</h3>
              <p className="gedaempft klein">
                {test.viele_funktionen
                  ? "Diese API hat sehr viele Funktionen. Zunächst ist alles gesperrt – wähle aus, was Missa sehen darf."
                  : "Vorschlag: Lesende Funktionen sind erlaubt, schreibende fragen erst nach. Gesperrte sieht Missa gar nicht."}
              </p>
              <RechteListe funktionen={test.funktionen} rechte={rechte} onAendern={setRechte} />
            </div>
          ) : (
            eintrag.art === "webhook" && (
              <p className="gedaempft">
                Ein Webhook hat keine Funktionen für Missa: Was er empfängt, wird zum Ereignis und kann Regeln auslösen.
              </p>
            )
          )}
          <FehlerMeldung fehler={aktivieren.error} />
          <div className="dialog-fuss">
            <Knopf
              onClick={() => {
                setTest(null);
                testen.reset();
                aktivieren.reset();
              }}
            >
              Zurück
            </Knopf>
            <Knopf art="haupt" type="submit" disabled={aktivieren.isPending}>
              {aktivieren.isPending ? "Aktiviere …" : "Aktivieren"}
            </Knopf>
          </div>
        </form>
      )}

      {fertig && (
        <div className="stapel">
          <div className="leer">
            <CircleCheck aria-hidden style={{ color: "var(--ok)" }} />
            <h2>„{fertig.name}“ ist aktiv</h2>
            {fertig.webhook ? (
              <p>Meldungen an die geheime Adresse werden ab jetzt zu Ereignissen für Missa.</p>
            ) : (
              <p>
                Missa kann jetzt {sichtbar} Funktion{sichtbar === 1 ? "" : "en"} nutzen.
              </p>
            )}
          </div>
          {fertig.webhook?.pfad && <WebhookAdresse pfad={fertig.webhook.pfad} />}
          <div className="dialog-fuss">
            <Link className="knopf" to="/integrationen" onClick={onSchliessen}>
              Zu den Integrationen
            </Link>
            <Knopf art="haupt" onClick={onSchliessen}>
              Fertig
            </Knopf>
          </div>
        </div>
      )}
    </Dialog>
  );
}
