# RFID Station Server

Flask server and browser dashboard for makerspace door entry, station usage,
card enrollment, certifications, Canvas synchronization, and audit history.

## At a Glance

- Live door tracking and inside count
- Active station tracking
- Card enrollment and card lookup
- Certifications by person and station
- Pending unknown-card queue
- Canvas certification import and sync tracking
- Audit logging for important actions
- CSV exports for operational data

## Roles

### Signed Out

Shows only the public live status view:

- people inside
- active stations
- last swipe time

### Volunteer

Can view the live dashboard and browse cards and certifications in read-only
mode. BroncoID remains hidden. Volunteers do not see Admin-only audit, import,
or dashboard credential tools.

### Staff

Can use the operational dashboard: live status, cards, certifications, station
usage, and exports. Staff can grant or revoke certifications only where they
have explicit station permission.

### Admin

Sees the full dashboard, including cards, certifications, audit logs, Canvas
import and sync controls, station visibility, certification permissions,
dashboard login management, and all export tools. Admins automatically have
permission for every station.

## Workflows

### Door Swipe

When someone swipes at a door reader, the server checks whether the card is
known and active. If allowed, the person is logged as inside the space. A later
door swipe out clears their inside status and records the total time they were
in the space.

### Station Swipe

When someone swipes at a station reader, the server checks whether the card is
known, active, and allowed for that station. If the station requires
certification, the user must be certified first. If the station does not
require certification, the swipe is logged as usage only.

### Certification Swipe

Staff or Admin cards can use the station double-swipe certification flow when
the station allows it. The server arms certification mode after the confirm
swipe, then the next valid trainee swipe creates or reactivates that station
certification and logs who granted it.

### Unknown Card Swipe

If a card is not in the card database, the swipe is still recorded as an
unknown-card event. Those swipes appear in the Pending Cards queue so Staff or
Admin can enroll the card later.

### Dashboard Refresh

The dashboard refreshes live counts, current sessions, cards, certifications,
and pending items from the server based on the current role.

## LED Guide

The Pico LED uses these common states:

- Green: swipe accepted or certification succeeded
- Red: swipe denied
- Yellow: waiting or ready state
- Blue slow blink: certification mode armed
- Blue fast blink: waiting for the second confirm swipe

## Project Files

- `app.py`: API, SQLite schema, authentication, swipe rules, and CSV exports.
- `dashboard.html`: single-file dashboard UI.
- `config.json`: reader names and door/station kinds.
- `station-server.service`: Raspberry Pi systemd service.
- `test_app.py`: isolated regression tests that do not use the live database.

The live database is `simple_station_swipes.db`. SQLite WAL sidecar files may
appear while the server is running. They are intentionally ignored by Git.

## Raspberry Pi Setup

These commands assume the service account and project directory are `siil` and
`/home/siil/station-server`.

```bash
sudo apt update
sudo apt install -y python3-venv
cd /home/siil/station-server
python3 -m venv venv
./venv/bin/python -m pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
```

Create `/etc/station-server.env`:

```bash
sudo nano /etc/station-server.env
```

```ini
STATION_API_KEY=replace-with-a-long-random-shared-key
STATION_PERSON_REF_SECRET=replace-with-a-different-long-random-key
STATION_BOOTSTRAP_ADMIN_CARD_ID=bootstrap-admin-card
STATION_BOOTSTRAP_ADMIN_USERNAME=siil
STATION_BOOTSTRAP_ADMIN_PASSWORD=replace-with-a-strong-password
STATION_BOOTSTRAP_ADMIN_NAME=Bootstrap Admin
```

Then protect the file and install the service:

```bash
sudo chmod 600 /etc/station-server.env
sudo cp /home/siil/station-server/station-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now station-server
```

Generate secrets with `openssl rand -hex 32`. The `STATION_API_KEY` value must
exactly match `STATION_API_KEY` in every Pico reader file. Do not commit real
keys or passwords to Git.

The bootstrap login is the value of `STATION_BOOTSTRAP_ADMIN_USERNAME`, not the
card ID. Bootstrap creation is idempotent: normal restarts do not reset an
existing active Admin password. If no active Admin remains, the configured
bootstrap account is restored on the next restart as a recovery path.

## Service Commands

```bash
sudo systemctl restart station-server
sudo systemctl status station-server --no-pager
sudo journalctl -u station-server -n 100 --no-pager
sudo journalctl -u station-server -f
```

The service runs one Gunicorn worker with four threads. Login sessions and
station certification timers live in memory, so multiple workers would split
that state. A Pi reboot signs dashboard users out; SQLite data remains intact.

## Common Commands

```bash
ssh siil@100.101.201.10
```

```powershell
scp "C:\path\to\file.py" siil@100.101.201.10:/home/siil/station-server/
```

```bash
sudo systemctl restart station-server
sudo systemctl status station-server --no-pager
sudo journalctl -u station-server -n 50 --no-pager
sudo systemctl stop station-server
sudo systemctl start station-server
```

```bash
sudo systemctl stop station-server
rm /home/siil/station-server/simple_station_swipes.db
sudo systemctl start station-server
```

```bash
cd /home/siil/station-server
./venv/bin/python app.py
```

Open the dashboard locally at `http://server.local:5000/dashboard` or through
Tailscale at `http://100.101.201.10:5000/dashboard`.

## Upload Through Tailscale

From PowerShell in this folder:

```powershell
scp .\app.py .\dashboard.html .\config.json .\requirements.txt .\station-server.service .\test_app.py .\README.md siil@100.101.201.10:/home/siil/station-server/
```

After dependency or service-file changes:

```bash
cd /home/siil/station-server
./venv/bin/pip install -r requirements.txt
sudo cp station-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart station-server
sudo systemctl status station-server --no-pager
```

## Canvas Import

The Admin import accepts UTF-8 CSV or tab-separated data copied from Canvas.
Required identity columns are `Email`, `Student`, and `bid`. The nine supported
course columns are identified by the Canvas course IDs in their headings.

- `1` means certified.
- A blank cell means not certified.
- Local certification changes that have not yet been reflected in Canvas stay
  in the Canvas Queue and are not overwritten by an older Canvas export.

Importing is a baseline synchronization, not an append-only operation. Review
the selected file before confirming the import.

## Exports

Staff and Admin can download swipe and active-person CSV files from the site.
Only Admin can export the audit log. Station-status CSV remains public but
omits names unless requested by Staff or Admin.

## Testing

Run the isolated suite from the project directory:

```bash
./venv/bin/python -m unittest -v test_app.py
```

## Database Backup

Stop the service before copying the database so the backup is consistent:

```bash
sudo systemctl stop station-server
cp simple_station_swipes.db simple_station_swipes.backup.db
sudo systemctl start station-server
```

Treat a database reset as a pre-launch-only operation. The database contains
the card registry, master certification state, usage history, and audit trail.
