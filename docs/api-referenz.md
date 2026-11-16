# HTTP-Schnittstelle (Referenz)

Alle Pfade, die das Panel anbietet. Die Oberfläche benutzt sie selbst; für Clients wie
missa-core sind nur die **Anschlüsse** gedacht. Eine automatisch erzeugte API-Beschreibung
(`/docs`, `/openapi.json`) gibt es bewusst nicht.

Wie man missa-core Schritt für Schritt anbindet – mit Beispielen und den Feldern der
Antworten: [anbindung-missa-core.md](anbindung-missa-core.md). Wer welchen Weg benutzen darf:
[architektur.md](architektur.md#zwei-getrennte-wege-hinein).

## Zugang

| Kürzel | Bedeutung |
| --- | --- |
| **offen** | ohne Anmeldung |
| **Panel** | Sitzungs-Cookie nach Anmeldung mit Passwort + 2FA; `POST`, `PUT`, `PATCH`, `DELETE` nur von derselben Herkunft wie das Panel |
| **Client** | `Authorization: Bearer <Client-Token>` (Token unter **Clients** anlegen) |
| **Webhook** | der geheime Schlüssel in der Adresse ist der Zugang |

Fehler kommen immer als JSON mit verständlicher Meldung und – wenn möglich – einem
Lösungshinweis (`fehler.py`).

## Anschlüsse für Clients

| Methode | Pfad | Zugang | Zweck |
| --- | --- | --- | --- |
| `POST`, `GET` | `/mcp` | Client | MCP-Gateway (Streamable HTTP): `tools/list` und `tools/call` für alle Funktionen aktiver Integrationen |
| `GET` | `/api/events` | Client | Ereignisse abrufen, älteste zuerst; `?nach_id=` oder `?seit=` (ISO 8601), `?limit=` (Standard 200, max. 1000) |
| `GET` | `/api/events/stream` | Client | Ereignisse als Server-Sent Events; `Last-Event-ID` setzt nach einer Unterbrechung fort |
| `GET` | `/api/config/integrations` | Client | aktive Integrationen mit ihren sichtbaren Funktionen |
| `GET` | `/api/config/profile` | Client | Missas Charakterprofil (`vorhanden: false`, solange keins gespeichert ist) |
| `GET` | `/v1/models` | Client | Rollen als Modelle (`missa-schnell`, `missa-stark`, …) |
| `POST` | `/v1/chat/completions` | Client | leitet an das Modell der Rolle weiter, mit Ersatzmodell |
| `POST` | `/api/telefonie/adapter/eingehend` | Client | Telefon-Adapter meldet einen eingehenden Anruf; Antwort sagt, ob er ihn annehmen darf |
| `POST` | `/api/telefonie/adapter/anrufe/{anruf_id}/beendet` | Client | Telefon-Adapter meldet das Ende eines Anrufs (mit Dauer) |

## Webhooks

| Methode | Pfad | Zugang | Zweck |
| --- | --- | --- | --- |
| `POST` | `/api/webhook/{schlüssel}` | Webhook | Meldung entgegennehmen (JSON, Formularfelder oder Text) und daraus ein Ereignis machen |
| `PUT` | `/api/webhook/{schlüssel}` | Webhook | wie `POST`, für Dienste, die nur `PUT` senden |
| `GET` | `/api/webhook/{schlüssel}` | Webhook | wie `POST`, für einfache Geräte (`?nachricht=…`) |

## Betrieb und Login

| Methode | Pfad | Zugang | Zweck |
| --- | --- | --- | --- |
| `GET` | `/api/health` | offen | läuft das Panel? |
| `GET` | `/api/auth/status` | offen | eingerichtet? angemeldet? |
| `POST` | `/api/auth/einrichten` | offen | erster Aufruf: Passwort setzen, QR-Code für die 2FA bekommen |
| `POST` | `/api/auth/einrichten/bestaetigen` | offen | Einrichtung mit dem ersten Code abschliessen |
| `POST` | `/api/auth/anmelden` | offen | Anmelden mit Passwort und Code |
| `POST` | `/api/auth/abmelden` | Panel | Abmelden |

## Panel

Alle folgenden Pfade: Zugang **Panel**.

### Übersicht und Statistik

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `GET` | `/api/status` | alles Eingerichtete als Knoten und Kanten mit Status (`ok`, `warn`, `fehler`, `grau`) |
| `POST` | `/api/status/pruefen` | missa-core (nur lesend) und die Integrationen sofort prüfen |
| `PUT` | `/api/status/positionen` | Anordnung der Knoten speichern |
| `DELETE` | `/api/status/positionen` | eigene Anordnung verwerfen |
| `GET` | `/api/statistik` | Aufrufe, Fehlerquote und Dauer pro Integration und Funktion |
| `GET` | `/api/serverlast` | aktuelle Werte und Verlauf (1 Stunde, 24 Stunden, 7 Tage) |

### Katalog und Integrationen

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `GET` | `/api/katalog` | alle Karten (eingebaut und eigene) |
| `POST` | `/api/katalog/einlesen` | Integrations-Ordner neu einlesen |
| `POST` | `/api/katalog/hochladen` | eigene Integration hochladen |
| `DELETE` | `/api/katalog/{manifest_id}` | hochgeladene Integration aus dem Katalog entfernen |
| `POST` | `/api/integrationen/testen` | Angaben testen, bevor eine Integration angelegt wird |
| `GET` | `/api/integrationen` | eingerichtete Integrationen |
| `POST` | `/api/integrationen` | Integration anlegen |
| `GET` | `/api/integrationen/{id}` | eine Integration mit Funktionen und Rechten |
| `PUT` | `/api/integrationen/{id}` | ändern (Einstellungen, Rechte, Zugriffsstufe, aktiv) |
| `POST` | `/api/integrationen/{id}/testen` | Verbindung erneut testen |
| `POST` | `/api/integrationen/{id}/aufrufen` | „Ausprobieren“: Funktion direkt aufrufen (unabhängig von Missas Rechten) |
| `POST` | `/api/integrationen/{id}/webhook/erneuern` | neue geheime Webhook-Adresse; die alte gilt sofort nicht mehr |
| `DELETE` | `/api/integrationen/{id}` | Integration entfernen |

### Freigaben, Protokoll, Ereignisse, Clients

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `GET` | `/api/freigaben` | offene Freigaben, Verlauf und Frist |
| `GET` | `/api/freigaben/anzahl` | Zahl der offenen Freigaben (für das Abzeichen in der Navigation) |
| `POST` | `/api/freigaben/{id}` | entscheiden: `{"erlauben": true}` oder `false` |
| `GET` | `/api/protokoll` | Protokoll aller Aufrufe über das Gateway |
| `GET` | `/api/ereignisse` | Ereignisse ansehen |
| `POST` | `/api/ereignisse/test` | Test-Ereignis erzeugen (Anbindung prüfen) |
| `GET` | `/api/clients` | Clients |
| `POST` | `/api/clients` | Client anlegen (Token wird nur einmal angezeigt) |
| `POST` | `/api/clients/missa-core` | „Missa-Core verbinden“: neuer Client plus die zwei Zeilen für `/etc/missa/missa.env` |
| `POST` | `/api/clients/{id}/widerrufen` | Token widerrufen |
| `DELETE` | `/api/clients/{id}` | Client löschen |

### Zugänge

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `GET` | `/api/zugaenge` | Zugänge (nur maskiert) |
| `POST` | `/api/zugaenge` | Zugang anlegen |
| `PUT` | `/api/zugaenge/{id}` | ändern |
| `DELETE` | `/api/zugaenge/{id}` | löschen |

### Modelle und Rollen

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `GET` | `/api/modelle` | Modelle und Rollen |
| `POST` | `/api/modelle` | Modell-Endpunkt anlegen |
| `PUT` | `/api/modelle/{id}` | ändern |
| `DELETE` | `/api/modelle/{id}` | löschen |
| `POST` | `/api/modelle/{id}/testen` | Modell testen |
| `POST` | `/api/rollen` | Rolle anlegen |
| `PUT` | `/api/rollen/{id}` | Haupt- und Ersatzmodell einer Rolle ändern |
| `DELETE` | `/api/rollen/{id}` | Rolle löschen |

### Charakter

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `GET` | `/api/profil` | aktuelles Profil |
| `PUT` | `/api/profil` | speichern (neue Version) |
| `POST` | `/api/profil/vorschau` | Systemprompt aus einem (auch ungespeicherten) Profil |
| `GET` | `/api/profil/versionen` | Versionsverlauf |
| `GET` | `/api/profil/versionen/{id}` | eine Version |
| `POST` | `/api/profil/versionen/{id}/wiederherstellen` | Version wiederherstellen |
| `GET` | `/api/profil/export` | als YAML herunterladen |
| `POST` | `/api/profil/import` | YAML einlesen (gespeichert wird erst mit „Speichern“) |
| `GET` | `/api/profil/beispiel` | Beispielprofil |
| `POST` | `/api/profil/testchat` | Test-Chat mit dem Profil |

### Gedächtnis

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `GET` | `/api/gedaechtnis` | Einträge, gefiltert nach Suchtext, Kategorie und Quelle |
| `GET` | `/api/gedaechtnis/export` | ganzes Gedächtnis als JSON |
| `POST` | `/api/gedaechtnis` | Eintrag anlegen |
| `PUT` | `/api/gedaechtnis/{id}` | korrigieren |
| `DELETE` | `/api/gedaechtnis/{id}` | löschen |

### Regeln

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `GET` | `/api/regeln` | alle Regeln (mit lesbarem Satz) und die Auswahl für den Editor |
| `GET` | `/api/regeln/verlauf` | Verlauf der Auslösungen |
| `POST` | `/api/regeln/satz` | Angaben prüfen und als Satz zurückgeben (ohne zu speichern) |
| `POST` | `/api/regeln` | Regel anlegen |
| `PUT` | `/api/regeln/{id}` | ändern |
| `PATCH` | `/api/regeln/{id}` | pausieren oder wieder einschalten |
| `DELETE` | `/api/regeln/{id}` | löschen |
| `POST` | `/api/regeln/{id}/testen` | Aktion sofort ausführen |

### Geräte

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `GET` | `/api/geraete` | Geräte mit Status, Fähigkeiten, letzten Werten und Zustand des MQTT-Brokers |
| `GET` | `/api/geraete/{id}/verlauf` | Verlauf eines Sensors (1 Stunde, 24 Stunden, 7 Tage) |
| `POST` | `/api/geraete/{id}/koppeln` | neue Zugangsdaten; die bisherigen gelten sofort nicht mehr |

Geräte selbst legt man als Integration der Art „Gerät“ an.

### Telefonie

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `GET` | `/api/telefonie` | Einstellungen, Adapter, ob gerade Ruhezeit ist |
| `PUT` | `/api/telefonie/einstellungen` | eigene Nummern, erlaubte Anrufer, Ruhezeiten |
| `GET` | `/api/telefonie/anrufe` | Anrufverlauf |
| `POST` | `/api/telefonie/anrufen` | Test-Anruf aus dem Panel (ohne Freigabe) |
| `POST` | `/api/telefonie/eingehend-simulieren` | zeigt, ob eine Nummer durchkäme – es klingelt nirgends |

### Sicherung und Meldungen

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `POST` | `/api/sicherung/export` | Einrichtung als Datei herunterladen (Zugänge nur mit eigenem Passwort verschlüsselt) |
| `POST` | `/api/sicherung/vorschau` | zeigen, was eine Sicherungsdatei enthält |
| `POST` | `/api/sicherung/einspielen` | Sicherungsdatei einspielen |
| `GET` | `/api/meldungen` | Meldeziele (ntfy, Webhook) |
| `POST` | `/api/meldungen` | Ziel anlegen |
| `PUT` | `/api/meldungen/{id}` | ändern |
| `DELETE` | `/api/meldungen/{id}` | löschen |
| `POST` | `/api/meldungen/{id}/testen` | Test-Meldung senden |
