import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { api } from "../api";
import { Bestaetigung, Dialog } from "../ui/Dialog";
import { FehlerMeldung, Knopf, Lade, Meldung } from "../ui/ui";
import { datum } from "../ui/format";
import { ZugangFormular } from "./ZugangFormular";
import { useZugaenge, type Zugang, ZUGAENGE } from "./zugaenge";

type Offen = { art: "neu" } | { art: "bearbeiten"; zugang: Zugang } | { art: "loeschen"; zugang: Zugang } | null;

/** Seite „Zugänge“: API-Keys, Tokens und Passwörter – verschlüsselt gespeichert, nur maskiert sichtbar. */
export function Zugaenge() {
  const queryClient = useQueryClient();
  const zugaenge = useZugaenge();
  const [offen, setOffen] = useState<Offen>(null);

  const loeschen = useMutation({
    mutationFn: (zugang: Zugang) => api.del(`/api/zugaenge/${zugang.id}`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ZUGAENGE });
      setOffen(null);
    },
  });

  const schliessen = () => {
    loeschen.reset();
    setOffen(null);
  };

  return (
    <div className="stapel">
      <div className="reihe zwischen">
        <p className="gedaempft fuellen">
          API-Keys, Tokens und Passwörter für Integrationen. Die Werte werden verschlüsselt gespeichert und
          nach dem Speichern nie wieder im Klartext angezeigt – ändern geht, auslesen nicht.
        </p>
        <Knopf art="haupt" onClick={() => setOffen({ art: "neu" })}>
          <Plus aria-hidden />
          Neuer Zugang
        </Knopf>
      </div>

      <FehlerMeldung fehler={zugaenge.error} />
      {zugaenge.isPending && <Lade />}

      {zugaenge.data?.length === 0 && (
        <div className="karte leer">
          <KeyRound aria-hidden />
          <h2>Noch keine Zugänge</h2>
          <p>Lege hier Zugänge an – oder direkt beim Einrichten einer Integration.</p>
        </div>
      )}

      {zugaenge.data?.some((zugang) => !zugang.lesbar) && (
        <Meldung
          art="warn"
          hinweis="Wurde ENCRYPTION_KEY in der .env geändert? Mit dem ursprünglichen Schlüssel sind die Werte wieder lesbar – sonst bitte neu eintragen."
        >
          Mindestens ein Zugang lässt sich nicht mehr entschlüsseln.
        </Meldung>
      )}

      {!!zugaenge.data?.length && (
        <div className="karte ohne-rand tabelle-huelle">
          <table className="tabelle">
            <thead>
              <tr>
                <th>Name</th>
                <th>Typ</th>
                <th>Wert</th>
                <th>Notiz</th>
                <th>Geändert</th>
                <th>
                  <span className="sr-only">Aktionen</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {zugaenge.data.map((zugang) => (
                <tr key={zugang.id}>
                  <td>
                    <strong>{zugang.name}</strong>
                  </td>
                  <td>{zugang.typ_name}</td>
                  <td className="mono">
                    {zugang.benutzer && <span>{zugang.benutzer} · </span>}
                    {zugang.maske}
                  </td>
                  <td className="gedaempft">
                    {zugang.notiz}
                    {!!zugang.verwendet_von?.length && (
                      <div className="klein">Verwendet von: {zugang.verwendet_von.join(", ")}</div>
                    )}
                  </td>
                  <td className="gedaempft klein">{datum(zugang.geaendert)}</td>
                  <td className="aktionen">
                    <Knopf
                      art="still"
                      aria-label={`${zugang.name} bearbeiten`}
                      onClick={() => setOffen({ art: "bearbeiten", zugang })}
                    >
                      <Pencil aria-hidden />
                    </Knopf>
                    <Knopf
                      art="still"
                      aria-label={`${zugang.name} löschen`}
                      onClick={() => setOffen({ art: "loeschen", zugang })}
                    >
                      <Trash2 aria-hidden />
                    </Knopf>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {offen?.art === "neu" && (
        <Dialog titel="Neuer Zugang" onSchliessen={schliessen}>
          <ZugangFormular onFertig={schliessen} onAbbrechen={schliessen} />
        </Dialog>
      )}
      {offen?.art === "bearbeiten" && (
        <Dialog titel={`Zugang „${offen.zugang.name}“ bearbeiten`} onSchliessen={schliessen}>
          <ZugangFormular zugang={offen.zugang} onFertig={schliessen} onAbbrechen={schliessen} />
        </Dialog>
      )}
      {offen?.art === "loeschen" && (
        <Bestaetigung
          titel="Zugang löschen?"
          text={
            <p>
              „{offen.zugang.name}“ wird endgültig gelöscht. Der Wert lässt sich danach nicht wiederherstellen.
            </p>
          }
          knopf="Endgültig löschen"
          laeuft={loeschen.isPending}
          fehler={<FehlerMeldung fehler={loeschen.error} />}
          onBestaetigen={() => loeschen.mutate(offen.zugang)}
          onAbbrechen={schliessen}
        />
      )}
    </div>
  );
}
