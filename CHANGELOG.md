# Changelog

Alle spürbaren Änderungen an Missa Control stehen in dieser Datei.

Das Format richtet sich nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
die Versionsnummern nach [Semantic Versioning](https://semver.org/lang/de/).

## Unveröffentlicht

### Hinzugefügt

- Panel mit Login (Passwort + 2FA) und Installation per Skript: Einrichtung beim ersten Aufruf,
  Sitzung läuft nach 12 Stunden ab, Sperre nach 5 Fehlversuchen für 15 Minuten;
  `scripts/install.sh`, `scripts/update.sh` und `scripts/backup.sh` (#3)
- Zugänge (API-Keys, Passwörter) verschlüsselt speichern: neue Seite „Zugänge“, Werte sind nach dem
  Speichern nur noch maskiert sichtbar (`••••abcd`) und erscheinen in keinem Log (#5)
- Integrations-Katalog: MCP-Server, REST-APIs und eigene Python-Integrationen in 3 Schritten
  einrichten (Karte wählen, Formular ausfüllen, testen und aktivieren); Rechte pro Funktion
  („erlaubt“, „erst nachfragen“, „gesperrt“), Seite „Integrationen“ zum Verwalten und Ausprobieren,
  eigene Integrationen als Ordner oder ZIP, Anleitung in `docs/eigene-integration.md` (#7)
- Ein Anschluss für Missa mit Freigaben, Clients, Protokoll und Ereignissen: MCP-Gateway unter `/mcp`
  bündelt alle aktiven Funktionen; Zugriff nur mit Client-Token (Seite „Clients“); „erst
  nachfragen“-Aufrufe warten unter „Freigaben“ auf Erlauben oder Ablehnen (höchstens 5 Minuten);
  Seite „Protokoll“ mit allen Aufrufen und Ereignissen; Ereignisse per `GET /api/events` und als
  Stream; lesende Konfig-API; Anleitung in `docs/anbindung-missa-core.md` (#9)
- Modelle verwalten (schnell/stark) mit gemeinsamem Modell-Anschluss: Modell-Endpunkte eintragen und
  testen (Antwortzeit, Tokens/s), Rollen mit Haupt- und Ersatzmodell, OpenAI-kompatibler Anschluss
  unter `/v1` mit den festen Namen `missa-schnell` und `missa-stark` (auch mit Streaming),
  Statistik der letzten 7 Tage (#11)
- Charakterprofil bearbeiten mit Versionsverlauf und Test-Chat: Seite „Charakter“ mit Feldern für
  Name, Aussprache, Wesen, Sprechweise, Regeln, Verhalten gegenüber Fremden und freiem Systemprompt;
  jede Speicherung ist eine Version (Unterschiede ansehen, wiederherstellen); Export und Import als
  YAML; Test-Chat direkt mit dem Modell, auch mit ungespeichertem Profil (#13)
- Serverlast von ai01 mit Verlauf: Seite „Serverlast“ mit CPU, Arbeitsspeicher, Speicherplatz und –
  falls vorhanden – GPU; Messung alle 30 Sekunden (nur lesend), Diagramme für 1 Stunde, 24 Stunden
  und 7 Tage, Tabellenansicht; Missa kann die Werte über die Funktion `serverlast_aktuell` abfragen (#15, #20)
- Gedächtnis von Missa ansehen, bearbeiten und löschen: Seite „Gedächtnis“ mit Suche (auch nach
  Wortteilen), Filter nach Kategorie und Quelle, Einträgen von Hand und Export als JSON; Missa merkt
  sich Dinge über die Funktionen `merken`, `suchen` und `vergessen` – vergessen nur nach Freigabe (#17)
- Freigaben sagen jetzt in einem Satz, was genau passieren würde (z. B. welcher Eintrag gelöscht
  wird), statt nur Funktion und Parameter zu zeigen – eigene Integrationen können das mit
  `@funktion(vorschau=…)` ebenfalls (#17)
- Regeln und Alarme, auch von Missa selbst anlegbar: Seite „Regeln“ mit Regeln als lesbaren Sätzen
  („Wenn die CPU-Auslastung 5 Minuten lang über 90 % liegt, dann …“), Editor mit Auswahlfeldern,
  „Jetzt testen“ und Verlauf der Auslösungen; Auslöser: Zeitplan (Uhrzeit oder Abstand), Messwert
  über/unter einer Schwelle mit Mindestdauer, Webhook, Gerät, Integration ausgefallen; Bedingung
  nach Wochentagen und Uhrzeit; Aktionen: Ereignis an Missa oder Funktion einer Integration
  aufrufen; Ruhezeit gegen Dauer-Alarme (Standard 30 Minuten), Regeln lassen sich pausieren (#19)
- Neue Einstellung `MISSA_CONTROL_ZEITZONE` für Uhrzeiten in Regeln; `install.sh` übernimmt die
  Zeitzone von ai01, sonst gilt Europe/Zurich (#19)
- Fertige Integrationen für Nextcloud-Kalender, Home Assistant und Webhooks, jeweils in 3 Schritten
  eingerichtet (#23):
  - Nextcloud-Kalender: Termine anzeigen, eintragen, ändern und löschen (schreibende Funktionen erst
    nach Freigabe); nach dem Verbindungstest stehen die gefundenen Kalender zur Auswahl
  - Home Assistant: Geräte anzeigen, Zustände lesen, schalten und Dienste aufrufen; ist in Home
    Assistant der MCP-Server eingerichtet, nutzt Missa stattdessen dessen Werkzeuge
  - Webhook: eine geheime Adresse, an die andere Dienste und Geräte Meldungen schicken – jede Meldung
    wird zum Ereignis für Missa und kann Regeln auslösen; das Panel zeigt ein `curl`-Beispiel
- Freigaben für Kalender und Home Assistant sagen, welcher Termin bzw. welches Gerät gemeint ist (#23)
- Eigene Integrationen können Funktionen abhängig von der Einrichtung anbieten (`wenn=`) und
  Funktionen durchreichen, die erst zur Laufzeit feststehen (`@weitere_funktionen`) (#23)

- Geräte (ESP32, Pico) per Kopplungscode anbinden: neue Seite „Geräte“ – Gerät hinzufügen, fertige
  Konfigurationsdatei herunterladen, aufs Gerät kopieren. Das Gerät erscheint als online und sagt
  selbst, was es kann: Sensoren werden zu Funktionen für Missa und zu Messwerten für Regeln, Knöpfe
  zu Ereignissen, Schalter zu Funktionen, die erst nachfragen. Letzte Werte, Verlauf über 7 Tage,
  Schalten direkt im Panel; offline wird nach spätestens 45 Sekunden angezeigt. Dazu ein eigener
  MQTT-Broker (Port 1883, jedes Gerät mit eigenem Zugang), Beispiel-Firmware für Pico 2 W und
  ESP32 in `examples/geraete/` und die Anleitung `docs/geraete.md` (#25)
- Regeln: Beim Auslöser „Gerät meldet etwas“ steht zur Auswahl, was das Gerät melden kann (seine
  Knöpfe, „geht offline“, „kommt online“) (#25)
- Neue Einstellungen `MQTT_BIND` (Adresse und Port des MQTT-Brokers) und `COMPOSE_PROFILES` (leer =
  ohne Broker); `install.sh` prüft auch den MQTT-Port und bricht ab, wenn er belegt ist (#25)

### Geändert

- `update.sh` übergibt nach dem Holen der neuen Version an `install.sh`: So werden auch die Ports
  geprüft und Ordner angelegt, die eine neue Version braucht. Wer von einem älteren Stand kommt,
  führt nach dem Update einmal `./scripts/install.sh` aus – das startet den MQTT-Broker (#25)

- Ist die Gegenstelle einer eigenen Python-Integration nicht erreichbar oder lehnt sie den Zugang
  ab, gilt die Integration jetzt als ausgefallen (Status „Fehler“, Ereignis für Regeln) – bisher
  galt das nur für MCP-Server und REST-APIs (#23)
