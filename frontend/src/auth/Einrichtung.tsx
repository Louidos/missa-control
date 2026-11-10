import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api } from "../api";
import { FehlerMeldung, Feld, Knopf, Meldung } from "../ui/ui";
import { AUTH_STATUS } from "./authStatus";
import { TorRahmen } from "./TorRahmen";

interface Einrichtungsdaten {
  geheimnis: string;
  otpauth_url: string;
  qr_svg: string;
}

const MIN_LAENGE = 10;

/** Erster Aufruf: Passwort setzen, QR-Code scannen, Code bestätigen. */
export function Einrichtung() {
  const queryClient = useQueryClient();
  const [passwort, setPasswort] = useState("");
  const [wiederholung, setWiederholung] = useState("");
  const [code, setCode] = useState("");
  const [daten, setDaten] = useState<Einrichtungsdaten | null>(null);

  const beginnen = useMutation({
    mutationFn: () => api.post<Einrichtungsdaten>("/api/auth/einrichten", { passwort }),
    onSuccess: setDaten,
  });
  const bestaetigen = useMutation({
    mutationFn: () => api.post("/api/auth/einrichten/bestaetigen", { code }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: AUTH_STATUS }),
    onError: () => setCode(""),
  });

  const passwortFehler =
    passwort.length > 0 && passwort.length < MIN_LAENGE
      ? `Noch ${MIN_LAENGE - passwort.length} Zeichen (mindestens ${MIN_LAENGE}).`
      : wiederholung.length > 0 && passwort !== wiederholung
        ? "Die beiden Passwörter stimmen nicht überein."
        : null;
  const passwortOk = passwort.length >= MIN_LAENGE && passwort === wiederholung;

  const schritt = daten ? 2 : 1;

  return (
    <TorRahmen titel="Einrichtung" untertitel="Einmalig: Passwort wählen und Zwei-Faktor-Anmeldung aktivieren.">
      <ol className="schritte" aria-label="Fortschritt">
        <li className={schritt === 1 ? "aktiv" : "fertig"}>1 · Passwort</li>
        <li className={schritt === 2 ? "aktiv" : ""}>2 · Code scannen</li>
        <li>3 · Bestätigen</li>
      </ol>

      {!daten && (
        <form
          className="stapel"
          onSubmit={(ereignis: FormEvent) => {
            ereignis.preventDefault();
            if (passwortOk) beginnen.mutate();
          }}
        >
          <Feld titel="Neues Passwort" fuer="passwort" hilfe={`Mindestens ${MIN_LAENGE} Zeichen.`}>
            <input
              id="passwort"
              type="password"
              autoComplete="new-password"
              autoFocus
              required
              value={passwort}
              onChange={(e) => setPasswort(e.target.value)}
            />
          </Feld>
          <Feld titel="Passwort wiederholen" fuer="wiederholung">
            <input
              id="wiederholung"
              type="password"
              autoComplete="new-password"
              required
              value={wiederholung}
              onChange={(e) => setWiederholung(e.target.value)}
            />
          </Feld>
          {passwortFehler && <Meldung art="warn">{passwortFehler}</Meldung>}
          <FehlerMeldung fehler={beginnen.error} />
          <Knopf art="haupt" type="submit" disabled={!passwortOk || beginnen.isPending}>
            Weiter
          </Knopf>
        </form>
      )}

      {daten && (
        <form
          className="stapel"
          onSubmit={(ereignis: FormEvent) => {
            ereignis.preventDefault();
            bestaetigen.mutate();
          }}
        >
          <p>
            Scanne den QR-Code mit einer Authenticator-App (z. B. Aegis, 2FAS, Google Authenticator) und gib
            danach den angezeigten Code ein.
          </p>
          <img className="qr" src={daten.qr_svg} alt="QR-Code für die Authenticator-App" />
          <div className="stapel eng">
            <span className="gedaempft klein">Scannen nicht möglich? Diesen Schlüssel von Hand eintragen:</span>
            <code className="geheimnis">{daten.geheimnis}</code>
          </div>
          <Feld titel="Code aus der App (6 Ziffern)" fuer="code">
            <input
              id="code"
              className="code-eingabe"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9 ]*"
              maxLength={7}
              autoFocus
              required
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </Feld>
          <FehlerMeldung fehler={bestaetigen.error} />
          <div className="reihe zwischen">
            <Knopf art="still" onClick={() => setDaten(null)}>
              Zurück
            </Knopf>
            <Knopf art="haupt" type="submit" disabled={bestaetigen.isPending}>
              {bestaetigen.isPending ? "Prüfe …" : "Bestätigen und fertig"}
            </Knopf>
          </div>
        </form>
      )}
    </TorRahmen>
  );
}
