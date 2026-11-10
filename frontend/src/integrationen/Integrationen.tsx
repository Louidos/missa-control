import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Pencil, Play, Plug, Plus, RefreshCw, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link } from "react-router";

import { api } from "../api";
import { Bestaetigung, Dialog } from "../ui/Dialog";
import { datum } from "../ui/format";
import { FehlerMeldung, Feld, Knopf, Lade, Meldung, type Status, StatusMarke } from "../ui/ui";
import { Formular } from "./Formular";
import { RechteListe } from "./RechteListe";
import { type Funktion, type Integration, INTEGRATIONEN, KATALOG, type Konfig, type Recht, type TestErgebnis, useIntegrationen } from "./typen";

type Offen =
  | { art: "bearbeiten"; integration: Integration }
  | { art: "entfernen"; integration: Integration }
  | { art: "ausprobieren"; integration: Integration; funktion: Funktion }
  | null;

function statusVon(integration: Integration): { status: Status; text: string } {
  if (!integration.aktiv) return { status: "grau", text: "deaktiviert" };
  if (integration.status === "fehler") return { status: "fehler", text: "Fehler" };
  if (integration.status === "ok") return { status: "ok", text: "in Ordnung" };
  return { status: "grau", text: "ungetestet" };
}

/** Seite „Integrationen“: alles Eingerichtete verwalten. */
export function Integrationen() {
  const queryClient = useQueryClient();
  const integrationen = useIntegrationen();
  const [aufgeklappt, setAufgeklappt] = useState<Set<number>>(new Set());
  const [offen, setOffen] = useState<Offen>(null);

  const uebernehmen = (neu: Integration) =>
    queryClient.setQueryData<Integration[]>(INTEGRATIONEN, (alt) => alt?.map((i) => (i.id === neu.id ? neu : i)));

  const aendern = useMutation({
    mutationFn: ({ id, ...daten }: { id: number; aktiv?: boolean; rechte?: Record<string, Recht> }) =>
      api.put<Integration>(`/api/integrationen/${id}`, daten),
    onSuccess: uebernehmen,
  });
  const testen = useMutation({
    mutationFn: (id: number) => api.post<Integration>(`/api/integrationen/${id}/testen`),
    onSuccess: uebernehmen,
  });
  const entfernen = useMutation({
    mutationFn: (integration: Integration) => api.del(`/api/integrationen/${integration.id}`),
    onSuccess: async () => {
      setOffen(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: INTEGRATIONEN }),
        queryClient.invalidateQueries({ queryKey: KATALOG }),
      ]);
    },
  });

  if (integrationen.isPending) return <Lade />;
  if (integrationen.isError) return <FehlerMeldung fehler={integrationen.error} />;

  const umklappen = (id: number) =>
    setAufgeklappt((alt) => {
      const neu = new Set(alt);
      if (!neu.delete(id)) neu.add(id);
      return neu;
    });

  return (
    <div className="stapel">
      <div className="reihe zwischen">
        <p className="gedaempft fuellen">Alle eingerichteten Integrationen: aktivieren, bearbeiten, testen, Rechte festlegen.</p>
        <Link className="knopf haupt" to="/katalog">
          <Plus aria-hidden />
          Integration hinzufügen
        </Link>
      </div>
      <FehlerMeldung fehler={aendern.error ?? testen.error} />

      {integrationen.data.length === 0 && (
        <div className="karte leer">
          <Plug aria-hidden />
          <h2>Noch keine Integrationen</h2>
          <p>
            Im <Link to="/katalog">Katalog</Link> lassen sich MCP-Server, REST-APIs und Vorlagen in drei Schritten einrichten.
          </p>
        </div>
      )}

      {integrationen.data.map((integration) => {
        const { status, text } = statusVon(integration);
        const istOffen = aufgeklappt.has(integration.id);
        const sichtbar = integration.funktionen.filter((f) => f.recht !== "gesperrt" && f.vorhanden).length;
        return (
          <section className="karte stapel eng" key={integration.id} aria-label={integration.name}>
            <div className="integration-kopf">
              <span className="symbol" aria-hidden>
                {integration.symbol}
              </span>
              <div className="fuellen">
                <div className="reihe" style={{ gap: "0.5rem" }}>
                  <h2>{integration.name}</h2>
                  <StatusMarke status={status}>{text}</StatusMarke>
                </div>
                <div className="gedaempft klein">
                  {integration.art_name} · {sichtbar} von {integration.funktionen.length} Funktionen für Missa sichtbar
                  {integration.geprueft && ` · geprüft ${datum(integration.geprueft)}`}
                </div>
              </div>
              <label className="schalter" title="Integration aktivieren oder deaktivieren">
                <input
                  type="checkbox"
                  checked={integration.aktiv}
                  aria-label={`${integration.name} aktiv`}
                  onChange={(e) => aendern.mutate({ id: integration.id, aktiv: e.target.checked })}
                />
                <span>aktiv</span>
              </label>
              <Knopf klein onClick={() => testen.mutate(integration.id)} disabled={testen.isPending && testen.variables === integration.id}>
                <RefreshCw aria-hidden />
                {testen.isPending && testen.variables === integration.id ? "Teste …" : "Testen"}
              </Knopf>
              <Knopf klein aria-label={`${integration.name} bearbeiten`} onClick={() => setOffen({ art: "bearbeiten", integration })} disabled={!integration.manifest}>
                <Pencil aria-hidden />
              </Knopf>
              <Knopf klein art="gefahr" aria-label={`${integration.name} entfernen`} onClick={() => setOffen({ art: "entfernen", integration })}>
                <Trash2 aria-hidden />
              </Knopf>
            </div>

            {integration.status === "fehler" && (
              <Meldung art="fehler" hinweis={integration.status_hinweis || undefined}>
                {integration.status_meldung}
              </Meldung>
            )}

            <button type="button" className="aufklapper" aria-expanded={istOffen} onClick={() => umklappen(integration.id)}>
              {istOffen ? <ChevronDown aria-hidden /> : <ChevronRight aria-hidden />}
              Funktionen und Rechte ({integration.funktionen.length})
            </button>
            {istOffen && (
              <RechteListe
                funktionen={integration.funktionen.map((f) => ({ ...f, anzeigeName: f.gateway_name }))}
                rechte={Object.fromEntries(integration.funktionen.map((f) => [f.name, f.recht]))}
                onAendern={(rechte) => aendern.mutate({ id: integration.id, rechte })}
                aktion={(funktion) => (
                  <Knopf
                    klein
                    art="still"
                    aria-label={`${funktion.name} ausprobieren`}
                    title="Ausprobieren"
                    onClick={() => setOffen({ art: "ausprobieren", integration, funktion: funktion as Funktion })}
                  >
                    <Play aria-hidden />
                  </Knopf>
                )}
              />
            )}
          </section>
        );
      })}

      {offen?.art === "bearbeiten" && (
        <Bearbeiten
          integration={offen.integration}
          onFertig={(neu) => {
            uebernehmen(neu);
            setOffen(null);
          }}
          onSchliessen={() => setOffen(null)}
        />
      )}
      {offen?.art === "ausprobieren" && (
        <Ausprobieren integration={offen.integration} funktion={offen.funktion} onSchliessen={() => setOffen(null)} />
      )}
      {offen?.art === "entfernen" && (
        <Bestaetigung
          titel="Integration entfernen?"
          text={
            <p>
              „{offen.integration.name}“ wird entfernt. Missa verliert damit {offen.integration.funktionen.length}{" "}
              Funktion(en). Zugänge bleiben erhalten.
            </p>
          }
          knopf="Entfernen"
          laeuft={entfernen.isPending}
          fehler={<FehlerMeldung fehler={entfernen.error} />}
          onBestaetigen={() => entfernen.mutate(offen.integration)}
          onAbbrechen={() => {
            entfernen.reset();
            setOffen(null);
          }}
        />
      )}
    </div>
  );
}

