import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Search, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { api, ApiFehler } from "../api";
import { Bestaetigung } from "../ui/Dialog";
import { FehlerMeldung, Knopf, Lade, Meldung } from "../ui/ui";
import { Assistent } from "./Assistent";
import { KATALOG, type Katalog as KatalogDaten, type KatalogEintrag, useKatalog } from "./typen";

/** Seite „Katalog“: alle verfügbaren Integrationen als Karten. Ein Klick öffnet den Assistenten. */
export function Katalog() {
  const queryClient = useQueryClient();
  const katalog = useKatalog();
  const [suche, setSuche] = useState("");
  const [parameter, setParameter] = useSearchParams();
  const [zuLoeschen, setZuLoeschen] = useState<KatalogEintrag | null>(null);
  const [ersetzen, setErsetzen] = useState<File | null>(null);
  const dateiFeld = useRef<HTMLInputElement>(null);

  const offen = katalog.data?.eintraege.find((eintrag) => eintrag.id === parameter.get("neu")) ?? null;
  const oeffnen = (id: string | null) => setParameter(id ? { neu: id } : {}, { replace: true });
  const neuLaden = (daten?: KatalogDaten) =>
    daten ? queryClient.setQueryData(KATALOG, daten) : queryClient.invalidateQueries({ queryKey: KATALOG });

  const einlesen = useMutation({
    mutationFn: () => api.post<KatalogDaten>("/api/katalog/einlesen"),
    onSuccess: (daten) => neuLaden(daten),
  });
  const hochladen = useMutation({
    mutationFn: ({ datei, ueberschreiben }: { datei: File; ueberschreiben: boolean }) => {
      const formular = new FormData();
      formular.append("datei", datei);
      formular.append("ersetzen", ueberschreiben ? "true" : "false");
      return api.post<{ id: string; name: string; ersetzt: boolean }>("/api/katalog/hochladen", formular);
    },
    onSuccess: async (ergebnis) => {
      setErsetzen(null);
      await neuLaden();
      oeffnen(ergebnis.id);
    },
    onError: (fehler, { datei, ueberschreiben }) => {
      // Gibt es die Integration schon, fragen wir nach, ob sie ersetzt werden soll.
      if (fehler instanceof ApiFehler && fehler.status === 409 && !ueberschreiben) setErsetzen(datei);
    },
  });
  const loeschen = useMutation({
    mutationFn: (eintrag: KatalogEintrag) => api.del(`/api/katalog/${eintrag.id}`),
    onSuccess: async () => {
      setZuLoeschen(null);
      await neuLaden();
    },
  });

  if (katalog.isPending) return <Lade />;
  if (katalog.isError) return <FehlerMeldung fehler={katalog.error} />;

  const begriff = suche.trim().toLowerCase();
  const treffer = katalog.data.eintraege.filter(
    (eintrag) =>
      !begriff ||
      [eintrag.name, eintrag.beschreibung, eintrag.art_name, eintrag.id].some((text) =>
        text.toLowerCase().includes(begriff),
      ),
  );

  return (
    <div className="stapel">
      <p className="gedaempft">
        Neue Fähigkeiten für Missa in drei Schritten: Karte wählen, Formular ausfüllen, testen und aktivieren.
      </p>
      <div className="reihe">
        <div className="suchfeld fuellen">
          <Search aria-hidden />
          <input
            type="search"
            placeholder="Katalog durchsuchen …"
            aria-label="Katalog durchsuchen"
            value={suche}
            onChange={(e) => setSuche(e.target.value)}
          />
        </div>
        <input
          ref={dateiFeld}
          type="file"
          accept=".zip,application/zip"
          hidden
          aria-label="ZIP-Datei auswählen"
          onChange={(e) => {
            const datei = e.target.files?.[0];
            if (datei) hochladen.mutate({ datei, ueberschreiben: false });
            e.target.value = "";
          }}
        />
        <Knopf onClick={() => dateiFeld.current?.click()} disabled={hochladen.isPending}>
          <Upload aria-hidden />
          Eigene Integration hochladen (ZIP)
        </Knopf>
        <Knopf onClick={() => einlesen.mutate()} disabled={einlesen.isPending} title="Ordner neu einlesen">
          <RefreshCw aria-hidden />
          Neu einlesen
        </Knopf>
      </div>

      {hochladen.error && !ersetzen && <FehlerMeldung fehler={hochladen.error} />}
      <FehlerMeldung fehler={einlesen.error} />

      {katalog.data.probleme.map((problem) => (
        <Meldung
          key={problem.ordner}
          art="warn"
          hinweis="Die Vorlage in integrations/_vorlage/ zeigt den richtigen Aufbau. Nach der Korrektur „Neu einlesen“."
        >
          Die Integration im Ordner „{problem.ordner}“ konnte nicht geladen werden: {problem.meldungen.join(" · ")}
        </Meldung>
      ))}

      <div className="karten">
        {treffer.map((eintrag) => (
          <article className="karte katalog-karte" key={eintrag.id}>
            <div className="katalog-kopf">
              <span className="symbol" aria-hidden>
                {eintrag.symbol}
              </span>
              <div className="fuellen">
                <h2>{eintrag.name}</h2>
                <div className="reihe" style={{ gap: "0.35rem" }}>
                  <span className="etikett">{eintrag.art_name}</span>
                  {!eintrag.eingebaut && <span className="etikett eigen">eigene</span>}
                  {eintrag.eingerichtet > 0 && (
                    <Link className="etikett aktiv" to="/integrationen">
                      {eintrag.eingerichtet}× eingerichtet
                    </Link>
                  )}
                </div>
              </div>
              {!eintrag.eingebaut && (
                <Knopf art="still" aria-label={`${eintrag.name} aus dem Katalog löschen`} onClick={() => setZuLoeschen(eintrag)}>
                  <Trash2 aria-hidden />
                </Knopf>
              )}
            </div>
            <p className="gedaempft fuellen">{eintrag.beschreibung}</p>
            <Knopf art="haupt" disabled={!eintrag.kann_hinzufuegen} onClick={() => oeffnen(eintrag.id)}>
              {!eintrag.verfuegbar
                ? "Kommt mit einer späteren Version"
                : eintrag.kann_hinzufuegen
                  ? "Einrichten"
                  : "Bereits eingerichtet"}
            </Knopf>
          </article>
        ))}
      </div>
      {treffer.length === 0 && <div className="karte leer">Keine Integration passt zu „{suche}“.</div>}

      {offen && <Assistent key={offen.id} eintrag={offen} onSchliessen={() => oeffnen(null)} />}

      {ersetzen && (
        <Bestaetigung
          titel="Vorhandene Integration ersetzen?"
          text={<p>Eine eigene Integration mit dieser id gibt es schon. Soll sie durch „{ersetzen.name}“ ersetzt werden?</p>}
          knopf="Ersetzen"
          laeuft={hochladen.isPending}
          onBestaetigen={() => hochladen.mutate({ datei: ersetzen, ueberschreiben: true })}
          onAbbrechen={() => {
            setErsetzen(null);
            hochladen.reset();
          }}
        />
      )}
      {zuLoeschen && (
        <Bestaetigung
          titel="Aus dem Katalog löschen?"
          text={<p>Der Ordner der eigenen Integration „{zuLoeschen.name}“ wird gelöscht.</p>}
          knopf="Löschen"
          laeuft={loeschen.isPending}
          fehler={<FehlerMeldung fehler={loeschen.error} />}
          onBestaetigen={() => loeschen.mutate(zuLoeschen)}
          onAbbrechen={() => {
            setZuLoeschen(null);
            loeschen.reset();
          }}
        />
      )}
    </div>
  );
}
