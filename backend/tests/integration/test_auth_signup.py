"""Signup API integration tests with the Flask test client and mocked DB seam."""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import app  # noqa: E402
from support import FakeConn, client, patch_db  # noqa: E402


def _signup_payload(**overrides):
    payload = {
        "name": "Ada Lovelace",
        "username": "ada_rita",
        "email": "ada.rita@example.com",
        "bio": "first programmer",
        "password": "S3cret-pass!",
    }
    payload.update(overrides)
    return payload


def _set_cookie_header(resp):
    return " || ".join(resp.headers.getlist("Set-Cookie"))


class SignupIntegrationTests(unittest.TestCase):
    def test_signup_creates_user_hashes_password_and_sets_session_cookie(self):
        # Arrange
        conn = FakeConn(fetchone=[None, None], lastrowid=123)
        payload = _signup_payload()

        # Act
        with patch_db(conn):
            resp = client().post("/api/users", json=payload)

        # Assert
        self.assertEqual(resp.status_code, 201)
        body = resp.get_json()
        self.assertEqual(body["id"], 123)
        self.assertEqual(body["username"], payload["username"])
        self.assertEqual(body["email"], payload["email"])
        self.assertNotIn("password_hash", body)
        self.assertIn("session_id=", _set_cookie_header(resp))
        insert = conn.find("insert into users")
        self.assertTrue(insert)
        stored_hash = insert[0][1][6]
        self.assertNotEqual(stored_hash, payload["password"])
        self.assertTrue(app._verify_password(payload["password"], stored_hash))
        self.assertTrue(conn.ran("insert into sessions"))
        self.assertEqual(conn.commits, 1)

    def test_signup_rejects_duplicate_username(self):
        # Arrange
        conn = FakeConn(fetchone=[{"id": 1}])
        payload = _signup_payload()

        # Act
        with patch_db(conn):
            resp = client().post("/api/users", json=payload)

        # Assert
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "Username already taken")
        self.assertFalse(conn.ran("insert into users"))
        self.assertNotIn("session_id=", _set_cookie_header(resp))

    def test_signup_rejects_duplicate_email(self):
        # Arrange
        conn = FakeConn(fetchone=[None, {"id": 2}])
        payload = _signup_payload()

        # Act
        with patch_db(conn):
            resp = client().post("/api/users", json=payload)

        # Assert
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "Email already registered")
        self.assertFalse(conn.ran("insert into users"))
        self.assertNotIn("session_id=", _set_cookie_header(resp))

    def test_signup_rejects_missing_password_before_db_work(self):
        # Arrange
        conn = FakeConn()
        payload = _signup_payload(password="")

        # Act
        with patch_db(conn):
            resp = client().post("/api/users", json=payload)

        # Assert
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "password is required")
        self.assertEqual(conn.executed, [])

    def test_signup_in_mock_mode_returns_503(self):
        # Arrange
        conn = FakeConn()
        payload = _signup_payload()

        # Act
        with patch_db(conn, db_available=False):
            resp = client().post("/api/users", json=payload)

        # Assert
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.get_json()["error"], "Database unavailable. Write actions are disabled.")


if __name__ == "__main__":
    unittest.main()
