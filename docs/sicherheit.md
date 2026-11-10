# Sicherheit

Missa Control ist der Schlüsselbund von Missa: Hier liegen Zugänge zu Kalender, Home Assistant und
anderen Diensten, von hier aus lässt sich schalten, anrufen und Missas Verhalten ändern. Deshalb
gilt eine einfache Regel:

> **Das Panel gehört ins eigene Netz – nie ins Internet.**

## Das Wichtigste in Kürze

- [ ] Das Panel wird **nicht über den öffentlichen Reverse Proxy (Caddy) veröffentlicht** – keine
      Domain, keine Weiterleitung von aussen.
- [ ] Der Panel-Port (8090) ist in der Firewall **nur für die Admin-Workstation WB01** freigegeben.
- [ ] Von unterwegs geht es **nur per VPN** ins eigene Netz – nicht über eine Portfreigabe.
- [ ] Der MQTT-Port (1883) ist **nur für das Geräte-Netz** freigegeben.
- [ ] `.env` und die Backups liegen so, dass nur du sie lesen kannst.
- [ ] Passwort und Zwei-Faktor-Anmeldung sind gleich nach der Installation eingerichtet.

Die Skripte von Missa Control ändern weder Firewall noch Caddy noch Systemdienste. Alles in diesem
Dokument stellst du selbst ein.

## Kein Reverse Proxy, keine Veröffentlichung

Das Panel bekommt keinen Eintrag in Caddy (oder einem anderen öffentlichen Reverse Proxy) und keine
Portfreigabe am Router.

- Ein Fehler im Panel oder ein erratenes Passwort hätte sonst Folgen für alles, was daran hängt.
- Das Panel spricht HTTP ohne Verschlüsselung. Im eigenen Netz und durch ein VPN ist das in Ordnung –
  im Internet nicht.
- Die Anschlüsse für Missa (`/mcp`, `/v1`, `/api/events`, `/api/config`) sind nur für missa-core
  gedacht, das auf derselben Maschine läuft. Auch sie brauchen keinen Weg von aussen.

Das gilt auch für eingehende Webhooks: Ihre Adresse enthält zwar einen geheimen Schlüssel, aber sie
ist für Dienste im eigenen Netz gedacht (z. B. Home Assistant) – nicht für Dienste im Internet.

## Wer das Panel erreichen darf: nur WB01

Den Port 8090 darf nur die Admin-Workstation **WB01** erreichen. Dafür gibt es drei Wege – einer
genügt:

1. **In der Netzwerk-Firewall** (Router, Firewall zwischen den Netzen): eine Regel „WB01 → ai01,
   Port 8090, TCP“ erlauben, alles andere zu diesem Port sperren. Das ist der klarste Weg.
2. **Panel nur auf ai01 selbst erreichbar machen** und von WB01 durch einen SSH-Tunnel zugreifen.
   In `.env`:

   ```bash
   MISSA_CONTROL_BIND=127.0.0.1:8090
   ```

   Dann `./scripts/install.sh` ausführen. Auf WB01:

   ```bash
   ssh -L 8090:127.0.0.1:8090 <benutzer>@ai01
   ```

   Solange die Verbindung steht, ist das Panel auf WB01 unter `http://localhost:8090` erreichbar –
   für niemanden sonst.
3. **In der Firewall von ai01 selbst.** Achtung, eine Eigenheit von Docker: Ports von Containern
   werden an den üblichen Eingangsregeln vorbei veröffentlicht. Eine Regel in `ufw` oder in der
   Kette `INPUT` für Port 8090 wirkt deshalb **nicht**. Regeln für Container-Ports gehören in die
   Kette `DOCKER-USER`; wie genau, beschreibt die Docker-Dokumentation unter „Packet filtering and
   firewalls“. Wer sich da nicht sicher ist, nimmt Weg 1 oder 2.

Zusätzlich sinnvoll: Das Panel nur an die Adresse von ai01 im internen Netz binden, statt an alle –
`MISSA_CONTROL_BIND=<Adresse-von-ai01>:8090`.

Prüfen: Von einem anderen Rechner als WB01 darf `http://<adresse-von-ai01>:8090` nicht antworten.

missa-core braucht keine Freigabe: Es läuft auf ai01 und erreicht das Panel dort direkt (siehe
[anbindung-missa-core.md](anbindung-missa-core.md)).

## Von unterwegs: nur per VPN

Wer das Panel von unterwegs braucht, verbindet sich per VPN (z. B. WireGuard) mit dem eigenen Netz
und öffnet es dann wie zu Hause – am besten von WB01 aus oder mit einer Firewall-Regel für die
VPN-Adresse des eigenen Geräts. Eine Portfreigabe am Router für 8090 ist kein Ersatz dafür.

## Geräte: MQTT nur im Geräte-Netz

Mikrocontroller verbinden sich über den MQTT-Broker (Port 1883).

- Den Port nur für das **Geräte-Netz** freigeben (das WLAN bzw. VLAN, in dem ESP32 und Pico hängen),
  nicht für andere Netze und nie ins Internet. Am einfachsten bindet man den Broker gleich an die
  Adresse von ai01 in diesem Netz: `MQTT_BIND=<Adresse-im-Geräte-Netz>:1883`.
- Die Verbindung ist nicht verschlüsselt; das Passwort eines Geräts ist im WLAN nur durch die
  WLAN-Verschlüsselung geschützt.
