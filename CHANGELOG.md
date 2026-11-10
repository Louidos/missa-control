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
