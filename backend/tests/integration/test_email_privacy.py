"""Email privacy: a user's email is visible only to that user.

Public endpoints (feeds, a single post, user search, the user list, profiles,
follow lists, a newly created post) never put an email in the response, and
neither do the admin lists (users, reports): an admin needs no address either. Their SQL
neither selects nor filters on the email column, so search results can't be used
to probe for an address either. Only the caller's own record carries it:
GET/PATCH /api/me and the login/signup responses.
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from support import FakeConn, client, db_down, patch_db, patch_mail  # noqa: E402

import app  # noqa: E402

ADA_EMAIL = "ada@example.com"


def _session_user(**over):
    """Row shape returned by require_session's JOIN, which does read the email."""
    row = {
        "id": 42, "name": "Ada", "username": "ada", "email": ADA_EMAIL,
        "bio": "hi", "avatar": "a.svg", "profile_image": "p.svg",
    }
    row.update(over)
    return row


def _post_row(**over):
    """A feed/article row. It carries an email on purpose: even if a query selected
    u.email again, the post shape must not pass it on."""
    row = {
        "id": 1, "title": "Hello", "description": "desc", "cover_image": None,
        "devto_url": None, "readable_publish_date": "Oct 7",
        "created_at": datetime(2026, 10, 7, 12, 30, 0),
        "username": "ada", "name": "Ada", "email": ADA_EMAIL,
        "avatar": None, "profile_image": "p.svg", "tag_name": "react",
        "body_html": "<p>hi</p>", "body": "hi", "devto_id": None,
    }
    row.update(over)
    return row


def _authed_client(sid="valid-sid"):
    c = client()
    c.set_cookie("session_id", sid)
    return c


