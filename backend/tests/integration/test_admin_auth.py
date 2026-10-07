"""Roles: the require_admin gate, and that no request can make itself an admin.

No route uses require_admin yet (the admin endpoints come in S11), so the gate is
tested by wrapping a stand-in view and calling it inside a request context, with
the DB seam patched like the endpoint tests. Only backend/manage.py make-admin
grants the role: signup and PATCH /api/me must ignore role and the user flags.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import g, jsonify

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import app  # noqa: E402
from support import FakeConn, client, db_down, flask_app, patch_db  # noqa: E402


def _session_user(**over):
    row = {
        "id": 42, "name": "Ada", "username": "ada", "email": "ada@example.com",
        "bio": "hi", "avatar": "a.svg", "profile_image": "p.svg", "role": "user",
    }
    row.update(over)
    return row


def _authed_client(sid="valid-sid"):
    c = client()
    c.set_cookie("session_id", sid)
    return c


class RequireAdminTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def admin_only(self):
        self.calls.append(g.current_user["id"])
        return jsonify({"ok": True})

    def _call(self, cookie="valid-sid"):
        headers = {"Cookie": f"session_id={cookie}"} if cookie else {}
        with flask_app.test_request_context("/api/admin/anything", headers=headers):
            return flask_app.make_response(app.require_admin(self.admin_only)())

    def test_no_session_is_401_and_the_view_never_runs(self):
        with patch_db(FakeConn()):
            resp = self._call(cookie=None)

        self.assertEqual(resp.status_code, 401)
        self.assertEqual(self.calls, [])

    def test_a_regular_user_is_403(self):
        with patch_db(FakeConn(fetchone=[_session_user(role="user")])):
            resp = self._call()

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json(), {"error": "Admin access required"})
        self.assertEqual(self.calls, [])

    def test_a_missing_role_is_never_admin(self):
        # Fail closed: NULL, or a row without the column, is not an admin.
        no_role = {key: value for key, value in _session_user().items() if key != "role"}
        for row in (_session_user(role=None), no_role):
            with self.subTest(role=row.get("role", "absent")):
                with patch_db(FakeConn(fetchone=[row])):
                    self.assertEqual(self._call().status_code, 403)
        self.assertEqual(self.calls, [])

    def test_an_admin_reaches_the_view(self):
        with patch_db(FakeConn(fetchone=[_session_user(role="admin")])):
            resp = self._call()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.calls, [42])

    def test_db_down_is_503(self):
        with db_down():
            resp = self._call()

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(self.calls, [])

    def test_the_session_lookup_reads_the_role(self):
        conn = FakeConn(fetchone=[_session_user(role="admin")])
        with patch_db(conn):
            self._call()

        session_sql = conn.find("from sessions s join users u")[0][0]
        self.assertIn("u.role", " ".join(session_sql.split()))

    def test_the_view_keeps_its_name_for_flask_routing(self):
        # Flask names endpoints after the function, so the wrapper must not rename it.
        def delete_any_post():
            pass

        self.assertEqual(app.require_admin(delete_any_post).__name__, "delete_any_post")


class RoleIsNeverSetByARequestTests(unittest.TestCase):
    def test_patch_me_ignores_role_and_flags(self):
        conn = FakeConn(fetchone=[_session_user()])
        with patch_db(conn):
            resp = _authed_client().patch("/api/me", json={
                "name": "Ada L", "role": "admin", "is_banned": False, "is_agent": True,
            })

        self.assertEqual(resp.status_code, 200)
        sql, params = conn.find("update users set")[0]
        self.assertEqual(" ".join(sql.split()), "UPDATE users SET name = %s WHERE id = %s")
        self.assertEqual(params, ["Ada L", 42])
        self.assertNotIn("role", resp.get_json())

    def test_patch_me_with_only_role_changes_nothing(self):
        conn = FakeConn(fetchone=[_session_user()])
        with patch_db(conn):
            resp = _authed_client().patch("/api/me", json={"role": "admin"})

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(conn.ran("update users"))

    def test_signup_ignores_role_and_flags(self):
        conn = FakeConn(fetchone=[None, None], lastrowid=7)   # username and email are free
        with patch_db(conn), patch.object(app, "_hash_password", return_value="hashed"):
            resp = client().post("/api/users", json={
                "name": "Eve", "username": "eve", "email": "eve@example.com",
                "password": "Passw0rd!", "role": "admin", "is_agent": True,
            })

        self.assertEqual(resp.status_code, 201)
        sql, params = conn.find("insert into users")[0]
        self.assertNotIn("role", sql.lower())
        self.assertNotIn("admin", params)
        self.assertNotIn("role", resp.get_json())


if __name__ == "__main__":
    unittest.main()
