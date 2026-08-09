import csv
import io
import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

from flask import Flask, Response, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "simple_station_swipes.db")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DASHBOARD_PATH = os.path.join(BASE_DIR, "dashboard.html")
BOOTSTRAP_ADMIN_CARD_ID = os.environ.get("STATION_BOOTSTRAP_ADMIN_CARD_ID", "").strip()
BOOTSTRAP_ADMIN_PASSWORD = os.environ.get("STATION_BOOTSTRAP_ADMIN_PASSWORD", "")
BOOTSTRAP_ADMIN_NAME = os.environ.get("STATION_BOOTSTRAP_ADMIN_NAME", "Bootstrap Admin")
STATION_API_KEY = os.environ.get("STATION_API_KEY", "").strip()
ROLE_LEVELS = {"volunteer": 1, "staff": 2, "admin": 3}
CERT_CONFIRM_SECONDS = 4
CERT_MODE_SECONDS = 40

app = Flask(__name__)
db_lock = threading.RLock()
session_tokens = {}
cert_modes = {}


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value):
    return datetime.fromisoformat(value)


def normalize_access_role(value):
    text = str(value or "").strip().lower()
    return text if text in ROLE_LEVELS else ""


def role_label(role):
    normalized = normalize_access_role(role)
    return normalized.title() if normalized else ""


def role_allows(actual_role, *allowed_roles):
    actual_level = ROLE_LEVELS.get(normalize_access_role(actual_role), 0)
    return any(
        actual_level >= ROLE_LEVELS.get(normalize_access_role(role), 999)
        for role in allowed_roles
    )


def token_from_request():
    return (
        request.headers.get("X-Access-Token", "")
        or request.args.get("access_token", "")
        or ""
    )


def account_for_token(token):
    session = session_tokens.get(token)
    if not session:
        return None

    with db_lock:
        conn = db_connect()
        row = conn.execute(
            """
            SELECT
                user_accounts.card_id,
                user_accounts.role,
                user_accounts.active,
                cards.name,
                cards.email
            FROM user_accounts
            JOIN cards ON cards.card_id = user_accounts.card_id
            WHERE user_accounts.card_id = ?
            """,
            (session["card_id"],),
        ).fetchone()
        conn.close()

    if not row or not row["active"]:
        session_tokens.pop(token, None)
        return None

    return dict(row)


def require_access(*allowed_roles):
    account = account_for_token(token_from_request())
    if account and role_allows(account["role"], *allowed_roles):
        return normalize_access_role(account["role"]), None

    if allowed_roles == ("admin",):
        message = "Admin login required"
    elif allowed_roles == ("staff",):
        message = "Staff or admin login required"
    else:
        message = "Authorized login required"

    return "", (jsonify({"ok": False, "error": message}), 403)


def require_station_api_key():
    provided_key = request.headers.get("X-Station-Key", "")
    if STATION_API_KEY and secrets.compare_digest(provided_key, STATION_API_KEY):
        return None

    return jsonify({"ok": False, "error": "Station API key required"}), 401


def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(conn, table, column, definition):
    columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if column not in [row["name"] for row in columns]:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    with db_lock:
        conn = db_connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS stations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'station',
                requires_certification INTEGER NOT NULL DEFAULT 1,
                cert_override_active INTEGER NOT NULL DEFAULT 0,
                cert_override_by TEXT NOT NULL DEFAULT '',
                cert_override_updated_at TEXT NOT NULL DEFAULT '',
                cert_override_expires_at TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS active_people (
                card_id TEXT PRIMARY KEY,
                entered_at TEXT NOT NULL,
                entry_door_id TEXT NOT NULL,
                entry_door_name TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS active_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id TEXT NOT NULL,
                station_id TEXT NOT NULL,
                station_name TEXT NOT NULL,
                started_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cards (
                card_id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                student_id TEXT NOT NULL DEFAULT '',
                designation TEXT NOT NULL DEFAULT 'User',
                active INTEGER NOT NULL DEFAULT 1,
                notes TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_accounts (
                card_id TEXT PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'Volunteer',
                password_hash TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (card_id) REFERENCES cards(card_id)
            );

            CREATE TABLE IF NOT EXISTS certifications (
                card_id TEXT NOT NULL,
                station_id TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                notes TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                granted_via TEXT NOT NULL DEFAULT 'dashboard',
                granted_by TEXT NOT NULL DEFAULT '',
                granted_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (card_id, station_id),
                FOREIGN KEY (card_id) REFERENCES cards(card_id),
                FOREIGN KEY (station_id) REFERENCES stations(id)
            );

            CREATE TABLE IF NOT EXISTS certify_permissions (
                card_id TEXT NOT NULL,
                station_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (card_id, station_id),
                FOREIGN KEY (card_id) REFERENCES user_accounts(card_id),
                FOREIGN KEY (station_id) REFERENCES stations(id)
            );

            CREATE TABLE IF NOT EXISTS swipe_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id TEXT NOT NULL,
                station_id TEXT NOT NULL,
                station_name TEXT NOT NULL,
                station_kind TEXT NOT NULL DEFAULT 'station',
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                allowed INTEGER NOT NULL DEFAULT 1,
                duration_seconds INTEGER,
                active_users INTEGER NOT NULL,
                warning TEXT NOT NULL DEFAULT '',
                details TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                actor_card_id TEXT NOT NULL DEFAULT '',
                actor_name TEXT NOT NULL DEFAULT '',
                actor_role TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL,
                target_type TEXT NOT NULL DEFAULT '',
                target_id TEXT NOT NULL DEFAULT '',
                details TEXT NOT NULL DEFAULT ''
            );
            """
        )

        ensure_column(conn, "stations", "kind", "TEXT NOT NULL DEFAULT 'station'")
        ensure_column(conn, "swipe_events", "station_kind", "TEXT NOT NULL DEFAULT 'station'")
        ensure_column(conn, "swipe_events", "allowed", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(conn, "swipe_events", "warning", "TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "swipe_events", "details", "TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "cards", "student_id", "TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "cards", "designation", "TEXT NOT NULL DEFAULT 'User'")
        ensure_column(
            conn,
            "stations",
            "requires_certification",
            "INTEGER NOT NULL DEFAULT 1",
        )
        ensure_column(
            conn,
            "stations",
            "cert_override_active",
            "INTEGER NOT NULL DEFAULT 0",
        )
        ensure_column(conn, "stations", "cert_override_by", "TEXT NOT NULL DEFAULT ''")
        ensure_column(
            conn,
            "stations",
            "cert_override_updated_at",
            "TEXT NOT NULL DEFAULT ''",
        )
        ensure_column(
            conn,
            "stations",
            "cert_override_expires_at",
            "TEXT NOT NULL DEFAULT ''",
        )
        ensure_column(
            conn,
            "certifications",
            "granted_via",
            "TEXT NOT NULL DEFAULT 'dashboard'",
        )
        ensure_column(
            conn,
            "certifications",
            "granted_by",
            "TEXT NOT NULL DEFAULT ''",
        )
        ensure_column(
            conn,
            "certifications",
            "granted_at",
            "TEXT NOT NULL DEFAULT ''",
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_certifications_card_station
            ON certifications(card_id, station_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cards_email
            ON cards(email)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_accounts_role
            ON user_accounts(role)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_swipe_events_timestamp
            ON swipe_events(timestamp)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp
            ON audit_log(timestamp)
            """
        )
        conn.execute("PRAGMA optimize")

        conn.commit()
        conn.close()


