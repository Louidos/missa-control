# API hinzufügen

Mit der Karte **„API hinzufügen“** (ganz vorne im Katalog) bekommt Missa Zugriff auf eine beliebige
REST-API – nur mit der Adresse und, falls nötig, einem Key. Eine OpenAPI-Datei musst du nicht suchen.

## In einem Schritt

1. **Katalog → „API hinzufügen“** öffnen.
2. **Adresse der API** eintragen, z. B. `https://api.example.ch/v1`. Verlangt die API einen Key:
   unter **Zugang** einen vorhandenen Zugang wählen oder direkt einen neuen anlegen.
3. **„Testen und aktivieren“** – fertig.

Danach stehen die Funktionen sofort am Gateway `/mcp` – Missa sieht sie beim nächsten `tools/list`,
ohne Neustart. Lesende Funktionen sind erlaubt, schreibende fragen erst nach (unter „Freigaben“). Die
Rechte lassen sich jederzeit unter **Integrationen** ändern.

## Was beim Testen passiert

Das Panel sucht selbst nach einer **OpenAPI-Beschreibung** – unter der Adresse und unter ihrem
Ursprung (`https://api.example.ch`), an den üblichen Stellen:

`openapi.json`, `swagger.json`, `v3/api-docs`, `api-docs`, `api/openapi.json`,
`swagger/v1/swagger.json`, `openapi.yaml`, `api/schema/`

Es probiert höchstens 10 Adressen, je höchstens 5 Sekunden, insgesamt höchstens 20 Sekunden.

- **Beschreibung gefunden:** Aus jedem Endpunkt wird eine Funktion (GET = lesend, alles andere =
  schreibend). Das Testergebnis sagt, wo die Beschreibung lag und wie viele Funktionen entstanden sind.
- **Keine gefunden:** Missa bekommt zwei allgemeine Funktionen:

  | Funktion | Was sie tut | Parameter |
  | --- | --- | --- |
  | `…_abrufen` | liest Daten (GET) – lesend | `pfad`, optional `parameter` (URL-Parameter) |
  | `…_senden` | ändert etwas (POST, PUT, PATCH, DELETE) – schreibend | `methode`, `pfad`, optional `daten` (JSON), `parameter` |

  `pfad` ist immer der Teil nach der Adresse, z. B. `/artikel/12`.

## Weitere Felder

| Feld | Wofür |
| --- | --- |
| **Wie wird der Key gesendet?** | `Authorization: Bearer …` (Standard), ein eigener Header (z. B. `X-API-Key`), ein URL-Parameter (z. B. `?api_key=…`) oder Benutzer und Passwort (Basic). Beim Header und beim URL-Parameter steht der Name in der Doku der API. |
| **Was ist das für eine API?** | Ein Satz wie „Lagerverwaltung – Artikel, Bestände und Lieferungen“. Er kommt in die Funktionsbeschreibungen, damit Missa weiss, wofür die API gut ist. |
| **Eigene Endpunkte** (aufklappbar) | Je Zeile Name, Methode, Pfad und Beschreibung – jede Zeile wird eine eigene Funktion. Platzhalter wie `{id}` im Pfad werden zu Parametern, bei allem ausser GET kommt `daten` dazu. GET ist lesend, alles andere schreibend. |

Eigene Endpunkte sind praktisch, wenn die API keine Beschreibung hat, Missa aber ein paar Aufgaben
ganz gezielt erledigen soll (z. B. `artikel_lesen` → `GET /artikel/{id}`).

## Sicherheit

- Aufrufe gehen **nur an die eingetragene Adresse**: gleiches Schema (http/https), gleicher Host und
  Port, nur Pfade unterhalb des Basis-Pfads. Ein `pfad` mit `..` oder einer vollständigen Adresse wird
  mit einer Meldung abgelehnt, ohne dass etwas gesendet wird.
- **Weiterleitungen** werden nur innerhalb dieser Adresse verfolgt. Leitet die API auf einen anderen
  Host weiter, bricht der Aufruf mit einer Meldung ab.
- Der **Key** steht in keinem Ergebnis, keiner Fehlermeldung, keinem Log und keinem Protokoll – auch
  dann nicht, wenn die API ihn in ihrer Antwort zurückschickt (er wird geschwärzt).
- Sehr lange Antworten werden gekürzt (höchstens 100 000 Zeichen).

## Prüfung im Betrieb

Wie alle Integrationen mit einer Gegenstelle prüft das Panel die API alle 20 Sekunden – mit einer
einzigen, günstigen Anfrage an die Adresse (ohne erneute Suche nach der Beschreibung). Antwortet die
API nicht oder lehnt sie den Zugang ab (401/403), steht die Integration auf rot und es gibt ein
Ereignis „Integration ausgefallen“.

## Neue Funktionen der API übernehmen

Hat die API neue Endpunkte bekommen: unter **Integrationen** bei der API **„Erneut testen“**. Neue
Funktionen kommen dazu, bekannte behalten ihr Recht.

## Und die Karte „REST-API (OpenAPI)“?

Die gibt es weiterhin – für den Fall, dass du eine OpenAPI-Datei selbst hast (hochladen) oder die
Beschreibung an einer ungewöhnlichen Adresse liegt.
