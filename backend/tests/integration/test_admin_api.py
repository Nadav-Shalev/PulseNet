"""Admin endpoints: the user list, ban and unban.

Each request gets two connections: the session lookup's (``require_admin`` runs
``require_session``, which closes its own) and the endpoint's. Giving them separate
FakeConns keeps the endpoint's SQL apart, and makes a "the connection was closed"
check mean the endpoint's own connection.
"""

import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import mysql.connector

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import app  # noqa: E402
from support import FakeConn, client  # noqa: E402

ADMIN_ID = 1


def _session_user(**over):
    row = {
        "id": ADMIN_ID, "name": "Root", "username": "root", "email": "root@example.com",
        "bio": "", "avatar": "a.svg", "profile_image": "p.svg", "role": "admin",
    }
    row.update(over)
    return row


def _user_row(**over):
    row = {"id": 7, "username": "eve", "name": "Eve", "role": "user", "is_banned": 0}
    row.update(over)
    return row


@contextmanager
def as_user(conn, *, role="admin", db_available=True):
    """Requests in the block log in as a user with ``role``; the endpoint gets ``conn``."""
    session = FakeConn(fetchone=[_session_user(role=role)])
    with patch.object(app, "get_db_connection", side_effect=[session, conn]), \
         patch.object(app, "is_db_available", return_value=db_available):
        yield session


def _client():
    c = client()
    c.set_cookie("session_id", "valid-sid")
    return c


class AdminUserListTests(unittest.TestCase):
    def test_search_matches_username_and_name_never_email(self):
        conn = FakeConn(fetchall=[[_user_row()]])
        with as_user(conn):
            resp = _client().get("/api/admin/users?q=ev")

        self.assertEqual(resp.status_code, 200)
        sql, params = conn.find("from users")[0]
        flat = " ".join(sql.split())
        self.assertIn("WHERE (username LIKE %s OR name LIKE %s)", flat)
        self.assertNotIn("email", flat.lower())
        self.assertEqual(params, ["%ev%", "%ev%", app.ADMIN_USER_LIMIT])
        self.assertTrue(conn.closed)

    def test_the_list_is_limited(self):
        conn = FakeConn(fetchall=[[]])
        with as_user(conn):
            _client().get("/api/admin/users")

        sql, params = conn.find("from users")[0]
        self.assertIn("ORDER BY username LIMIT %s", " ".join(sql.split()))
        self.assertNotIn("WHERE", sql)
        self.assertEqual(params, [20])

    def test_banned_only(self):
        conn = FakeConn(fetchall=[[]])
        with as_user(conn):
            _client().get("/api/admin/users?banned=1&q=ev")

        sql, params = conn.find("from users")[0]
        self.assertIn("WHERE (username LIKE %s OR name LIKE %s) AND is_banned", " ".join(sql.split()))
        self.assertEqual(params, ["%ev%", "%ev%", 20])

    def test_shape_has_no_email(self):
        conn = FakeConn(fetchall=[[_user_row(is_banned=1, email="eve@example.com")]])
        with as_user(conn):
            resp = _client().get("/api/admin/users")

        self.assertEqual(resp.get_json(), [
            {"id": 7, "username": "eve", "name": "Eve", "role": "user", "is_banned": True},
        ])

    def test_a_regular_user_is_403(self):
        conn = FakeConn()
        with as_user(conn, role="user"):
            resp = _client().get("/api/admin/users")

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(conn.executed, [])

    def test_db_down_is_503(self):
        error = mysql.connector.errors.InterfaceError("2003: Can't connect")
        session = FakeConn(fetchone=[_session_user()])
        with patch.object(app, "get_db_connection", side_effect=[session, error]):
            resp = _client().get("/api/admin/users")

        self.assertEqual(resp.status_code, 503)


class BanTests(unittest.TestCase):
    def test_ban_sets_the_flag_and_deletes_every_session_in_one_commit(self):
        conn = FakeConn(fetchone=[_user_row()])
        with as_user(conn):
            resp = _client().post("/api/admin/users/7/ban")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(),
                         {"id": 7, "username": "eve", "name": "Eve", "role": "user", "is_banned": True})
        self.assertEqual(conn.params_for("update users set is_banned"), (True, 7))
        self.assertEqual(conn.params_for("delete from sessions where user_id"), (7,))
        self.assertEqual(conn.commits, 1)
        self.assertTrue(conn.closed)

    def test_ban_leaves_the_reports_open(self):
        # Reports about the user's content stay for an admin to dismiss or act on.
        conn = FakeConn(fetchone=[_user_row()])
        with as_user(conn):
            _client().post("/api/admin/users/7/ban")

        self.assertFalse(conn.ran("reports"))

    def test_unban_clears_the_flag_and_keeps_sessions_alone(self):
        conn = FakeConn(fetchone=[_user_row(is_banned=1)])
        with as_user(conn):
            resp = _client().delete("/api/admin/users/7/ban")

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.get_json()["is_banned"])
        self.assertEqual(conn.params_for("update users set is_banned"), (False, 7))
        self.assertFalse(conn.ran("delete from sessions"))
        self.assertEqual(conn.commits, 1)

    def test_an_admin_cannot_ban_themselves(self):
        conn = FakeConn()
        with as_user(conn):
            resp = _client().post(f"/api/admin/users/{ADMIN_ID}/ban")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(conn.executed, [])

    def test_another_admin_cannot_be_banned(self):
        conn = FakeConn(fetchone=[_user_row(role="admin")])
        with as_user(conn):
            resp = _client().post("/api/admin/users/7/ban")

        self.assertEqual(resp.status_code, 403)
        self.assertFalse(conn.ran("update users"))
        self.assertFalse(conn.ran("delete from sessions"))
        self.assertTrue(conn.closed)

    def test_an_unknown_user_is_404(self):
        conn = FakeConn(fetchone=[None])
        with as_user(conn):
            resp = _client().post("/api/admin/users/99/ban")

        self.assertEqual(resp.status_code, 404)
        self.assertFalse(conn.ran("update users"))
        self.assertTrue(conn.closed)

    def test_a_regular_user_cannot_ban(self):
        for method in ("post", "delete"):
            with self.subTest(method=method):
                conn = FakeConn(fetchone=[_user_row()])
                with as_user(conn, role="user"):
                    resp = getattr(_client(), method)("/api/admin/users/7/ban")

                self.assertEqual(resp.status_code, 403)
                self.assertEqual(conn.executed, [])

    def test_db_unavailable_is_503(self):
        conn = FakeConn(fetchone=[_user_row()])
        with as_user(conn, db_available=False):
            resp = _client().post("/api/admin/users/7/ban")

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(conn.executed, [])


if __name__ == "__main__":
    unittest.main()
