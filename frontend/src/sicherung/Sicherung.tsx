import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, Upload } from "lucide-react";
import { type FormEvent, useState } from "react";

import { api } from "../api";
import { herunterladen } from "../geraete/geraete";
import { FehlerMeldung, Feld, Knopf, Meldung } from "../ui/ui";

type Status = "neu" | "ueberschrieben" | "unveraendert" | "fehlt";
type Modus = "ergaenzen" | "ersetzen" | "auslassen";

interface Bereich {
  bereich: string;
  titel: string;
  eintraege: { name: string; status: Status }[];
  nur_hier: string[];
}

interface Vorschau {
  panel_version: string | null;
  erstellt: string | null;
  mit_zugaengen: boolean;
  bereiche: Bereich[];
}

interface Ergebnis {
  eingespielt: Record<string, number>;
  zugang_fehlt: string[];
}

const STATUS_TEXT: Record<Status, string> = {
  neu: "neu",
  ueberschrieben: "würde überschrieben",
  unveraendert: "unverändert",
  fehlt: "Zugang fehlt (ohne Passwort gesichert)",
};

/** Passwort und Code des Panels – zur Bestätigung heikler Aktionen. */
function Bestaetigen({ werte, onAendern, id }: { werte: { passwort: string; code: string }; onAendern: (w: { passwort: string; code: string }) => void; id: string }) {
  return (
    <div className="reihe" style={{ alignItems: "flex-end" }}>
      <Feld titel="Passwort des Panels" fuer={`${id}-passwort`}>
        <input
          id={`${id}-passwort`}
          type="password"
          autoComplete="current-password"
          required
          value={werte.passwort}
          onChange={(e) => onAendern({ ...werte, passwort: e.target.value })}
        />
      </Feld>
      <Feld titel="Code aus der Authenticator-App" fuer={`${id}-code`}>
        <input
          id={`${id}-code`}
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          required
          value={werte.code}
          onChange={(e) => onAendern({ ...werte, code: e.target.value })}
        />
      </Feld>
    </div>
  );
}

/**
 * Seite „Sicherung“: die ganze Einrichtung als eine Datei herunterladen und wieder einspielen.
 * Für ein Voll-Backup von data/ und .env gibt es weiterhin ./scripts/backup.sh.
 */
export function Sicherung() {
  return (
    <div className="stapel">
      <p className="gedaempft">
        Die ganze Einrichtung als eine Datei: Integrationen mit Rechten und Zugriffsstufe, Regeln, Charakterprofil, Modelle und
        Rollen, Telefonie und die Anordnung der Übersicht. Nicht enthalten: Login und 2FA, Client-Tokens, Protokoll, Messwerte,
        Gedächtnis (eigener Export unter „Gedächtnis“) und Geräte. Für ein Voll-Backup von <code>data/</code> und <code>.env</code>{" "}
        auf ai01: <code>./scripts/backup.sh</code>.
      </p>
      <Herunterladen />
      <Einspielen />
    </div>
  );
}

