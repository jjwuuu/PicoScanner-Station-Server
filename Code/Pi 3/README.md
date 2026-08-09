# Pi Station Server

This is the local swipe server for the Raspberry Pi Zero W.

It separates doors from shop stations:

```text
Door swipe    -> enter or exit the building
Station swipe -> start or end station usage
```

Doors count people inside. Stations do not add to the building count.

## Current Places

Doors:

```text
front-door
back-door
```

Stations:

```text
3d-printing
soldering
embroidery
sewing
laser-cutting
buttons-stickers
vinyl
```

## Mismatch Handling

The server avoids double-counting cards:

```text
Same card enters through a door once -> counted as 1 person inside
Same card exits through either door -> removed from people inside
Station swipe does not change people-inside count
```

If someone leaves through a door while still checked into a station, the server:

```text
flags the card on the dashboard
auto-closes the open station session
logs a station_auto_out event
```

If someone swipes into a second station without swiping out of the first one, the server:

```text
auto-closes the old station session
starts the new station session
shows a moved_station_without_swipe_out warning
```

## Data Flow

```text
Pico W scanner -> hotspot Wi-Fi -> Pi Zero W server -> dashboard and Excel
```

## Run On The Pi

```bash
cd ~/station-server
source venv/bin/activate
python app.py
```

Open the dashboard:

```text
http://server.local:5000/dashboard
```

or:

```text
http://192.168.1.41:5000/dashboard
```

The page has three tabs:

```text
Dashboard       live people/station status, showing names when cards are known
Certifications  assign a card/person to stations
Card Database   add or edit card ID, name, email, and designation
```

## Dashboard Access

The dashboard can always show live status, but editing is password locked:

```text
Staff password      edit certifications and card database
Volunteer password  add or edit card database only
```

For quick testing, the defaults are:

```text
staff
volunteer
```

Change them before using this over Tailscale or any shared network:

```bash
export STATION_STAFF_PASSWORD='your-staff-password'
export STATION_VOLUNTEER_PASSWORD='your-volunteer-password'
python app.py
```

If using systemd, add these under `[Service]` in `station-server.service`:

```ini
Environment=STATION_STAFF_PASSWORD=your-staff-password
Environment=STATION_VOLUNTEER_PASSWORD=your-volunteer-password
```

Card designations are:

```text
Staff
Volunteer
User
```

## Pico W Request

Each Pico should send its place as variables.
The server requires a shared station API key on every swipe request.

On the Pi:

```bash
export STATION_API_KEY='change-this-shared-station-key'
python app.py
```

If using systemd, add this under `[Service]` in `station-server.service`:

```ini
Environment=STATION_API_KEY=change-this-shared-station-key
```

Each Pico firmware file must use the same value:

```python
STATION_API_KEY = "change-this-shared-station-key"
```

Soldering station example:

```python
STATION_ID = "soldering"
STATION_NAME = "Soldering Station"
STATION_KIND = "station"
```

Front door example:

```python
STATION_ID = "front-door"
STATION_NAME = "Front Door"
STATION_KIND = "door"
```

Request body:

```json
{
  "card_id": "209451056",
  "station_id": "soldering",
  "station_name": "Soldering Station",
  "station_kind": "station"
}
```

Door response example:

```json
{
  "card_id": "209451056",
  "station_id": "front-door",
  "station_name": "Front Door",
  "station_kind": "door",
  "action": "enter",
  "duration_seconds": null,
  "active_users": 1,
  "warning": "",
  "details": ""
}
```

Station response example:

```json
{
  "card_id": "209451056",
  "station_id": "soldering",
  "station_name": "Soldering Station",
  "station_kind": "station",
  "action": "station_in",
  "duration_seconds": null,
  "active_users": 1,
  "warning": "",
  "details": ""
}
```

## Test Data

With the server running, open a second SSH session:

```bash
cd ~/station-server
source venv/bin/activate
python send_test_data.py http://127.0.0.1:5000
```

The test data includes a mismatch where a card exits through a door while still checked into soldering.

## Excel Power Query

Excel is for history/reporting. The dashboard is for live status.

In Excel:

```text
Data -> Get Data -> From Web
```

Swipe history:

```text
http://server.local:5000/swipes.csv
```

People currently inside:

```text
http://server.local:5000/active.csv
```

Station status:

```text
http://server.local:5000/station_status.csv
```

`/swipes.csv` columns:

```text
card_id
station_id
station_name
station_kind
timestamp
action
duration_seconds
active_users
warning
details
```

## Auto-Start On Boot

After the server works manually:

```bash
sudo cp station-server.service /etc/systemd/system/station-server.service
sudo systemctl daemon-reload
sudo systemctl enable station-server
sudo systemctl start station-server
sudo systemctl status station-server
```

## Reset Test Data

Stop the server, delete the database, and start it again:

```bash
rm simple_station_swipes.db
python app.py
```