def _emails_in(value):
    """Every place an email shows up in a JSON value: an "email" key or an address."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "email":
                found.append(f"key {key!r}")
            found += _emails_in(item)
    elif isinstance(value, list):
        for item in value:
            found += _emails_in(item)
    elif isinstance(value, str) and "@example.com" in value:
        found.append(value)
    return found


class PublicResponsesHideEmailTests(unittest.TestCase):
    def assertNoEmail(self, resp, conn=None):
        self.assertLess(resp.status_code, 300, resp.get_data(as_text=True))
        self.assertEqual(_emails_in(resp.get_json()), [])
        if conn is not None:
            self.assertEqual(
                [sql for sql, _ in conn.executed if "email" in sql.lower()], [],
                "a public endpoint must not select or filter on users.email",
            )

    def test_article_feeds(self):
        for url in ("/api/articles", "/api/articles?username=ada", "/api/articles?tag=react"):
            with self.subTest(url=url):
                conn = FakeConn(fetchall=[[_post_row()]])
                with patch_db(conn):
                    resp = client().get(url)

                self.assertNoEmail(resp, conn)

    def test_following_feed(self):
        conn = FakeConn(fetchone=[{"id": 7, "username": "bob"}], fetchall=[[_post_row()]])
        with patch_db(conn):
            resp = _authed_client().get("/api/articles?feed=following")

        self.assertNoEmail(resp, conn)

    def test_single_article(self):
        conn = FakeConn(fetchall=[[_post_row()]])
        with patch_db(conn):
            resp = client().get("/api/articles/1")

        self.assertNoEmail(resp, conn)

    def test_mock_feeds_when_the_db_is_down(self):
        with db_down():
            for url in ("/api/articles", "/api/articles/1"):
                with self.subTest(url=url):
                    self.assertNoEmail(client().get(url))

    def test_created_post_hides_its_author_email(self):
        # The author is the caller, but the post shape is the public one the feed
        # shows to everybody, so it carries no email either.
        conn = FakeConn(fetchone=[_session_user(), (5,)], lastrowid=9)
        with patch_db(conn):
            resp = _authed_client().post("/api/articles", json={"article": {
                "title": "T", "body_html": "<p>hi</p>", "tags": ["react"],
            }})

        self.assertEqual(resp.status_code, 201)
        self.assertNoEmail(resp)

    def test_user_search(self):
        rows = [{"id": 42, "name": "Ada", "username": "ada", "avatar": None}]
        conn = FakeConn(fetchall=[rows])
        with patch_db(conn):
            resp = client().get("/api/users/search?q=ada")

        self.assertNoEmail(resp, conn)

    def test_user_search_mock_fallback(self):
        with db_down():
            resp = client().get("/api/users/search?q=a")

        self.assertTrue(resp.get_json())
        self.assertNoEmail(resp)

    def test_user_list(self):
        for url in ("/api/users", "/api/users?q=ada"):
            with self.subTest(url=url):
                conn = FakeConn(fetchall=[[{"id": 42, "username": "ada", "post_count": 1}]])
                with patch_db(conn):
                    resp = client().get(url)

                self.assertNoEmail(resp, conn)

    def test_profile_seen_by_anyone_including_its_owner(self):
        profile = {"id": 42, "name": "Ada", "username": "ada", "bio": "hi",
                   "avatar": None, "profile_image": "p.svg",
                   "post_count": 1, "followers_count": 0, "following_count": 0}
        for viewer, fetchone in (("anonymous", [dict(profile)]),
                                 ("owner", [dict(profile), {"id": 42, "username": "ada"}])):
            with self.subTest(viewer=viewer):
                conn = FakeConn(fetchone=fetchone)
                c = client() if viewer == "anonymous" else _authed_client()
                with patch_db(conn):
                    resp = c.get("/api/users/ada")

                self.assertNoEmail(resp, conn)

    def test_follow_lists(self):
        for side in ("followers", "following"):
            with self.subTest(side=side):
                conn = FakeConn(fetchone=[{"id": 42}],
                                fetchall=[[{"id": 7, "name": "Bob", "username": "bob"}]])
                with patch_db(conn):
                    resp = client().get(f"/api/users/ada/{side}")

                self.assertNoEmail(resp, conn)

    def test_lookup_by_email_endpoint_is_gone(self):
        conn = FakeConn()
        with patch_db(conn):
            resp = client().get(f"/api/users/by-email?email={ADA_EMAIL}")

        # The path now falls through to /api/users/<username>, which looks up a user
        # named "by-email" (there is none) and ignores the address.
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(conn.params_for("where u.username = %s"), ("by-email",))
        self.assertFalse(conn.ran("email"))


class SearchDoesNotMatchEmailTests(unittest.TestCase):
    """A hidden field must not be searchable either: otherwise searching "@gmail"
    or a full address would reveal whose email it is."""

    def test_user_search_matches_name_and_username_only(self):
        conn = FakeConn()
        with patch_db(conn):
            client().get("/api/users/search?q=ada@example.com")

        self.assertEqual(conn.params_for("where name like %s or username like %s limit"),
                         ("%ada@example.com%", "%ada@example.com%", 10, 0))

    def test_user_list_matches_name_and_username_only(self):
        conn = FakeConn()
        with patch_db(conn):
            client().get("/api/users?q=ada@example.com")

        self.assertEqual(
            conn.params_for("where (u.username like %s or u.name like %s) group by"),
            ["%ada@example.com%", "%ada@example.com%", 10, 0],
        )

    def test_mock_search_ignores_email(self):
        # Every mock user's address ends in "@dev.to"; no name or username has it.
        with db_down():
            resp = client().get("/api/users/search?q=@dev.to")

        self.assertEqual(resp.get_json(), [])


class OwnRecordKeepsEmailTests(unittest.TestCase):
    """The user's own account screens still need their address."""

    def test_me(self):
        conn = FakeConn(fetchone=[_session_user()])
        with patch_db(conn):
            resp = _authed_client().get("/api/me")

        self.assertEqual(resp.get_json()["email"], ADA_EMAIL)

    def test_update_me(self):
        conn = FakeConn(fetchone=[_session_user()])
        with patch_db(conn):
            resp = _authed_client().patch("/api/me", json={"bio": "new"})

        self.assertEqual(resp.get_json()["email"], ADA_EMAIL)

    def test_login(self):
        user = _session_user(password_hash=app._hash_password("AdaPass123!"))
        conn = FakeConn(fetchone=[user])
        with patch_db(conn):
            resp = client().post("/api/login", json={"email": ADA_EMAIL, "password": "AdaPass123!"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["email"], ADA_EMAIL)



class PasswordResetHidesEmailTests(unittest.TestCase):
    """"Forgot" looks the address up (like login), but answers the same words for
    every address and never echoes one; the reset answer carries none either."""

    def test_forgot_says_the_same_for_a_known_and_an_unknown_address(self):
        answers = []
        for rows in ([{"id": 42, "name": "Ada", "email": ADA_EMAIL}, {"recent": 0}], [None]):
            conn = FakeConn(fetchone=rows)
            with patch_db(conn), patch_mail():
                resp = client().post("/api/password/forgot", json={"email": ADA_EMAIL})
            self.assertEqual(_emails_in(resp.get_json()), [])
            answers.append((resp.status_code, resp.get_json()))
        self.assertEqual(answers[0], answers[1])

    def test_reset_answers_without_an_email(self):
        conn = FakeConn(fetchone=[{"id": 5, "user_id": 42}])
        with patch_db(conn):
            resp = client().post("/api/password/reset", json={"token": "tok", "password": "N3w-pass!"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_emails_in(resp.get_json()), [])
        self.assertEqual([sql for sql, _ in conn.executed if "email" in sql.lower()], [])


class AdminResponsesHideEmailTests(unittest.TestCase):
    """The session lookup reads the admin's own email, so the endpoint gets a
    connection of its own and only its SQL is checked."""

    def _get(self, url, conn):
        session = FakeConn(fetchone=[_session_user(role="admin")])
        with patch.object(app, "get_db_connection", side_effect=[session, conn]):
            return _authed_client().get(url)

    def assertNoEmail(self, resp, conn):
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        self.assertEqual(_emails_in(resp.get_json()), [])
        self.assertEqual([sql for sql, _ in conn.executed if "email" in sql.lower()], [])

    def test_admin_user_list(self):
        for url in ("/api/admin/users", "/api/admin/users?q=ada@example.com", "/api/admin/users?banned=1"):
            with self.subTest(url=url):
                conn = FakeConn(fetchall=[[{"id": 42, "username": "ada", "name": "Ada", "role": "user",
                                            "is_banned": 0, "email": ADA_EMAIL}]])
                self.assertNoEmail(self._get(url, conn), conn)

    def test_admin_report_list(self):
        conn = FakeConn(fetchall=[[{
            "id": 1, "post_id": 1, "comment_id": None, "reason": "spam", "details": None,
            "status": "open", "created_at": None, "resolved_at": None,
            "reporter_username": "bob", "resolved_by_username": None, "target_post_id": 1,
            "post_title": "Hello", "target_html": "<p>hi</p>", "author_id": 42,
            "author_username": "ada", "author_is_banned": 0, "email": ADA_EMAIL,
        }]])
        self.assertNoEmail(self._get("/api/admin/reports", conn), conn)


if __name__ == "__main__":
    unittest.main()