function Herunterladen() {
  const [mitZugaengen, setMitZugaengen] = useState(false);
  const [sicherungsPasswort, setSicherungsPasswort] = useState("");
  const [wiederholung, setWiederholung] = useState("");
  const [bestaetigung, setBestaetigung] = useState({ passwort: "", code: "" });

  const exportieren = useMutation({
    mutationFn: () =>
      api.post<object>(
        "/api/sicherung/export",
        mitZugaengen ? { sicherungs_passwort: sicherungsPasswort, ...bestaetigung } : {},
      ),
    onSuccess: (datei) => {
      const tag = new Date().toISOString().slice(0, 10);
      herunterladen(`missa-control-sicherung-${tag}.json`, JSON.stringify(datei, null, 2));
      setBestaetigung({ passwort: "", code: "" });
    },
  });
  const ungleich = mitZugaengen && wiederholung !== "" && wiederholung !== sicherungsPasswort;

  return (
    <section className="karte stapel" aria-label="Sicherung herunterladen">
      <h2>Herunterladen</h2>
      <form
        className="stapel"
        onSubmit={(ereignis: FormEvent) => {
          ereignis.preventDefault();
          if (!ungleich) exportieren.mutate();
        }}
      >
        <label className="schalter">
          <input type="checkbox" checked={mitZugaengen} onChange={(e) => setMitZugaengen(e.target.checked)} />
          <span>Zugänge mitsichern (verschlüsselt mit eigenem Passwort)</span>
        </label>
        {mitZugaengen ? (
          <>
            <div className="reihe" style={{ alignItems: "flex-end" }}>
              <Feld titel="Passwort für die Sicherung" fuer="sicherung-passwort" hilfe="Mindestens 10 Zeichen. Ohne dieses Passwort lassen sich die Zugänge nicht wieder einspielen.">
                <input id="sicherung-passwort" type="password" autoComplete="new-password" minLength={10} required value={sicherungsPasswort} onChange={(e) => setSicherungsPasswort(e.target.value)} />
              </Feld>
              <Feld titel="Passwort wiederholen" fuer="sicherung-wiederholung">
                <input id="sicherung-wiederholung" type="password" autoComplete="new-password" required value={wiederholung} onChange={(e) => setWiederholung(e.target.value)} />
              </Feld>
            </div>
            {ungleich && <Meldung art="warn">Die beiden Passwörter stimmen nicht überein.</Meldung>}
            <p className="gedaempft klein">Zur Bestätigung, dass du es bist:</p>
            <Bestaetigen id="export" werte={bestaetigung} onAendern={setBestaetigung} />
          </>
        ) : (
          <p className="gedaempft klein">
            Ohne Passwort steht kein Geheimnis in der Datei. Zugänge sind dann nur mit Namen vermerkt – nach dem Einspielen sind
            betroffene Integrationen als „Zugang fehlt“ markiert.
          </p>
        )}
        <FehlerMeldung fehler={exportieren.error} />
        {exportieren.isSuccess && <Meldung art="ok">Die Sicherung wurde heruntergeladen.</Meldung>}
        <div>
          <Knopf art="haupt" type="submit" disabled={exportieren.isPending || ungleich}>
            <Download aria-hidden />
            {exportieren.isPending ? "Erstelle Sicherung …" : "Sicherung herunterladen"}
          </Knopf>
        </div>
      </form>
    </section>
  );
}

