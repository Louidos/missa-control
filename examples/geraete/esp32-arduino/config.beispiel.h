// Konfiguration für die Beispiel-Firmware (ESP32, Arduino).
//
// Diese Datei ist nur ein Muster. Die echte Datei heisst config.h – das Panel erzeugt sie fertig
// ausgefüllt: Seite „Geräte“ → Gerät hinzufügen → „config.h herunterladen“.
// Sie enthält Passwörter und gehört deshalb nicht ins Repo.

#define WLAN_NAME "Name deines WLANs"
#define WLAN_PASSWORT "Passwort deines WLANs"

#define MQTT_HOST "192.168.1.10"  // Adresse von ai01 im Geräte-Netz
#define MQTT_PORT 1883
#define MQTT_BENUTZER "geraet-xxxxxxxx"  // aus dem Panel
#define MQTT_PASSWORT "aus dem Panel"

#define KNOPF_PIN 0  // BOOT-Taste der meisten ESP32-Boards
#define LED_PIN 2    // eingebaute LED vieler ESP32-Boards
