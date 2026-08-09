import network
import time
import urequests


SSID = "Y"
PASSWORD = "YOUR_HOTSPOT_PASSWORD"

SERVER_URL = "http://192.168.1.41:5000/swipe"

# Set these per Pico W / station.
STATION_ID = "soldering"
STATION_NAME = "Soldering Station"
STATION_KIND = "station"


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(SSID, PASSWORD)

    while not wlan.isconnected():
        time.sleep(0.5)

    print("Wi-Fi connected:", wlan.ifconfig())


def send_swipe(card_id):
    data = {
        "card_id": str(card_id),
        "station_id": STATION_ID,
        "station_name": STATION_NAME,
        "station_kind": STATION_KIND,
    }

    response = urequests.post(SERVER_URL, json=data)
    result = response.json()
    response.close()
    return result


connect_wifi()

# Replace this with the RFID ID read from your MFRC522 code.
print(send_swipe(209451056))
