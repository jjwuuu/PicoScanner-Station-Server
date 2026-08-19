"""Add or remove removable demo data for the Admin analytics dashboard."""

import argparse
from datetime import datetime, timedelta, timezone

import app as station_app


DEMO_CARD_PREFIX = "DEMO-ANALYTICS-"
DEMO_EVENT_PREFIX = "demo-analytics-"
DEMO_NOTE = "Removable analytics dashboard demo data"

DEMO_PEOPLE = (
    ("DEMO-ANALYTICS-001", "Alex Rivera", "alex.demo@example.test", "User"),
    ("DEMO-ANALYTICS-002", "Jordan Lee", "jordan.demo@example.test", "User"),
    ("DEMO-ANALYTICS-003", "Taylor Chen", "taylor.demo@example.test", "User"),
    ("DEMO-ANALYTICS-004", "Morgan Patel", "morgan.demo@example.test", "User"),
    ("DEMO-ANALYTICS-STAFF", "Demo Staff", "staff.demo@example.test", "Staff"),
    (
        "DEMO-ANALYTICS-VOLUNTEER",
        "Demo Volunteer",
        "volunteer.demo@example.test",
        "Volunteer",
    ),
)

# (station_id, completed sessions, base duration in minutes)
STATION_ACTIVITY = (
    ("3d-printing", 9, 105),
    ("soldering", 7, 70),
    ("laser-cutting", 6, 42),
    ("sewing", 5, 80),
    ("vinyl", 4, 35),
    ("embroidery", 3, 55),
)


def iso_utc(value):
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def recent_local_time(days_ago, hour, minute=0):
    local_now = datetime.now(station_app.SPACE_TIMEZONE)
    local_value = (local_now - timedelta(days=days_ago)).replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )
    return local_value.astimezone(timezone.utc)


def clear_demo_data(conn):
    conn.execute(
        "DELETE FROM active_sessions WHERE card_id LIKE ?",
        (f"{DEMO_CARD_PREFIX}%",),
    )
    deleted_events = conn.execute(
        "DELETE FROM swipe_events WHERE event_id LIKE ?",
        (f"{DEMO_EVENT_PREFIX}%",),
    ).rowcount
    deleted_cards = conn.execute(
        "DELETE FROM cards WHERE card_id LIKE ?",
        (f"{DEMO_CARD_PREFIX}%",),
    ).rowcount
    return deleted_events, deleted_cards


def add_event(
    conn,
    sequence,
    *,
    card_id,
    station_id,
    station_name,
    station_kind,
    timestamp,
    action,
    duration_seconds=None,
    active_users=0,
):
    conn.execute(
        """
        INSERT INTO swipe_events (
            card_id, station_id, station_name, station_kind, timestamp,
            action, allowed, duration_seconds, active_users, warning,
            details, event_id
        ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, '', ?, ?)
        """,
        (
            card_id,
            station_id,
            station_name,
            station_kind,
            iso_utc(timestamp),
            action,
            duration_seconds,
            active_users,
            DEMO_NOTE,
            f"{DEMO_EVENT_PREFIX}{sequence:04d}",
        ),
    )


