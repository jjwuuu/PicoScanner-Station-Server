# RFID Station Server

Flask server and browser dashboard for makerspace door entry, station usage,
card enrollment, certifications, Canvas synchronization, and audit history.

## Files

- `app.py`: API, SQLite schema, authentication, swipe rules, and CSV exports.
- `dashboard.html`: single-file dashboard UI.
- `config.json`: authoritative reader names and door/station kinds.
- `station-server.service`: Raspberry Pi systemd service.
- `send_test_data.py`: optional command-line swipe generator.
- `test_app.py`: isolated regression tests; it never uses the live database.

The live database is `simple_station_swipes.db`. SQLite WAL sidecar files may
also appear while the server is running. These files are intentionally ignored
by Git.

## Raspberry Pi Setup

These commands assume the service account and project directory are
`siil` and `/home/siil/station-server`.

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

The service deliberately runs one Gunicorn worker with four threads. Login
sessions and station certification-mode timers are kept in memory, so using
multiple workers would split that state. A Pi reboot signs dashboard users out;
all SQLite data remains intact.

Open the dashboard locally at `http://server.local:5000/dashboard` or through
Tailscale at `http://100.101.201.10:5000/dashboard`.

## Upload Through Tailscale

From PowerShell in this folder:

```powershell
scp .\app.py .\dashboard.html .\config.json .\requirements.txt .\station-server.service .\send_test_data.py .\test_app.py .\README.md siil@100.101.201.10:/home/siil/station-server/
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

## Access Model

- Signed out: aggregate people count, aggregate station usage, and last swipe.
- Volunteer: people inside, anonymous station counts, cards, and certifications.
- Staff: full operations data except Admin-only audit/account/import controls.
- Admin: all data and controls.

BroncoID is returned only to Admin sessions. Volunteers cannot create Staff
records or edit higher-access accounts. Admin is the only role that can manage
dashboard credentials, station visibility, certification permissions, Canvas
imports, and audit exports.

Every Staff or Volunteer must have an explicit per-station permission before
granting or revoking certifications there. Admin accounts automatically have
all station permissions. The same permission is enforced by the dashboard and
the station-reader double-swipe flow.

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
Only Admin can export the audit log. Station-status CSV remains public but omits
names unless requested by Staff or Admin. Protected downloads use the login
header and never place session tokens in URLs.

## Testing

Run the isolated suite from the project directory:

```bash
./venv/bin/python -m unittest -v test_app.py
```

For a command-line swipe test:

```bash
STATION_API_KEY='your-key' ./venv/bin/python send_test_data.py http://127.0.0.1:5000
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
