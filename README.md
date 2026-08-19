# PicoScanner Station Server

PicoScanner is an RFID check-in system for makerspaces and similar shared spaces. Raspberry Pi Pico W readers send card swipes to a Raspberry Pi 3 server, which provides a live dashboard, card database, certifications, station rules, and CSV exports.

## What it does

- Tracks entry and exit through doors.
- Tracks active use of equipment stations without changing the building count.
- Requires active card records and station certifications where configured.
- Limits regular User entry to opening hours (12:00 PM-5:00 PM by default).
- Allows Admin, Staff, and Volunteer accounts to enter after hours.
- Automatically closes a station session when a person exits the building.
- Records swipe history and administrative actions for reporting.
- Provides Admin-only live usage analytics and Excel/CSV exports.

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
export STATION_TIMEZONE='America/Los_Angeles'
export STATION_OPENING_HOUR='12'
export STATION_CLOSING_HOUR='17'
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

## Opening hours

Regular User cards can enter from 12:00 PM up to 5:00 PM. Admin, Staff, and Volunteer accounts can enter outside that window. Exits are always allowed. Change the hours with `STATION_OPENING_HOUR` and `STATION_CLOSING_HOUR`; both use 24-hour whole-hour values.

## Analytics and exports

The Admin tab shows live station rankings, total usage time, completed sessions, unique station users, busiest times, and authorized after-hours activity. Choose a 7, 30, or 90-day range, or all time. The view refreshes automatically while open.

The server stores its SQLite database beside `app.py`. Admins can download a master Excel workbook with separate People, Certifications, Cards, Pending Canvas, Swipe Log, Audit Log, Station Analytics, and After Hours sheets. Individual CSV exports remain available for focused reporting:

- `/swipes.csv` — swipe history
- `/active.csv` — people currently inside
- `/station_status.csv` — current station use
- `/audit.csv` — administrative audit history

Only Admin sessions can export CSV data from the site.
The master workbook is a reporting snapshot. Continue using the original wide Canvas CSV for Canvas imports.

## Production notes

- Use a strong, unique API key and administrator password.
- Keep the Pi server on a trusted network.
- Login protection is enforced server-side: repeated failures are limited per username/IP pair, per username across IPs, and per IP across usernames.
- Login error messages do not reveal whether an account exists, and failed-login audit entries are throttled to prevent log flooding.
- Each account may keep up to three active dashboard sessions; older tokens are invalidated automatically.
- Browser writes from a different origin are rejected, and HTTPS responses include strict transport and isolation headers.
- Configure the supplied `station-server.service` file if the server should start automatically after boot.
- Back up the SQLite database before upgrades or schema changes.
