import machine
from machine import Pin
import neopixel
import network
import time
import ujson
from ubinascii import hexlify

try:
    import urequests
except ImportError:
    urequests = None

from mfrc522 import MFRC522
from offline_queue import OfflineQueue


# Edit these for your hotspot and Pi server.
WIFI_SSID = "replace-with-hotspot-ssid"
WIFI_PASSWORD = "replace-with-hotspot-password"
SERVER_URL = "http://192.168.1.60:5000/swipe"
STATION_API_KEY = "replace-with-station-api-key"

print("Station key loaded:", STATION_API_KEY)
print("Server URL:", SERVER_URL)

# Sewing station reader.
STATION_ID = "sewing"
STATION_NAME = "Sewing Station"
STATION_KIND = "station"

# Hardware pins. These match the newer wiring in test.py.
LIMIT_SWITCH_PIN = 5
NEOPIXEL_PIN = 13

RFID_SCK = 18
RFID_MISO = 16
RFID_MOSI = 19
RFID_CS = 20
RFID_RST = 22


reader = MFRC522(
    spi_id=0,
    sck=RFID_SCK,
    miso=RFID_MISO,
    mosi=RFID_MOSI,
    cs=RFID_CS,
    rst=RFID_RST,
)
queue = OfflineQueue()
event_counter = 0
QUEUE_RETRY_MS = 10000
next_queue_retry = 0

limit_switch = Pin(LIMIT_SWITCH_PIN, Pin.IN, Pin.PULL_UP)
pixel = neopixel.NeoPixel(Pin(NEOPIXEL_PIN), 1)

COLORS = {
    "off": (0, 0, 0),
    "green": (0, 60, 0),
    "yellow": (60, 45, 0),
    "blue": (0, 0, 80),
    "cyan": (0, 50, 50),
    "red": (80, 0, 0),
    "purple": (45, 0, 60),
}

led_state = {
    "mode": "idle",
    "until": 0,
    "next_toggle": 0,
    "on": False,
}


def set_led(color):
    pixel[0] = COLORS[color]
    pixel.write()


def wifi_connected():
    try:
        return wlan.isconnected()
    except NameError:
        return False


def set_led_mode(mode, duration_ms=0):
    now = time.ticks_ms()
    led_state["mode"] = mode
    led_state["until"] = time.ticks_add(now, duration_ms) if duration_ms else 0
    led_state["next_toggle"] = now
    led_state["on"] = False

    if mode == "idle":
        set_led("green" if wifi_connected() else "purple")
    elif mode == "cert_success":
        set_led("green")
    elif mode == "access_granted":
        set_led("blue")
    elif mode == "station_out":
        set_led("cyan")
    elif mode == "access_denied":
        set_led("red")
    elif mode == "server_error":
        set_led("purple")


def update_led():
    now = time.ticks_ms()
    if led_state["until"] and time.ticks_diff(now, led_state["until"]) >= 0:
        set_led_mode("idle")
        return

    mode = led_state["mode"]
    if mode == "cert_mode_pending":
        interval = 120
    elif mode == "cert_mode_armed":
        interval = 650
    else:
        return

    if time.ticks_diff(now, led_state["next_toggle"]) >= 0:
        led_state["on"] = not led_state["on"]
        set_led("blue" if led_state["on"] else "off")
        led_state["next_toggle"] = time.ticks_add(now, interval)


def apply_server_led(result):
    signal = result.get("led_signal", "")
    action = result.get("action", "")

    if signal == "cert_mode_pending":
        set_led_mode("cert_mode_pending", 5000)
    elif signal == "cert_mode_armed":
        set_led_mode("cert_mode_armed", 41000)
    elif signal == "cert_success":
        set_led_mode("cert_success", 2000)
    elif signal == "server_error":
        set_led_mode("server_error", 2000)
    elif signal == "access_denied":
        set_led_mode("access_denied", 1200)
    elif action in ("swipe_out", "station_out", "station_auto_out", "exit"):
        set_led_mode("station_out", 1200)
    else:
        set_led_mode("access_granted", 1200)


def blink(color, count=3, delay=0.15):
    for _ in range(count):
        set_led(color)
        time.sleep(delay)
        set_led("off")
        time.sleep(delay)


def limit_pressed():
    # Pull-up wiring: pressed/closed switch reads 0.
    return limit_switch.value() == 0


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if wlan.isconnected():
        return wlan

    set_led("yellow")
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)

    start = time.time()
    while not wlan.isconnected():
        if time.time() - start > 20:
            blink("purple", 4)
            return wlan
        time.sleep(0.25)

    set_led("green")
    print("Wi-Fi connected:", wlan.ifconfig())
    return wlan


def read_card_and_send(reads=40, required_hits=1):
    counts = {}

    for _ in range(reads):
        update_led()
        reader.init()
        status, _tag_type = reader.request(reader.REQIDL)

        if status == reader.OK:
            status, uid = reader.SelectTagSN()

            if status == reader.OK:
                card_id = str(int.from_bytes(bytes(uid), "little", False))
                counts[card_id] = counts.get(card_id, 0) + 1
                print("CARD ID:", card_id)

                if counts[card_id] >= required_hits:
                    return send_swipe(card_id)

        time.sleep(0.08)

    print("No card read")
    return None


def event_for(card_id):
    global event_counter
    event_counter += 1
    return "%s-%s-%s" % (hexlify(machine.unique_id()).decode(), time.ticks_ms(), event_counter)


def post_event(data):
    body = ujson.dumps(data)
    response = urequests.post(
        SERVER_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Station-Key": STATION_API_KEY,
        },
    )
    text = response.text
    response.close()
    return ujson.loads(text)


def resend_queued():
    global next_queue_retry
    if urequests is None or not wifi_connected():
        return

    now = time.ticks_ms()
    if time.ticks_diff(now, next_queue_retry) < 0:
        return
    next_queue_retry = time.ticks_add(now, QUEUE_RETRY_MS)

    event = queue.peek()
    if not event:
        return
    try:
        post_event(event)
        queue.remove_first()
        print("Queued swipe delivered; remaining:", len(queue))
    except Exception as error:
        print("Queued swipe server retry failed:", repr(error))


def send_swipe(card_id):
    if urequests is None:
        print("urequests is not installed")
        return {"led_signal": "server_error", "error": "urequests is not installed"}

    data = {
        "card_id": card_id,
        "station_id": STATION_ID,
        "station_name": STATION_NAME,
        "station_kind": STATION_KIND,
        "event_id": event_for(card_id),
    }

    try:
        result = post_event(data)
        print("Server response:", result)
        return result
    except Exception as error:
        print("Server error:", error)
        pending = queue.add(data)
        print("Swipe queued; pending:", pending)
        return {"led_signal": "server_error", "error": "Swipe queued for retry"}


def show_result(result):
    if not result:
        return

    apply_server_led(result)


def wait_for_release():
    while limit_pressed():
        update_led()
        time.sleep(0.05)
    time.sleep(0.2)


reader.init()
wlan = connect_wifi()
set_led("green" if wlan.isconnected() else "purple")

print(STATION_NAME, "scanner ready")

while True:
    update_led()

    if not wlan.isconnected():
        wlan = connect_wifi()
    else:
        resend_queued()

    if limit_pressed():
        set_led("yellow")
        result = read_card_and_send()

        if result:
            show_result(result)
        else:
            set_led_mode("access_denied", 1000)

        wait_for_release()

    time.sleep(0.05)
