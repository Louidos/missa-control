import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link } from "react-router";

import { api } from "../api";
import { ParameterFelder } from "../integrationen/ParameterFelder";
import { FehlerMeldung, Feld, Knopf } from "../ui/ui";
import { useVerzoegert } from "../ui/verzoegert";
import { type Aktion, aktionStart, type Ausloeser, ausloeserStart, type Entwurf, neuerEntwurf, type Optionen, type Regel } from "./regeln";

const TAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const TAGE_LANG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];

interface Props {
  /** Die Regel, die bearbeitet wird – fehlt sie, entsteht eine neue. */
  regel?: Regel;
  optionen: Optionen;
  onFertig: () => void;
  onAbbrechen: () => void;
}

function nummer(wert: string): number | null {
  return wert === "" ? null : Number(wert);
}

/** Der Editor für eine Regel: Wenn (Auslöser) – nur wenn (Bedingung) – dann (Aktion). */
export function RegelEditor({ regel, optionen, onFertig, onAbbrechen }: Props) {
  const id = useId();
  const [entwurf, setEntwurf] = useState<Entwurf>(() =>
    regel
      ? {
          name: regel.name,
          ausloeser: regel.ausloeser,
          bedingung: regel.bedingung,
          aktion: regel.aktion,
          ruhezeit_minuten: regel.ruhezeit_minuten,
          aktiv: regel.aktiv,
        }
      : neuerEntwurf(optionen),
  );
  const { ausloeser, bedingung, aktion } = entwurf;
  const setzeAusloeser = (teil: Partial<Ausloeser>) => setEntwurf({ ...entwurf, ausloeser: { ...ausloeser, ...teil } });
  const setzeAktion = (teil: Partial<Aktion>) => setEntwurf({ ...entwurf, aktion: { ...aktion, ...teil } });
  const setzeBedingung = (teil: Partial<Entwurf["bedingung"]>) => setEntwurf({ ...entwurf, bedingung: { ...bedingung, ...teil } });

  // Die Regel als Satz – das Backend prüft dabei gleich, ob alles vollständig ist.
  const stand = useVerzoegert(entwurf, 300);
  const vorschau = useQuery({
    queryKey: ["regel-satz", stand],
    queryFn: () => api.post<{ ok: boolean; satz?: string; meldung?: string }>("/api/regeln/satz", stand),
    placeholderData: keepPreviousData,
    retry: false,
  });
  const speichern = useMutation({
    mutationFn: () => (regel ? api.put(`/api/regeln/${regel.id}`, entwurf) : api.post("/api/regeln", entwurf)),
    onSuccess: onFertig,
  });

  const messwert = optionen.messwerte.find((einer) => einer.kennung === ausloeser.messwert);
  const funktion = optionen.funktionen.find((eine) => eine.name === aktion.funktion);
  const integrationen = [...new Set(optionen.funktionen.map((eine) => eine.integration))];
  const tage = bedingung.tage ?? [];

  return (
    <form
      className="stapel"
      onSubmit={(ereignis) => {
        ereignis.preventDefault();
        speichern.mutate();
      }}
    >
      <Feld titel="Name" fuer={`${id}-name`} pflicht>
        <input id={`${id}-name`} type="text" maxLength={80} required autoFocus placeholder="z. B. CPU-Alarm" value={entwurf.name} onChange={(e) => setEntwurf({ ...entwurf, name: e.target.value })} />
      </Feld>

      <fieldset className="regel-teil">
        <legend>Wenn</legend>
        <Feld titel="Auslöser" fuer={`${id}-ausloeser`}>
          <select id={`${id}-ausloeser`} value={ausloeser.art} onChange={(e) => setEntwurf({ ...entwurf, ausloeser: ausloeserStart(e.target.value) })}>
            {optionen.ausloeser.map((einer) => (
              <option key={einer.wert} value={einer.wert}>
                {einer.titel}
              </option>
            ))}
          </select>
        </Feld>

        {ausloeser.art === "zeitplan" && (
          <>
            <div className="auswahl" role="radiogroup" aria-label="Art des Zeitplans">
              <button type="button" role="radio" aria-checked={ausloeser.modus !== "intervall"} onClick={() => setEntwurf({ ...entwurf, ausloeser: { art: "zeitplan", modus: "uhrzeit", uhrzeit: "07:30" } })}>
                Zu einer Uhrzeit
              </button>
              <button type="button" role="radio" aria-checked={ausloeser.modus === "intervall"} onClick={() => setEntwurf({ ...entwurf, ausloeser: { art: "zeitplan", modus: "intervall", intervall_minuten: 60 } })}>
                In einem festen Abstand
              </button>
            </div>
            {ausloeser.modus === "intervall" ? (
              <Feld titel="Abstand in Minuten" fuer={`${id}-intervall`} hilfe="60 = jede Stunde, 1440 = einmal am Tag.">
                <input id={`${id}-intervall`} type="number" min={1} max={10080} value={ausloeser.intervall_minuten ?? ""} onChange={(e) => setzeAusloeser({ intervall_minuten: e.target.value })} />
              </Feld>
            ) : (
              <Feld titel="Uhrzeit" fuer={`${id}-uhrzeit`} hilfe={`Zeitzone: ${optionen.zeitzone}. An welchen Tagen, steht unter „Nur wenn“.`}>
                <input id={`${id}-uhrzeit`} type="time" value={ausloeser.uhrzeit ?? ""} onChange={(e) => setzeAusloeser({ uhrzeit: e.target.value })} />
              </Feld>
            )}
          </>
        )}

        {ausloeser.art === "messwert" && (
          <div className="felder-reihe">
            <Feld titel="Messwert" fuer={`${id}-messwert`}>
              <select id={`${id}-messwert`} value={ausloeser.messwert ?? ""} onChange={(e) => setzeAusloeser({ messwert: e.target.value })}>
                {optionen.messwerte.map((einer) => (
                  <option key={einer.kennung} value={einer.kennung}>
                    {einer.titel}
                    {einer.verfuegbar ? "" : " (hier nicht vorhanden)"}
                  </option>
                ))}
              </select>
            </Feld>
            <Feld titel="Vergleich" fuer={`${id}-vergleich`}>
              <select id={`${id}-vergleich`} value={ausloeser.vergleich ?? "ueber"} onChange={(e) => setzeAusloeser({ vergleich: e.target.value as "ueber" | "unter" })}>
                <option value="ueber">liegt über</option>
                <option value="unter">liegt unter</option>
              </select>
            </Feld>
            <Feld titel={`Schwelle${messwert?.einheit ? ` (${messwert.einheit})` : ""}`} fuer={`${id}-schwelle`}>
              <input id={`${id}-schwelle`} type="number" step="any" value={ausloeser.schwelle ?? ""} onChange={(e) => setzeAusloeser({ schwelle: e.target.value })} />
            </Feld>
            <Feld titel="Mindestdauer (Minuten)" fuer={`${id}-dauer`} hilfe="0 = sofort">
              <input id={`${id}-dauer`} type="number" min={0} max={1440} value={ausloeser.dauer_minuten ?? 0} onChange={(e) => setzeAusloeser({ dauer_minuten: e.target.value })} />
            </Feld>
          </div>
        )}

        {ausloeser.art === "geraet" && (
          <div className="felder-reihe">
            <Feld titel="Gerät" fuer={`${id}-geraet`} hilfe={optionen.geraete.length === 0 ? "Noch kein Gerät eingerichtet – die Regel gilt für jedes, das dazukommt." : undefined}>
              <select id={`${id}-geraet`} value={ausloeser.geraet_id ?? ""} onChange={(e) => setzeAusloeser({ geraet_id: nummer(e.target.value) })}>
                <option value="">Jedes Gerät</option>
                {optionen.geraete.map((eines) => (
                  <option key={eines.id} value={eines.id}>
                    {eines.name}
                  </option>
                ))}
              </select>
            </Feld>
            <Feld titel="Was es meldet" fuer={`${id}-faehigkeit`} hilfe="z. B. knopf – leer lassen für alles">
              <input id={`${id}-faehigkeit`} type="text" value={ausloeser.faehigkeit ?? ""} onChange={(e) => setzeAusloeser({ faehigkeit: e.target.value })} />
            </Feld>
          </div>
        )}

        {ausloeser.art === "webhook" && (
          <Feld
            titel="Webhook"
            fuer={`${id}-webhook`}
            hilfe={
              optionen.webhooks.length === 0 ? (
                <>
                  Noch kein Webhook eingerichtet. Im <Link to="/katalog">Katalog</Link> lässt sich einer hinzufügen.
                </>
              ) : undefined
            }
          >
            <select id={`${id}-webhook`} value={ausloeser.integration_id ?? ""} onChange={(e) => setzeAusloeser({ integration_id: nummer(e.target.value) })}>
              <option value="">Jeder Webhook</option>
              {optionen.webhooks.map((einer) => (
                <option key={einer.id} value={einer.id}>
                  {einer.name}
                </option>
              ))}
            </select>
          </Feld>
        )}

        {ausloeser.art === "integration_ausgefallen" && (
          <Feld titel="Integration" fuer={`${id}-integration`}>
            <select id={`${id}-integration`} value={ausloeser.integration_id ?? ""} onChange={(e) => setzeAusloeser({ integration_id: nummer(e.target.value) })}>
              <option value="">Jede Integration</option>
              {optionen.integrationen.map((eine) => (
                <option key={eine.id} value={eine.id}>
                  {eine.name}
                </option>
              ))}
            </select>
          </Feld>
        )}
      </fieldset>

      <fieldset className="regel-teil">
        <legend>Nur wenn (freiwillig)</legend>
        <div className="tage" role="group" aria-label="Wochentage">
          {TAGE.map((kurz, tag) => (
            <button
              key={kurz}
              type="button"
              aria-pressed={tage.includes(tag)}
              aria-label={TAGE_LANG[tag]}
              onClick={() => setzeBedingung({ tage: tage.includes(tag) ? tage.filter((einer) => einer !== tag) : [...tage, tag].sort() })}
            >
              {kurz}
            </button>
          ))}
        </div>
        <div className="felder-reihe">
          <Feld titel="Von" fuer={`${id}-von`}>
            <input id={`${id}-von`} type="time" value={bedingung.von ?? ""} onChange={(e) => setzeBedingung({ von: e.target.value })} />
          </Feld>
          <Feld titel="Bis" fuer={`${id}-bis`}>
            <input id={`${id}-bis`} type="time" value={bedingung.bis ?? ""} onChange={(e) => setzeBedingung({ bis: e.target.value })} />
          </Feld>
        </div>
        <div className="feld-hilfe">Ohne Auswahl gilt die Regel an jedem Tag und zu jeder Uhrzeit.</div>
      </fieldset>

      <fieldset className="regel-teil">
        <legend>Dann</legend>
        <Feld titel="Aktion" fuer={`${id}-aktion`}>
          <select id={`${id}-aktion`} value={aktion.art} onChange={(e) => setEntwurf({ ...entwurf, aktion: aktionStart(e.target.value) })}>
            {optionen.aktionen.map((eine) => (
              <option key={eine.wert} value={eine.wert}>
                {eine.titel}
              </option>
            ))}
          </select>
        </Feld>

        {aktion.art === "ereignis" && (
          <>
            <Feld titel="Nachricht an Missa" fuer={`${id}-nachricht`} pflicht hilfe="Missa bekommt die Nachricht als Ereignis. {wert} steht für den aktuellen Messwert.">
              <textarea id={`${id}-nachricht`} rows={2} maxLength={500} placeholder="z. B. Die CPU ist seit 5 Minuten bei {wert} %." value={aktion.nachricht ?? ""} onChange={(e) => setzeAktion({ nachricht: e.target.value })} />
            </Feld>
            <Feld titel="Dringlichkeit" fuer={`${id}-dringlichkeit`}>
              <select id={`${id}-dringlichkeit`} value={aktion.dringlichkeit ?? "normal"} onChange={(e) => setzeAktion({ dringlichkeit: e.target.value })}>
                {optionen.dringlichkeiten.map((eine) => (
                  <option key={eine}>{eine}</option>
                ))}
              </select>
            </Feld>
          </>
        )}

        {aktion.art === "funktion" && (
          <>
            <Feld
              titel="Funktion"
              fuer={`${id}-funktion`}
              pflicht
              hilfe={
                optionen.funktionen.length === 0 ? (
                  <>
                    Noch keine Funktionen vorhanden. Im <Link to="/katalog">Katalog</Link> lässt sich eine Integration einrichten.
                  </>
                ) : (
                  funktion?.beschreibung
                )
              }
            >
              <select id={`${id}-funktion`} value={aktion.funktion ?? ""} onChange={(e) => setzeAktion({ funktion: e.target.value, argumente: {} })}>
                <option value="">Bitte wählen …</option>
                {integrationen.map((integration) => (
                  <optgroup key={integration} label={integration}>
                    {optionen.funktionen
                      .filter((eine) => eine.integration === integration)
                      .map((eine) => (
                        <option key={eine.name} value={eine.name}>
                          {eine.name}
                        </option>
                      ))}
                  </optgroup>
                ))}
              </select>
            </Feld>
            {funktion && <ParameterFelder schema={funktion.parameter} werte={aktion.argumente ?? {}} onAendern={(argumente) => setzeAktion({ argumente })} />}
            {funktion?.recht === "nachfragen" && (
              <div className="feld-hilfe">Missa muss bei dieser Funktion erst nachfragen. Die Regel führt sie ohne Nachfrage aus – du richtest sie hier ja selbst ein.</div>
            )}
          </>
        )}
      </fieldset>

      {ausloeser.art !== "zeitplan" && (
        <Feld titel="Ruhezeit (Minuten)" fuer={`${id}-ruhezeit`} hilfe="So lange bleibt die Regel nach einer Auslösung still. 0 = löst jedes Mal aus.">
          <input id={`${id}-ruhezeit`} type="number" min={0} max={10080} value={entwurf.ruhezeit_minuten} onChange={(e) => setEntwurf({ ...entwurf, ruhezeit_minuten: e.target.value })} />
        </Feld>
      )}

      <div className="regel-vorschau" aria-live="polite">
        <div className="gedaempft klein">So liest sich die Regel</div>
        {vorschau.data?.ok && <p>{vorschau.data.satz}</p>}
        {vorschau.data && !vorschau.data.ok && <p className="gedaempft">Noch nicht vollständig: {vorschau.data.meldung}</p>}
      </div>

      <FehlerMeldung fehler={speichern.error} />
      <div className="dialog-fuss">
        <Knopf onClick={onAbbrechen}>Abbrechen</Knopf>
        <Knopf art="haupt" type="submit" disabled={speichern.isPending}>
          {speichern.isPending ? "Speichere …" : "Speichern"}
        </Knopf>
      </div>
    </form>
  );
}