- Der Schaden durch ein gekapertes Gerät ist begrenzt: Jedes hat ein eigenes Passwort und darf nur
  unter seinen eigenen Themen senden und nur seine eigenen Befehle empfangen. Ohne Anmeldung lässt
  der Broker niemanden herein.
- Geräte brauchen **keinen** Zugriff auf den Panel-Port 8090.
- Ein Gerät verloren oder weitergegeben? Auf der Seite „Geräte“ entfernen oder neu koppeln – der
  alte Zugang gilt sofort nicht mehr.
- Ohne Geräte: Broker abschalten mit `COMPOSE_PROFILES=` in `.env`.

Mehr dazu: [geraete.md](geraete.md).

## Was ai01 selbst erreichen muss

Das Panel baut von sich aus nur Verbindungen zu dem auf, was du einrichtest:

| Ziel | Wofür | Weg |
| --- | --- | --- |
| **Nextcloud** | Kalender (Termine lesen und eintragen) | CalDAV über **HTTPS** (Port 443) von ai01 zur Nextcloud |
| Home Assistant | Geräte anzeigen und schalten | die Adresse, die du einträgst (meist Port 8123) |
| Modell-Server | Antworten der Sprachmodelle | die eingetragenen Adressen |
| Eigene MCP-Server und REST-APIs | deren Funktionen | die eingetragenen Adressen |
| missa-core | nur wenn `MISSA_CORE_HEALTH_URL` gesetzt ist: ein lesender Abruf (HTTP-GET) | Health-Adresse auf ai01 |

Sonst nichts: keine Telemetrie, keine Cloud-Dienste, keine Update-Abfragen. Internet braucht ai01 nur
beim Installieren und Aktualisieren (Docker lädt Images und Pakete).

Zugänge (App-Passwort der Nextcloud, Tokens) sollten nur das dürfen, was Missa braucht – für
Nextcloud ein eigenes App-Passwort statt des Hauptpassworts.

## `.env` und Backups

`.env` enthält die beiden Schlüssel des Panels:

- `SECRET_KEY` schützt Anmeldungen und Client-Tokens.
- `ENCRYPTION_KEY` verschlüsselt alle gespeicherten Zugänge.

Regeln dafür:

- `.env` bleibt auf ai01, ist nur für dich lesbar (`install.sh` legt sie so an) und wird nie ins
  Repo eingecheckt. Dasselbe gilt für `data/` und `backups/` – `.gitignore` schliesst alle drei aus.
- Ein Backup (`./scripts/backup.sh`) enthält `data/` **und** `.env`. Wer die Datei hat, kann alle
  Zugänge lesen. Sie gehört an einen sicheren Ort ausserhalb von ai01 – am besten verschlüsselt –
  und nicht in einen geteilten Ordner.
- Ohne `ENCRYPTION_KEY` sind die Zugänge verloren. Ein Backup ohne `.env` ist deshalb wertlos.
- Verdacht, dass ein Schlüssel oder ein Backup in fremde Hände kam: die betroffenen Zugänge bei den
  jeweiligen Diensten erneuern (neues App-Passwort, neuer Token), im Panel neu eintragen und die
  Tokens unter „Clients“ widerrufen und neu ausstellen.

## Was das Panel selbst absichert

| Schutz | Wie |
| --- | --- |
| Anmeldung | Passwort und Code aus der Authenticator-App; nach 5 Fehlversuchen 15 Minuten gesperrt; die Anmeldung läuft nach 12 Stunden ab. |
| Zugriff | Ohne Anmeldung ist nur die Anmeldeseite erreichbar. missa-core und andere Clients brauchen einen eigenen Token, der sich einzeln widerrufen lässt und nur an die Anschlüsse für Clients kommt. |
| Zugänge | verschlüsselt gespeichert, nach dem Speichern nur noch maskiert sichtbar, in keinem Protokoll. |
| Was Missa darf | Rechte pro Funktion: Lesen ist erlaubt, alles andere fragt erst nach – du entscheidest unter „Freigaben“. Jeder Aufruf steht im Protokoll. |
| Container | laufen ohne root, mit schreibgeschütztem Dateisystem und ohne Sonderrechte; kein Zugriff auf den Docker-Socket. Für die Serverlast liest das Panel `/proc` und `/sys` von ai01 – ausschliesslich lesend. |
| missa-core | wird nie verändert. Das Panel schickt höchstens einen lesenden Abruf an die Health-Adresse. |

Eigene Integrationen (Ordner mit `main.py`) laufen als Teil des Panels und dürfen alles, was das
Panel darf. Nur Code einspielen, den du selbst geschrieben oder gelesen hast.

## Notfall

| Lage | Was tun |
| --- | --- |
| Handy mit der Authenticator-App verloren | Auf ai01: `./scripts/reset-2fa.sh` – danach mit dem bisherigen Passwort einen neuen QR-Code einrichten. Alle Anmeldungen enden sofort. |
| Passwort und Handy verloren | `./scripts/reset-2fa.sh --auch-passwort` – und das Panel sofort neu einrichten. |
| Jemand Fremdes war angemeldet | `./scripts/reset-2fa.sh` beendet alle Anmeldungen. Danach Client-Tokens und Zugänge erneuern, das Protokoll und die Regeln durchsehen. |
| Ein Client-Token ist bekannt geworden | Unter „Clients“ widerrufen und einen neuen ausstellen. |
| Die Adresse eines Webhooks ist bekannt geworden | Unter „Integrationen“ eine neue Adresse erzeugen – die alte gilt sofort nicht mehr. |

Die Skripte betreffen nur Missa Control selbst – missa-core und andere Container bleiben unberührt.
