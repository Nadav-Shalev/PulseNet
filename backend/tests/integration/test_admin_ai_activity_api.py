"""GET /api/admin/ai-activity: admins only, the query checked before the DB, one
page of ai_activity's stream, and a generic 503.

Like test_admin_api.py, each request gets two connections: the session lookup's
and the endpoint's, so the endpoint's SQL stays apart.
"""

import sys
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import mysql.connector

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ai_activity  # noqa: E402
import ai_assist  # noqa: E402
import app  # noqa: E402
from support import FakeConn, client  # noqa: E402

URL = "/api/admin/ai-activity"
AT = datetime(2026, 10, 15, 19, 0, 0)


def _session_user(**over):
    row = {
        "id": 1, "name": "Root", "username": "root", "email": "root@example.com",
        "bio": "", "avatar": "a.svg", "profile_image": "p.svg", "role": "admin",
    }
    row.update(over)
    return row


@contextmanager
def as_user(conn, *, role="admin"):
    """Requests in the block log in as a user with ``role``; the endpoint gets ``conn``."""
    session = FakeConn(fetchone=[_session_user(role=role)])
    with patch.object(app, "get_db_connection", side_effect=[session, conn]):
        yield session


def _client():
    c = client()
    c.set_cookie("session_id", "valid-sid")
    return c


def agent_row(kind, **over):
    row = {"source": "agent", "source_id": 41, "created_at": AT, "kind": kind, "status": None,
           "actor_id": 11, "actor_username": "mei_ai", "actor_name": "Mei Tanaka", "actor_is_agent": 1,
           "post_id": None, "post_title": None, "comment_id": None,
           "target_id": None, "target_username": None, "target_name": None, "target_is_agent": None}
    row.update(over)
    return row


def ai_row(purpose, status="ok", **over):
    row = {"source": "ai_assist", "source_id": 17, "created_at": AT, "kind": purpose, "status": status,
           "actor_id": 2, "actor_username": "nadav", "actor_name": "Nadav", "actor_is_agent": 0,
           "post_id": None, "post_title": None, "comment_id": None,
           "target_id": None, "target_username": None, "target_name": None, "target_is_agent": None}
    row.update(over)
    return row


def _page(counts, rows=()):
    return FakeConn(fetchone=[{"n": n} for n in counts], fetchall=[list(rows)])


class AccessTests(unittest.TestCase):
    def test_a_visitor_is_401(self):
        with patch.object(app, "get_db_connection") as connect:
            resp = client().get(URL)

        self.assertEqual(resp.status_code, 401)
        connect.assert_not_called()

    def test_a_regular_user_is_403_and_nothing_is_read(self):
        conn = FakeConn()
        with as_user(conn, role="user"):
            resp = _client().get(URL)

        self.assertEqual((resp.status_code, resp.get_json()), (403, {"error": "Admin access required"}))
        self.assertEqual(conn.executed, [])


