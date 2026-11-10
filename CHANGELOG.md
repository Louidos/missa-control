# Changelog

Alle spürbaren Änderungen an Missa Control stehen in dieser Datei.

Das Format richtet sich nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
die Versionsnummern nach [Semantic Versioning](https://semver.org/lang/de/).

## Unveröffentlicht

### Hinzugefügt

- Panel mit Login (Passwort + 2FA) und Installation per Skript: Einrichtung beim ersten Aufruf,
  Sitzung läuft nach 12 Stunden ab, Sperre nach 5 Fehlversuchen für 15 Minuten;
  `scripts/install.sh`, `scripts/update.sh` und `scripts/backup.sh` (#3)
