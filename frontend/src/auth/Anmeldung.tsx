import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api } from "../api";
import { FehlerMeldung, Feld, Knopf } from "../ui/ui";
import { AUTH_STATUS } from "./authStatus";
import { TorRahmen } from "./TorRahmen";

export function Anmeldung() {
  const queryClient = useQueryClient();
  const [passwort, setPasswort] = useState("");
  const [code, setCode] = useState("");

  const anmelden = useMutation({
    mutationFn: () => api.post("/api/auth/anmelden", { passwort, code }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: AUTH_STATUS }),
    onError: () => setCode(""),
  });

  const absenden = (ereignis: FormEvent) => {
    ereignis.preventDefault();
    anmelden.mutate();
  };

  return (
    <TorRahmen titel="Anmelden" untertitel="Mit Passwort und dem Code aus der Authenticator-App.">
      <form className="stapel" onSubmit={absenden}>
        <Feld titel="Passwort" fuer="passwort">
          <input
            id="passwort"
            type="password"
            autoComplete="current-password"
            autoFocus
            required
            value={passwort}
            onChange={(e) => setPasswort(e.target.value)}
          />
        </Feld>
        <Feld titel="Code (6 Ziffern)" fuer="code">
          <input
            id="code"
            className="code-eingabe"
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9 ]*"
            maxLength={7}
            required
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
        </Feld>
        <FehlerMeldung fehler={anmelden.error} />
        <Knopf art="haupt" type="submit" disabled={anmelden.isPending}>
          {anmelden.isPending ? "Prüfe …" : "Anmelden"}
        </Knopf>
      </form>
    </TorRahmen>
  );
}