function Bearbeiten({
  integration,
  onFertig,
  onSchliessen,
}: {
  integration: Integration;
  onFertig: (integration: Integration) => void;
  onSchliessen: () => void;
}) {
  const felder = integration.manifest?.felder ?? [];
  const [name, setName] = useState(integration.name);
  const [werte, setWerte] = useState<Konfig>(integration.konfig);
  // Auswahlmöglichkeiten für Felder, die aus dem Verbindungstest kommen (z. B. Kalender).
  const [optionen, setOptionen] = useState<Record<string, { wert: string; titel: string }[]>>({});

  const optionenLaden = useMutation({
    mutationFn: () =>
      api.post<TestErgebnis>("/api/integrationen/testen", {
        manifest_id: integration.manifest_id,
        konfig: werte,
        integration_id: integration.id,
      }),
    onSuccess: (ergebnis) => ergebnis.ok && setOptionen(ergebnis.optionen),
  });
  const speichern = useMutation({
    mutationFn: () => api.put<Integration>(`/api/integrationen/${integration.id}`, { name, konfig: werte }),
    onSuccess: onFertig,
  });
  const brauchtOptionen = felder.some((feld) => feld.nach_test && feld.typ === "auswahl");

  return (
    <Dialog titel={`${integration.symbol} ${integration.name} bearbeiten`} onSchliessen={onSchliessen} breit>
      <form
        className="stapel"
        onSubmit={(ereignis: FormEvent) => {
          ereignis.preventDefault();
          speichern.mutate();
        }}
      >
        <Feld titel="Name" fuer="bearbeiten-name" hilfe={`Die Funktionsnamen behalten ihre Vorsilbe „${integration.kennung}“.`}>
          <input id="bearbeiten-name" type="text" required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
        </Feld>
        <Formular felder={felder} werte={werte} onAendern={setWerte} optionen={optionen} zugangName={name} />
        {brauchtOptionen && Object.keys(optionen).length === 0 && (
          <Knopf klein onClick={() => optionenLaden.mutate()} disabled={optionenLaden.isPending}>
            <RefreshCw aria-hidden />
            Auswahlmöglichkeiten laden
          </Knopf>
        )}
        <p className="gedaempft klein">Beim Speichern wird die Verbindung neu getestet; eingestellte Rechte bleiben erhalten.</p>
        <FehlerMeldung fehler={speichern.error ?? optionenLaden.error} />
        <div className="dialog-fuss">
          <Knopf onClick={onSchliessen}>Abbrechen</Knopf>
          <Knopf art="haupt" type="submit" disabled={speichern.isPending}>
            {speichern.isPending ? "Speichere und teste …" : "Speichern und testen"}
          </Knopf>
        </div>
      </form>
    </Dialog>
  );
}

