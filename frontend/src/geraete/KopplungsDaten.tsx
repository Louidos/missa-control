import { Download } from "lucide-react";
import { useId, useState } from "react";

import { KopierFeld } from "../ui/KopierFeld";
import { Feld, Knopf, Meldung } from "../ui/ui";
import { type Board, BOARDS, herunterladen, konfigDatei, type Kopplung } from "./geraete";

function vorschlagHost(): string {
  const host = window.location.hostname;
  return host === "localhost" || host === "127.0.0.1" || host === "::1" ? "" : host;
}

/**
 * Die Zugangsdaten eines frisch gekoppelten Geräts – mit der fertig ausgefüllten Konfigurationsdatei
 * für die Beispiel-Firmware. Das Passwort ist nur hier und nur jetzt zu sehen.
 */
export function KopplungsDaten({ name, kopplung }: { name: string; kopplung: Kopplung }) {
  const id = useId();
  const [board, setBoard] = useState<Board>("pico");
  const [host, setHost] = useState(vorschlagHost);
  const [wlanName, setWlanName] = useState("");
  const [wlanPasswort, setWlanPasswort] = useState("");
  const [geladen, setGeladen] = useState(false);

  const gewaehlt = BOARDS.find((eintrag) => eintrag.wert === board) ?? BOARDS[0];
  const inhalt = konfigDatei(board, name, kopplung, { host: host.trim(), wlanName, wlanPasswort });
  const vollstaendig = host.trim() !== "" && wlanName !== "";

  return (
    <div className="stapel">
      <Meldung art="warn" hinweis="Später lässt es sich nicht mehr anzeigen – dann hilft nur „Neu koppeln“ auf der Seite „Geräte“.">
        Das Passwort des Geräts ist nur jetzt zu sehen. Lade die Konfiguration gleich herunter.
      </Meldung>

      <div className="felder-reihe">
        <Feld titel="Board" fuer={`${id}-board`}>
          <select id={`${id}-board`} value={board} onChange={(e) => setBoard(e.target.value as Board)}>
            {BOARDS.map((eintrag) => (
              <option key={eintrag.wert} value={eintrag.wert}>
                {eintrag.titel}
              </option>
            ))}
          </select>
        </Feld>
        <Feld
          titel="Adresse dieses Servers im WLAN"
          fuer={`${id}-host`}
          hilfe={`Unter dieser Adresse erreicht das Gerät den MQTT-Broker (Port ${kopplung.port}), z. B. 192.168.1.10.`}
        >
          <input id={`${id}-host`} type="text" value={host} placeholder="192.168.1.10" onChange={(e) => setHost(e.target.value)} />
        </Feld>
      </div>
      <div className="felder-reihe">
        <Feld titel="WLAN-Name" fuer={`${id}-wlan`}>
          <input id={`${id}-wlan`} type="text" autoComplete="off" value={wlanName} onChange={(e) => setWlanName(e.target.value)} />
        </Feld>
        <Feld titel="WLAN-Passwort" fuer={`${id}-wlan-passwort`} hilfe="Bleibt in deinem Browser: Es steht nur in der Datei, die du herunterlädst.">
          <input
            id={`${id}-wlan-passwort`}
            type="password"
            autoComplete="off"
            value={wlanPasswort}
            onChange={(e) => setWlanPasswort(e.target.value)}
          />
        </Feld>
      </div>

      <div className="reihe">
        <Knopf
          art="haupt"
          disabled={!vollstaendig}
          onClick={() => {
            herunterladen(gewaehlt.datei, inhalt);
            setGeladen(true);
          }}
        >
          <Download aria-hidden />
          {gewaehlt.datei} herunterladen
        </Knopf>
        {!vollstaendig && <span className="gedaempft klein">Erst Adresse und WLAN-Name eintragen.</span>}
        {geladen && <span className="gedaempft klein">Heruntergeladen. {gewaehlt.ablegen}</span>}
      </div>

      <ol className="gedaempft klein schritt-liste">
        <li>
          Die Beispiel-Firmware liegt im Repo unter <code>{gewaehlt.ordner}</code> (Anleitung: <code>docs/geraete.md</code>).
        </li>
        <li>{gewaehlt.ablegen}</li>
        <li>Sobald das Gerät Strom hat, erscheint es auf der Seite „Geräte“ als online.</li>
      </ol>

      <details className="einklappbar">
        <summary>Zugangsdaten für eigene Firmware anzeigen</summary>
        <div className="stapel eng">
          <Feld titel="Benutzer (zugleich Client-ID)" fuer={`${id}-benutzer`}>
            <KopierFeld id={`${id}-benutzer`} wert={kopplung.benutzer} beschriftung="Benutzer kopieren" />
          </Feld>
          <Feld titel="Passwort" fuer={`${id}-passwort`}>
            <KopierFeld id={`${id}-passwort`} wert={kopplung.passwort} beschriftung="Passwort kopieren" />
          </Feld>
          <Feld titel="Themen" fuer={`${id}-themen`} hilfe="Das Gerät darf nur unter seinen eigenen Themen senden und nur seine eigenen Befehle empfangen.">
            <pre id={`${id}-themen`} className="ergebnis">
              {[
                `${kopplung.themen.status}  →  online / offline (gemerkt, „offline“ als letzter Wille)`,
                `${kopplung.themen.faehigkeiten}  →  JSON: was das Gerät kann (gemerkt)`,
                `${kopplung.themen.wert}  →  Messwert eines Sensors`,
                `${kopplung.themen.ereignis}  →  Knopfdruck`,
                `${kopplung.themen.zustand}  →  Zustand eines Aktors`,
                `${kopplung.themen.befehl}  ←  Befehl an einen Aktor`,
              ].join("\n")}
            </pre>
          </Feld>
          <Feld titel={`Inhalt von ${gewaehlt.datei}`} fuer={`${id}-datei`}>
            <pre id={`${id}-datei`} className="ergebnis" aria-label={`Inhalt von ${gewaehlt.datei}`}>
              {inhalt}
            </pre>
          </Feld>
        </div>
      </details>
    </div>
  );
}