def seed_stations():
    if not os.path.exists(CONFIG_PATH):
        return

    with open(CONFIG_PATH, "r", encoding="utf-8") as file:
        config = json.load(file)

    with db_lock:
        conn = db_connect()
        for station in config.get("stations", []):
            conn.execute(
                """
                INSERT INTO stations (id, name, kind)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    kind = excluded.kind
                """,
                (
                    station["id"],
                    station["name"],
                    station.get("kind", "station"),
                ),
            )
        conn.commit()
        conn.close()


def bootstrap_admin():
    if not BOOTSTRAP_ADMIN_CARD_ID or not BOOTSTRAP_ADMIN_PASSWORD:
        return

    with db_lock:
        conn = db_connect()
        admin_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM user_accounts
            WHERE lower(role) = 'admin' AND active = 1
            """
        ).fetchone()["count"]

        if admin_count:
            conn.close()
            return

        timestamp = now_iso()
        conn.execute(
            """
            INSERT OR IGNORE INTO cards (
                card_id, name, email, designation, active, notes, updated_at
            )
            VALUES (?, ?, '', 'Staff', 1, 'Bootstrap admin account', ?)
            """,
            (BOOTSTRAP_ADMIN_CARD_ID, BOOTSTRAP_ADMIN_NAME, timestamp),
        )
        conn.execute(
            """
            INSERT INTO user_accounts (
                card_id, role, password_hash, active, updated_at
            )
            VALUES (?, 'Admin', ?, 1, ?)
            ON CONFLICT(card_id) DO UPDATE SET
                role = 'Admin',
                password_hash = excluded.password_hash,
                active = 1,
                updated_at = excluded.updated_at
            """,
            (
                BOOTSTRAP_ADMIN_CARD_ID,
                generate_password_hash(BOOTSTRAP_ADMIN_PASSWORD),
                timestamp,
            ),
        )
        conn.commit()
        conn.close()


def infer_kind(station_id, station_name):
    text = f"{station_id} {station_name}".lower()
    return "door" if "door" in text else "station"


def override_is_effective(station):
    if not station or not station["cert_override_active"]:
        return False

    expires_at = station["cert_override_expires_at"]
    if not expires_at:
        return False

    try:
        return parse_iso(expires_at) > datetime.now(timezone.utc)
    except ValueError:
        return False


def station_override_warning(station, warning="", details=""):
    if not override_is_effective(station):
        return warning, details

    override_details = (
        "Certification override active until "
        f"{station['cert_override_expires_at']}; "
        f"enabled by {station['cert_override_by'] or 'unknown'}"
    )
    if warning:
        override_details += f"; original warning={warning}"
    if details:
        override_details += f"; {details}"

    return "cert_override_active", override_details


def get_station_info(conn, station_id, provided_name="", provided_kind=""):
    station = conn.execute(
        """
        SELECT
            id,
            name,
            kind,
            requires_certification,
            cert_override_active,
            cert_override_by,
            cert_override_updated_at,
            cert_override_expires_at
        FROM stations
        WHERE id = ?
        """,
        (station_id,),
    ).fetchone()

    if station:
        return {
            "station_id": station_id,
            "station_name": station["name"],
            "station_kind": station["kind"],
            "requires_certification": bool(station["requires_certification"]),
            "cert_override_active": override_is_effective(station),
            "cert_override_by": station["cert_override_by"] or "",
            "cert_override_updated_at": station["cert_override_updated_at"] or "",
            "cert_override_expires_at": station["cert_override_expires_at"] or "",
        }

    station_name = provided_name or station_id
    station_kind = provided_kind or infer_kind(station_id, station_name)

    conn.execute(
        """
        INSERT INTO stations (id, name, kind)
        VALUES (?, ?, ?)
        """,
        (station_id, station_name, station_kind),
    )

    return {
        "station_id": station_id,
        "station_name": station_name,
        "station_kind": station_kind,
        "requires_certification": True,
        "cert_override_active": False,
        "cert_override_by": "",
        "cert_override_updated_at": "",
        "cert_override_expires_at": "",
    }


def building_active_count(conn):
    row = conn.execute("SELECT COUNT(*) AS count FROM active_people").fetchone()
    return int(row["count"])


def parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return str(value).strip().lower() in ("1", "true", "yes", "on", "active")


def normalize_designation(value):
    text = str(value or "User").strip().lower()
    options = {
        "staff": "Staff",
        "volunteer": "Volunteer",
        "user": "User",
    }
    return options.get(text, "User")


def card_row(conn, card_id):
    return conn.execute(
        """
        SELECT card_id, name, email, student_id, designation, active, notes, updated_at
        FROM cards
        WHERE card_id = ?
        """,
        (card_id,),
    ).fetchone()


def card_display(row, fallback):
    if row and row["name"]:
        return row["name"]
    return fallback


def account_field(account, key, default=""):
    if not account:
        return default
    if isinstance(account, sqlite3.Row):
        return account[key] if key in account.keys() else default
    return account.get(key, default)


def add_audit_log(conn, account, action, target_type="", target_id="", details=None):
    conn.execute(
        """
        INSERT INTO audit_log (
            timestamp,
            actor_card_id,
            actor_name,
            actor_role,
            action,
            target_type,
            target_id,
            details
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now_iso(),
            account_field(account, "card_id"),
            account_field(account, "name"),
            role_label(account_field(account, "role")),
            action,
            target_type,
            target_id,
            json.dumps(details or {}, sort_keys=True),
        ),
    )


def card_can_enter(row):
    return bool(row and row["active"])


