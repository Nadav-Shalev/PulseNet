"""Reports: POST /api/reports, the admin's list and resolve, and an admin deleting
any post or comment.

As in test_admin_api.py, the session lookup gets a FakeConn of its own, so the
endpoint's connection holds only the endpoint's SQL and its closed flag means
something.
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

import app  # noqa: E402
from support import FakeConn, client  # noqa: E402

ME = 42


def _session_user(**over):
    row = {
        "id": ME, "name": "Ada", "username": "ada", "email": "ada@example.com",
        "bio": "", "avatar": "a.svg", "profile_image": "p.svg", "role": "user",
    }
    row.update(over)
    return row


@contextmanager
def as_user(conn, *, role="user", db_available=True):
    session = FakeConn(fetchone=[_session_user(role=role)])
    with patch.object(app, "get_db_connection", side_effect=[session, conn]), \
         patch.object(app, "is_db_available", return_value=db_available):
        yield session


def _client():
    c = client()
    c.set_cookie("session_id", "valid-sid")
    return c


def _integrity_error(errno, msg="boom"):
    return mysql.connector.errors.IntegrityError(msg=msg, errno=errno)


class CreateReportTests(unittest.TestCase):
    def post(self, body, conn, **kw):
        with as_user(conn, **kw):
            return _client().post("/api/reports", json=body)

    def test_report_a_post(self):
        conn = FakeConn(fetchone=[{"author_id": 7}], lastrowid=5)
        resp = self.post({"post_id": 3, "reason": "spam", "details": "  ads everywhere "}, conn)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.get_json(), {"reported": True, "already": False, "id": 5})
        self.assertEqual(conn.params_for("select author_id from posts"), (3,))
        sql, params = conn.find("insert into reports")[0]
        self.assertIn("(reporter_id, post_id, reason, details)", sql)
        self.assertEqual(params, (ME, 3, "spam", "ads everywhere"))
        self.assertEqual(conn.commits, 1)
        self.assertTrue(conn.closed)

    def test_report_a_comment_without_details(self):
        conn = FakeConn(fetchone=[{"author_id": 7}])
        resp = self.post({"comment_id": 9, "reason": "harassment"}, conn)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(conn.params_for("select author_id from comments"), (9,))
        sql, params = conn.find("insert into reports")[0]
        self.assertIn("(reporter_id, comment_id, reason, details)", sql)
        self.assertEqual(params, (ME, 9, "harassment", None))   # an empty note is NULL

    def test_the_reporter_comes_from_the_session(self):
        conn = FakeConn(fetchone=[{"author_id": 7}])
        self.post({"post_id": 3, "reason": "spam", "reporter_id": 1}, conn)

        self.assertEqual(conn.params_for("insert into reports")[0], ME)

    def test_a_second_report_is_already_reported(self):
        conn = FakeConn(fetchone=[{"author_id": 7}],
                        raise_on={"insert into reports": _integrity_error(1062, "Duplicate entry")})
        resp = self.post({"post_id": 3, "reason": "spam"}, conn)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"reported": True, "already": True})
        self.assertEqual(conn.rollbacks, 1)
        self.assertEqual(conn.commits, 0)
        self.assertTrue(conn.closed)

    def test_other_db_errors_are_not_already_reported(self):
        # A foreign-key error (the post deleted meanwhile), or any other one, is a
        # failure: it must never be reported back as a duplicate.
        errors = {
            "fk": _integrity_error(1452, "Cannot add or update a child row"),
            "check": mysql.connector.errors.DatabaseError(msg="Check constraint", errno=3819),
            "enum": mysql.connector.errors.DatabaseError(msg="Data truncated", errno=1265),
        }
        for name, error in errors.items():
            with self.subTest(error=name):
                conn = FakeConn(fetchone=[{"author_id": 7}], raise_on={"insert into reports": error})
                app.app.testing, testing = False, app.app.testing   # a real 500, not a raise
                try:
                    # Flask logs the unhandled error: captured here, and so asserted.
                    with self.assertLogs(app.app.logger, "ERROR"):
                        resp = self.post({"post_id": 3, "reason": "spam"}, conn)
                finally:
                    app.app.testing = testing

                self.assertEqual(resp.status_code, 500)
                self.assertNotIn(b"already", resp.data)
                self.assertEqual(conn.rollbacks, 0)
                self.assertTrue(conn.closed)

    def test_exactly_one_target(self):
        for body in ({"reason": "spam"},
                     {"post_id": 3, "comment_id": 9, "reason": "spam"},
                     {"post_id": None, "comment_id": None, "reason": "spam"}):
            with self.subTest(body=body):
                conn = FakeConn()
                resp = self.post(body, conn)

                self.assertEqual(resp.status_code, 400)
                self.assertEqual(conn.executed, [])

    def test_the_target_must_be_an_id(self):
        for value in ("3", 3.0, True, [3]):
            with self.subTest(value=value):
                conn = FakeConn()
                resp = self.post({"comment_id": value, "reason": "spam"}, conn)

                self.assertEqual(resp.status_code, 400)
                self.assertEqual(resp.get_json(), {"error": "comment_id must be an id"})
                self.assertEqual(conn.executed, [])

    def test_the_reason_must_be_on_the_list(self):
        for body in ({"post_id": 3}, {"post_id": 3, "reason": "rude"}, {"post_id": 3, "reason": "Spam"}):
            with self.subTest(body=body):
                conn = FakeConn()
                self.assertEqual(self.post(body, conn).status_code, 400)
                self.assertEqual(conn.executed, [])

    def test_bad_types_are_400(self):
        for body in ({"post_id": 3, "reason": 1}, {"post_id": 3, "reason": "spam", "details": 5}, ["x"]):
            with self.subTest(body=body):
                conn = FakeConn()
                self.assertEqual(self.post(body, conn).status_code, 400)
                self.assertEqual(conn.executed, [])

    def test_details_have_a_limit(self):
        conn = FakeConn(fetchone=[{"author_id": 7}])
        ok = self.post({"post_id": 3, "reason": "other", "details": "x" * 500}, conn)
        self.assertEqual(ok.status_code, 201)

        conn = FakeConn()
        resp = self.post({"post_id": 3, "reason": "other", "details": "x" * 501}, conn)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(conn.executed, [])

    def test_a_missing_target_is_404_before_any_insert(self):
        for key, message in (("post_id", "Post not found"), ("comment_id", "Comment not found")):
            with self.subTest(key=key):
                conn = FakeConn(fetchone=[None])
                resp = self.post({key: 3, "reason": "spam"}, conn)

                self.assertEqual(resp.status_code, 404)
                self.assertEqual(resp.get_json(), {"error": message})
                self.assertFalse(conn.ran("insert"))
                self.assertTrue(conn.closed)

    def test_own_content_cannot_be_reported(self):
        conn = FakeConn(fetchone=[{"author_id": ME}])
        resp = self.post({"comment_id": 9, "reason": "spam"}, conn)

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json(), {"error": "You cannot report your own comment"})
        self.assertFalse(conn.ran("insert"))

    def test_requires_a_session(self):
        resp = client().post("/api/reports", json={"post_id": 3, "reason": "spam"})

        self.assertEqual(resp.status_code, 401)

    def test_db_unavailable_is_503(self):
        conn = FakeConn()
        resp = self.post({"post_id": 3, "reason": "spam"}, conn, db_available=False)

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(conn.executed, [])


def _report_row(**over):
    row = {
        "id": 11, "post_id": 3, "comment_id": None, "reason": "spam", "details": "<b>ads</b>",
        "status": "open", "created_at": datetime(2026, 10, 8, 9, 0, 0), "resolved_at": None,
        "reporter_username": "bob", "resolved_by_username": None,
        "target_post_id": 3, "post_title": "Buy now",
        "target_html": "<p>Cheap <b>pills</b></p>",
        "author_id": 7, "author_username": "eve", "author_is_banned": 0,
        "email": "eve@example.com",            # never passed on, even if selected
    }
    row.update(over)
    return row


class AdminReportListTests(unittest.TestCase):
    def test_lists_open_reports_newest_first(self):
        conn = FakeConn(fetchall=[[_report_row()]])
        with as_user(conn, role="admin"):
            resp = _client().get("/api/admin/reports")

        self.assertEqual(resp.status_code, 200)
        sql, params = conn.find("from reports r")[0]
        flat = " ".join(sql.split())
        self.assertIn("WHERE r.status = %s ORDER BY r.created_at DESC, r.id DESC LIMIT %s", flat)
        self.assertNotIn("email", flat.lower())
        self.assertEqual(params, ("open", app.ADMIN_REPORT_LIMIT))
        self.assertEqual(resp.get_json(), [{
            "id": 11, "reason": "spam", "details": "<b>ads</b>", "status": "open",
            "created_at": "2026-10-08T09:00:00+00:00", "resolved_at": None, "resolved_by": None,
            "reporter": {"username": "bob"},
            "target": {"type": "post", "id": 3, "post_id": 3, "post_title": "Buy now",
                       "excerpt": "Cheap pills"},
            "author": {"id": 7, "username": "eve", "is_banned": False},
        }])
        self.assertTrue(conn.closed)

    def test_a_comment_report_points_at_its_post(self):
        conn = FakeConn(fetchall=[[_report_row(post_id=None, comment_id=9, author_is_banned=1,
                                               target_html="x" * 300)]])
        with as_user(conn, role="admin"):
            report = _client().get("/api/admin/reports").get_json()[0]

        self.assertEqual(report["target"]["type"], "comment")
        self.assertEqual(report["target"]["id"], 9)
        self.assertEqual(report["target"]["post_id"], 3)
        self.assertEqual(len(report["target"]["excerpt"]), app.REPORT_EXCERPT_CHARS)
        self.assertTrue(report["target"]["excerpt"].endswith("…"))
        self.assertTrue(report["author"]["is_banned"])

    def test_resolved_reports(self):
        conn = FakeConn(fetchall=[[]])
        with as_user(conn, role="admin"):
            resp = _client().get("/api/admin/reports?status=resolved")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(conn.find("from reports r")[0][1], ("resolved", 100))

    def test_an_unknown_status_is_400(self):
        conn = FakeConn()
        with as_user(conn, role="admin"):
            resp = _client().get("/api/admin/reports?status=all")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(conn.executed, [])

    def test_a_regular_user_is_403(self):
        conn = FakeConn()
        with as_user(conn):
            resp = _client().get("/api/admin/reports")

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(conn.executed, [])

    def test_db_down_is_503_never_an_empty_list(self):
        error = mysql.connector.errors.InterfaceError("2003: Can't connect")
        session = FakeConn(fetchone=[_session_user(role="admin")])
        with patch.object(app, "get_db_connection", side_effect=[session, error]):
            resp = _client().get("/api/admin/reports")

        self.assertEqual(resp.status_code, 503)


class ResolveReportTests(unittest.TestCase):
    def test_resolve_records_the_admin(self):
        conn = FakeConn(fetchone=[{"status": "open"}])
        with as_user(conn, role="admin"):
            resp = _client().post("/api/admin/reports/11/resolve")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"id": 11, "status": "resolved"})
        sql, params = conn.find("update reports")[0]
        self.assertIn("status = 'resolved', resolved_by = %s, resolved_at = NOW()", sql)
        self.assertEqual(params, (ME, 11))
        self.assertEqual(conn.commits, 1)
        self.assertTrue(conn.closed)

    def test_resolving_again_keeps_the_first_resolution(self):
        conn = FakeConn(fetchone=[{"status": "resolved"}])
        with as_user(conn, role="admin"):
            resp = _client().post("/api/admin/reports/11/resolve")

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(conn.ran("update reports"))

    def test_an_unknown_report_is_404(self):
        conn = FakeConn(fetchone=[None])
        with as_user(conn, role="admin"):
            resp = _client().post("/api/admin/reports/99/resolve")

        self.assertEqual(resp.status_code, 404)
        self.assertFalse(conn.ran("update"))
        self.assertTrue(conn.closed)

    def test_a_regular_user_is_403(self):
        conn = FakeConn(fetchone=[{"status": "open"}])
        with as_user(conn):
            resp = _client().post("/api/admin/reports/11/resolve")

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(conn.executed, [])

    def test_db_unavailable_is_503(self):
        conn = FakeConn()
        with as_user(conn, role="admin", db_available=False):
            resp = _client().post("/api/admin/reports/11/resolve")

        self.assertEqual(resp.status_code, 503)


class AdminDeletesAnyContentTests(unittest.TestCase):
    def test_an_admin_deletes_someone_elses_post(self):
        conn = FakeConn(fetchone=[(7,)])               # the post's author_id: not the admin
        with as_user(conn, role="admin"):
            resp = _client().delete("/api/articles/3")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(conn.params_for("delete from posts where"), (3,))

    def test_a_user_still_cannot_delete_someone_elses_post(self):
        conn = FakeConn(fetchone=[(7,)])
        with as_user(conn):
            resp = _client().delete("/api/articles/3")

        self.assertEqual(resp.status_code, 403)
        self.assertFalse(conn.ran("delete from posts"))

    def test_an_admin_gets_404_for_a_missing_post(self):
        conn = FakeConn(fetchone=[None])
        with as_user(conn, role="admin"):
            resp = _client().delete("/api/articles/3")

        self.assertEqual(resp.status_code, 404)
        self.assertFalse(conn.ran("delete"))

    def test_the_admin_override_is_for_delete_only(self):
        # Removing a tag stays the author's: moderation deletes, it does not edit.
        conn = FakeConn(fetchone=[(7,)])
        with as_user(conn, role="admin"):
            resp = _client().delete("/api/articles/3/tags?name=react")

        self.assertEqual(resp.status_code, 403)

    def test_an_admin_deletes_someone_elses_comment(self):
        conn = FakeConn(fetchone=[{"author_id": 7, "post_id": 3}, {"comment_count": 0}])
        with as_user(conn, role="admin"):
            resp = _client().delete("/api/comments/9")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(conn.params_for("delete from comments where"), (9,))

    def test_a_user_still_cannot_delete_someone_elses_comment(self):
        conn = FakeConn(fetchone=[{"author_id": 7, "post_id": 3}])
        with as_user(conn):
            resp = _client().delete("/api/comments/9")

        self.assertEqual(resp.status_code, 403)
        self.assertFalse(conn.ran("delete from comments"))


if __name__ == "__main__":
    unittest.main()