def seed_demo_data(conn):
    timestamp = station_app.now_iso()
    for card_id, name, email, designation in DEMO_PEOPLE:
        conn.execute(
            """
            INSERT INTO cards (
                card_id, bronco_id, name, email, designation,
                active, notes, updated_at
            ) VALUES (?, '', ?, ?, ?, 1, ?, ?)
            ON CONFLICT(card_id) DO UPDATE SET
                name = excluded.name,
                email = excluded.email,
                designation = excluded.designation,
                active = 1,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (card_id, name, email, designation, DEMO_NOTE, timestamp),
        )

    station_names = {
        row["id"]: row["name"]
        for row in conn.execute(
            "SELECT id, name FROM stations WHERE kind = 'station'"
        ).fetchall()
    }
    missing = [station_id for station_id, _, _ in STATION_ACTIVITY if station_id not in station_names]
    if missing:
        raise RuntimeError("Missing configured stations: " + ", ".join(missing))

    user_cards = [person[0] for person in DEMO_PEOPLE[:4]]
    sequence = 1
    completed_sessions = 0
    for station_offset, (station_id, session_count, base_minutes) in enumerate(
        STATION_ACTIVITY
    ):
        for session_index in range(session_count):
            card_id = user_cards[(session_index + station_offset) % len(user_cards)]
            days_ago = 1 + ((session_index * 2 + station_offset) % 25)
            start_hour = 12 + ((session_index + station_offset) % 4)
            started_at = recent_local_time(days_ago, start_hour, (session_index * 7) % 50)
            duration_seconds = (base_minutes + (session_index % 3) * 12) * 60
            ended_at = started_at + timedelta(seconds=duration_seconds)
            add_event(
                conn,
                sequence,
                card_id=card_id,
                station_id=station_id,
                station_name=station_names[station_id],
                station_kind="station",
                timestamp=started_at,
                action="station_in",
                active_users=1,
            )
            sequence += 1
            add_event(
                conn,
                sequence,
                card_id=card_id,
                station_id=station_id,
                station_name=station_names[station_id],
                station_kind="station",
                timestamp=ended_at,
                action="station_out",
                duration_seconds=duration_seconds,
                active_users=0,
            )
            sequence += 1
            completed_sessions += 1

    # These visits cross the configured opening-hours boundary and populate the
    # authorized after-hours Staff/Volunteer charts.
    after_hours_visits = (
        ("DEMO-ANALYTICS-STAFF", 2, 16, 30, 180),
        ("DEMO-ANALYTICS-STAFF", 9, 15, 30, 240),
        ("DEMO-ANALYTICS-VOLUNTEER", 4, 9, 0, 180),
        ("DEMO-ANALYTICS-VOLUNTEER", 13, 16, 0, 150),
    )
    for card_id, days_ago, start_hour, start_minute, duration_minutes in after_hours_visits:
        started_at = recent_local_time(days_ago, start_hour, start_minute)
        ended_at = started_at + timedelta(minutes=duration_minutes)
        add_event(
            conn,
            sequence,
            card_id=card_id,
            station_id="front-door",
            station_name="Front Door",
            station_kind="door",
            timestamp=started_at,
            action="enter",
            active_users=1,
        )
        sequence += 1
        add_event(
            conn,
            sequence,
            card_id=card_id,
            station_id="front-door",
            station_name="Front Door",
            station_kind="door",
            timestamp=ended_at,
            action="exit",
            duration_seconds=duration_minutes * 60,
            active_users=0,
        )
        sequence += 1

    # One active demo session exercises the Active Now column without altering
    # the completed-session totals.
    conn.execute(
        """
        INSERT INTO active_sessions (card_id, station_id, station_name, started_at)
        VALUES (?, 'soldering', ?, ?)
        """,
        (
            "DEMO-ANALYTICS-001",
            station_names["soldering"],
            iso_utc(datetime.now(timezone.utc) - timedelta(minutes=18)),
        ),
    )
    return completed_sessions, sequence - 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clear",
        action="store_true",
        help="remove analytics demo cards, events, and active sessions",
    )
    args = parser.parse_args()

    station_app.init_db()
    with station_app.db_lock:
        conn = station_app.db_connect()
        try:
            deleted_events, deleted_cards = clear_demo_data(conn)
            if args.clear:
                conn.commit()
                print(
                    f"Removed {deleted_events} demo events and "
                    f"{deleted_cards} demo cards from {station_app.DB_PATH}"
                )
                return

            completed_sessions, event_count = seed_demo_data(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    print(f"Analytics demo data added to {station_app.DB_PATH}")
    print(f"Created {completed_sessions} completed station sessions and {event_count} events")
    print("Open Dashboard > Analytics as an Admin, then refresh the page")
    print("Remove this data later with: ./venv/bin/python seed_analytics_demo.py --clear")


if __name__ == "__main__":
    main()
