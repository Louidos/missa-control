// Beispiel-Firmware für den ESP32 (Arduino): Knopf, Temperatur und LED.
//
// Das Gerät meldet sich bei Missa Control an, sagt, was es kann, schickt alle 30 Sekunden die
// Temperatur seines eingebauten Fühlers, meldet jeden Knopfdruck und lässt seine LED von Missa
// (oder einer Regel) schalten.
//
// So geht's (ausführlich in docs/geraete.md):
// 1. In der Arduino-IDE das Board „ESP32“ und die Bibliothek „PubSubClient“ installieren.
// 2. Im Panel unter „Geräte“ ein Gerät hinzufügen und die Datei config.h herunterladen.
// 3. config.h neben diese Datei legen und hochladen – fertig.
//
// Ohne Verdrahtung: Als Knopf dient die BOOT-Taste (GPIO 0), als LED die eingebaute (GPIO 2).

#include <WiFi.h>
#include <PubSubClient.h>

#include "config.h"

// So oft meldet sich das Gerät beim Broker. Bleibt es weg, gilt es nach dem Anderthalbfachen
// (45 Sekunden) als offline – das Panel zeigt das dann an.
const int LEBENSZEICHEN_SEKUNDEN = 30;
const unsigned long MESSEN_ALLE_MS = 30000;

// Was dieses Gerät kann. Das Panel macht daraus Funktionen für Missa und Auslöser für Regeln.
const char FAEHIGKEITEN[] =
  "{\"firmware\":\"esp32-beispiel 1.0\",\"faehigkeiten\":["
  "{\"id\":\"temperatur\",\"art\":\"sensor\",\"name\":\"Temperatur\",\"einheit\":\"°C\"},"
  "{\"id\":\"knopf\",\"art\":\"knopf\",\"name\":\"Knopf\"},"
  "{\"id\":\"led\",\"art\":\"aktor\",\"name\":\"LED\",\"typ\":\"schalter\"}]}";

const String BASIS = String("missa/geraete/") + MQTT_BENUTZER;

WiFiClient netz;
PubSubClient mqtt(netz);
bool gedrueckt = false;
unsigned long letzteMessung = 0;
bool schonGemessen = false;

String thema(const char* teil) {
  return BASIS + "/" + teil;
}

// Temperatur des eingebauten Fühlers in °C. Er misst den Chip, nicht das Zimmer – für die
// Raumtemperatur einen eigenen Fühler anschliessen (siehe docs/geraete.md) und hier auslesen.
float temperatur() {
  return temperatureRead();
}

// Schaltet die LED und meldet den neuen Zustand zurück – so weiss das Panel, dass es geklappt hat.
void ledSetzen(bool an) {
  digitalWrite(LED_PIN, an ? HIGH : LOW);
  mqtt.publish(thema("zustand/led").c_str(), an ? "an" : "aus", true);
}

// Wird aufgerufen, wenn das Panel einen Befehl schickt (Thema …/befehl/<fähigkeit>).
void befehlEmpfangen(char* empfangenesThema, byte* inhalt, unsigned int laenge) {
  String text;
  for (unsigned int i = 0; i < laenge; i++) {
    text += (char)inhalt[i];
  }
  if (String(empfangenesThema) == thema("befehl/led")) {
    ledSetzen(text == "an");
  }
}

void wlanVerbinden() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WLAN_NAME, WLAN_PASSWORT);
  Serial.print("Verbinde mit dem WLAN");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println(" verbunden.");
}

bool mqttVerbinden() {
  // Letzter Wille: Verschwindet das Gerät ohne Abmeldung, meldet der Broker es als offline.
  bool verbunden = mqtt.connect(MQTT_BENUTZER, MQTT_BENUTZER, MQTT_PASSWORT,
                                thema("status").c_str(), 1, true, "offline");
  if (!verbunden) {
    // 4 oder 5: Benutzer oder Passwort falsch – im Panel neu koppeln und config.h ersetzen.
    // Negative Zahlen: Der Broker ist nicht erreichbar – MQTT_HOST in config.h und das WLAN prüfen.
    Serial.print("Keine Verbindung zum MQTT-Broker, Fehler ");
    Serial.println(mqtt.state());
    return false;
  }
  mqtt.publish(thema("status").c_str(), "online", true);
  mqtt.publish(thema("faehigkeiten").c_str(), FAEHIGKEITEN, true);
  mqtt.subscribe(thema("befehl/#").c_str(), 1);
  ledSetzen(digitalRead(LED_PIN) == HIGH);
  schonGemessen = false;  // nach dem Verbinden gleich einmal messen
  return true;
}

void setup() {
  Serial.begin(115200);
  pinMode(KNOPF_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  wlanVerbinden();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setKeepAlive(LEBENSZEICHEN_SEKUNDEN);
  mqtt.setBufferSize(512);  // die Liste der Fähigkeiten braucht etwas mehr Platz als üblich
  mqtt.setCallback(befehlEmpfangen);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    wlanVerbinden();
  }
  if (!mqtt.connected() && !mqttVerbinden()) {
    delay(5000);  // neuer Versuch in 5 Sekunden
    return;
  }
  mqtt.loop();  // empfängt Befehle und hält die Verbindung am Leben

  bool jetzt = digitalRead(KNOPF_PIN) == LOW;  // gedrückt: der Eingang liegt an GND
  if (jetzt && !gedrueckt) {
    mqtt.publish(thema("ereignis/knopf").c_str(), "gedrueckt");
  }
  gedrueckt = jetzt;

  if (!schonGemessen || millis() - letzteMessung >= MESSEN_ALLE_MS) {
    mqtt.publish(thema("wert/temperatur").c_str(), String(temperatur(), 1).c_str());
    letzteMessung = millis();
    schonGemessen = true;
  }
  delay(30);  // entprellt zugleich den Knopf
}
