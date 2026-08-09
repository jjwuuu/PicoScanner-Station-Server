# PicoScanner Station Server

PicoScanner is an RFID check-in system for makerspaces and similar shared spaces. Raspberry Pi Pico W readers send card swipes to a Raspberry Pi 3 server, which provides a live dashboard, card database, certifications, station rules, and CSV exports.

## What it does

- Tracks entry and exit through doors.
- Tracks active use of equipment stations without changing the building count.
- Requires active card records and station certifications where configured.
- Automatically closes a station session when a person exits the building.
- Records swipe history and administrative actions for reporting.

## Project layout

```text
Code/
  Pi 3/       Flask server, dashboard, configuration, and test-data sender
  Pico W/     MicroPython reader firmware and RFID helpers
```

## Server setup (Raspberry Pi 3)

```bash
cd "Code/Pi 3"
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Set secure credentials before starting the server:

```bash
export STATION_API_KEY='replace-with-one-shared-reader-key'
export STATION_BOOTSTRAP_ADMIN_CARD_ID='your-admin-card-id'
export STATION_BOOTSTRAP_ADMIN_PASSWORD='choose-a-strong-password'
python app.py
```

Open the dashboard at `http://<pi-address>:5000/dashboard`.

The default station configuration is in [`Code/Pi 3/config.json`](Code/Pi%203/config.json). Edit it to add, rename, or remove doors and stations before deployment.

## Dashboard roles

| Role | Capabilities |
| --- | --- |
| Admin | Manages dashboard accounts, station rules, certification permissions, cards, certifications, swipe history, and audit history. |
| Staff | Manages station rules, cards, certifications, and swipe history. |
| Volunteer | Manages cards and assigned certifications. |
| Public | Views high-level live occupancy and station activity only. |

## Pico W reader setup

Use the reader firmware in `Code/Pico W` as a starting point:

- `door_pico.py` is for entry/exit readers.
- `soldering_station_pico.py` is an equipment-station example.

Update these values in each firmware file before copying it to a Pico W:

```python
SERVER_URL = "http://<pi-address>:5000/swipe"
STATION_API_KEY = "replace-with-one-shared-reader-key"
STATION_ID = "soldering"
STATION_NAME = "Soldering Station"
STATION_KIND = "station"  # use "door" for doors
```

Every reader must use the same `STATION_API_KEY` configured on the server. Each station ID must match an entry in `config.json`.

## Data and exports

The server stores its SQLite database beside `app.py`. The dashboard can export CSV data for reporting:

- `/swipes.csv` — swipe history
- `/active.csv` — people currently inside
- `/station_status.csv` — current station use
- `/audit.csv` — administrative audit history

Exports that contain protected information require an authorized dashboard session.

## Test data

With the server running:

```bash
cd "Code/Pi 3"
source venv/bin/activate
python send_test_data.py http://127.0.0.1:5000
```

This sends sample door and station activity, including a mismatch scenario for validating incident handling.

## Production notes

- Use a strong, unique API key and administrator password.
- Keep the Pi server on a trusted network.
- Configure the supplied `station-server.service` file if the server should start automatically after boot.
- Back up the SQLite database before upgrades or schema changes.