function Einspielen() {
  const queryClient = useQueryClient();
  const [datei, setDatei] = useState<string | null>(null);
  const [sicherungsPasswort, setSicherungsPasswort] = useState("");
  const [modi, setModi] = useState<Record<string, Modus>>({});
  const [bestaetigung, setBestaetigung] = useState({ passwort: "", code: "" });

  const vorschau = useMutation({
    mutationFn: (inhalt: string) =>
      api.post<Vorschau>("/api/sicherung/vorschau", { datei: inhalt, sicherungs_passwort: sicherungsPasswort || null }),
  });
  const einspielen = useMutation({
    mutationFn: () =>
      api.post<Ergebnis>("/api/sicherung/einspielen", {
        datei,
        sicherungs_passwort: sicherungsPasswort || null,
        modi,
        ...bestaetigung,
      }),
    onSuccess: async () => {
      setBestaetigung({ passwort: "", code: "" });
      await queryClient.invalidateQueries();
    },
  });

  return (
    <section className="karte stapel" aria-label="Sicherung einspielen">
      <h2>Einspielen</h2>
      <Feld titel="Sicherungsdatei" fuer="sicherung-datei">
        <input
          id="sicherung-datei"
          type="file"
          accept=".json,application/json"
          onChange={async (e) => {
            const gewaehlt = e.target.files?.[0];
            const inhalt = gewaehlt ? await gewaehlt.text() : null;
            setDatei(inhalt);
            einspielen.reset();
            vorschau.reset();
            if (inhalt) vorschau.mutate(inhalt);
          }}
        />
      </Feld>
      <Feld titel="Passwort der Sicherung (falls mit Zugängen gesichert)" fuer="einspielen-sicherungspasswort">
        <div className="reihe">
          <input
            id="einspielen-sicherungspasswort"
            type="password"
            autoComplete="off"
            className="fuellen"
            style={{ width: "auto" }}
            value={sicherungsPasswort}
            onChange={(e) => setSicherungsPasswort(e.target.value)}
          />
          <Knopf disabled={!datei || vorschau.isPending} onClick={() => datei && vorschau.mutate(datei)}>
            Vorschau aktualisieren
          </Knopf>
        </div>
      </Feld>
      <FehlerMeldung fehler={vorschau.error} />

      {vorschau.data && !einspielen.isSuccess && (
        <form
          className="stapel"
          onSubmit={(ereignis: FormEvent) => {
            ereignis.preventDefault();
            einspielen.mutate();
          }}
        >
          <p className="gedaempft klein">
            Vorschau{vorschau.data.erstellt ? ` der Sicherung vom ${new Date(vorschau.data.erstellt).toLocaleString("de-CH")}` : ""}
            {vorschau.data.mit_zugaengen ? " – mit Zugängen" : " – ohne Zugänge"}. Pro Bereich wählen: „ergänzen“ (neue dazu,
            gleichnamige überschreiben, übrige bleiben) oder „ersetzen“ (Bereich vorher leeren).
          </p>
          {vorschau.data.bereiche.map((bereich) => (
            <fieldset key={bereich.bereich} className="stapel eng sicherung-bereich">
              <legend>{bereich.titel}</legend>
              <div className="auswahl" role="radiogroup" aria-label={`${bereich.titel}: Modus`}>
                {(["ergaenzen", "ersetzen", "auslassen"] as Modus[]).map((modus) => (
                  <button
                    key={modus}
                    type="button"
                    role="radio"
                    aria-checked={(modi[bereich.bereich] ?? "ergaenzen") === modus}
                    onClick={() => setModi({ ...modi, [bereich.bereich]: modus })}
                  >
                    {modus === "ergaenzen" ? "ergänzen" : modus === "ersetzen" ? "ersetzen" : "auslassen"}
                  </button>
                ))}
              </div>
              {bereich.eintraege.length === 0 && <p className="gedaempft klein">Nichts in der Sicherung.</p>}
              <ul className="sicherung-liste">
                {bereich.eintraege.map((eintrag) => (
                  <li key={eintrag.name}>
                    <span>{eintrag.name}</span> <span className={`etikett ${eintrag.status}`}>{STATUS_TEXT[eintrag.status]}</span>
                  </li>
                ))}
                {(modi[bereich.bereich] ?? "ergaenzen") === "ersetzen" &&
                  bereich.nur_hier.map((name) => (
                    <li key={`weg-${name}`}>
                      <span>{name}</span> <span className="etikett fehlt">würde entfernt</span>
                    </li>
                  ))}
              </ul>
            </fieldset>
          ))}
          <p className="gedaempft klein">
            Eingespielte Integrationen stehen auf „ungetestet“, bis sie unter „Integrationen“ getestet sind. Zur Bestätigung:
          </p>
          <Bestaetigen id="einspielen" werte={bestaetigung} onAendern={setBestaetigung} />
          <FehlerMeldung fehler={einspielen.error} />
          <div>
            <Knopf art="haupt" type="submit" disabled={einspielen.isPending}>
              <Upload aria-hidden />
              {einspielen.isPending ? "Spiele ein …" : "Einspielen"}
            </Knopf>
          </div>
        </form>
      )}
      {einspielen.data && (
        <Meldung
          art={einspielen.data.zugang_fehlt.length ? "warn" : "ok"}
          hinweis={
            einspielen.data.zugang_fehlt.length
              ? `Zugang fehlt bei: ${einspielen.data.zugang_fehlt.join(", ")} – unter „Integrationen“ bearbeiten und einen Zugang wählen.`
              : "Bitte die Integrationen unter „Integrationen“ einmal testen."
          }
        >
          Die Sicherung ist eingespielt.
        </Meldung>
      )}
    </section>
  );
}
