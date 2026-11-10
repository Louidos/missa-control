# Anbindung an missa-core

Diese Anleitung beschreibt, wie **du selbst** missa-core mit Missa Control verbindest.

> **Missa Control verändert missa-core nie.** Kein Skript und keine Funktion des Panels fasst Code,
> Container, Volumes, Netzwerke oder Compose-Dateien von missa-core an. Das Panel schickt auch
> nichts an missa-core. Alles, was Missa braucht, **holt missa-core selbst ab** – über die
> Anschlüsse unten. Die Änderungen dafür machst du von Hand in missa-core.

## Überblick

| Was Missa braucht | Anschluss am Panel | Art |
| --- | --- | --- |
| Funktionen (Tools) aller Integrationen | `/mcp` | MCP, Streamable HTTP |
| Ereignisse (Regel ausgelöst, Gerät meldet, …) | `/api/events/stream` und `/api/events` | Server-Sent Events bzw. Abfrage |
| Was ist eingerichtet? | `/api/config/integrations` | JSON, nur lesend |
| Charakterprofil | `/api/config/profile` | JSON, nur lesend |
| Sprachmodelle (schnell / stark) | `/v1/chat/completions`, `/v1/models` | OpenAI-kompatibel |

Alle Anschlüsse verlangen denselben **Client-Token** im Header
`Authorization: Bearer <Token>`. Ohne gültigen Token antwortet das Panel mit `401`.

## Schritt 1: Client anlegen

1. Im Panel **Clients → Neuer Client** öffnen, Namen eingeben (z. B. `missa-core`).
2. Den angezeigten Token kopieren. **Er wird nur dieses eine Mal angezeigt.**
3. Den Token in missa-core als Geheimnis ablegen (z. B. in dessen `.env` – nicht ins Repo).

Jeder Client bekommt einen eigenen Token. Geht einer verloren oder wird er nicht mehr gebraucht:
**Clients → Token widerrufen**. Das wirkt sofort; ein bereits offener Ereignis-Stream endet innerhalb
weniger Sekunden.

## Schritt 2: Adresse des Panels

Das Panel lauscht auf ai01 auf Port `8090` (einstellbar über `MISSA_CONTROL_BIND` in `.env`).

- Läuft missa-core direkt auf ai01: `http://127.0.0.1:8090`
- Läuft missa-core in einem Container auf ai01: `http://<IP-Adresse von ai01>:8090`
  („localhost“ meint im Container den Container selbst, nicht ai01.)

Mehr braucht es nicht. Wer missa-core lieber ins Docker-Netzwerk `missa-control-net` hängen möchte,
kann das in der Compose-Datei von missa-core selbst eintragen – nötig ist es nicht, und Missa Control
tut das nie von sich aus.

Kurzer Test von dort, wo missa-core läuft:

```bash
curl -s http://<adresse>:8090/api/health
```

## Schritt 3: Funktionen über das MCP-Gateway

Das Gateway bündelt die Funktionen **aller aktiven Integrationen** an einem einzigen MCP-Endpoint.
missa-core muss also nur diesen einen MCP-Server kennen – neue Integrationen im Panel erscheinen
dort von selbst.

| Einstellung | Wert |
| --- | --- |
| URL | `http://<adresse>:8090/mcp` |
| Transport | Streamable HTTP |
| Header | `Authorization: Bearer <Token>` |

Viele MCP-Clients nehmen eine Konfiguration in dieser Form:

```json
{
  "mcpServers": {
    "missa-control": {
      "type": "http",
      "url": "http://<adresse>:8090/mcp",
      "headers": { "Authorization": "Bearer <Token>" }
    }
  }
}
```

Mit dem MCP-Python-SDK sieht die Verbindung so aus:

```python
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

kopf = {"Authorization": f"Bearer {TOKEN}"}
zeitlimit = httpx2.Timeout(30, read=330)  # Freigaben dürfen bis zu 5 Minuten dauern
async with httpx2.AsyncClient(headers=kopf, timeout=zeitlimit) as http:
    async with Client(streamable_http_client("http://<adresse>:8090/mcp", http_client=http)) as client:
        funktionen = (await client.list_tools()).tools
        ergebnis = await client.call_tool("kalender_termine_anzeigen", {"tage": 7})
```

Test ohne Programm:

