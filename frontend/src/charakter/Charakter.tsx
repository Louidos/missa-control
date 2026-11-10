import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Save, Upload } from "lucide-react";
import { type FormEvent, useRef, useState } from "react";

import { api } from "../api";
import { datum } from "../ui/format";
import { FehlerMeldung, Feld, Knopf, Lade, Meldung } from "../ui/ui";
import { gleich, PROFIL, PROFIL_VERSIONEN, type Profil, type ProfilAntwort } from "./profil";
import { TestChat } from "./TestChat";
import { Versionen } from "./Versionen";

type Reiter = "chat" | "versionen" | "vorschau";

/** Seite „Charakter“: links das Profil bearbeiten, rechts ausprobieren, vergleichen, zurückholen. */
export function Charakter() {
  const profil = useQuery({ queryKey: PROFIL, queryFn: () => api.get<ProfilAntwort>("/api/profil"), staleTime: Infinity });
  if (profil.isPending) return <Lade />;
  if (profil.isError) return <FehlerMeldung fehler={profil.error} />;
  // Der Schlüssel sorgt dafür, dass der Editor nach „Wiederherstellen“ mit dem neuen Stand neu beginnt.
  return <Editor key={profil.data.version?.id ?? 0} start={profil.data} />;
}

function Editor({ start }: { start: ProfilAntwort }) {
  const queryClient = useQueryClient();
  const [entwurf, setEntwurf] = useState<Profil>(start.profil);
  const [gespeichert, setGespeichert] = useState<ProfilAntwort>(start);
  const [kommentar, setKommentar] = useState("");
  const [reiter, setReiter] = useState<Reiter>("chat");
  const [hinweis, setHinweis] = useState("");
  const dateiFeld = useRef<HTMLInputElement>(null);
  const geaendert = !gleich(entwurf, gespeichert.profil);
  const setze = (teil: Partial<Profil>) => {
    setEntwurf({ ...entwurf, ...teil });
    setHinweis("");
  };

  const speichern = useMutation({
    mutationFn: () => api.put<ProfilAntwort>("/api/profil", { profil: entwurf, kommentar }),
    onSuccess: async (antwort) => {
      setGespeichert(antwort);
      setEntwurf(antwort.profil);
      setKommentar("");
      setHinweis(antwort.unveraendert ? "Nichts geändert – keine neue Version." : "Gespeichert als neue Version.");
      await queryClient.invalidateQueries({ queryKey: PROFIL_VERSIONEN });
    },
  });
  const laden = useMutation({
    mutationFn: async (quelle: File | "beispiel") =>
      quelle === "beispiel"
        ? api.get<{ profil: Profil }>("/api/profil/beispiel")
        : api.post<{ profil: Profil }>("/api/profil/import", { yaml: await quelle.text() }),
    onSuccess: (antwort) => {
      setEntwurf(antwort.profil);
      setHinweis("In den Editor geladen. Gespeichert wird erst mit „Speichern“.");
    },
  });
  const vorschau = useQuery({
    queryKey: ["profil-vorschau", entwurf],
    queryFn: () => api.post<{ systemprompt: string }>("/api/profil/vorschau", entwurf),
    enabled: reiter === "vorschau",
  });

  const text = (feld: "wesen" | "sprechweise" | "fremde" | "systemprompt", titel: string, hilfe: string, zeilen = 4) => (
    <Feld titel={titel} fuer={`profil-${feld}`} hilfe={hilfe}>
      <textarea id={`profil-${feld}`} rows={zeilen} className={feld === "systemprompt" ? "mono" : undefined} value={entwurf[feld]} onChange={(e) => setze({ [feld]: e.target.value })} />
    </Feld>
  );
  const liste = (feld: "darf" | "darf_nicht", titel: string) => (
    <Feld titel={titel} fuer={`profil-${feld}`} hilfe="Eine Regel pro Zeile.">
      <textarea id={`profil-${feld}`} rows={4} value={entwurf[feld].join("\n")} onChange={(e) => setze({ [feld]: e.target.value.split("\n") })} />
    </Feld>
  );

  return (
    <div className="zweispaltig">
      <form
        className="karte stapel"
        aria-label="Charakterprofil"
        onSubmit={(ereignis: FormEvent) => {
          ereignis.preventDefault();
          speichern.mutate();
        }}
      >
        <div className="reihe zwischen">
          <span className="gedaempft klein">
            {gespeichert.version ? `Aktuelle Version vom ${datum(gespeichert.version.erstellt)}` : "Noch nicht gespeichert"}
          </span>
          <div className="reihe" style={{ gap: "0.35rem" }}>
            <input
              ref={dateiFeld}
              type="file"
              accept=".yaml,.yml"
              hidden
              aria-label="YAML-Datei auswählen"
              onChange={(e) => {
                const datei = e.target.files?.[0];
                if (datei) laden.mutate(datei);
                e.target.value = "";
              }}
            />
            <Knopf klein onClick={() => laden.mutate("beispiel")} disabled={laden.isPending}>
              Beispiel laden
            </Knopf>
            <Knopf klein onClick={() => dateiFeld.current?.click()} disabled={laden.isPending}>
              <Upload aria-hidden />
              Importieren
            </Knopf>
            <a className="knopf klein" href="/api/profil/export" download title="Exportiert den gespeicherten Stand als YAML">
              <Download aria-hidden />
              Exportieren
            </a>
          </div>
        </div>
        <FehlerMeldung fehler={laden.error} />

        <div className="reihe" style={{ alignItems: "flex-start" }}>
          <div className="fuellen">
            <Feld titel="Name" fuer="profil-name">
              <input id="profil-name" type="text" maxLength={80} value={entwurf.name} onChange={(e) => setze({ name: e.target.value })} />
            </Feld>
          </div>
          <div className="fuellen">
            <Feld titel="Aussprache" fuer="profil-aussprache" hilfe="Wie der Name ausgesprochen wird.">
              <input id="profil-aussprache" type="text" maxLength={200} value={entwurf.aussprache} onChange={(e) => setze({ aussprache: e.target.value })} />
            </Feld>
          </div>
        </div>
        {text("wesen", "Wesen", "Wer ist Missa? Charakter, Haltung, Eigenheiten.")}
        {text("sprechweise", "Sprechweise", "Wie redet sie? Sprache, Ton, Länge der Antworten.")}
        {liste("darf", "Regeln: Das darf Missa")}
        {liste("darf_nicht", "Regeln: Das darf Missa nicht")}
        {text("fremde", "Verhalten gegenüber Fremden", "Was gilt, wenn jemand Unbekanntes mit Missa spricht?", 3)}
        {text("systemprompt", "Freier Systemprompt", "Wird unverändert ans Ende gehängt. Für alles, was in kein Feld passt.", 6)}

        <FehlerMeldung fehler={speichern.error} />
        {hinweis && <Meldung art="ok">{hinweis}</Meldung>}
        <div className="reihe speicherleiste">
          <input
            type="text"
            className="fuellen"
            style={{ width: "auto" }}
            aria-label="Kommentar zur Version"
            placeholder="Kommentar zu dieser Version (optional)"
            maxLength={300}
            value={kommentar}
            onChange={(e) => setKommentar(e.target.value)}
          />
          {geaendert && (
            <span className="etikett schreibend" title="ungespeicherte Änderungen">
              ungespeichert
            </span>
          )}
          <Knopf art="haupt" type="submit" disabled={speichern.isPending || !geaendert}>
            <Save aria-hidden />
            Speichern
          </Knopf>
        </div>
      </form>

      <div className="karte stapel seitenspalte">
        <div className="reiter" role="tablist">
          {(
            [
              ["chat", "Test-Chat"],
              ["versionen", "Versionen"],
              ["vorschau", "Systemprompt"],
            ] as const
          ).map(([wert, titel]) => (
            <button key={wert} type="button" role="tab" aria-selected={reiter === wert} onClick={() => setReiter(wert)}>
              {titel}
            </button>
          ))}
        </div>
        {reiter === "chat" && <TestChat profil={entwurf} />}
        {reiter === "versionen" && (
          <Versionen
            onWiederhergestellt={async (antwort) => {
              queryClient.setQueryData(PROFIL, antwort);
              await queryClient.invalidateQueries({ queryKey: PROFIL_VERSIONEN });
            }}
          />
        )}
        {reiter === "vorschau" && (
          <div className="stapel eng">
            <p className="gedaempft klein">
              Das bekommt das Modell als Systemprompt – zusammengesetzt aus den Feldern links (auch ungespeichert).
              Missa ruft es über <code>/api/config/profile</code> ab.
            </p>
            <FehlerMeldung fehler={vorschau.error} />
            <pre className="ergebnis">{vorschau.data?.systemprompt ?? "…"}</pre>
          </div>
        )}
      </div>
    </div>
  );
}
