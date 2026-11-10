# Konfiguration für die Beispiel-Firmware (Raspberry Pi Pico 2 W).
#
# Diese Datei ist nur ein Muster. Die echte Datei heisst config.py – das Panel erzeugt sie fertig
# ausgefüllt: Seite „Geräte“ → Gerät hinzufügen → „config.py herunterladen“.
# Sie enthält Passwörter und gehört deshalb nicht ins Repo.

WLAN_NAME = "Name deines WLANs"
WLAN_PASSWORT = "Passwort deines WLANs"

MQTT_HOST = "192.168.1.10"  # Adresse von ai01 im Geräte-Netz
MQTT_PORT = 1883
MQTT_BENUTZER = "geraet-xxxxxxxx"  # aus dem Panel
MQTT_PASSWORT = "aus dem Panel"

KNOPF_PIN = 15  # Taster zwischen GP15 und GND