```bash
curl -s http://<adresse>:8090/mcp \
  -H "Authorization: Bearer <Token>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

### Was missa-core dabei wissen muss

- **Namen:** Jede Funktion trägt die Vorsilbe ihrer Integration, z. B. `kalender_termine_anzeigen`.
  Die Namen bleiben gleich, auch wenn die Integration im Panel umbenannt wird.
- **Sichtbarkeit:** Sichtbar sind nur Funktionen aktiver Integrationen, die nicht „gesperrt“ sind.
  Änderungen im Panel wirken sofort. Die Liste am besten zu Beginn jedes Gesprächs neu holen
  (`tools/list`) – das Gateway merkt sich keine Sitzungen und übersteht Neustarts des Panels.
- **„Erst nachfragen“:** Solche Funktionen hält das Gateway an, bis du im Panel unter „Freigaben“
  entschieden hast. Der Aufruf bleibt so lange offen – **höchstens 5 Minuten**. Das Zeitlimit für
  Tool-Aufrufe in missa-core sollte deshalb mindestens 5½ Minuten betragen. In der Beschreibung
  dieser Funktionen steht ein Hinweis, damit Missa sagen kann: „Ich warte auf deine Freigabe.“
- **Ablehnung und Zeitablauf:** kommen als normales Ergebnis mit `isError: true` und einem Satz,
  den Missa direkt weitergeben kann, z. B. „Die Aktion … wurde vom Besitzer im Panel abgelehnt und
  nicht ausgeführt.“
- **Fehler von Integrationen** (Dienst nicht erreichbar, falscher Key, …) kommen ebenfalls mit
  `isError: true`, verständlicher Meldung und Lösungshinweis.
- **Zugänge:** API-Keys und Passwörter setzt das Panel ein. missa-core sieht sie nie.

### Gedächtnis

Ist im Panel die Integration „Gedächtnis“ aktiv, stehen am Gateway drei Funktionen bereit:

| Funktion | Zweck | Standardrecht |
| --- | --- | --- |
| `gedaechtnis_merken` | merkt sich einen Satz (`text`, optional `kategorie`) | erlaubt |
| `gedaechtnis_suchen` | sucht nach Stichwörtern (`text`), optional nur in einer `kategorie` | erlaubt |
| `gedaechtnis_vergessen` | löscht einen Eintrag (`id` aus der Suche) | erst nachfragen |

Kategorien: `vorlieben`, `gewohnheiten`, `projektwissen`, `personen`, `sonstiges`. Damit Missa das
Gedächtnis von sich aus nutzt, hilft ein Satz im Charakterprofil, z. B.: „Merke dir Dinge, die für
später wichtig sind, mit `gedaechtnis_merken` und sieh mit `gedaechtnis_suchen` nach, bevor du
nach etwas fragst, das du schon wissen könntest.“ Alle Einträge stehen im Panel unter „Gedächtnis“.

### Regeln

Mit der Integration „Regeln“ kann Missa Regeln und Alarme per Sprache verwalten („Sag mir Bescheid,
wenn die CPU länger als 5 Minuten über 90 % liegt“):

| Funktion | Zweck | Standardrecht |
| --- | --- | --- |
| `regeln_auflisten` | alle Regeln mit Nummer, Name und einem Satz, was sie tun | erlaubt |
| `regeln_regel_anlegen` | neue Regel aus Auslöser, Bedingung und Aktion | erst nachfragen |
| `regeln_regel_aendern` | einzelne Angaben ändern, pausieren (`aktiv: false`) | erst nachfragen |
| `regeln_regel_loeschen` | Regel löschen | erst nachfragen |

Die Parameter sind einzeln benannt und beschrieben (z. B. `ausloeser: "messwert"`, `messwert: "cpu"`,
`schwelle: 90`, `dauer_minuten: 5`, `nachricht: "…"`), damit auch kleinere Modelle sie zuverlässig
füllen. In der Freigabe steht die Regel als ganzer Satz – du siehst also, was Missa anlegen möchte,
bevor du zustimmst. Eine Regel, deren Aktion eine Funktion aufruft, führt diese später ohne weitere
Nachfrage aus: die Freigabe der Regel gilt dafür.

Löst eine Regel mit der Aktion „Ereignis an Missa“ aus, kommt das als Ereignis der Art `regel`
(siehe Schritt 4).

### Kalender und Home Assistant

Die fertigen Integrationen aus dem Katalog bringen diese Funktionen mit (Vorsilbe wie im Panel
angezeigt; bei mehreren Kalendern heisst der zweite `kalender_2_…`):

| Funktion | Zweck | Standardrecht |
| --- | --- | --- |
| `kalender_termine_anzeigen` | Termine in einem Zeitraum (`von`, `bis`, `suche`) – ohne Angaben die nächsten 7 Tage | erlaubt |
| `kalender_termin_eintragen` | neuer Termin (`titel`, `beginn`, optional `ende`, `ort`, `beschreibung`) | erst nachfragen |
| `kalender_termin_aendern` | Termin ändern (`id` aus dem Anzeigen, dazu nur das, was sich ändert) | erst nachfragen |
| `kalender_termin_loeschen` | Termin löschen (`id`) | erst nachfragen |
| `home_assistant_geraete_anzeigen` | Geräte mit Zustand (`art`, `suche`) | erlaubt |
| `home_assistant_zustand_lesen` | ein Gerät genau (`id`, z. B. `light.wohnzimmer`) | erlaubt |
| `home_assistant_einschalten` / `…_ausschalten` | Gerät schalten (`id`) | erst nachfragen |
| `home_assistant_dienst_aufrufen` | beliebiger Dienst (`dienst`, `id`, `daten`) | erst nachfragen |

Zeitangaben für den Kalender dürfen `2026-11-12 14:00`, `12.11.2026 14:00`, `heute`, `morgen` oder
`morgen 9:30` sein; gemeint ist immer die Ortszeit (`MISSA_CONTROL_ZEITZONE`). Die Antwort von
`kalender_termine_anzeigen` nennt das heutige Datum – praktisch, falls Missa es nicht kennt.

Ist in Home Assistant der **MCP-Server** eingerichtet (Integration „Model Context Protocol Server“),
reicht das Panel stattdessen dessen Werkzeuge durch, z. B. `home_assistant_HassTurnOn` und
`home_assistant_GetLiveContext`. Welche Geräte dabei sichtbar sind, bestimmt Home Assistant.

## Schritt 4: Ereignisse abholen

Ereignisse sind Dinge, die Missa wissen sollte, ohne gefragt zu haben: eine Regel hat ausgelöst,
ein Gerät meldet etwas, ein Webhook ist eingegangen, eine Integration ist ausgefallen, eine
Freigabe wartet.

### Laufend, per Stream (empfohlen)

```bash
curl -N http://<adresse>:8090/api/events/stream -H "Authorization: Bearer <Token>"
```

Der Stream liefert Server-Sent Events. Jedes Ereignis sieht so aus:

```text
id: 42
event: ereignis
data: {"id": 42, "zeit": "2026-01-15T12:00:00+00:00", "art": "regel", "quelle": "Regeln", "titel": "Regel „CPU-Alarm“ ausgelöst", "nachricht": "Die CPU von ai01 liegt seit 5 Minuten über 90 %.", "dringlichkeit": "hoch", "daten": {"regel_id": 1, "regel": "CPU-Alarm", "anlass": "CPU-Auslastung: 97,4 % (über 90 % seit 5 Minuten)", "wert": 97.4, "test": false}}
```

- Zeilen, die mit `:` beginnen, sind Lebenszeichen (etwa alle 15 Sekunden) und können ignoriert werden.
- Nach einer Unterbrechung beim Wiederverbinden den Header `Last-Event-ID: <letzte id>` mitsenden
  (oder `?nach_id=<letzte id>` anhängen): Das Panel liefert zuerst alles Verpasste nach.

### Auf Abruf

```bash
curl -s "http://<adresse>:8090/api/events?seit=2026-01-15T12:00:00Z" -H "Authorization: Bearer <Token>"
```

| Parameter | Bedeutung |
| --- | --- |
| `seit` | Zeitpunkt (ISO 8601): nur Ereignisse ab dann |
| `nach_id` | nur Ereignisse mit grösserer Nummer (praktisch zum Weiterblättern) |
| `limit` | höchstens so viele (Standard 200, maximal 1000) |

Antwort: `{"ereignisse": [...], "letzte_id": 42}` – älteste zuerst.

### Felder eines Ereignisses

| Feld | Inhalt |
| --- | --- |
| `id` | fortlaufende Nummer, wird nie wiederverwendet |
| `zeit` | Zeitpunkt in UTC (ISO 8601) |
| `art` | `regel`, `geraet`, `webhook`, `integration_ausgefallen`, `integration_wieder_da`, `freigabe`, `anruf`, `test` |
| `quelle` | woher es kommt (z. B. `Regeln`, Name des Geräts oder der Integration) |
| `titel` | kurze Überschrift |
| `nachricht` | ausformulierter Text, den Missa vorlesen kann |
| `dringlichkeit` | `niedrig`, `normal`, `hoch` oder `dringend` |
| `daten` | weitere Angaben je nach Art (z. B. Messwert, Nummer der Freigabe; bei `webhook` steht unter `inhalt`, was empfangen wurde) |

Ereignisse bleiben 30 Tage gespeichert.

**Testen:** Im Panel unter **Protokoll → Ereignisse → Test-Ereignis senden**. Das Ereignis muss
im Stream von missa-core ankommen.

## Schritt 5: Konfiguration lesen

```bash
curl -s http://<adresse>:8090/api/config/integrations -H "Authorization: Bearer <Token>"
```

liefert alle aktiven Integrationen mit ihren sichtbaren Funktionen, dem Recht jeder Funktion
(`erlaubt` oder `nachfragen`) und dem Status der Integration (`ok` oder `fehler`). Nützlich, wenn
Missa wissen soll, was sie kann, ohne erst die Tool-Liste zu holen.

```bash
curl -s http://<adresse>:8090/api/config/profile -H "Authorization: Bearer <Token>"
```

liefert Missas Charakterprofil. Solange im Panel noch keines gespeichert ist, steht dort
`"vorhanden": false`.

Die Konfig-API ist **nur lesend** – es gibt keine Möglichkeit, darüber etwas zu ändern.

## Schritt 6: Modelle über den Modell-Anschluss

Unter **Modelle** legst du im Panel fest, welches Sprachmodell für welche Aufgabe verwendet wird.
missa-core kennt nur feste Namen – welches Modell gerade dahinter steckt, kann sich im Panel jederzeit
ändern, ohne dass in missa-core etwas angepasst werden muss.

| Einstellung in missa-core | Wert |
| --- | --- |
| Basis-URL (OpenAI-kompatibel) | `http://<adresse>:8090/v1` |
| API-Key | der Client-Token |
| Modell für Gespräche | `missa-schnell` |
| Modell für schwierige Aufgaben | `missa-stark` |

