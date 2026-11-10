import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";

import { api } from "../api";
import { FehlerMeldung, Feld, Knopf } from "../ui/ui";
import { TYPEN, type Zugang, type ZugangTyp, ZUGAENGE } from "./zugaenge";

interface Props {
  /** Vorhandener Zugang zum Bearbeiten – fehlt er, wird ein neuer angelegt. */
  zugang?: Zugang;
  /** Schränkt beim Anlegen auf bestimmte Typen ein (z. B. nur Bearer-Token). */
  erlaubteTypen?: ZugangTyp[];
  vorschlagName?: string;
  onFertig: (zugang: Zugang) => void;
  onAbbrechen: () => void;
}

/** Formular zum Anlegen oder Ändern eines Zugangs. Der gespeicherte Wert wird nie angezeigt. */
export function ZugangFormular({ zugang, erlaubteTypen, vorschlagName, onFertig, onAbbrechen }: Props) {
  const queryClient = useQueryClient();
  const id = useId();
  const typen = TYPEN.filter((typ) => !erlaubteTypen?.length || erlaubteTypen.includes(typ.wert));
  const [name, setName] = useState(zugang?.name ?? vorschlagName ?? "");
  const [typ, setTyp] = useState<ZugangTyp>(zugang?.typ ?? typen[0]?.wert ?? "api_key");
  const [benutzer, setBenutzer] = useState(zugang?.benutzer ?? "");
  const [wert, setWert] = useState("");
  const [notiz, setNotiz] = useState(zugang?.notiz ?? "");

  const speichern = useMutation({
    mutationFn: () =>
      zugang
        ? api.put<Zugang>(`/api/zugaenge/${zugang.id}`, {
            name,
            notiz,
            ...(typ === "benutzer_passwort" ? { benutzer } : {}),
            ...(wert ? { wert } : {}),
          })
        : api.post<Zugang>("/api/zugaenge", {
            name,
            typ,
            wert,
            notiz,
            ...(typ === "benutzer_passwort" ? { benutzer } : {}),
          }),
    onSuccess: async (gespeichert) => {
      setWert("");
      await queryClient.invalidateQueries({ queryKey: ZUGAENGE });
      onFertig(gespeichert);
    },
  });

  const wertTitel = TYPEN.find((eintrag) => eintrag.wert === typ)?.wertTitel ?? "Wert";

  return (
    <form
      className="stapel"
      onSubmit={(ereignis: FormEvent) => {
        ereignis.preventDefault();
        ereignis.stopPropagation();
        speichern.mutate();
      }}
    >
      <Feld titel="Name" fuer={`${id}-name`} pflicht hilfe="Frei wählbar, z. B. „Wetter-API“ oder „Nextcloud Missa“.">
        <input id={`${id}-name`} type="text" required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
      </Feld>
      {!zugang && typen.length > 1 && (
        <Feld titel="Typ" fuer={`${id}-typ`}>
          <select id={`${id}-typ`} value={typ} onChange={(e) => setTyp(e.target.value as ZugangTyp)}>
            {typen.map((eintrag) => (
              <option key={eintrag.wert} value={eintrag.wert}>
                {eintrag.name}
              </option>
            ))}
          </select>
        </Feld>
      )}
      {typ === "benutzer_passwort" && (
        <Feld titel="Benutzername" fuer={`${id}-benutzer`} pflicht>
          <input
            id={`${id}-benutzer`}
            type="text"
            required
            autoComplete="off"
            value={benutzer}
            onChange={(e) => setBenutzer(e.target.value)}
          />
        </Feld>
      )}
      <Feld
        titel={wertTitel}
        fuer={`${id}-wert`}
        pflicht={!zugang}
        hilfe={
          zugang
            ? `Gespeichert: ${zugang.maske} – leer lassen, um den Wert nicht zu ändern.`
            : "Wird verschlüsselt gespeichert und danach nie wieder im Klartext angezeigt."
        }
      >
        <input
          id={`${id}-wert`}
          type="password"
          required={!zugang}
          autoComplete="new-password"
          value={wert}
          onChange={(e) => setWert(e.target.value)}
        />
      </Feld>
      <Feld titel="Notiz" fuer={`${id}-notiz`}>
        <input id={`${id}-notiz`} type="text" maxLength={2000} value={notiz} onChange={(e) => setNotiz(e.target.value)} />
      </Feld>
      <FehlerMeldung fehler={speichern.error} />
      <div className="dialog-fuss">
        <Knopf onClick={onAbbrechen}>Abbrechen</Knopf>
        <Knopf art="haupt" type="submit" disabled={speichern.isPending}>
          {zugang ? "Speichern" : "Zugang anlegen"}
        </Knopf>
      </div>
    </form>
  );
}
