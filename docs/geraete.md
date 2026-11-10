# Geräte anbinden (ESP32, Raspberry Pi Pico)

Kleine Geräte wie ein ESP32 oder ein Raspberry Pi Pico 2 W werden zu Sensoren, Knöpfen und
Schaltern für Missa. Sie verbinden sich über WLAN mit dem MQTT-Broker von Missa Control und sagen
selbst, was sie können. Daraus macht das Panel

- **Funktionen für Missa** – z. B. `wohnzimmer_temperatur` (lesen) oder `wohnzimmer_led_schalten`,
- **Auslöser für Regeln** – „Knopf gedrückt“, „Gerät geht offline“, „Temperatur über 28 °C“,
- die Seite **Geräte** mit online/offline, letzten Werten und dem Verlauf über 7 Tage.

## In 3 Schritten

1. Im Panel **Geräte → Gerät hinzufügen**: Namen eingeben, **Verbindung testen**, **Aktivieren**.
2. Board wählen, WLAN-Name und WLAN-Passwort eintragen und **config.py** (Pico) bzw. **config.h**
   (ESP32) **herunterladen**. Das Passwort des Geräts ist nur in diesem Moment zu sehen.
3. Die Datei zusammen mit der Beispiel-Firmware aufs Gerät bringen (siehe unten). Sobald es Strom
   hat, erscheint es auf der Seite „Geräte“ als **online**.

WLAN-Name und WLAN-Passwort bleiben im Browser: Sie stehen nur in der heruntergeladenen Datei, das
Panel speichert sie nicht.

Voraussetzungen: Der MQTT-Broker läuft (nach `./scripts/install.sh` ist das der Normalfall), das
Gerät erreicht ai01 im WLAN auf Port 1883, und das WLAN funkt auf 2,4 GHz (beide Boards können kein
5 GHz).

## Raspberry Pi Pico 2 W (MicroPython)

Firmware: [`examples/geraete/pico-micropython/main.py`](../examples/geraete/pico-micropython/main.py)

1. MicroPython für den „Raspberry Pi Pico 2 W“ aufspielen: BOOTSEL gedrückt halten, USB anstecken,
   die `.uf2`-Datei von micropython.org auf das Laufwerk kopieren.
2. Die MQTT-Bibliothek installieren – mit [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html)
   am Rechner:

   ```bash
   mpremote mip install umqtt.simple
   ```

   (In Thonny: Werkzeuge → Pakete verwalten → `umqtt.simple`.)
3. `config.py` aus dem Panel und `main.py` auf den Pico kopieren:

   ```bash
   mpremote cp config.py main.py :
   ```

4. Pico neu starten (USB kurz abziehen). Beim Verbinden mit dem WLAN blinkt die LED.

Was das Beispiel kann:

| Fähigkeit | Bedeutung | Verdrahtung |
| --- | --- | --- |
| Temperatur | eingebauter Fühler, alle 30 Sekunden | keine |
| Knopf | jeder Druck wird zum Ereignis | Taster zwischen **GP15** und **GND** |
| LED | lässt sich von Missa oder einer Regel schalten | keine (eingebaute LED) |

Der eingebaute Fühler misst die Temperatur des Chips – sie liegt meist ein paar Grad über der
Raumtemperatur. Meldungen der Firmware (z. B. „WLAN nicht erreichbar“) erscheinen auf der seriellen
Konsole: `mpremote` ohne weitere Angaben.

## ESP32 (Arduino)

Firmware: [`examples/geraete/esp32-arduino/esp32-arduino.ino`](../examples/geraete/esp32-arduino/esp32-arduino.ino)

1. In der Arduino-IDE das Board-Paket **esp32** (von Espressif) installieren und das eigene Board
   auswählen.