Weitere Rollen, die du im Panel anlegst, heissen entsprechend `missa-<kurzname>`.

```bash
curl -s http://<adresse>:8090/v1/chat/completions \
  -H "Authorization: Bearer <Token>" \
  -H "Content-Type: application/json" \
  -d '{"model": "missa-schnell", "messages": [{"role": "user", "content": "Hallo Missa"}]}'
```

- **Streaming** funktioniert wie gewohnt mit `"stream": true`.
- **Ausfall:** Antwortet das Hauptmodell einer Rolle nicht, übernimmt automatisch das Ersatzmodell.
  Welches Modell geantwortet hat, steht im Antwort-Header `X-Missa-Modell`.
- **`GET /v1/models`** listet alle Rollen auf, für die ein Modell ausgewählt ist.
- Fehler kommen im Format der OpenAI-API (`{"error": {"message": …}}`) mit verständlichem Text.
- „Stark“ darf länger dauern: Das Zeitlimit in missa-core für diese Rolle grosszügig wählen.

## Prüfliste

- [ ] `curl …/api/health` antwortet von dort, wo missa-core läuft
- [ ] `tools/list` mit Token zeigt die Funktionen, ohne Token kommt `401`
- [ ] Eine „erlaubte“ Funktion lässt sich aufrufen und erscheint im Panel unter **Protokoll**
- [ ] Eine „erst nachfragen“-Funktion erscheint unter **Freigaben** und läuft nach „Erlauben“
- [ ] Ein Test-Ereignis kommt im Stream an
- [ ] `missa-schnell` antwortet über `/v1/chat/completions`
- [ ] Im Panel steht beim Client unter „Zuletzt gesehen“ eine aktuelle Zeit

## Wenn etwas nicht klappt

| Anzeichen | Ursache und Lösung |
| --- | --- |
| `401` mit „Kein gültiger Client-Token“ | Token fehlt, ist falsch oder widerrufen. Header prüfen: `Authorization: Bearer <Token>` |
| Verbindung wird abgelehnt / Zeitüberschreitung | Adresse oder Port falsch, Firewall, oder „localhost“ aus einem Container heraus verwendet |
| Tool-Aufruf bricht nach ~60 s ab | Zeitlimit in missa-core zu kurz für Freigaben – auf mindestens 5½ Minuten stellen |
| Funktion fehlt in `tools/list` | Integration deaktiviert, Funktion „gesperrt“ oder Status „Fehler“ – im Panel unter **Integrationen** nachsehen |
| „Die Funktion … gibt es nicht oder sie ist für Missa nicht freigegeben“ | Liste veraltet: `tools/list` neu holen |
