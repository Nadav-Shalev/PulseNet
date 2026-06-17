"""Auth / session API tests (Flask test client + mocked DB seam).

These exercise login, /api/me, logout and the session-lifecycle helpers without a
real database: ``app.get_db_connection`` is patched to a ``FakeConn`` seeded with
the rows each request reads, and behavior is asserted on the recorded SQL/params.
"""

import sys
import unittest
from pathlib import Path

import bcrypt

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import app  # noqa: E402
from support import FakeConn, client, patch_db  # noqa: E402

# bcrypt hashing is deliberately slow — hash the test password once for the module.
PASSWORD = "s3cret-pw"
PASSWORD_HASH = bcrypt.hashpw(PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _login_row(**over):
    """Row shape returned by login's SELECT (includes password_hash)."""
    row = {
        "id": 42, "name": "Ada", "username": "ada", "email": "ada@example.com",
        "bio": "hi", "avatar": "a.svg", "profile_image": "p.svg",
        "password_hash": PASSWORD_HASH,
    }
    row.update(over)
    return row


def _session_user(**over):
    """Row shape returned by require_session's JOIN (no password_hash)."""
    row = {
        "id": 42, "name": "Ada", "username": "ada", "email": "ada@example.com",
        "bio": "hi", "avatar": "a.svg", "profile_image": "p.svg",
    }
    row.update(over)
    return row


def _set_cookie_header(resp):
    return " || ".join(resp.headers.getlist("Set-Cookie"))


class LoginTests(unittest.TestCase):
    def test_valid_credentials_set_session_cookie(self):
        conn = FakeConn(fetchone=[_login_row()])
        with patch_db(conn):
            resp = client().post("/api/login",
                                 json={"email": "ada@example.com", "password": PASSWORD})

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["username"], "ada")
        self.assertNotIn("password_hash", body)              # never leak the hash
        cookie = _set_cookie_header(resp)
        self.assertIn("session_id=", cookie)
        self.assertNotIn("session_id=;", cookie)             # a real value, not a clear
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        # A session row was created for the authenticated user.
        self.assertTrue(conn.ran("insert into sessions"))

    def test_wrong_password_is_rejected_without_cookie(self):
        conn = FakeConn(fetchone=[_login_row()])
        with patch_db(conn):
            resp = client().post("/api/login",
                                 json={"email": "ada@example.com", "password": "wrong"})

        self.assertEqual(resp.status_code, 401)
        self.assertNotIn("session_id=", _set_cookie_header(resp))
        self.assertFalse(conn.ran("insert into sessions"))

    def test_unknown_email_is_rejected(self):
        conn = FakeConn(fetchone=[None])                     # no user row
        with patch_db(conn):
            resp = client().post("/api/login",
                                 json={"email": "nobody@example.com", "password": PASSWORD})

        self.assertEqual(resp.status_code, 401)

    def test_missing_fields_returns_400(self):
        conn = FakeConn()
        with patch_db(conn):
            resp = client().post("/api/login", json={"email": "ada@example.com"})

        self.assertEqual(resp.status_code, 400)

    def test_login_in_mock_mode_returns_503(self):
        conn = FakeConn()
        with patch_db(conn, db_available=False):
            resp = client().post("/api/login",
                                 json={"email": "ada@example.com", "password": PASSWORD})

        self.assertEqual(resp.status_code, 503)


class MeTests(unittest.TestCase):
    def test_me_without_cookie_returns_401(self):
        # No cookie → require_session aborts before any DB access.
        resp = client().get("/api/me")

        self.assertEqual(resp.status_code, 401)

    def test_me_with_valid_session_returns_current_user(self):
        conn = FakeConn(fetchone=[_session_user()])
        c = client()
        c.set_cookie("session_id", "valid-sid")
        with patch_db(conn):
            resp = c.get("/api/me")

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["username"], "ada")
        self.assertEqual(body["id"], 42)
        self.assertNotIn("password_hash", body)

    def test_expired_or_invalid_session_is_rejected_and_cookie_cleared(self):
        conn = FakeConn(fetchone=[None])                     # session SELECT finds nothing
        c = client()
        c.set_cookie("session_id", "stale-sid")
        with patch_db(conn):
            resp = c.get("/api/me")

        self.assertEqual(resp.status_code, 401)
        cookie = _set_cookie_header(resp)
        self.assertIn("session_id=;", cookie)                # cleared
        self.assertIn("Max-Age=0", cookie)

    def test_expired_rows_are_purged_during_auth_flow(self):
        conn = FakeConn(fetchone=[_session_user()])
        c = client()
        c.set_cookie("session_id", "valid-sid")
        with patch_db(conn):
            c.get("/api/me")

        self.assertTrue(conn.ran("delete from sessions where expires_at <= now()"))


class LogoutTests(unittest.TestCase):
    def test_logout_current_device_deletes_only_this_session(self):
        conn = FakeConn(fetchone=[_session_user()])
        c = client()
        c.set_cookie("session_id", "this-sid")
        with patch_db(conn):
            resp = c.post("/api/logout")

        self.assertEqual(resp.status_code, 200)
        match = conn.find("delete from sessions where session_id")
        self.assertTrue(match, "expected a delete scoped to the current session_id")
        self.assertEqual(match[0][1], ("this-sid",))
        self.assertFalse(conn.ran("delete from sessions where user_id"))
        self.assertIn("session_id=;", _set_cookie_header(resp))   # cookie cleared

    def test_logout_all_devices_deletes_every_session_for_user(self):
        conn = FakeConn(fetchone=[_session_user(id=42)])
        c = client()
        c.set_cookie("session_id", "this-sid")
        with patch_db(conn):
            resp = c.post("/api/logout", json={"allDevices": True})

        self.assertEqual(resp.status_code, 200)
        match = conn.find("delete from sessions where user_id")
        self.assertTrue(match, "expected a delete scoped to the user id")
        self.assertEqual(match[0][1], (42,))
        self.assertIn("session_id=;", _set_cookie_header(resp))

    def test_logout_without_cookie_returns_401(self):
        resp = client().post("/api/logout")

        self.assertEqual(resp.status_code, 401)


class SessionHelperTests(unittest.TestCase):
    def test_delete_expired_sessions_issues_cleanup_delete(self):
        conn = FakeConn()
        app._delete_expired_sessions(conn.cursor())

        self.assertTrue(conn.ran("delete from sessions where expires_at <= now()"))

    def test_create_session_inserts_row_and_returns_token(self):
        conn = FakeConn()
        token = app._create_session(conn.cursor(), 42)

        self.assertIsInstance(token, str)
        self.assertTrue(token)
        insert = conn.find("insert into sessions")
        self.assertTrue(insert)
        # params are (session_id, user_id, SESSION_DURATION_DAYS)
        params = insert[0][1]
        self.assertEqual(params[0], token)
        self.assertEqual(params[1], 42)


if __name__ == "__main__":
    unittest.main()
