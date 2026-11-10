import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ScrollText, Send } from "lucide-react";
import { useState } from "react";

import { api } from "../api";
import { datum } from "../ui/format";
import { FehlerMeldung, Knopf, Lade, type Status, StatusMarke } from "../ui/ui";

interface Aufruf {
  id: number;
  zeit: string;
  quelle: string;
  client: string;
  integration: string;
  funktion: string;
  ok: boolean;
  fehler: string;
  dauer_ms: number;
  freigabe: string;
}

interface Aufrufe {
  anzahl: number;
  eintraege: Aufruf[];
  clients: string[];
  integrationen: string[];
}

export interface Ereignis {
  id: number;
  zeit: string;
  art: string;
  quelle: string;
  titel: string;
  nachricht: string;
  dringlichkeit: "niedrig" | "normal" | "hoch" | "dringend";
  daten: Record<string, unknown>;
}

const SEITE = 100;
const DRINGLICHKEIT: Record<Ereignis["dringlichkeit"], Status> = { niedrig: "grau", normal: "ok", hoch: "warn", dringend: "fehler" };

function dauer(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;
}

/** Seite „Protokoll“: alle Funktionsaufrufe und alle Ereignisse. */
export function Protokoll() {
  const [reiter, setReiter] = useState<"aufrufe" | "ereignisse">("aufrufe");
  return (
    <div className="stapel">
      <div className="reiter" role="tablist">
        <button type="button" role="tab" aria-selected={reiter === "aufrufe"} onClick={() => setReiter("aufrufe")}>
          Aufrufe
        </button>
        <button type="button" role="tab" aria-selected={reiter === "ereignisse"} onClick={() => setReiter("ereignisse")}>
          Ereignisse
        </button>
      </div>
      {reiter === "aufrufe" ? <AufrufListe /> : <EreignisListe />}
    </div>
  );
}