class PageTests(unittest.TestCase):
    def get(self, conn, query=""):
        with as_user(conn):
            return _client().get(URL + query)

    def test_an_admin_gets_a_page_of_events(self):
        rows = [agent_row("liked", post_id=39, post_title="Practical Baselines for ML"),
                ai_row("ai_correct", actor_id=None, actor_username=None, actor_name=None, actor_is_agent=None)]
        conn = _page([1, 1], rows)

        resp = self.get(conn)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {
            "items": [
                {"id": "agent-41", "source": "agent", "type": "liked", "created_at": "2026-10-15T19:00:00+00:00",
                 "actor": {"id": 11, "username": "mei_ai", "name": "Mei Tanaka", "is_agent": True},
                 "post": {"id": 39, "title": "Practical Baselines for ML"}, "comment_id": None,
                 "target_user": None, "status": None},
                # A deleted user stays null: the page shows "Deleted user", never a guess.
                {"id": "ai_assist-17", "source": "ai_assist", "type": "ai_correct",
                 "created_at": "2026-10-15T19:00:00+00:00", "actor": None, "post": None,
                 "comment_id": None, "target_user": None, "status": "ok"},
            ],
            "page": 1, "per_page": 25, "total": 2, "has_more": False,
        })
        self.assertTrue(conn.closed)

    def test_the_defaults_are_all_newest_first_25(self):
        conn = _page([1, 1])
        self.get(conn)

        sql, params = conn.find("select * from (")[0]
        self.assertIn("ORDER BY ev.created_at DESC, ev.source, ev.source_id DESC LIMIT %s OFFSET %s",
                      " ".join(sql.split()))
        self.assertEqual(params[-2:], (25, 0))
        self.assertEqual(conn.params_for("from llm_usage where purpose in"), tuple(ai_assist.PURPOSES))

    def test_type_sort_and_paging_reach_the_query(self):
        conn = _page([40])
        resp = self.get(conn, "?type=followed&sort=oldest&page=2&per_page=10")

        self.assertEqual(conn.find("select * from (")[0][1], ("followed", 10, 10))
        self.assertTrue(conn.ran("order by ev.created_at, ev.source, ev.source_id limit"))
        self.assertFalse(conn.ran("llm_usage"))
        body = resp.get_json()
        self.assertEqual((body["page"], body["per_page"], body["total"], body["has_more"]), (2, 10, 40, True))

    def test_the_last_page_has_no_more(self):
        for page, more in ((1, True), (2, False)):
            with self.subTest(page=page):
                resp = self.get(_page([30, 0]), f"?page={page}")
                self.assertIs(resp.get_json()["has_more"], more)

    def test_grouped_by_type(self):
        conn = _page([1, 1])
        self.get(conn, "?sort=type&type=all")

        self.assertTrue(conn.ran("order by field(ev.kind,"))
        self.assertEqual(conn.find("select * from (")[0][1][-10:-2], ai_activity.TYPE_ORDER)

    def test_ai_assist_only(self):
        conn = _page([3])
        self.get(conn, "?type=ai_assist")

        self.assertFalse(conn.ran("agent_actions"))
        self.assertTrue(conn.ran("from llm_usage l left join users u on u.id = l.user_id"))

    def test_nothing_yet(self):
        resp = self.get(_page([0, 0]))

        self.assertEqual(resp.get_json(), {"items": [], "page": 1, "per_page": 25, "total": 0, "has_more": False})

    def test_an_empty_filter_means_the_default(self):
        conn = _page([1, 1])
        resp = self.get(conn, "?type=&sort=&page=&per_page=")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(conn.find("select * from (")[0][1][-2:], (25, 0))
        self.assertTrue(conn.ran("order by ev.created_at desc"))

    def test_a_bad_query_is_400_before_the_db(self):
        for query in ("?type=moderation", "?type=check", "?sort=random", "?page=0", "?page=abc",
                      "?per_page=0", "?per_page=101", "?page=10001"):
            with self.subTest(query=query):
                conn = FakeConn()
                resp = self.get(conn, query)
                self.assertEqual(resp.status_code, 400)
                self.assertIn("error", resp.get_json())
                self.assertEqual(conn.executed, [])


class DatabaseDownTests(unittest.TestCase):
    def test_no_connection_is_a_generic_503(self):
        error = mysql.connector.errors.InterfaceError("2003: Can't connect to MySQL server on 'db.example'")
        session = FakeConn(fetchone=[_session_user()])
        with patch.object(app, "get_db_connection", side_effect=[session, error]), \
             self.assertLogs(app.app.logger, "WARNING") as logs:
            resp = _client().get(URL)

        self.assertEqual((resp.status_code, resp.get_json()), (503, {"error": "Database unavailable"}))
        self.assertNotIn("db.example", resp.get_data(as_text=True))
        self.assertNotIn("db.example", logs.output[0])
        self.assertIn("InterfaceError", logs.output[0])

    def test_a_failed_query_is_503_and_the_connection_closed(self):
        conn = FakeConn(raise_on={"from agent_actions": mysql.connector.errors.ProgrammingError("1054")})
        with as_user(conn), self.assertLogs(app.app.logger, "WARNING"):
            resp = _client().get(URL)

        self.assertEqual(resp.status_code, 503)
        self.assertTrue(conn.closed)


if __name__ == "__main__":
    unittest.main()
