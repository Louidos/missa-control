import { useMutation } from "@tanstack/react-query";
import { RotateCcw, Send } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router";

import { api } from "../api";
import { useModelle, zeitspanne } from "../modelle/modelle";
import { FehlerMeldung, Knopf, Meldung } from "../ui/ui";
import type { Nachricht, Profil } from "./profil";

interface Antwort {
  antwort: string;
  modell: string;
  dauer_ms: number;
}

/** Probiert das Profil aus – auch ungespeichert. Geht direkt ans Modell, nicht an missa-core. */
export function TestChat({ profil }: { profil: Profil }) {
  const modelle = useModelle(false);
  const rollen = (modelle.data?.rollen ?? []).filter((rolle) => rolle.haupt_modell_id !== null);
  const [gewaehlt, setGewaehlt] = useState("");
  const rolle = rollen.some((r) => r.kennung === gewaehlt) ? gewaehlt : (rollen[0]?.kennung ?? "");
  const [verlauf, setVerlauf] = useState<Nachricht[]>([]);
  const [eingabe, setEingabe] = useState("");
  const [info, setInfo] = useState("");
  const ende = useRef<HTMLDivElement>(null);

  const senden = useMutation({
    mutationFn: (nachrichten: Nachricht[]) => api.post<Antwort>("/api/profil/testchat", { profil, rolle, nachrichten }),
    onSuccess: (antwort) => {
      setVerlauf((alt) => [...alt, { von: "missa", text: antwort.antwort }]);
      setInfo(`${antwort.modell} · ${zeitspanne(antwort.dauer_ms)}`);
    },
  });

  useEffect(() => {
    ende.current?.scrollIntoView?.({ block: "nearest" });
  }, [verlauf, senden.isPending]);

  if (modelle.isSuccess && rollen.length === 0) {
    return (
      <Meldung art="info">
        Für den Test-Chat braucht mindestens eine Rolle ein Modell. Das lässt sich unter <Link to="/modelle">Modelle</Link>{" "}
        einstellen.
      </Meldung>
    );
  }

  const absenden = (ereignis: FormEvent) => {
    ereignis.preventDefault();
    const text = eingabe.trim();
    if (!text || senden.isPending) return;
    const neu: Nachricht[] = [...verlauf, { von: "nutzer", text }];
    setVerlauf(neu);
    setEingabe("");
    senden.mutate(neu);
  };

  return (
    <div className="stapel eng">
      <div className="reihe">
        <label className="reihe fuellen" style={{ gap: "0.4rem" }}>
          <span className="klein gedaempft">Modell-Rolle</span>
          <select aria-label="Modell-Rolle" style={{ width: "auto" }} value={rolle} onChange={(e) => setGewaehlt(e.target.value)}>
            {rollen.map((r) => (
              <option key={r.kennung} value={r.kennung}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        <Knopf
          klein
          onClick={() => {
            setVerlauf([]);
            setInfo("");
            senden.reset();
          }}
          disabled={verlauf.length === 0}
        >
          <RotateCcw aria-hidden />
          Neu beginnen
        </Knopf>
      </div>
      <div className="chat" aria-label="Test-Chat" role="log">
        {verlauf.length === 0 && (
          <p className="gedaempft klein">
            Schreib Missa etwas – sie antwortet mit dem Profil, so wie es gerade links steht (auch ungespeichert).
          </p>
        )}
        {verlauf.map((nachricht, index) => (
          <div key={index} className={`blase ${nachricht.von}`}>
            {nachricht.text}
          </div>
        ))}
        {senden.isPending && <div className="blase missa gedaempft">Missa schreibt … (höchstens 2 Minuten)</div>}
        <div ref={ende} />
      </div>
      <FehlerMeldung fehler={senden.error} />
      {info && !senden.error && <div className="gedaempft klein">Antwort von {info}</div>}
      <form className="reihe" onSubmit={absenden}>
        <input
          type="text"
          className="fuellen"
          style={{ width: "auto" }}
          aria-label="Nachricht an Missa"
          placeholder="Nachricht an Missa …"
          value={eingabe}
          onChange={(e) => setEingabe(e.target.value)}
        />
        <Knopf art="haupt" type="submit" disabled={senden.isPending || !eingabe.trim()}>
          <Send aria-hidden />
          Senden
        </Knopf>
      </form>
    </div>
  );
}