def certify_permission_rows(conn):
    rows = conn.execute(
        """
        SELECT card_id, station_id, updated_at
        FROM certify_permissions
        ORDER BY card_id, station_id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def permitted_station_ids(conn, card_id):
    rows = conn.execute(
        """
        SELECT station_id
        FROM certify_permissions
        WHERE card_id = ?
        ORDER BY station_id
        """,
        (card_id,),
    ).fetchall()
    return [row["station_id"] for row in rows]


def account_can_certify_station(conn, account, station_id):
    if not account:
        return False

    role = normalize_access_role(account["role"])
    if role == "admin":
        return True

    if role not in ("staff", "volunteer"):
        return False

    row = conn.execute(
        """
        SELECT 1
        FROM certify_permissions
        WHERE card_id = ? AND station_id = ?
        """,
        (account["card_id"], station_id),
    ).fetchone()
    return bool(row)


def certifier_account_for_card(conn, card_id, station_id):
    row = conn.execute(
        """
        SELECT
            user_accounts.card_id,
            user_accounts.role,
            user_accounts.active,
            cards.name,
            cards.email,
            cards.active AS card_active
        FROM user_accounts
        JOIN cards ON cards.card_id = user_accounts.card_id
        WHERE user_accounts.card_id = ?
        """,
        (card_id,),
    ).fetchone()

    if not row or not row["active"] or not row["card_active"]:
        return None

    account = dict(row)
    if account_can_certify_station(conn, account, station_id):
        return account

    return None


def active_cert_mode(station_id):
    mode = cert_modes.get(station_id)
    if not mode:
        return None

    current_time = time.time()
    if (
        mode["arm_state"] == "pending_second_swipe"
        and mode["first_swipe_expires_at"] <= current_time
    ):
        cert_modes.pop(station_id, None)
        return None

    if mode["arm_state"] == "armed" and mode["expires_at"] <= current_time:
        cert_modes.pop(station_id, None)
        return None

    return mode


def start_pending_cert_mode(station_id, grantor):
    current_time = time.time()
    cert_modes[station_id] = {
        "grantor_card_id": grantor["card_id"],
        "grantor_name": grantor["name"] or grantor["card_id"],
        "grantor_role": grantor["role"],
        "expires_at": 0,
        "arm_state": "pending_second_swipe",
        "first_swipe_expires_at": current_time + CERT_CONFIRM_SECONDS,
    }
    return cert_modes[station_id]


def arm_cert_mode(station_id, grantor):
    current_time = time.time()
    cert_modes[station_id] = {
        "grantor_card_id": grantor["card_id"],
        "grantor_name": grantor["name"] or grantor["card_id"],
        "grantor_role": grantor["role"],
        "expires_at": current_time + CERT_MODE_SECONDS,
        "arm_state": "armed",
        "first_swipe_expires_at": 0,
    }
    return cert_modes[station_id]


def cert_mode_response(conn, card_id, station, action, led_signal, mode):
    return {
        "card_id": card_id,
        "station_id": station["station_id"],
        "station_name": station["station_name"],
        "station_kind": "station",
        "timestamp": now_iso(),
        "action": action,
        "allowed": True,
        "duration_seconds": None,
        "active_users": building_active_count(conn),
        "warning": "",
        "details": "",
        "led_signal": led_signal,
        "cert_mode_expires_at": mode["expires_at"],
    }


def is_certified(conn, card_id, station_id):
    row = conn.execute(
        """
        SELECT active
        FROM certifications
        WHERE card_id = ? AND station_id = ?
        """,
        (card_id, station_id),
    ).fetchone()
    return bool(row and row["active"])


def log_event(
    conn,
    card_id,
    station_id,
    station_name,
    station_kind,
    action,
    allowed=True,
    duration_seconds=None,
    warning="",
    details="",
):
    event_time = now_iso()
    active_users = building_active_count(conn)

    conn.execute(
        """
        INSERT INTO swipe_events (
            card_id, station_id, station_name, station_kind, timestamp,
            action, allowed, duration_seconds, active_users, warning, details
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            card_id,
            station_id,
            station_name,
            station_kind,
            event_time,
            action,
            1 if allowed else 0,
            duration_seconds,
            active_users,
            warning,
            details,
        ),
    )

    led_signal = "access_granted" if allowed else "access_denied"

    return {
        "card_id": card_id,
        "station_id": station_id,
        "station_name": station_name,
        "station_kind": station_kind,
        "timestamp": event_time,
        "action": action,
        "allowed": allowed,
        "duration_seconds": duration_seconds,
        "active_users": active_users,
        "warning": warning,
        "details": details,
        "led_signal": led_signal,
    }


def active_station_sessions_for_card(conn, card_id):
    return conn.execute(
        """
        SELECT id, card_id, station_id, station_name, started_at
        FROM active_sessions
        WHERE card_id = ?
        ORDER BY started_at
        """,
        (card_id,),
    ).fetchall()


def handle_door_swipe(conn, card_id, door_id, door_name):
    card = card_row(conn, card_id)
    active_person = conn.execute(
        """
        SELECT card_id, entered_at, entry_door_id, entry_door_name
        FROM active_people
        WHERE card_id = ?
        """,
        (card_id,),
    ).fetchone()

    if not active_person:
        if not card:
            return log_event(
                conn,
                card_id,
                door_id,
                door_name,
                "door",
                "denied",
                allowed=False,
                warning="unknown_card",
                details="Card is not in the card database",
            )

        if not card_can_enter(card):
            return log_event(
                conn,
                card_id,
                door_id,
                door_name,
                "door",
                "denied",
                allowed=False,
                warning="inactive_card",
                details="Card is disabled in the card database",
            )

        conn.execute(
            """
            INSERT INTO active_people (
                card_id, entered_at, entry_door_id, entry_door_name
            )
            VALUES (?, ?, ?, ?)
            """,
            (card_id, now_iso(), door_id, door_name),
        )
        return log_event(conn, card_id, door_id, door_name, "door", "enter")

    exited_at = datetime.now(timezone.utc).replace(microsecond=0)
    entered_at = parse_iso(active_person["entered_at"])
    duration_seconds = int((exited_at - entered_at).total_seconds())
    open_sessions = active_station_sessions_for_card(conn, card_id)

    conn.execute("DELETE FROM active_people WHERE card_id = ?", (card_id,))

    warning = ""
    details = ""

    if open_sessions:
        warning = "left_with_station_active"
        details = "; ".join(row["station_name"] for row in open_sessions)

        for session in open_sessions:
            started_at = parse_iso(session["started_at"])
            station_duration = int((exited_at - started_at).total_seconds())
            conn.execute("DELETE FROM active_sessions WHERE id = ?", (session["id"],))
            log_event(
                conn,
                card_id,
                session["station_id"],
                session["station_name"],
                "station",
                "station_auto_out",
                duration_seconds=station_duration,
                warning=warning,
                details=f"Auto closed because card exited at {door_name}",
            )

    return log_event(
        conn,
        card_id,
        door_id,
        door_name,
        "door",
        "exit",
        duration_seconds=duration_seconds,
        warning=warning,
        details=details,
    )


def grant_certification_via_swipe(conn, card, station, mode):
    timestamp = now_iso()
    grantor_card_id = mode["grantor_card_id"]
    grantor_name = mode["grantor_name"]
    trainee_name = card_display(card, card["card_id"])

    conn.execute(
        """
        INSERT INTO certifications (
            card_id,
            station_id,
            active,
            notes,
            updated_at,
            granted_via,
            granted_by,
            granted_at
        )
        VALUES (?, ?, 1, ?, ?, 'swipe', ?, ?)
        ON CONFLICT(card_id, station_id) DO UPDATE SET
            active = 1,
            notes = CASE
                WHEN certifications.notes = '' THEN excluded.notes
                ELSE certifications.notes
            END,
            updated_at = excluded.updated_at,
            granted_via = excluded.granted_via,
            granted_by = excluded.granted_by,
            granted_at = excluded.granted_at
        """,
        (
            card["card_id"],
            station["station_id"],
            f"Swipe-certified by {grantor_name}",
            timestamp,
            grantor_card_id,
            timestamp,
        ),
    )

    add_audit_log(
        conn,
        {
            "card_id": grantor_card_id,
            "name": grantor_name,
            "role": mode.get("grantor_role", ""),
        },
        "certification_granted_via_swipe",
        "certification",
        f"{card['card_id']}:{station['station_id']}",
        {
            "card_id": card["card_id"],
            "station_id": station["station_id"],
            "station_name": station["station_name"],
            "trainee_name": trainee_name,
        },
    )

    cert_modes.pop(station["station_id"], None)
    result = log_event(
        conn,
        card["card_id"],
        station["station_id"],
        station["station_name"],
        "station",
        "certification_granted",
        warning="cert_granted_via_swipe",
        details=(
            f"{trainee_name} certified for {station['station_name']} "
            f"via swipe by {grantor_name}"
        ),
    )
    result["led_signal"] = "cert_success"
    return result


