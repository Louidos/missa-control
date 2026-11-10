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
