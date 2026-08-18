import json
import os
import sys
import time
import uuid
import urllib.error
import urllib.request


DEFAULT_SERVER = "http://server.local:5000"
DEFAULT_API_KEY = os.environ.get("STATION_API_KEY", "").strip()


TEST_SWIPES = [
    {
        "card_id": "209451056",
        "station_id": "front-door",
        "station_name": "Front Door",
        "station_kind": "door",
    },
    {
        "card_id": "209451056",
        "station_id": "soldering",
        "station_name": "Soldering",
        "station_kind": "station",
    },
    {
        "card_id": "123456789",
        "station_id": "back-door",
        "station_name": "Back Door",
        "station_kind": "door",
    },
    {
        "card_id": "123456789",
        "station_id": "laser-cutting",
        "station_name": "Laser Cutting",
        "station_kind": "station",
    },
    {
        "card_id": "209451056",
        "station_id": "back-door",
        "station_name": "Back Door",
        "station_kind": "door",
    },
    {
        "card_id": "123456789",
        "station_id": "laser-cutting",
        "station_name": "Laser Cutting",
        "station_kind": "station",
    },
    {
        "card_id": "123456789",
        "station_id": "front-door",
        "station_name": "Front Door",
        "station_kind": "door",
    },
]


def post_json(url, payload, api_key):
    payload = {**payload, "event_id": str(uuid.uuid4())}
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Station-Key": api_key,
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        text = response.read().decode("utf-8")
        return response.status, json.loads(text)


def main():
    server = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else DEFAULT_SERVER
    api_key = sys.argv[2].strip() if len(sys.argv) > 2 else DEFAULT_API_KEY
    if not api_key:
        print("Set STATION_API_KEY or pass the key as the second argument.")
        return 1

    swipe_url = server + "/swipe"

    print("Sending test swipes to", swipe_url)

    for swipe in TEST_SWIPES:
        try:
            status, result = post_json(swipe_url, swipe, api_key)
            print(
                "HTTP {} card={} place={} action={} inside={} warning={}".format(
                    status,
                    result.get("card_id"),
                    result.get("station_name"),
                    result.get("action"),
                    result.get("active_users"),
                    result.get("warning"),
                )
            )
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            print(f"Server rejected the swipe (HTTP {error.code}): {detail}")
            return 1
        except urllib.error.URLError as error:
            print("Failed to reach server:", error)
            return 1

        time.sleep(1)

    print("")
    print("Open the dashboard:")
    print(server + "/dashboard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