type Antwort = { ok: true; ergebnis: string } | { ok: false; meldung?: string; hinweis?: string | null; ergebnis?: string };

function beispielArgumente(funktion: Funktion): string {
  const pflicht = funktion.parameter.required ?? [];
  return JSON.stringify(Object.fromEntries(pflicht.map((name) => [name, ""])), null, 2);
}

function Ausprobieren({ integration, funktion, onSchliessen }: { integration: Integration; funktion: Funktion; onSchliessen: () => void }) {
  const [eingabe, setEingabe] = useState(() => beispielArgumente(funktion));
  const [eingabeFehler, setEingabeFehler] = useState<string | null>(null);
  const aufruf = useMutation({
    mutationFn: (argumente: unknown) =>
      api.post<Antwort>(`/api/integrationen/${integration.id}/aufrufen`, { funktion: funktion.name, argumente }),
  });

  return (
    <Dialog titel={`${funktion.gateway_name} ausprobieren`} onSchliessen={onSchliessen} breit>
      <form
        className="stapel"
        onSubmit={(ereignis: FormEvent) => {
          ereignis.preventDefault();
          try {
            const argumente: unknown = JSON.parse(eingabe || "{}");
            setEingabeFehler(null);
            aufruf.mutate(argumente);
          } catch {
            setEingabeFehler("Die Parameter müssen gültiges JSON sein, z. B. {\"name\": \"Missa\"}.");
          }
        }}
      >
        <p className="gedaempft">{funktion.beschreibung}</p>
        <Meldung art="info">
          Der Aufruf wird wirklich ausgeführt{funktion.schreibend ? " – diese Funktion kann etwas verändern" : ""}. Die Rechte
          für Missa spielen hier keine Rolle.
        </Meldung>
        <Feld titel="Parameter (JSON)" fuer="ausprobieren-parameter" hilfe={`Erwartet: ${Object.keys(funktion.parameter.properties ?? {}).join(", ") || "keine Parameter"}`}>
          <textarea id="ausprobieren-parameter" className="mono" rows={5} value={eingabe} onChange={(e) => setEingabe(e.target.value)} />
        </Feld>
        {eingabeFehler && <Meldung art="warn">{eingabeFehler}</Meldung>}
        <FehlerMeldung fehler={aufruf.error} />
        {aufruf.data &&
          (aufruf.data.ok ? (
            <div className="stapel eng">
              <Meldung art="ok">Aufruf erfolgreich.</Meldung>
              <pre className="ergebnis">{aufruf.data.ergebnis}</pre>
            </div>
          ) : (
            <Meldung art="fehler" hinweis={aufruf.data.hinweis ?? undefined}>
              {aufruf.data.meldung ?? aufruf.data.ergebnis ?? "Der Aufruf ist fehlgeschlagen."}
            </Meldung>
          ))}
        <div className="dialog-fuss">
          <Knopf onClick={onSchliessen}>Schliessen</Knopf>
          <Knopf art="haupt" type="submit" disabled={aufruf.isPending}>
            <Play aria-hidden />
            {aufruf.isPending ? "Rufe auf …" : "Aufrufen"}
          </Knopf>
        </div>
      </form>
    </Dialog>
  );
}