function AufrufListe() {
  const [filter, setFilter] = useState({ client: "", integration: "", ergebnis: "", suche: "" });
  const [limit, setLimit] = useState(SEITE);
  const setze = (teil: Partial<typeof filter>) => {
    setFilter({ ...filter, ...teil });
    setLimit(SEITE);
  };

  const parameter = new URLSearchParams({ limit: String(limit) });
  for (const [name, wert] of Object.entries(filter)) if (wert) parameter.set(name, wert);
  const aufrufe = useQuery({
    queryKey: ["protokoll", filter, limit],
    queryFn: () => api.get<Aufrufe>(`/api/protokoll?${parameter}`),
    placeholderData: keepPreviousData,
    refetchInterval: 10_000,
  });

  if (aufrufe.isPending) return <Lade />;
  if (aufrufe.isError) return <FehlerMeldung fehler={aufrufe.error} />;
  const { anzahl, eintraege, clients, integrationen } = aufrufe.data;

  return (
    <>
      <p className="gedaempft">
        Wer hat wann welche Funktion aufgerufen. Parameter und Ergebnisse werden nicht gespeichert, Einträge nach 30
        Tagen gelöscht.
      </p>
      <div className="reihe">
        <select aria-label="Client" value={filter.client} onChange={(e) => setze({ client: e.target.value })} style={{ width: "auto" }}>
          <option value="">Alle Clients</option>
          {clients.map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
        <select aria-label="Integration" value={filter.integration} onChange={(e) => setze({ integration: e.target.value })} style={{ width: "auto" }}>
          <option value="">Alle Integrationen</option>
          {integrationen.map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
        <select aria-label="Ergebnis" value={filter.ergebnis} onChange={(e) => setze({ ergebnis: e.target.value })} style={{ width: "auto" }}>
          <option value="">Alle Ergebnisse</option>
          <option value="ok">Nur erfolgreiche</option>
          <option value="fehler">Nur Fehler</option>
        </select>
        <input type="search" className="fuellen" style={{ width: "auto" }} placeholder="Funktion oder Fehlertext suchen …" aria-label="Suche" value={filter.suche} onChange={(e) => setze({ suche: e.target.value })} />
      </div>

      {eintraege.length === 0 ? (
        <div className="karte leer">
          <ScrollText aria-hidden />
          <h2>Keine Einträge</h2>
          <p>{anzahl === 0 && !Object.values(filter).some(Boolean) ? "Noch hat niemand eine Funktion aufgerufen." : "Zu diesem Filter gibt es keine Einträge."}</p>
        </div>
      ) : (
        <div className="karte ohne-rand tabelle-huelle">
          <table className="tabelle">
            <thead>
              <tr>
                <th>Zeit</th>
                <th>Client</th>
                <th>Funktion</th>
                <th>Ergebnis</th>
                <th>Dauer</th>
              </tr>
            </thead>
            <tbody>
              {eintraege.map((aufruf) => (
                <tr key={aufruf.id}>
                  <td className="gedaempft klein">{datum(aufruf.zeit)}</td>
                  <td>{aufruf.client || aufruf.quelle}</td>
                  <td>
                    <span className="mono">{aufruf.funktion}</span>
                    {aufruf.fehler && <div className="gedaempft klein">{aufruf.fehler}</div>}
                  </td>
                  <td>
                    <StatusMarke status={aufruf.ok ? "ok" : "fehler"}>{aufruf.ok ? "ok" : "Fehler"}</StatusMarke>
                    {aufruf.freigabe !== "ohne" && <div className="gedaempft klein">Freigabe: {aufruf.freigabe}</div>}
                  </td>
                  <td className="gedaempft klein">{dauer(aufruf.dauer_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="reihe zwischen">
        <span className="gedaempft klein">
          {eintraege.length} von {anzahl} Einträgen
        </span>
        {eintraege.length < anzahl && <Knopf onClick={() => setLimit(limit + SEITE)}>Mehr laden</Knopf>}
      </div>
    </>
  );
}

function EreignisListe() {
  const queryClient = useQueryClient();
  const ereignisse = useQuery({
    queryKey: ["ereignisse"],
    queryFn: () => api.get<Ereignis[]>("/api/ereignisse"),
    refetchInterval: 5000,
  });
  const testen = useMutation({
    mutationFn: () => api.post<Ereignis>("/api/ereignisse/test", {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ereignisse"] }),
  });

  if (ereignisse.isPending) return <Lade />;
  if (ereignisse.isError) return <FehlerMeldung fehler={ereignisse.error} />;

  return (
    <>
      <div className="reihe zwischen">
        <p className="gedaempft fuellen">
          Ereignisse holt Missa selbst ab: ausgelöste Regeln, Meldungen von Geräten, eingegangene Webhooks, ausgefallene
          Integrationen. Mit einem Test-Ereignis lässt sich die Anbindung prüfen.
        </p>
        <Knopf onClick={() => testen.mutate()} disabled={testen.isPending}>
          <Send aria-hidden />
          Test-Ereignis senden
        </Knopf>
      </div>
      <FehlerMeldung fehler={testen.error} />
      {ereignisse.data.length === 0 ? (
        <div className="karte leer">
          <ScrollText aria-hidden />
          <h2>Noch keine Ereignisse</h2>
        </div>
      ) : (
        <div className="karte ohne-rand tabelle-huelle">
          <table className="tabelle">
            <thead>
              <tr>
                <th>Zeit</th>
                <th>Art</th>
                <th>Ereignis</th>
                <th>Dringlichkeit</th>
              </tr>
            </thead>
            <tbody>
              {ereignisse.data.map((ereignis) => (
                <tr key={ereignis.id}>
                  <td className="gedaempft klein">{datum(ereignis.zeit)}</td>
                  <td>
                    <span className="etikett">{ereignis.art}</span>
                  </td>
                  <td>
                    <strong>{ereignis.titel}</strong>
                    {ereignis.nachricht && <div className="gedaempft klein">{ereignis.nachricht}</div>}
                  </td>
                  <td>
                    <StatusMarke status={DRINGLICHKEIT[ereignis.dringlichkeit] ?? "grau"}>{ereignis.dringlichkeit}</StatusMarke>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
