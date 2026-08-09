import json
import sys
import time
import urllib.error
import urllib.request


DEFAULT_SERVER = "http://server.local:5000"


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
        "station_name": "Soldering Station",
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


def post_json(url, payload):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        text = response.read().decode("utf-8")
        return response.status, json.loads(text)


def main():
    server = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else DEFAULT_SERVER
    swipe_url = server + "/swipe"

    print("Sending test swipes to", swipe_url)

    for swipe in TEST_SWIPES:
        try:
            status, result = post_json(swipe_url, swipe)
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
        except urllib.error.URLError as error:
            print("Failed to reach server:", error)
            return 1

        time.sleep(1)

    print("")
    print("Open these:")
    print(server + "/dashboard")
    print(server + "/swipes.csv")
    print(server + "/active.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