2. Die Bibliothek **PubSubClient** (von Nick O'Leary, ab Version 2.8) installieren.
3. Den Ordner `esp32-arduino` öffnen, `config.h` aus dem Panel **neben** `esp32-arduino.ino` legen
   und hochladen.

Was das Beispiel kann – ganz ohne Verdrahtung:

| Fähigkeit | Bedeutung | Anschluss |
| --- | --- | --- |
| Temperatur | eingebauter Fühler des Chips, alle 30 Sekunden | – |
| Knopf | jeder Druck wird zum Ereignis | **BOOT**-Taste (GPIO 0) |
| LED | lässt sich von Missa oder einer Regel schalten | eingebaute LED (GPIO 2) |

Hat das Board keine LED an GPIO 2 oder soll ein anderer Taster dienen: `KNOPF_PIN` und `LED_PIN` in
`config.h` anpassen. Der eingebaute Fühler ist ungenau und misst den Chip, nicht das Zimmer – für
die Raumtemperatur einen Fühler (z. B. DS18B20 oder BME280) anschliessen und in der Funktion
`temperatur()` auslesen. Meldungen der Firmware erscheinen im seriellen Monitor (115200 Baud).

> **Stand der Beispiele:** Beide wurden ohne echte Hardware entwickelt. Die Pico-Firmware läuft in
> den Tests des Repos mit der echten MQTT-Bibliothek von MicroPython gegen den echten Broker; der
> ESP32-Sketch wurde nur übersetzt und durchgespielt. Hakt es auf deinem Board, hilft die
> Fehlersuche unten.

## Ohne Hardware ausprobieren

Die Pico-Firmware läuft auch am Rechner – als „Gerät“ ohne Pico. Praktisch, um Regeln zu testen,
bevor das echte Gerät da ist. Im Ordner `backend` des Repos (einmalig vorher `uv sync`):

```bash
uv run python tests/pico.py /pfad/zu/config.py
```

`config.py` ist die Datei aus dem Panel; als „Adresse dieses Servers“ dort die Adresse von ai01
eintragen (läuft alles auf einem Rechner: `127.0.0.1`). Danach: Eingabetaste = Knopf drücken, eine
Zahl = Temperatur einstellen, `q` = Strom weg.

## Im Panel

- **Seite „Geräte“:** Status (online, offline, „wartet auf das Gerät“), Firmware, letzte Werte,
  Verlauf als Diagramm oder Tabelle (1 Stunde, 24 Stunden, 7 Tage). Ausgänge lassen sich dort direkt
  schalten.
- **Funktionen für Missa:** Der Name setzt sich aus Gerät und Fähigkeit zusammen, z. B.
  `wohnzimmer_temperatur`. Lesen ist „erlaubt“, Schalten ist „erst nachfragen“ – ändern unter
  **Integrationen**.
- **Regeln:** Auslöser „Gerät meldet etwas“ (Knopf, geht offline, kommt online) oder „Messwert über
  oder unter einer Schwelle“ mit einem Sensor des Geräts.
- **Offline:** Das Gerät sendet alle 30 Sekunden ein Lebenszeichen. Bleibt es aus, meldet der Broker
  das Gerät nach 45 Sekunden als offline – auch wenn einfach der Strom weg war.
- **Neu koppeln:** erzeugt neue Zugangsdaten; die alten gelten sofort nicht mehr. Nötig, wenn die
  Konfiguration verloren ging oder ein Gerät ersetzt wird.
- **Entfernen:** löscht den Zugang am Broker, die Funktionen und den Verlauf.

## Eigene Firmware

Jedes Gerät hat einen eigenen Benutzer am Broker (zugleich seine Client-ID) und darf nur unter
`missa/geraete/<benutzer>/…` senden. Die Zugangsdaten stehen beim Koppeln unter „Zugangsdaten für
eigene Firmware anzeigen“.

| Thema | Richtung | Inhalt |
| --- | --- | --- |
| `…/status` | Gerät → Panel | `online` beim Verbinden (gemerkt/retained); `offline` als **letzter Wille** (gemerkt) |
| `…/faehigkeiten` | Gerät → Panel | JSON, was das Gerät kann (gemerkt), siehe unten |
| `…/wert/<id>` | Gerät → Panel | Messwert eines Sensors: `21.5`, `21,5`, `an`/`aus` oder `{"wert": 21.5}` |
| `…/ereignis/<id>` | Gerät → Panel | ein Knopf wurde gedrückt (Inhalt beliebig, z. B. `gedrueckt`) |
| `…/zustand/<id>` | Gerät → Panel | aktueller Zustand eines Aktors – als Rückmeldung nach einem Befehl (gemerkt) |
| `…/befehl/<id>` | Panel → Gerät | Befehl an einen Aktor: `an`/`aus`, eine Zahl oder ein Text |

Die Meldung der Fähigkeiten:

```json
{
  "firmware": "mein-geraet 1.0",
  "faehigkeiten": [
    {"id": "temperatur", "art": "sensor", "name": "Temperatur", "einheit": "°C"},
    {"id": "tuer", "art": "sensor", "name": "Tür", "typ": "schalter"},
    {"id": "knopf", "art": "knopf", "name": "Knopf"},
    {"id": "led", "art": "aktor", "name": "LED", "typ": "schalter"},
    {"id": "helligkeit", "art": "aktor", "name": "Helligkeit", "typ": "zahl", "min": 0, "max": 100, "einheit": "%"},
    {"id": "anzeige", "art": "aktor", "name": "Anzeige", "typ": "text"}
  ]
}
```

- `id`: Kleinbuchstaben, Ziffern und `_`, beginnt mit einem Buchstaben, höchstens 30 Zeichen.
- `art`: `sensor` (wird zur lesenden Funktion und zum Messwert für Regeln), `knopf` (wird zum
  Ereignis) oder `aktor` (wird zur schaltenden Funktion: `…_schalten`, `…_setzen` bzw. `…_senden`).
- `typ`: `zahl`, `schalter` oder `text`. Ohne Angabe: Sensoren `zahl`, Aktoren `schalter`.
- Höchstens 32 Fähigkeiten pro Gerät. Ist die Meldung ungültig, steht der Grund auf der Seite „Geräte“.
- Als Lebenszeichen ein MQTT-Keepalive von 30 Sekunden einstellen.
- Der Verlauf speichert höchstens einen Wert pro halbe Minute und Fähigkeit, für 7 Tage.

## Sicherheit

- Der Broker lässt niemanden ohne Anmeldung hinein. Jedes Gerät hat ein eigenes Passwort und darf
  nur unter seinen eigenen Themen senden und nur seine eigenen Befehle empfangen – ein gekapertes
  Gerät kann sich nicht als ein anderes ausgeben.
- Der Port 1883 ist nicht verschlüsselt. Er gehört nur ins eigene Geräte-Netz, nie ins Internet.
  Mit `MQTT_BIND` in `.env` lässt er sich auf eine Adresse beschränken, z. B.
  `MQTT_BIND=192.168.20.5:1883`.
- Die Daten des Brokers liegen in `data/mosquitto/` und sind im Backup enthalten.
- Wer keine Geräte nutzt, schaltet den Broker ab: in `.env` `COMPOSE_PROFILES=` (leer) eintragen,
  dann `docker compose -p missa-control stop mqtt` und `./scripts/install.sh`.

## Fehlersuche

| Beobachtung | Ursache und Lösung |
| --- | --- |
| Seite „Geräte“: „Der MQTT-Broker … ist nicht eingerichtet“ | In `.env` fehlt `COMPOSE_PROFILES=geraete`. Eintragen und `./scripts/install.sh` ausführen. |
| Seite „Geräte“: Broker nicht erreichbar | `docker compose -p missa-control ps` – läuft der Dienst `mqtt`? Protokoll: `docker compose -p missa-control logs mqtt` |
| `install.sh`: „Port 1883 ist bereits belegt“ | Auf ai01 läuft schon ein MQTT-Broker. In `.env` einen anderen Port wählen, z. B. `MQTT_BIND=0.0.0.0:1884` – das Panel schreibt ihn dann in die Konfiguration der Geräte. |
| Gerät bleibt „wartet auf das Gerät“ | Serielle Konsole ansehen. „WLAN nicht erreichbar“: Name/Passwort, 2,4 GHz. „Keine Verbindung“: Adresse von ai01 in der Konfiguration, Firewall für Port 1883 im Geräte-Netz. |
| Pico: „Der Broker lehnt Benutzer oder Passwort ab“ · ESP32: „Fehler 4“ oder „Fehler 5“ | Die Zugangsdaten gelten nicht (mehr). Im Panel **Neu koppeln** und die neue Datei aufs Gerät bringen. |
| „Der Zugang dieses Geräts am MQTT-Broker fehlt“ | Der Broker wurde zurückgesetzt (z. B. `data/mosquitto` gelöscht). **Neu koppeln.** |
| Gerät wechselt ständig zwischen online und offline | Zwei Geräte nutzen dieselbe Konfiguration – jedes braucht seine eigene. Oder das WLAN ist am Standort zu schwach. |
| Knopf löst nichts aus | Unter **Protokoll** nachsehen, ob das Ereignis ankommt. Dann die Regel prüfen: richtiges Gerät, „Was es meldet“ = Knopf, Ruhezeit. |
