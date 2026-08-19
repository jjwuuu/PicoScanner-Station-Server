import importlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class StationServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_directory = tempfile.TemporaryDirectory(prefix="station-server-tests-")
        cls.database_path = str(Path(cls.temp_directory.name) / "test.db")
        cls.original_environment = {
            key: os.environ.get(key)
            for key in (
                "STATION_DB_PATH",
                "STATION_API_KEY",
                "STATION_PERSON_REF_SECRET",
                "STATION_BOOTSTRAP_ADMIN_CARD_ID",
                "STATION_BOOTSTRAP_ADMIN_USERNAME",
                "STATION_BOOTSTRAP_ADMIN_PASSWORD",
                "STATION_BOOTSTRAP_ADMIN_NAME",
                "STATION_TIMEZONE",
                "STATION_OPENING_HOUR",
                "STATION_CLOSING_HOUR",
            )
        }
        os.environ.update(
            {
                "STATION_DB_PATH": cls.database_path,
                "STATION_API_KEY": "test-station-key",
                "STATION_PERSON_REF_SECRET": "test-person-reference-secret",
                "STATION_BOOTSTRAP_ADMIN_CARD_ID": "admin-card",
                "STATION_BOOTSTRAP_ADMIN_USERNAME": "admin",
                "STATION_BOOTSTRAP_ADMIN_PASSWORD": "AdminPass123",
                "STATION_BOOTSTRAP_ADMIN_NAME": "Test Admin",
                "STATION_TIMEZONE": "UTC",
                "STATION_OPENING_HOUR": "0",
                "STATION_CLOSING_HOUR": "24",
            }
        )
        cls.server = importlib.import_module("app")

    @classmethod
    def tearDownClass(cls):
        cls.temp_directory.cleanup()
        for key, value in cls.original_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def setUp(self):
        with self.server.db_lock:
            conn = self.server.db_connect()
            for table in (
                "certify_permissions",
                "user_accounts",
                "certifications",
                "bronco_certifications",
                "canvas_sync_tasks",
                "active_sessions",
                "active_people",
                "pending_card_dismissals",
                "swipe_events",
                "audit_log",
                "cards",
                "people",
                "stations",
            ):
                conn.execute(f"DELETE FROM {table}")
            conn.commit()
            conn.close()

        with self.server.session_lock:
            self.server.session_tokens.clear()
            self.server.login_attempts.clear()
            self.server.security_audit_cooldowns.clear()
        self.server.cert_modes.clear()
        self.server.seed_stations()
        self.server.bootstrap_admin()
        self.client = self.server.app.test_client()
        self.admin_token = self.login("admin", "AdminPass123")

    def login(self, username, password):
        response = self.client.post(
            "/api/access",
            json={"login": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()["access_token"]

    @staticmethod
    def auth(token):
        return {"X-Access-Token": token}

    @staticmethod
    def station_auth():
        return {"X-Station-Key": "test-station-key"}

    def create_card(
        self,
        card_id,
        bronco_id,
        name,
        email,
        designation="User",
        login_role="",
        password="",
    ):
        body = {
            "card_id": card_id,
            "bronco_id": bronco_id,
            "name": name,
            "email": email,
            "designation": designation,
            "active": True,
            "notes": "",
        }
        if login_role:
            body.update(
                {
                    "login_role": login_role,
                    "login_password": password,
                    "login_active": True,
                }
            )
        response = self.client.post(
            "/api/cards",
            headers=self.auth(self.admin_token),
            json=body,
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def swipe(self, card_id, station_id, event_id, **extra):
        return self.client.post(
            "/swipe",
            headers=self.station_auth(),
            json={
                "card_id": card_id,
                "station_id": station_id,
                "event_id": event_id,
                **extra,
            },
        )

    def test_health_and_station_key_are_enforced(self):
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.get_json()["database"], "ok")
        self.assertTrue(health.get_json()["station_api_key_configured"])

        response = self.client.post(
            "/swipe",
            json={"card_id": "unknown", "station_id": "front-door"},
        )
        self.assertEqual(response.status_code, 401)

    def test_opening_hours_allow_authorized_roles_after_hours(self):
        self.create_card("regular-card", "B110", "Regular User", "regular@cpp.edu")
        self.create_card(
            "staff-card",
            "B111",
            "Staff User",
            "staff@cpp.edu",
            designation="Staff",
            login_role="staff",
            password="StaffPass123",
        )
        self.create_card(
            "volunteer-card",
            "B112",
            "Volunteer User",
            "volunteer@cpp.edu",
            designation="Volunteer",
            login_role="volunteer",
            password="VolunteerPass123",
        )

        with patch.object(self.server, "space_is_open", return_value=False):
            regular = self.swipe("regular-card", "front-door", "after-hours-user")
            staff = self.swipe("staff-card", "front-door", "after-hours-staff")
            volunteer = self.swipe(
                "volunteer-card", "front-door", "after-hours-volunteer"
            )

        self.assertFalse(regular.get_json()["allowed"])
        self.assertEqual(regular.get_json()["warning"], "outside_open_hours")
        self.assertTrue(staff.get_json()["allowed"])
        self.assertTrue(volunteer.get_json()["allowed"])

    def test_login_rate_limits_block_username_rotation_and_throttle_audit(self):
        responses = []
        with patch.object(self.server, "LOGIN_IP_ATTEMPT_LIMIT", 3):
            for index in range(3):
                responses.append(
                    self.client.post(
                        "/api/access",
                        json={"login": f"unknown-{index}", "password": "wrong"},
                        environ_base={"REMOTE_ADDR": "10.20.30.40"},
                    )
                )
            blocked = self.client.post(
                "/api/access",
                json={"login": "another-name", "password": "wrong"},
                environ_base={"REMOTE_ADDR": "10.20.30.40"},
            )

        self.assertEqual(responses[-1].status_code, 429)
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)
        self.assertGreater(blocked.get_json()["retry_after_seconds"], 0)

        conn = sqlite3.connect(self.database_path)
        try:
            failed_logs = conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'login_failed'"
            ).fetchone()[0]
            limited_logs = conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'login_rate_limited'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(failed_logs, 1)
        self.assertEqual(limited_logs, 1)

    def test_login_rate_limits_block_distributed_account_attack(self):
        with patch.object(self.server, "LOGIN_ACCOUNT_ATTEMPT_LIMIT", 3):
            responses = [
                self.client.post(
                    "/api/access",
                    json={"login": "admin", "password": "wrong"},
                    environ_base={"REMOTE_ADDR": f"10.30.0.{index}"},
                )
                for index in range(1, 4)
            ]
            blocked = self.client.post(
                "/api/access",
                json={"login": "admin", "password": "AdminPass123"},
                environ_base={"REMOTE_ADDR": "10.30.0.99"},
            )

        self.assertEqual(responses[-1].status_code, 429)
        self.assertEqual(blocked.status_code, 429)

    def test_login_sessions_origins_and_payloads_are_hardened(self):
        self.create_card(
            "secure-staff-card",
            "B113",
            "Secure Staff",
            "securestaff@cpp.edu",
            designation="Staff",
            login_role="staff",
            password="StaffPass123",
        )
        tokens = [self.login("securestaff", "StaffPass123") for _ in range(4)]
        self.assertEqual(
            self.client.get("/api/admin", headers=self.auth(tokens[0])).status_code,
            403,
        )
        self.assertEqual(
            self.client.get("/api/admin", headers=self.auth(tokens[-1])).status_code,
            200,
        )

        cross_origin = self.client.post(
            "/api/logout",
            headers={**self.auth(tokens[-1]), "Origin": "https://attacker.invalid"},
        )
        self.assertEqual(cross_origin.status_code, 403)

        oversized = self.client.post(
            "/api/access",
            data="x" * (self.server.MAX_LOGIN_BODY_BYTES + 1),
            content_type="application/json",
        )
        self.assertEqual(oversized.status_code, 413)

        secure_headers = self.client.get(
            "/dashboard",
            headers={"X-Forwarded-Proto": "https"},
        ).headers
        self.assertEqual(secure_headers["Cross-Origin-Opener-Policy"], "same-origin")
        self.assertIn("max-age=", secure_headers["Strict-Transport-Security"])

    def test_swipe_metadata_is_locked_and_event_id_is_idempotent(self):
        payload = {
            "station_name": "Forged Station",
            "station_kind": "station",
        }
        first = self.swipe("unknown", "front-door", "same-event", **payload)
        duplicate = self.swipe("unknown", "front-door", "same-event", **payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["station_name"], "Front Door")
        self.assertEqual(first.get_json()["station_kind"], "door")
        self.assertFalse(first.get_json()["allowed"])
        self.assertTrue(duplicate.get_json()["duplicate"])
        self.assertFalse(duplicate.get_json()["allowed"])

        conn = sqlite3.connect(self.database_path)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM swipe_events WHERE event_id = 'same-event'"
            ).fetchone()[0]
            station = conn.execute(
                "SELECT name, kind FROM stations WHERE id = 'front-door'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(count, 1)
        self.assertEqual(station, ("Front Door", "door"))

    def test_public_dashboard_and_exports_hide_identity(self):
        self.create_card("user-card", "B100", "Visible User", "user@cpp.edu")
        self.assertEqual(
            self.swipe("user-card", "front-door", "public-enter").get_json()["action"],
            "enter",
        )
        conn = sqlite3.connect(self.database_path)
        try:
            conn.execute(
                """
                INSERT INTO active_sessions (card_id, station_id, station_name, started_at)
                VALUES ('user-card', 'soldering', 'Soldering', ?)
                """,
                (self.server.now_iso(),),
            )
            conn.commit()
        finally:
            conn.close()

        dashboard = self.client.get("/api/dashboard").get_json()
        self.assertEqual(dashboard["total_active"], 1)
        self.assertEqual(dashboard["active_people"], [])
        self.assertEqual(dashboard["active_sessions"], [])
        self.assertEqual(dashboard["recent_swipes"], [])
        self.assertTrue(all(not row["active_cards"] for row in dashboard["stations"]))

        status = self.client.get("/status").get_json()
        self.assertTrue(all(not row["active_cards"] for row in status))
        station_csv = self.client.get("/station_status.csv").get_data(as_text=True)
        self.assertNotIn("Visible User", station_csv)
        self.assertEqual(self.client.get("/active.csv").status_code, 403)

    def test_card_and_certification_permissions_are_server_enforced(self):
        self.create_card(
            "staff-card",
            "B200",
            "Staff User",
            "staffer@cpp.edu",
            designation="Staff",
            login_role="staff",
            password="StaffPass123",
        )
        self.create_card(
            "volunteer-card",
            "B300",
            "Volunteer User",
            "helper@cpp.edu",
            designation="Volunteer",
            login_role="volunteer",
            password="VolunteerPass123",
        )
        self.create_card("trainee-card", "B400", "Trainee", "trainee@cpp.edu")
        volunteer_token = self.login("helper", "VolunteerPass123")

        create_staff = self.client.post(
            "/api/cards",
            headers=self.auth(volunteer_token),
            json={
                "card_id": "blocked-card",
                "bronco_id": "B500",
                "name": "Blocked",
                "email": "blocked@cpp.edu",
                "designation": "Staff",
                "active": True,
                "notes": "",
            },
        )
        self.assertEqual(create_staff.status_code, 403)

        create_user = self.client.post(
            "/api/cards",
            headers=self.auth(volunteer_token),
            json={
                "card_id": "blocked-user-card",
                "bronco_id": "B501",
                "name": "Blocked User",
                "email": "blocked-user@cpp.edu",
                "designation": "User",
                "active": True,
                "notes": "",
            },
        )
        self.assertEqual(create_user.status_code, 403)
        self.assertEqual(
            self.client.get(
                "/api/pending-cards",
                headers=self.auth(volunteer_token),
            ).status_code,
            403,
        )

        edit_staff = self.client.post(
            "/api/cards",
            headers=self.auth(volunteer_token),
            json={
                "card_id": "staff-card",
                "name": "Changed",
                "email": "staffer@cpp.edu",
                "designation": "Staff",
                "active": True,
                "notes": "",
            },
        )
        self.assertEqual(edit_staff.status_code, 403)

        denied_cert = self.client.post(
            "/api/certifications",
            headers=self.auth(volunteer_token),
            json={
                "card_id": "trainee-card",
                "station_id": "soldering",
                "active": True,
                "notes": "",
            },
        )
        self.assertEqual(denied_cert.status_code, 403)

        grant = self.client.post(
            "/api/certify-permissions",
            headers=self.auth(self.admin_token),
            json={"card_id": "volunteer-card", "station_ids": ["soldering"]},
        )
        self.assertEqual(grant.status_code, 200)
        allowed_cert = self.client.post(
            "/api/certifications",
            headers=self.auth(volunteer_token),
            json={
                "card_id": "trainee-card",
                "station_id": "soldering",
                "active": True,
                "notes": "trained",
            },
        )
        self.assertEqual(allowed_cert.status_code, 200)

    def test_account_self_lockout_duplicate_bid_and_login_aliases_are_blocked(self):
        self.create_card("user-card", "B510", "Original Name", "user@cpp.edu")
        self.create_card(
            "staff-card",
            "B520",
            "Staff Login",
            "stafflogin@cpp.edu",
            designation="Staff",
            login_role="staff",
            password="StaffPass123",
        )

        self.assertEqual(
            self.client.post(
                "/api/access",
                json={"login": "stafflogin@cpp.edu", "password": "StaffPass123"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/access",
                json={"login": "staff-card", "password": "StaffPass123"},
            ).status_code,
            403,
        )
        self.login("stafflogin", "StaffPass123")

        no_password = self.client.post(
            "/api/cards",
            headers=self.auth(self.admin_token),
            json={
                "card_id": "user-card",
                "bronco_id": "B510",
                "name": "Changed Before Rollback",
                "email": "user@cpp.edu",
                "designation": "User",
                "active": True,
                "notes": "",
                "login_role": "volunteer",
                "login_password": "",
                "login_active": True,
            },
        )
        self.assertEqual(no_password.status_code, 400)

        duplicate_bid = self.client.post(
            "/api/cards",
            headers=self.auth(self.admin_token),
            json={
                "card_id": "duplicate-card",
                "bronco_id": "b510",
                "name": "Duplicate",
                "email": "duplicate@cpp.edu",
                "designation": "User",
                "active": True,
                "notes": "",
            },
        )
        self.assertEqual(duplicate_bid.status_code, 409)

        self_lockout = self.client.post(
            "/api/cards",
            headers=self.auth(self.admin_token),
            json={
                "card_id": "admin-card",
                "bronco_id": "ADMIN-BID",
                "name": "Test Admin",
                "email": "admin@cpp.edu",
                "designation": "Staff",
                "active": True,
                "notes": "",
                "login_role": "staff",
                "login_password": "",
                "login_active": True,
            },
        )
        self.assertEqual(self_lockout.status_code, 409)

        update = self.client.post(
            "/api/cards",
            headers=self.auth(self.admin_token),
            json={
                "card_id": "user-card",
                "bronco_id": "B510",
                "name": "Updated Name",
                "email": "updated@cpp.edu",
                "designation": "User",
                "active": True,
                "notes": "updated",
            },
        )
        self.assertEqual(update.status_code, 200)
        conn = sqlite3.connect(self.database_path)
        try:
            person = conn.execute(
                "SELECT name, email FROM people WHERE bronco_id = 'B510'"
            ).fetchone()
            admin_role = conn.execute(
                "SELECT role FROM user_accounts WHERE card_id = 'admin-card'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(person, ("Updated Name", "updated@cpp.edu"))
        self.assertEqual(admin_role, "Admin")

    def test_expired_override_does_not_bypass_certification(self):
        self.create_card("uncertified", "B530", "Uncertified", "uncertified@cpp.edu")
        invalid_duration = self.client.post(
            "/api/stations",
            headers=self.auth(self.admin_token),
            json={
                "station_id": "soldering",
                "cert_override_active": True,
                "cert_override_duration_minutes": 0,
            },
        )
        self.assertEqual(invalid_duration.status_code, 400)

        conn = sqlite3.connect(self.database_path)
        try:
            conn.execute(
                """
                UPDATE stations
                SET cert_override_active = 1,
                    cert_override_expires_at = '2000-01-01T00:00:00+00:00',
                    cert_override_by = 'admin-card'
                WHERE id = 'soldering'
                """
            )
            conn.commit()
        finally:
            conn.close()

        denied = self.swipe("uncertified", "soldering", "expired-override")
        self.assertFalse(denied.get_json()["allowed"])
        self.assertEqual(denied.get_json()["warning"], "not_certified")

        pure_usage = self.client.post(
            "/api/stations",
            headers=self.auth(self.admin_token),
            json={"station_id": "soldering", "requires_certification": False},
        )
        self.assertEqual(pure_usage.status_code, 200)
        allowed = self.swipe("uncertified", "soldering", "pure-usage")
        self.assertTrue(allowed.get_json()["allowed"])
        self.assertNotEqual(allowed.get_json()["warning"], "cert_override_active")

    def test_exports_are_protected_and_formula_safe(self):
        self.create_card("formula-card", "B540", "=2+2", "formula@cpp.edu")
        self.create_card(
            "export-staff-card",
            "B541",
            "Export Staff",
            "exportstaff@cpp.edu",
            designation="Staff",
            login_role="staff",
            password="StaffPass123",
        )
        self.swipe("formula-card", "front-door", "formula-enter")
        staff_token = self.login("exportstaff", "StaffPass123")

        swipes = self.client.get(
            "/swipes.csv", headers=self.auth(self.admin_token)
        )
        self.assertEqual(swipes.status_code, 200)
        self.assertIn("attachment", swipes.headers["Content-Disposition"])
        self.assertIn("'=2+2", swipes.get_data(as_text=True))
        self.assertEqual(self.client.get("/audit.csv").status_code, 403)
        self.assertEqual(
            self.client.get(
                "/audit.csv", headers=self.auth(self.admin_token)
            ).status_code,
            200,
        )

        self.assertEqual(self.client.get("/cards.csv").status_code, 403)
        staff_cards = self.client.get(
            "/cards.csv", headers=self.auth(staff_token)
        )
        self.assertEqual(staff_cards.status_code, 403)
        admin_cards = self.client.get(
            "/cards.csv", headers=self.auth(self.admin_token)
        )
        self.assertEqual(admin_cards.status_code, 200)
        self.assertIn("bronco_id", admin_cards.get_data(as_text=True).splitlines()[0])
        self.assertIn("login_role", admin_cards.get_data(as_text=True).splitlines()[0])

        analytics = self.client.get(
            "/api/analytics?days=30", headers=self.auth(self.admin_token)
        )
        self.assertEqual(analytics.status_code, 200)
        self.assertIn("station_usage", analytics.get_json()["analytics"])
        self.assertEqual(
            self.client.get(
                "/api/analytics?days=30", headers=self.auth(staff_token)
            ).status_code,
            403,
        )

        workbook = self.client.get(
            "/master-export.xlsx", headers=self.auth(self.admin_token)
        )
        self.assertEqual(workbook.status_code, 200)
        self.assertTrue(workbook.data.startswith(b"PK"))
        self.assertIn(".xlsx", workbook.headers["Content-Disposition"])
        self.assertEqual(
            self.client.get(
                "/master-export.xlsx", headers=self.auth(staff_token)
            ).status_code,
            403,
        )

        invalid_reader = self.client.post(
            "/api/test-swipe",
            headers=self.auth(self.admin_token),
            json={"card_id": "formula-card", "station_id": "not-configured"},
        )
        self.assertEqual(invalid_reader.status_code, 404)
        conn = sqlite3.connect(self.database_path)
        try:
            station_count = conn.execute(
                "SELECT COUNT(*) FROM stations WHERE id = 'not-configured'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(station_count, 0)

    def test_admin_double_swipe_grants_certification(self):
        self.create_card("trainee-card", "B600", "Trainee", "trainee@cpp.edu")

        pending = self.swipe("admin-card", "soldering", "cert-pending").get_json()
        armed = self.swipe("admin-card", "soldering", "cert-armed").get_json()
        granted = self.swipe("trainee-card", "soldering", "cert-granted").get_json()

        self.assertEqual(pending["led_signal"], "cert_mode_pending")
        self.assertEqual(armed["led_signal"], "cert_mode_armed")
        self.assertEqual(granted["led_signal"], "cert_success")
        self.assertEqual(granted["warning"], "cert_granted_via_swipe")
        conn = sqlite3.connect(self.database_path)
        try:
            certification = conn.execute(
                """
                SELECT active, granted_via, granted_by
                FROM certifications
                WHERE card_id = 'trainee-card' AND station_id = 'soldering'
                """
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(certification, (1, "swipe", "admin-card"))

    def test_canvas_tsv_import_and_card_assignment(self):
        headings = [
            "Email",
            "Student",
            "bid",
            *[column[0] for column in self.server.CERTIFICATION_IMPORT_COLUMNS],
        ]
        values = [
            "canvas@cpp.edu",
            "Last, First",
            "B700",
            "1",
            "",
            "",
            "1",
            "",
            "",
            "",
            "",
            "",
        ]
        tsv = "\t".join(headings) + "\n" + "\t".join(values) + "\n"
        imported = self.client.post(
            "/api/import/canvas",
            headers=self.auth(self.admin_token),
            json={"csv": tsv},
        )
        self.assertEqual(imported.status_code, 200, imported.get_data(as_text=True))
        imported_person = imported.get_json()["people"][0]
        self.assertEqual(imported_person["name"], "First Last")

        assigned = self.client.post(
            "/api/cards",
            headers=self.auth(self.admin_token),
            json={
                "card_id": "canvas-card",
                "person_ref": imported_person["person_ref"],
                "name": "",
                "email": "",
                "designation": "User",
                "active": True,
                "notes": "",
            },
        )
        self.assertEqual(assigned.status_code, 200, assigned.get_data(as_text=True))
        self.assertEqual(assigned.get_json()["people"], [])
        station_ids = {
            row["station_id"]
            for row in assigned.get_json()["certifications"]
            if row["card_id"] == "canvas-card" and row["active"]
        }
        self.assertEqual(station_ids, {"stickers", "3d-printing"})

    def test_deleted_unknown_card_only_reappears_after_a_new_swipe(self):
        self.swipe("pending-card", "front-door", "pending-before")
        pending = self.client.get(
            "/api/pending-cards", headers=self.auth(self.admin_token)
        ).get_json()
        self.assertEqual(pending["pending_count"], 1)

        self.create_card("pending-card", "B800", "Pending User", "pending@cpp.edu")
        deleted = self.client.delete(
            "/api/cards/pending-card", headers=self.auth(self.admin_token)
        )
        self.assertEqual(deleted.status_code, 200)
        after_delete = self.client.get(
            "/api/pending-cards", headers=self.auth(self.admin_token)
        ).get_json()
        self.assertEqual(after_delete["pending_count"], 0)

        self.swipe("pending-card", "front-door", "pending-after")
        after_new_swipe = self.client.get(
            "/api/pending-cards", headers=self.auth(self.admin_token)
        ).get_json()
        self.assertEqual(after_new_swipe["pending_count"], 1)


if __name__ == "__main__":
    unittest.main()