def handle_station_swipe(conn, card_id, station_id, station):
    station_name = station["station_name"]
    requires_certification = station["requires_certification"]
    skip_cert_mode_for_this_swipe = False
    active_session = conn.execute(
        """
        SELECT id, started_at
        FROM active_sessions
        WHERE card_id = ? AND station_id = ?
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (card_id, station_id),
    ).fetchone()

    if active_session:
        ended_at = datetime.now(timezone.utc).replace(microsecond=0)
        started_at = parse_iso(active_session["started_at"])
        duration_seconds = int((ended_at - started_at).total_seconds())

        conn.execute("DELETE FROM active_sessions WHERE id = ?", (active_session["id"],))
        warning, details = station_override_warning(station)
        return log_event(
            conn,
            card_id,
            station_id,
            station_name,
            "station",
            "station_out",
            duration_seconds=duration_seconds,
            warning=warning,
            details=details,
        )

    if requires_certification:
        mode = active_cert_mode(station_id)
        if mode and mode["arm_state"] == "pending_second_swipe":
            if card_id == mode["grantor_card_id"]:
                grantor = certifier_account_for_card(conn, card_id, station_id)
                if grantor:
                    mode = arm_cert_mode(station_id, grantor)
                    return cert_mode_response(
                        conn,
                        card_id,
                        station,
                        "cert_mode_armed",
                        "cert_mode_armed",
                        mode,
                    )
                cert_modes.pop(station_id, None)
            else:
                cert_modes.pop(station_id, None)
                skip_cert_mode_for_this_swipe = True
    else:
        cert_modes.pop(station_id, None)

    card = card_row(conn, card_id)
    if not card:
        return log_event(
            conn,
            card_id,
            station_id,
            station_name,
            "station",
            "denied",
            allowed=False,
            warning="unknown_card",
            details="Card is not in the card database",
        )

    if not card_can_enter(card):
        return log_event(
            conn,
            card_id,
            station_id,
            station_name,
            "station",
            "denied",
            allowed=False,
            warning="inactive_card",
            details="Card is disabled in the card database",
        )

    grantor = (
        certifier_account_for_card(conn, card_id, station_id)
        if requires_certification
        else None
    )
    mode = active_cert_mode(station_id) if requires_certification else None

    if requires_certification and not skip_cert_mode_for_this_swipe:
        if mode and mode["arm_state"] == "armed":
            if grantor:
                mode = arm_cert_mode(station_id, grantor)
                return cert_mode_response(
                    conn,
                    card_id,
                    station,
                    "cert_mode_armed",
                    "cert_mode_armed",
                    mode,
                )
            return grant_certification_via_swipe(conn, card, station, mode)

        if grantor:
            mode = start_pending_cert_mode(station_id, grantor)
            return cert_mode_response(
                conn,
                card_id,
                station,
                "cert_mode_pending",
                "cert_mode_pending",
                mode,
            )

    override_active = override_is_effective(station)

    if (
        requires_certification
        and not override_active
        and not is_certified(conn, card_id, station_id)
    ):
        return log_event(
            conn,
            card_id,
            station_id,
            station_name,
            "station",
            "denied",
            allowed=False,
            warning="not_certified",
            details="Card is not certified for this station",
        )

    moved_from = active_station_sessions_for_card(conn, card_id)
    if moved_from:
        ended_at = datetime.now(timezone.utc).replace(microsecond=0)
        for session in moved_from:
            started_at = parse_iso(session["started_at"])
            station_duration = int((ended_at - started_at).total_seconds())
            conn.execute("DELETE FROM active_sessions WHERE id = ?", (session["id"],))
            log_event(
                conn,
                card_id,
                session["station_id"],
                session["station_name"],
                "station",
                "station_auto_out",
                duration_seconds=station_duration,
                warning="moved_station_without_swipe_out",
                details=f"Auto closed before starting {station_name}",
            )

    active_person = conn.execute(
        "SELECT card_id FROM active_people WHERE card_id = ?",
        (card_id,),
    ).fetchone()

    warning = ""
    details = ""
    if moved_from:
        warning = "moved_station_without_swipe_out"
        details = "; ".join(row["station_name"] for row in moved_from)
    elif not active_person:
        warning = "station_swipe_without_door_entry"
        details = "Card is not currently counted inside"

    warning, details = station_override_warning(station, warning, details)

    conn.execute(
        """
        INSERT INTO active_sessions (
            card_id, station_id, station_name, started_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (card_id, station_id, station_name, now_iso()),
    )

    return log_event(
        conn,
        card_id,
        station_id,
        station_name,
        "station",
        "station_in",
        warning=warning,
        details=details,
    )


@app.post("/swipe")
def swipe():
    key_error = require_station_api_key()
    if key_error:
        return key_error

    data = request.get_json(silent=True) or {}
    card_id = str(data.get("card_id", "")).strip()
    station_id = str(data.get("station_id", "")).strip()
    station_name = str(data.get("station_name", "")).strip()
    station_kind = str(data.get("station_kind", data.get("kind", ""))).strip()

    if not card_id or not station_id:
        return jsonify(
            {
                "error": "card_id and station_id are required",
                "card_id": card_id,
                "station_id": station_id,
            }
        ), 400

    with db_lock:
        conn = db_connect()
        station = get_station_info(
            conn,
            station_id,
            station_name,
            station_kind,
        )

        if station["station_kind"] == "door":
            result = handle_door_swipe(
                conn,
                card_id,
                station_id,
                station["station_name"],
            )
        else:
            result = handle_station_swipe(conn, card_id, station_id, station)

        conn.commit()
        conn.close()

    return jsonify(result)


@app.get("/health")
def health():
    return jsonify({"ok": True, "time": now_iso()})


@app.get("/")
@app.get("/dashboard")
def dashboard():
    with open(DASHBOARD_PATH, "r", encoding="utf-8") as file:
        return Response(file.read(), mimetype="text/html")


@app.get("/api/dashboard")
def dashboard_data():
    limit = request.args.get("limit", "20")
    account = account_for_token(token_from_request())
    role = normalize_access_role(account["role"]) if account else ""
    can_view_people = role in ("admin", "staff", "volunteer")
    can_view_full_dashboard = role in ("admin", "staff")

    try:
        limit = int(limit)
    except ValueError:
        limit = 20

    limit = max(1, min(limit, 100))

    with db_lock:
        conn = db_connect()
        total_active = building_active_count(conn)
        station_status = station_status_rows(conn)
        active_people = active_people_rows(conn) if can_view_people else []
        stations = [
            {
                **station,
                "active_cards": (
                    station["active_cards"]
                    if can_view_full_dashboard
                    else ""
                ),
            }
            for station in station_status
        ]
        active_sessions = active_session_rows(conn) if can_view_full_dashboard else []
        recent_swipes = (
            recent_swipe_rows(conn, limit)
            if can_view_full_dashboard
            else []
        )
        latest_swipes = recent_swipe_rows(conn, 1)
        warnings = warning_rows(conn, 10) if can_view_full_dashboard else []
        conn.close()

    return jsonify(
        {
            "server_time": now_iso(),
            "dashboard_access": role or "public",
            "total_active": total_active,
            "active_station_count": len(
                [
                    station
                    for station in station_status
                    if station["active_sessions"] > 0
                ]
            ),
            "last_swipe_at": (
                latest_swipes[0]["timestamp"]
                if latest_swipes
                else ""
            ),
            "stations": stations,
            "active_people": active_people,
            "active_sessions": active_sessions,
            "recent_swipes": recent_swipes,
            "warnings": warnings,
        }
    )


@app.post("/api/access")
def access_check():
    data = request.get_json(silent=True) or {}
    login = str(data.get("login", data.get("card_id", ""))).strip()
    password = str(data.get("password", ""))

    if not login or not password:
        return jsonify({"ok": False, "error": "Login and password are required"}), 400

    with db_lock:
        conn = db_connect()
        account = conn.execute(
            """
            SELECT
                user_accounts.card_id,
                user_accounts.role,
                user_accounts.password_hash,
                user_accounts.active,
                cards.name,
                cards.email
            FROM user_accounts
            JOIN cards ON cards.card_id = user_accounts.card_id
            WHERE user_accounts.card_id = ? OR lower(cards.email) = lower(?)
            LIMIT 1
            """,
            (login, login),
        ).fetchone()

        if (
            not account
            or not account["active"]
            or not check_password_hash(account["password_hash"], password)
        ):
            add_audit_log(
                conn,
                None,
                "login_failed",
                "account",
                login,
                {"login": login},
            )
            conn.commit()
            conn.close()
            return jsonify({"ok": False, "error": "Login not recognized"}), 403

        account = dict(account)
        token = secrets.token_urlsafe(32)
        role = normalize_access_role(account["role"])
        session_tokens[token] = {"card_id": account["card_id"]}
        add_audit_log(
            conn,
            account,
            "login",
            "account",
            account["card_id"],
            {"login": login},
        )
        conn.commit()
        conn.close()

    return jsonify(
        {
            "ok": True,
            "access_token": token,
            "role": role,
            "card_id": account["card_id"],
            "name": account["name"],
            "email": account["email"],
        }
    )


@app.post("/api/logout")
def logout():
    token = token_from_request()
    account = account_for_token(token)
    with db_lock:
        conn = db_connect()
        if account:
            add_audit_log(conn, account, "logout", "account", account["card_id"])
        conn.commit()
        conn.close()
    session_tokens.pop(token, None)
    return jsonify({"ok": True})


@app.get("/api/admin")
def admin_data():
    role, error = require_access("staff", "volunteer")
    if error:
        return error

    account = account_for_token(token_from_request())

    with db_lock:
        conn = db_connect()
        cards = card_rows(conn, include_accounts=(role == "admin"))
        stations = station_option_rows(conn)
        certifications = certification_rows(conn)
        certify_permissions = certify_permission_rows(conn) if role == "admin" else []
        audit_log = audit_log_rows(conn) if role == "admin" else []
        can_certify_station_ids = (
            [station["station_id"] for station in stations]
            if role == "admin"
            else permitted_station_ids(conn, account["card_id"])
        )
        conn.close()

    return jsonify(
        {
            "role": role,
            "cards": cards,
            "stations": stations,
            "certifications": certifications,
            "certify_permissions": certify_permissions,
            "audit_log": audit_log,
            "can_certify_station_ids": can_certify_station_ids,
        }
    )


@app.get("/api/pending-cards")
def pending_cards():
    role, error = require_access("staff", "volunteer")
    if error:
        return error

    with db_lock:
        conn = db_connect()
        rows = conn.execute(
            """
            SELECT
                latest.card_id,
                latest.timestamp AS last_seen_at,
                COALESCE(
                    NULLIF(latest.station_name, ''),
                    latest.station_id
                ) AS last_seen_station
            FROM swipe_events AS latest
            JOIN (
                SELECT card_id, MAX(id) AS latest_id
                FROM swipe_events
                WHERE warning = 'unknown_card'
                GROUP BY card_id
            ) AS newest
                ON newest.latest_id = latest.id
            LEFT JOIN cards
                ON cards.card_id = latest.card_id
            WHERE cards.card_id IS NULL
            ORDER BY latest.id DESC
            LIMIT 50
            """
        ).fetchall()
        conn.close()

    return jsonify(
        {
            "pending_cards": [
                {
                    "card_id": row["card_id"],
                    "last_seen_at": row["last_seen_at"],
                    "last_seen_station": row["last_seen_station"],
                }
                for row in rows
            ]
        }
    )


@app.post("/api/cards")
def save_card():
    role, error = require_access("staff", "volunteer")
    if error:
        return error

    account = account_for_token(token_from_request())
    data = request.get_json(silent=True) or {}
    card_id = str(data.get("card_id", "")).strip()
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip()
    student_id = str(data.get("student_id", "")).strip()
    designation = normalize_designation(data.get("designation", "User"))
    notes = str(data.get("notes", "")).strip()
    active = 1 if parse_bool(data.get("active", True)) else 0
    account_fields_present = any(
        key in data
        for key in ("login_role", "login_password", "login_active")
    )

    if not card_id:
        return jsonify({"ok": False, "error": "card_id is required"}), 400

    if account_fields_present and role != "admin":
        return jsonify(
            {
                "ok": False,
                "error": "Admin login required to edit dashboard credentials",
            }
        ), 403

    with db_lock:
        conn = db_connect()
        existing_card = card_row(conn, card_id)
        conn.execute(
            """
            INSERT INTO cards (
                card_id, name, email, student_id, designation, active, notes, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(card_id) DO UPDATE SET
                name = excluded.name,
                email = excluded.email,
                student_id = excluded.student_id,
                designation = excluded.designation,
                active = excluded.active,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (card_id, name, email, student_id, designation, active, notes, now_iso()),
        )

        if account_fields_present:
            login_role = normalize_access_role(data.get("login_role", ""))
            login_password = str(data.get("login_password", ""))
            login_active = 1 if parse_bool(data.get("login_active", True)) else 0

            if not login_role:
                conn.execute("DELETE FROM user_accounts WHERE card_id = ?", (card_id,))
            else:
                existing = conn.execute(
                    """
                    SELECT password_hash
                    FROM user_accounts
                    WHERE card_id = ?
                    """,
                    (card_id,),
                ).fetchone()

                if not login_password and not existing:
                    conn.close()
                    return jsonify(
                        {
                            "ok": False,
                            "error": "Password is required for a new login",
                        }
                    ), 400

                password_hash = (
                    generate_password_hash(login_password)
                    if login_password
                    else existing["password_hash"]
                )
                conn.execute(
                    """
                    INSERT INTO user_accounts (
                        card_id, role, password_hash, active, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(card_id) DO UPDATE SET
                        role = excluded.role,
                        password_hash = excluded.password_hash,
                        active = excluded.active,
                        updated_at = excluded.updated_at
                    """,
                    (
                        card_id,
                        role_label(login_role),
                        password_hash,
                        login_active,
                        now_iso(),
                    ),
                )

        add_audit_log(
            conn,
            account,
            "card_updated" if existing_card else "card_created",
            "card",
            card_id,
            {
                "name": name,
                "email": email,
                "student_id": student_id,
                "designation": designation,
                "active": bool(active),
                "login_fields_changed": account_fields_present,
            },
        )

        conn.commit()
        cards = card_rows(conn, include_accounts=(role == "admin"))
        conn.close()

    return jsonify({"ok": True, "cards": cards})


@app.delete("/api/cards/<card_id>")
def delete_card(card_id):
    role, error = require_access("admin")
    if error:
        return error

    account = account_for_token(token_from_request())
    card_id = str(card_id or "").strip()

    if not card_id:
        return jsonify({"ok": False, "error": "card_id is required"}), 400

    with db_lock:
        conn = db_connect()
        existing = card_row(conn, card_id)
        if not existing:
            conn.close()
            return jsonify({"ok": False, "error": "Card not found"}), 404

        related_counts = {
            "active_sessions": conn.execute(
                "SELECT COUNT(*) AS count FROM active_sessions WHERE card_id = ?",
                (card_id,),
            ).fetchone()["count"],
            "active_people": conn.execute(
                "SELECT COUNT(*) AS count FROM active_people WHERE card_id = ?",
                (card_id,),
            ).fetchone()["count"],
            "certifications": conn.execute(
                "SELECT COUNT(*) AS count FROM certifications WHERE card_id = ?",
                (card_id,),
            ).fetchone()["count"],
            "certify_permissions": conn.execute(
                "SELECT COUNT(*) AS count FROM certify_permissions WHERE card_id = ?",
                (card_id,),
            ).fetchone()["count"],
            "dashboard_login": conn.execute(
                "SELECT COUNT(*) AS count FROM user_accounts WHERE card_id = ?",
                (card_id,),
            ).fetchone()["count"],
        }

        conn.execute("DELETE FROM active_sessions WHERE card_id = ?", (card_id,))
        conn.execute("DELETE FROM active_people WHERE card_id = ?", (card_id,))
        conn.execute("DELETE FROM certifications WHERE card_id = ?", (card_id,))
        conn.execute("DELETE FROM certify_permissions WHERE card_id = ?", (card_id,))
        conn.execute("DELETE FROM user_accounts WHERE card_id = ?", (card_id,))
        conn.execute("DELETE FROM cards WHERE card_id = ?", (card_id,))

        for token, session in list(session_tokens.items()):
            if session.get("card_id") == card_id:
                session_tokens.pop(token, None)

        for station_id, mode in list(cert_modes.items()):
            if mode.get("grantor_card_id") == card_id:
                cert_modes.pop(station_id, None)

        add_audit_log(
            conn,
            account,
            "card_deleted",
            "card",
            card_id,
            {
                "name": existing["name"],
                "email": existing["email"],
                "student_id": existing["student_id"],
                "designation": existing["designation"],
                "swipe_events_preserved": True,
                **related_counts,
            },
        )

        conn.commit()
        cards = card_rows(conn, include_accounts=True)
        certifications = certification_rows(conn)
        certify_permissions = certify_permission_rows(conn)
        audit_log = audit_log_rows(conn)
        conn.close()

    return jsonify(
        {
            "ok": True,
            "cards": cards,
            "certifications": certifications,
            "certify_permissions": certify_permissions,
            "audit_log": audit_log,
        }
    )


@app.post("/api/stations")
def save_station_rules():
    role, error = require_access("staff")
    if error:
        return error

    account = account_for_token(token_from_request())
    data = request.get_json(silent=True) or {}
    station_id = str(data.get("station_id", "")).strip()

    if not station_id:
        return jsonify({"ok": False, "error": "station_id is required"}), 400

    with db_lock:
        conn = db_connect()
        station = conn.execute(
            """
            SELECT
                id,
                kind,
                requires_certification,
                cert_override_active,
                cert_override_by,
                cert_override_updated_at,
                cert_override_expires_at
            FROM stations
            WHERE id = ?
            """,
            (station_id,),
        ).fetchone()

        if not station or station["kind"] != "station":
            conn.close()
            return jsonify({"ok": False, "error": "station_id must be a station"}), 400

        requires_certification = station["requires_certification"]
        override_active = station["cert_override_active"]
        override_by = station["cert_override_by"] or ""
        override_updated_at = station["cert_override_updated_at"] or ""
        override_expires_at = station["cert_override_expires_at"] or ""

        if "requires_certification" in data:
            requires_certification = (
                1 if parse_bool(data.get("requires_certification")) else 0
            )

        if "cert_override_active" in data:
            override_updated_at = now_iso()
            if parse_bool(data.get("cert_override_active")):
                try:
                    duration_minutes = int(
                        data.get("cert_override_duration_minutes", 30)
                    )
                except (TypeError, ValueError):
                    conn.close()
                    return jsonify(
                        {
                            "ok": False,
                            "error": "Override duration must be a number of minutes",
                        }
                    ), 400

                duration_minutes = max(1, min(duration_minutes, 1440))
                expires_at = datetime.now(timezone.utc).replace(
                    microsecond=0
                ) + timedelta(minutes=duration_minutes)
                override_active = 1
                override_by = account["card_id"] if account else role
                override_expires_at = expires_at.isoformat()
            else:
                override_active = 0
                override_by = ""
                override_expires_at = ""

        conn.execute(
            """
            UPDATE stations
            SET
                requires_certification = ?,
                cert_override_active = ?,
                cert_override_by = ?,
                cert_override_updated_at = ?,
                cert_override_expires_at = ?
            WHERE id = ?
            """,
            (
                requires_certification,
                override_active,
                override_by,
                override_updated_at,
                override_expires_at,
                station_id,
            ),
        )
        add_audit_log(
            conn,
            account,
            "station_rules_updated",
            "station",
            station_id,
            {
                "requires_certification": bool(requires_certification),
                "cert_override_active": bool(override_active),
                "cert_override_by": override_by,
                "cert_override_expires_at": override_expires_at,
            },
        )
        conn.commit()
        stations = station_option_rows(conn)
        conn.close()

    return jsonify({"ok": True, "stations": stations})


@app.post("/api/certify-permissions")
def save_certify_permissions():
    role, error = require_access("admin")
    if error:
        return error

    actor = account_for_token(token_from_request())
    data = request.get_json(silent=True) or {}
    card_id = str(data.get("card_id", "")).strip()
    station_ids = [
        str(item).strip()
        for item in data.get("station_ids", [])
        if str(item).strip()
    ]
    station_ids = list(dict.fromkeys(station_ids))

    if not card_id:
        return jsonify({"ok": False, "error": "card_id is required"}), 400

    with db_lock:
        conn = db_connect()
        account = conn.execute(
            """
            SELECT card_id, role
            FROM user_accounts
            WHERE card_id = ? AND active = 1
            """,
            (card_id,),
        ).fetchone()

        if not account or normalize_access_role(account["role"]) not in (
            "staff",
            "volunteer",
        ):
            conn.close()
            return jsonify(
                {
                    "ok": False,
                    "error": "Choose an active Staff or Volunteer login",
                }
            ), 400

        valid_station_ids = {
            row["id"]
            for row in conn.execute(
                """
                SELECT id
                FROM stations
                WHERE kind = 'station'
                """
            ).fetchall()
        }
        if any(station_id not in valid_station_ids for station_id in station_ids):
            conn.close()
            return jsonify(
                {
                    "ok": False,
                    "error": "One or more station IDs are invalid",
                }
            ), 400

        conn.execute("DELETE FROM certify_permissions WHERE card_id = ?", (card_id,))
        timestamp = now_iso()
        for station_id in station_ids:
            conn.execute(
                """
                INSERT INTO certify_permissions (card_id, station_id, updated_at)
                VALUES (?, ?, ?)
                """,
                (card_id, station_id, timestamp),
            )

        add_audit_log(
            conn,
            actor,
            "certify_permissions_updated",
            "card",
            card_id,
            {"station_ids": station_ids},
        )
        conn.commit()
        rows = certify_permission_rows(conn)
        conn.close()

    return jsonify({"ok": True, "certify_permissions": rows})


@app.post("/api/certifications")
def save_certification():
    role, error = require_access("staff", "volunteer")
    if error:
        return error

    account = account_for_token(token_from_request())
    data = request.get_json(silent=True) or {}
    card_id = str(data.get("card_id", "")).strip()
    station_id = str(data.get("station_id", "")).strip()
    active = 1 if parse_bool(data.get("active", True)) else 0
    notes = str(data.get("notes", "")).strip()

    if not card_id or not station_id:
        return jsonify({"ok": False, "error": "card_id and station_id are required"}), 400

    with db_lock:
        conn = db_connect()
        card = card_row(conn, card_id)
        station = conn.execute(
            """
            SELECT id, kind
            FROM stations
            WHERE id = ?
            """,
            (station_id,),
        ).fetchone()

        if not card:
            conn.close()
            return jsonify({"ok": False, "error": "card_id is not in card database"}), 404

        if not station or station["kind"] != "station":
            conn.close()
            return jsonify({"ok": False, "error": "station_id must be a station"}), 400

        if not account_can_certify_station(conn, account, station_id):
            conn.close()
            return jsonify(
                {
                    "ok": False,
                    "error": (
                        "You are not authorized to manage certifications "
                        "for this station"
                    ),
                }
            ), 403

        timestamp = now_iso()
        granted_by = account["card_id"] if account else ""
        conn.execute(
            """
            INSERT INTO certifications (
                card_id,
                station_id,
                active,
                notes,
                updated_at,
                granted_via,
                granted_by,
                granted_at
            )
            VALUES (?, ?, ?, ?, ?, 'dashboard', ?, ?)
            ON CONFLICT(card_id, station_id) DO UPDATE SET
                active = excluded.active,
                notes = excluded.notes,
                updated_at = excluded.updated_at,
                granted_via = CASE
                    WHEN excluded.active = 1
                    THEN excluded.granted_via
                    ELSE certifications.granted_via
                END,
                granted_by = CASE
                    WHEN excluded.active = 1
                    THEN excluded.granted_by
                    ELSE certifications.granted_by
                END,
                granted_at = CASE
                    WHEN excluded.active = 1
                    THEN excluded.granted_at
                    ELSE certifications.granted_at
                END
            """,
            (card_id, station_id, active, notes, timestamp, granted_by, timestamp),
        )
        add_audit_log(
            conn,
            account,
            "certification_granted" if active else "certification_revoked",
            "certification",
            f"{card_id}:{station_id}",
            {
                "card_id": card_id,
                "station_id": station_id,
                "active": bool(active),
                "notes": notes,
            },
        )
        conn.commit()
        certifications = certification_rows(conn)
        conn.close()

    return jsonify({"ok": True, "certifications": certifications})


@app.get("/status")
def status():
    with db_lock:
        conn = db_connect()
        rows = station_status_rows(conn)
        conn.close()
    return jsonify(rows)


def card_rows(conn, include_accounts=False):
    if include_accounts:
        rows = conn.execute(
            """
            SELECT
                cards.card_id,
                cards.name,
                cards.email,
                cards.student_id,
                cards.designation,
                cards.active,
                cards.notes,
                cards.updated_at,
                user_accounts.role AS login_role,
                user_accounts.active AS login_active,
                user_accounts.card_id AS login_card_id
            FROM cards
            LEFT JOIN user_accounts
                ON user_accounts.card_id = cards.card_id
            ORDER BY
                CASE WHEN cards.name = '' THEN 1 ELSE 0 END,
                cards.name,
                cards.card_id
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT card_id, name, email, student_id, designation, active, notes, updated_at
            FROM cards
            ORDER BY
                CASE WHEN name = '' THEN 1 ELSE 0 END,
                name,
                card_id
            """
        ).fetchall()

    result = []
    for row in rows:
        card = {
            "card_id": row["card_id"],
            "name": row["name"],
            "email": row["email"],
            "student_id": row["student_id"],
            "designation": row["designation"],
            "active": bool(row["active"]),
            "notes": row["notes"],
            "updated_at": row["updated_at"],
            "display_name": card_display(row, row["card_id"]),
        }

        if include_accounts:
            card["has_login"] = bool(row["login_card_id"])
            card["login_role"] = row["login_role"] or ""
            card["login_active"] = (
                bool(row["login_active"])
                if row["login_card_id"]
                else False
            )

        result.append(card)

    return result


def audit_log_rows(conn, limit=80):
    rows = conn.execute(
        """
        SELECT
            id,
            timestamp,
            actor_card_id,
            actor_name,
            actor_role,
            action,
            target_type,
            target_id,
            details
        FROM audit_log
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    result = []
    for row in rows:
        try:
            details = json.loads(row["details"]) if row["details"] else {}
        except json.JSONDecodeError:
            details = {"details": row["details"]}

        result.append(
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "actor_card_id": row["actor_card_id"],
                "actor_name": row["actor_name"],
                "actor_role": row["actor_role"],
                "action": row["action"],
                "target_type": row["target_type"],
                "target_id": row["target_id"],
                "details": details,
            }
        )

    return result


def station_option_rows(conn):
    rows = conn.execute(
        """
        SELECT
            id AS station_id,
            name AS station_name,
            requires_certification,
            cert_override_active,
            cert_override_by,
            cert_override_updated_at,
            cert_override_expires_at
        FROM stations
        WHERE kind = 'station'
        ORDER BY name
        """
    ).fetchall()
    return [
        {
            "station_id": row["station_id"],
            "station_name": row["station_name"],
            "requires_certification": bool(row["requires_certification"]),
            "cert_override_active": override_is_effective(row),
            "cert_override_by": row["cert_override_by"] or "",
            "cert_override_updated_at": row["cert_override_updated_at"] or "",
            "cert_override_expires_at": row["cert_override_expires_at"] or "",
        }
        for row in rows
    ]


def certification_rows(conn):
    rows = conn.execute(
        """
        SELECT
            certifications.card_id,
            cards.name,
            cards.email,
            cards.student_id,
            cards.designation,
            certifications.station_id,
            stations.name AS station_name,
            certifications.active,
            certifications.notes,
            certifications.updated_at,
            certifications.granted_via,
            certifications.granted_by,
            certifications.granted_at
        FROM certifications
        JOIN cards ON cards.card_id = certifications.card_id
        JOIN stations ON stations.id = certifications.station_id
        ORDER BY cards.name, certifications.card_id, stations.name
        """
    ).fetchall()

    return [
        {
            "card_id": row["card_id"],
            "name": row["name"],
            "email": row["email"],
            "student_id": row["student_id"],
            "designation": row["designation"],
            "display_name": card_display(row, row["card_id"]),
            "station_id": row["station_id"],
            "station_name": row["station_name"],
            "active": bool(row["active"]),
            "notes": row["notes"],
            "updated_at": row["updated_at"],
            "granted_via": row["granted_via"],
            "granted_by": row["granted_by"],
            "granted_at": row["granted_at"],
        }
        for row in rows
    ]


def active_people_rows(conn):
    current_time = datetime.now(timezone.utc)
    rows = conn.execute(
        """
        SELECT
            active_people.card_id,
            cards.name,
            cards.email,
            cards.designation,
            active_people.entered_at,
            active_people.entry_door_id,
            active_people.entry_door_name
        FROM active_people
        LEFT JOIN cards ON cards.card_id = active_people.card_id
        ORDER BY entered_at
        """
    ).fetchall()

    result = []
    for row in rows:
        entered_at = parse_iso(row["entered_at"])
        result.append(
            {
                "card_id": row["card_id"],
                "name": row["name"] or "",
                "email": row["email"] or "",
                "designation": row["designation"] or "",
                "display_name": card_display(row, row["card_id"]),
                "entered_at": row["entered_at"],
                "entry_door_id": row["entry_door_id"],
                "entry_door_name": row["entry_door_name"],
                "elapsed_seconds": int((current_time - entered_at).total_seconds()),
            }
        )

    return result


def station_status_rows(conn):
    rows = conn.execute(
        """
        SELECT
            stations.id AS station_id,
            stations.name AS station_name,
            COUNT(active_sessions.id) AS active_sessions,
            GROUP_CONCAT(
                COALESCE(NULLIF(cards.name, ''), active_sessions.card_id),
                '; '
            ) AS active_cards
        FROM stations
        LEFT JOIN active_sessions
            ON active_sessions.station_id = stations.id
        LEFT JOIN cards
            ON cards.card_id = active_sessions.card_id
        WHERE stations.kind = 'station'
        GROUP BY stations.id, stations.name
        ORDER BY stations.id
        """
    ).fetchall()

    return [
        {
            "station_id": row["station_id"],
            "station_name": row["station_name"],
            "active_sessions": int(row["active_sessions"]),
            "active_cards": row["active_cards"] or "",
        }
        for row in rows
    ]


def active_session_rows(conn):
    current_time = datetime.now(timezone.utc)
    rows = conn.execute(
        """
        SELECT
            active_sessions.card_id,
            cards.name,
            cards.email,
            cards.designation,
            active_sessions.station_id,
            active_sessions.station_name,
            active_sessions.started_at
        FROM active_sessions
        LEFT JOIN cards ON cards.card_id = active_sessions.card_id
        ORDER BY station_id, started_at
        """
    ).fetchall()

    result = []
    for row in rows:
        started_at = parse_iso(row["started_at"])
        result.append(
            {
                "card_id": row["card_id"],
                "name": row["name"] or "",
                "email": row["email"] or "",
                "designation": row["designation"] or "",
                "display_name": card_display(row, row["card_id"]),
                "station_id": row["station_id"],
                "station_name": row["station_name"],
                "started_at": row["started_at"],
                "elapsed_seconds": int((current_time - started_at).total_seconds()),
            }
        )

    return result


def recent_swipe_rows(conn, limit):
    rows = conn.execute(
        """
        SELECT
            swipe_events.card_id,
            cards.name,
            cards.email,
            cards.designation,
            swipe_events.station_id,
            swipe_events.station_name,
            swipe_events.station_kind,
            swipe_events.timestamp,
            swipe_events.action,
            swipe_events.allowed,
            swipe_events.duration_seconds,
            swipe_events.active_users,
            swipe_events.warning,
            swipe_events.details
        FROM swipe_events
        LEFT JOIN cards ON cards.card_id = swipe_events.card_id
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    return [
        {
            **dict(row),
            "name": row["name"] or "",
            "email": row["email"] or "",
            "designation": row["designation"] or "",
            "display_name": card_display(row, row["card_id"]),
            "allowed": bool(row["allowed"]),
        }
        for row in rows
    ]


def warning_rows(conn, limit):
    rows = conn.execute(
        """
        SELECT
            swipe_events.card_id,
            cards.name,
            cards.email,
            cards.designation,
            swipe_events.station_id,
            swipe_events.station_name,
            swipe_events.timestamp,
            swipe_events.action,
            swipe_events.warning,
            swipe_events.details
        FROM swipe_events
        LEFT JOIN cards ON cards.card_id = swipe_events.card_id
        WHERE warning != ''
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    return [
        {
            **dict(row),
            "name": row["name"] or "",
            "email": row["email"] or "",
            "designation": row["designation"] or "",
            "display_name": card_display(row, row["card_id"]),
        }
        for row in rows
    ]


def csv_reply(filename, headers, rows):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )


@app.get("/swipes.csv")
def swipes_csv():
    role, error = require_access("staff")
    if error:
        return error

    with db_lock:
        conn = db_connect()
        rows = conn.execute(
            """
            SELECT
                swipe_events.card_id,
                cards.name,
                cards.email,
                cards.designation,
                swipe_events.station_id,
                swipe_events.station_name,
                swipe_events.station_kind,
                swipe_events.timestamp,
                swipe_events.action,
                swipe_events.allowed,
                swipe_events.duration_seconds,
                swipe_events.active_users,
                swipe_events.warning,
                swipe_events.details
            FROM swipe_events
            LEFT JOIN cards ON cards.card_id = swipe_events.card_id
            ORDER BY id
            """
        ).fetchall()
        conn.close()

    headers = [
        "card_id",
        "name",
        "email",
        "designation",
        "station_id",
        "station_name",
        "station_kind",
        "timestamp",
        "action",
        "allowed",
        "duration_seconds",
        "active_users",
        "warning",
        "details",
    ]
    return csv_reply("swipes.csv", headers, [dict(row) for row in rows])


@app.get("/audit.csv")
def audit_csv():
    role, error = require_access("admin")
    if error:
        return error

    with db_lock:
        conn = db_connect()
        rows = conn.execute(
            """
            SELECT
                timestamp,
                actor_card_id,
                actor_name,
                actor_role,
                action,
                target_type,
                target_id,
                details
            FROM audit_log
            ORDER BY id
            """
        ).fetchall()
        conn.close()

    headers = [
        "timestamp",
        "actor_card_id",
        "actor_name",
        "actor_role",
        "action",
        "target_type",
        "target_id",
        "details",
    ]
    return csv_reply("audit.csv", headers, [dict(row) for row in rows])


@app.get("/active.csv")
def active_csv():
    with db_lock:
        conn = db_connect()
        rows = active_people_rows(conn)
        conn.close()

    headers = [
        "card_id",
        "name",
        "email",
        "designation",
        "display_name",
        "entered_at",
        "entry_door_id",
        "entry_door_name",
        "elapsed_seconds",
    ]
    return csv_reply("active.csv", headers, rows)


@app.get("/station_status.csv")
def station_status_csv():
    with db_lock:
        conn = db_connect()
        rows = station_status_rows(conn)
        conn.close()

    headers = ["station_id", "station_name", "active_sessions", "active_cards"]
    return csv_reply("station_status.csv", headers, rows)


init_db()
seed_stations()
bootstrap_admin()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
