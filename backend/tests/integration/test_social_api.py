"""Follow / unfollow API tests (Flask test client + mocked DB seam).

Covers the self-follow guard, follow target existence, the idempotent INSERT IGNORE
relation, and unfollow removal.
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from support import FakeConn, client, patch_db  # noqa: E402


def _session_user(**over):
    row = {
        "id": 42, "name": "Ada", "username": "ada", "email": "ada@example.com",
        "bio": "hi", "avatar": "a.svg", "profile_image": "p.svg",
    }
    row.update(over)
    return row


def _authed_client(sid="valid-sid"):
    c = client()
    c.set_cookie("session_id", sid)
    return c


class FollowTests(unittest.TestCase):
    def test_cannot_follow_self(self):
        # user_id in the URL equals the session user's id → 400 before any DB write.
        conn = FakeConn(fetchone=[_session_user(id=42)])
        with patch_db(conn):
            resp = _authed_client().post("/api/users/42/follow")

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(conn.ran("insert ignore into follows"))

    def test_follow_unknown_user_returns_404(self):
        # require_session row, then the target-exists SELECT finds nothing.
        conn = FakeConn(fetchone=[_session_user(id=42), None])
        with patch_db(conn):
            resp = _authed_client().post("/api/users/99/follow")

        self.assertEqual(resp.status_code, 404)
        self.assertFalse(conn.ran("insert ignore into follows"))

    def test_follow_creates_relation(self):
        conn = FakeConn(fetchone=[_session_user(id=42), (99,)])
        with patch_db(conn):
            resp = _authed_client().post("/api/users/99/follow")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"following": True})
        insert = conn.find("insert ignore into follows")
        self.assertTrue(insert, "follow must use INSERT IGNORE for idempotency")
        self.assertEqual(insert[0][1], (42, 99))      # (follower_id, following_id)

    def test_duplicate_follow_is_handled_safely(self):
        # Following someone again hits the same INSERT IGNORE path → still 200, no error.
        conn = FakeConn(fetchone=[_session_user(id=42), (99,)])
        with patch_db(conn):
            resp = _authed_client().post("/api/users/99/follow")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"following": True})

    def test_follow_requires_session(self):
        resp = client().post("/api/users/99/follow")

        self.assertEqual(resp.status_code, 401)


class UnfollowTests(unittest.TestCase):
    def test_unfollow_removes_relation(self):
        conn = FakeConn(fetchone=[_session_user(id=42)])
        with patch_db(conn):
            resp = _authed_client().delete("/api/users/99/follow")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"following": False})
        delete = conn.find("delete from follows")
        self.assertTrue(delete)
        self.assertEqual(delete[0][1], (42, 99))      # (follower_id, following_id)

    def test_unfollow_requires_session(self):
        resp = client().delete("/api/users/99/follow")

        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()
