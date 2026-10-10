"""GET /api/tags/trending and GET /api/users/suggested: the home page's sidebar.

The queries and the merge are in tests/unit/test_recommend.py; here, the HTTP side:
the defaults and limits, the viewer (from the session cookie, or a guest), the
route that wins over /api/users/<username>, 503 when the DB is down, and the
connection closed every time.
"""

import sys
import unittest
from pathlib import Path

import mysql.connector

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from support import FakeConn, client, db_down, patch_db  # noqa: E402

VIEWER = {"id": 42, "username": "ada"}


def _user(uid, **extra):
    row = {"id": uid, "name": f"User {uid}", "username": f"user{uid}", "avatar": None,
           "profile_image": None, "is_agent": 0}
    row.update(extra)
    return row


def _authed_client(sid="valid-sid"):
    c = client()
    c.set_cookie("session_id", sid)
    return c


class TrendingApiTests(unittest.TestCase):
    def get(self, url, rows=()):
        self.conn = FakeConn(fetchall=[list(rows)])
        with patch_db(self.conn):
            return client().get(url)

    def test_the_last_24_hours_by_default(self):
        resp = self.get("/api/tags/trending", [{"name": "python", "post_count": 3}])

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), [{"name": "python", "post_count": 3}])
        self.assertEqual(self.conn.params_for("from posts_tags pt"), (24, 10))
        self.assertTrue(self.conn.closed)

    def test_a_window_and_a_limit_of_your_own(self):
        for url, params in (("/api/tags/trending?hours=168&limit=20", (168, 20)),
                            ("/api/tags/trending?hours=1&limit=1", (1, 1)),
                            ("/api/tags/trending?hours=&limit=", (24, 10))):
            with self.subTest(url=url):
                self.assertEqual(self.get(url).status_code, 200)
                self.assertEqual(self.conn.params_for("from posts_tags pt"), params)

    def test_a_bad_window_or_limit_is_a_400_before_any_query(self):
        for url, words in (("/api/tags/trending?hours=0", "hours must be a whole number from 1 to 168"),
                           ("/api/tags/trending?hours=169", "hours must be a whole number from 1 to 168"),
                           ("/api/tags/trending?hours=abc", "hours"),
                           ("/api/tags/trending?hours=1.5", "hours"),
                           ("/api/tags/trending?limit=0", "limit must be a whole number from 1 to 20"),
                           ("/api/tags/trending?limit=21", "limit")):
            with self.subTest(url=url):
                resp = self.get(url)
                self.assertEqual(resp.status_code, 400)
                self.assertIn(words, resp.get_json()["error"])
                self.assertEqual(self.conn.executed, [])

    def test_db_down_is_a_503(self):
        with db_down():
            resp = client().get("/api/tags/trending")

        self.assertEqual(resp.status_code, 503)

    def test_a_failed_query_closes_its_connection(self):
        conn = FakeConn(raise_on={"from posts_tags pt": mysql.connector.Error("1054: Unknown column")})
        with patch_db(conn):
            resp = client().get("/api/tags/trending")

        self.assertEqual(resp.status_code, 503)
        self.assertTrue(conn.closed)


class SuggestedApiTests(unittest.TestCase):
    def test_a_guest_gets_the_most_followed(self):
        conn = FakeConn(fetchall=[[_user(9, followers=4, is_agent=1)]])
        with patch_db(conn):
            resp = client().get("/api/users/suggested")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), [{
            "id": 9, "name": "User 9", "username": "user9", "avatar": None, "profile_image": None,
            "is_agent": True, "reason": {"kind": "popular", "count": 4},
        }])
        self.assertFalse(conn.ran("from follows f1"))
        self.assertEqual(conn.params_for("from users u join follows f"), (5,))
        self.assertTrue(conn.closed)

    def test_a_viewer_gets_friends_of_friends_first(self):
        conn = FakeConn(fetchone=[VIEWER],
                        fetchall=[[_user(7, mutuals=2)], [_user(8, shared=1, tag_names="go")], []])
        with patch_db(conn):
            resp = _authed_client().get("/api/users/suggested")

        body = resp.get_json()
        self.assertEqual([(u["id"], u["reason"]["kind"]) for u in body], [(7, "friends"), (8, "tags")])
        # The viewer comes from the session, never from the request.
        self.assertEqual(conn.params_for("from follows f1"), (42, 42, 42, 5))

    def test_a_viewer_is_never_suggested_to_themselves(self):
        conn = FakeConn(fetchone=[VIEWER], fetchall=[[], [], []])
        with patch_db(conn):
            _authed_client().get("/api/users/suggested?user_id=7")

        for needle in ("from follows f1", "from posts_tags theirs", "from users u join follows f"):
            with self.subTest(needle=needle):
                sql, params = conn.find(needle)[0]
                self.assertIn("u.id <> %s", sql)
                self.assertIn(42, params)
                self.assertNotIn(7, params)

    def test_a_stale_cookie_is_a_guest(self):
        conn = FakeConn(fetchone=[None], fetchall=[[_user(9, followers=1)]])
        with patch_db(conn):
            resp = _authed_client("stale-sid").get("/api/users/suggested")

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(conn.ran("from follows f1"))

    def test_the_limit(self):
        conn = FakeConn(fetchall=[[_user(9, followers=1)]])
        with patch_db(conn):
            self.assertEqual(client().get("/api/users/suggested?limit=10").status_code, 200)
        self.assertEqual(conn.params_for("from users u join follows f"), (10,))

        for bad in ("0", "11", "five", "-1"):
            with self.subTest(limit=bad):
                conn = FakeConn()
                with patch_db(conn):
                    resp = client().get(f"/api/users/suggested?limit={bad}")
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(resp.get_json()["error"], "limit must be a whole number from 1 to 10")
                self.assertEqual(conn.executed, [])

    def test_the_fixed_path_is_not_a_username(self):
        conn = FakeConn(fetchall=[[]])
        with patch_db(conn):
            resp = client().get("/api/users/suggested")

        self.assertEqual((resp.status_code, resp.get_json()), (200, []))
        self.assertFalse(conn.ran("where u.username = %s"))

    def test_db_down_is_a_503(self):
        with db_down():
            resp = client().get("/api/users/suggested")

        self.assertEqual(resp.status_code, 503)

    def test_a_failed_query_closes_its_connection(self):
        conn = FakeConn(raise_on={"from users u join follows f": mysql.connector.Error("2013: Lost connection")})
        with patch_db(conn):
            resp = client().get("/api/users/suggested")

        self.assertEqual(resp.status_code, 503)
        self.assertTrue(conn.closed)


if __name__ == "__main__":
    unittest.main()
