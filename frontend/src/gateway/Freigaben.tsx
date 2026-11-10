import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ShieldCheck, X } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../api";
import { datum } from "../ui/format";
import { FehlerMeldung, Knopf, Lade, type Status, StatusMarke } from "../ui/ui";
import { type Freigabe, FREIGABEN, FREIGABEN_ANZAHL, type FreigabenAntwort } from "./freigaben";

const STATUS: Record<Freigabe["status"], Status> = { offen: "warn", erlaubt: "ok", abgelehnt: "fehler", abgelaufen: "grau" };

function restzeit(freigabe: Freigabe, jetzt: number): string {
  const sekunden = Math.max(Math.round((new Date(freigabe.laeuft_ab).getTime() - jetzt) / 1000), 0);
  return `${Math.floor(sekunden / 60)}:${String(sekunden % 60).padStart(2, "0")}`;
}

function wertAlsText(wert: unknown): string {
  return typeof wert === "string" ? wert : JSON.stringify(wert, null, 2);
}

/** Seite „Freigaben“: angehaltene Aufrufe erlauben oder ablehnen. */
export function Freigaben() {
  const queryClient = useQueryClient();
  const freigaben = useQuery({
    queryKey: FREIGABEN,
    queryFn: () => api.get<FreigabenAntwort>("/api/freigaben"),
    refetchInterval: 3000,
  });
  const [jetzt, setJetzt] = useState(() => Date.now());
  useEffect(() => {
    const takt = window.setInterval(() => setJetzt(Date.now()), 1000);
    return () => window.clearInterval(takt);
  }, []);

  const entscheiden = useMutation({
    mutationFn: ({ id, erlauben }: { id: number; erlauben: boolean }) => api.post<Freigabe>(`/api/freigaben/${id}`, { erlauben }),
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: FREIGABEN }),
        queryClient.invalidateQueries({ queryKey: FREIGABEN_ANZAHL }),
      ]),
  });

  if (freigaben.isPending) return <Lade />;
  if (freigaben.isError) return <FehlerMeldung fehler={freigaben.error} />;
  const { offen, verlauf, frist_sekunden } = freigaben.data;

  return (
    <div className="stapel">
      <p className="gedaempft">
        Funktionen mit dem Recht „erst nachfragen“ laufen erst, wenn du hier zustimmst. Ohne Antwort innerhalb von{" "}
        {Math.round(frist_sekunden / 60)} Minuten wird der Aufruf abgelehnt.
      </p>
      <FehlerMeldung fehler={entscheiden.error} />

      {offen.length === 0 && (
        <div className="karte leer">
          <ShieldCheck aria-hidden />
          <h2>Nichts zu entscheiden</h2>
          <p>Sobald Missa etwas tun möchte, das eine Freigabe braucht, erscheint es hier.</p>
        </div>
      )}

      {offen.map((freigabe) => (
        <section className="karte stapel eng freigabe" key={freigabe.id} aria-label={`Freigabe für ${freigabe.funktion}`}>
          <div className="reihe zwischen">
            <div>
              <div className="gedaempft klein">
                „{freigabe.client}“ möchte über „{freigabe.integration}“ ausführen:
              </div>
              <h2 className="mono">{freigabe.funktion}</h2>
              <div className="gedaempft">{freigabe.beschreibung}</div>
            </div>
            <StatusMarke status="warn">wartet noch {restzeit(freigabe, jetzt)}</StatusMarke>
          </div>
          {freigabe.vorschau && <p className="vorschau">{freigabe.vorschau}</p>}
          {Object.keys(freigabe.argumente).length > 0 ? (
            <dl className="argumente">
              {Object.entries(freigabe.argumente).map(([name, wert]) => (
                <div key={name}>
                  <dt>{name}</dt>
                  <dd>{wertAlsText(wert)}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="gedaempft klein">Ohne Parameter.</p>
          )}
          <div className="dialog-fuss">
            <Knopf art="gefahr" onClick={() => entscheiden.mutate({ id: freigabe.id, erlauben: false })} disabled={entscheiden.isPending}>
              <X aria-hidden />
              Ablehnen
            </Knopf>
            <Knopf art="haupt" onClick={() => entscheiden.mutate({ id: freigabe.id, erlauben: true })} disabled={entscheiden.isPending}>
              <Check aria-hidden />
              Erlauben
            </Knopf>
          </div>
        </section>
      ))}

      {verlauf.length > 0 && (
        <>
          <h2>Verlauf</h2>
          <div className="karte ohne-rand tabelle-huelle">
            <table className="tabelle">
              <thead>
                <tr>
                  <th>Zeit</th>
                  <th>Client</th>
                  <th>Funktion</th>
                  <th>Entscheidung</th>
                </tr>
              </thead>
              <tbody>
                {verlauf.map((freigabe) => (
                  <tr key={freigabe.id}>
                    <td className="gedaempft klein">{datum(freigabe.erstellt)}</td>
                    <td>{freigabe.client}</td>
                    <td className="mono">{freigabe.funktion}</td>
                    <td>
                      <StatusMarke status={STATUS[freigabe.status]}>{freigabe.status}</StatusMarke>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
