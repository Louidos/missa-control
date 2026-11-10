"""Beispiel-Firmware für den Raspberry Pi Pico 2 W (MicroPython): Knopf, Temperatur und LED.

Das Gerät meldet sich bei Missa Control an, sagt, was es kann, schickt alle 30 Sekunden die
Temperatur seines eingebauten Fühlers, meldet jeden Knopfdruck und lässt seine LED von Missa
(oder einer Regel) schalten.

So geht's (ausführlich in docs/geraete.md):
1. MicroPython für den Pico 2 W aufspielen und die Bibliothek „umqtt.simple“ installieren.
2. Im Panel unter „Geräte“ ein Gerät hinzufügen und die Datei config.py herunterladen.
3. config.py und diese main.py auf den Pico kopieren – fertig.

Verdrahtung: ein Taster zwischen GP15 und GND (oder ein Draht, den man kurz an GND hält).
"""

import gc
import json
import time

import machine
import network
from umqtt.simple import MQTTClient, MQTTException

import config

# So oft meldet sich das Gerät beim Broker. Bleibt es weg, gilt es nach dem Anderthalbfachen
# (45 Sekunden) als offline – das Panel zeigt das dann an.
LEBENSZEICHEN_SEKUNDEN = 30
MESSEN_ALLE_SEKUNDEN = 30
BASIS = "missa/geraete/" + config.MQTT_BENUTZER

# Was dieses Gerät kann. Das Panel macht daraus Funktionen für Missa und Auslöser für Regeln.
FAEHIGKEITEN = {
    "firmware": "pico-beispiel 1.0",
    "faehigkeiten": [
        {"id": "temperatur", "art": "sensor", "name": "Temperatur", "einheit": "°C"},
        {"id": "knopf", "art": "knopf", "name": "Knopf"},
        {"id": "led", "art": "aktor", "name": "LED", "typ": "schalter"},
    ],
}

led = machine.Pin("LED", machine.Pin.OUT)
knopf = machine.Pin(config.KNOPF_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
fuehler = machine.ADC(4)  # der eingebaute Temperaturfühler


def thema(teil):
    return (BASIS + "/" + teil).encode()


def temperatur():
    """Temperatur des eingebauten Fühlers in °C (Formel aus dem Datenblatt des Pico)."""
    spannung = fuehler.read_u16() * 3.3 / 65535
    return round(27 - (spannung - 0.706) / 0.001721, 1)


def led_setzen(client, an):
    """Schaltet die LED und meldet den neuen Zustand zurück – so weiss das Panel, dass es geklappt hat."""
    led.value(1 if an else 0)
    client.publish(thema("zustand/led"), b"an" if an else b"aus", retain=True)


def wlan_verbinden():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return
    vorher = led.value()
    wlan.connect(config.WLAN_NAME, config.WLAN_PASSWORT)
    for _ in range(60):  # höchstens 30 Sekunden warten, die LED blinkt dabei
        if wlan.isconnected():
            break
        led.toggle()
        time.sleep(0.5)
    led.value(vorher)
    if not wlan.isconnected():
        raise OSError("WLAN nicht erreichbar - Name und Passwort in config.py pruefen")


def mqtt_verbinden():
    client = MQTTClient(
        config.MQTT_BENUTZER,
        config.MQTT_HOST,
        port=config.MQTT_PORT,
        user=config.MQTT_BENUTZER,
        password=config.MQTT_PASSWORT,
        keepalive=LEBENSZEICHEN_SEKUNDEN,
    )
    # Letzter Wille: Verschwindet das Gerät ohne Abmeldung, meldet der Broker es als offline.
    client.set_last_will(thema("status"), b"offline", retain=True, qos=1)

    def befehl(empfangen, inhalt):
        # Wird aufgerufen, wenn das Panel einen Befehl schickt (Thema …/befehl/<fähigkeit>).
        if empfangen == thema("befehl/led"):
            led_setzen(client, inhalt == b"an")

    client.set_callback(befehl)
    client.connect()
    client.publish(thema("status"), b"online", retain=True, qos=1)
    client.publish(thema("faehigkeiten"), json.dumps(FAEHIGKEITEN).encode(), retain=True, qos=1)
    client.subscribe(thema("befehl/#"), qos=1)
    led_setzen(client, led.value() == 1)
    return client


def lauf(client, schritte=None):
    """Die Hauptschleife: Befehle abholen, Knopf beobachten, regelmässig messen, Lebenszeichen senden.

    `schritte` begrenzt die Durchläufe (nur zum Ausprobieren am Rechner) – auf dem Pico läuft sie endlos.
    """
    gedrueckt = False
    naechste_messung = time.ticks_ms()
    naechstes_lebenszeichen = time.ticks_add(time.ticks_ms(), LEBENSZEICHEN_SEKUNDEN * 500)
    while schritte is None or schritte > 0:
        jetzt = time.ticks_ms()
        client.check_msg()  # liegt ein Befehl vor, ruft das die Funktion befehl() auf
        if knopf.value() == 0 and not gedrueckt:  # gedrückt: der Eingang liegt an GND
            gedrueckt = True
            client.publish(thema("ereignis/knopf"), b"gedrueckt", qos=1)
        elif knopf.value() == 1:
            gedrueckt = False
        if time.ticks_diff(jetzt, naechste_messung) >= 0:
            client.publish(thema("wert/temperatur"), str(temperatur()).encode())
            naechste_messung = time.ticks_add(jetzt, MESSEN_ALLE_SEKUNDEN * 1000)
        if time.ticks_diff(jetzt, naechstes_lebenszeichen) >= 0:
            client.ping()
            naechstes_lebenszeichen = time.ticks_add(jetzt, LEBENSZEICHEN_SEKUNDEN * 500)
        time.sleep_ms(50)  # entprellt zugleich den Knopf
        if schritte is not None:
            schritte -= 1


def fehler_text(fehler):
    """Macht aus einem Fehler einen Satz, mit dem man etwas anfangen kann."""
    if isinstance(fehler, MQTTException):
        if fehler.args and fehler.args[0] in (4, 5):
            return "Der Broker lehnt Benutzer oder Passwort ab - im Panel neu koppeln und config.py ersetzen"
        return "Der Broker lehnt die Verbindung ab (Code %s)" % (fehler.args[0] if fehler.args else "?")
    if isinstance(fehler, OSError):
        return "Keine Verbindung (%s) - Adresse des Brokers in config.py und das WLAN pruefen" % fehler
    return repr(fehler)


def start():
    """Verbindet sich und läuft. Geht etwas schief, wird alle 5 Sekunden neu versucht."""
    while True:
        try:
            wlan_verbinden()
            lauf(mqtt_verbinden())
        except Exception as fehler:  # WLAN weg, Broker weg, Zugang falsch …
            print(fehler_text(fehler), "- neuer Versuch in 5 Sekunden")
            gc.collect()  # räumt die alte Verbindung weg
            time.sleep(5)


if __name__ == "__main__":
    start()
