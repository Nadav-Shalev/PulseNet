"""Wrong JSON types are a 400, not a 500 (Flask test client + mocked DB seam).

Every write endpoint used to do ``(data.get(key) or "").strip()``, which raises
AttributeError when the client sends a number, list, object or bool instead of a
string, and ``data.get(...)`` crashes the same way when the body (or ``article``)
is a list. These tests send each wrong type to each field and expect a 400 that
names the field, with nothing written to the database.
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

# One of each JSON type that is not a string (null is "missing", tested apart).
NOT_STRINGS = [123, 1.5, True, ["a"], {"a": 1}]
NOT_OBJECTS = [["a"], "text", 123, True]


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


def _valid_article(**over):
    article = {"title": "T", "body_html": "<p>hi</p>", "tags": []}
    article.update(over)
    return article


def _valid_signup(**over):
    payload = {
        "name": "Ada Lovelace", "username": "ada", "email": "ada@example.com",
        "bio": "math", "password": "S3cret-pass!",
    }
    payload.update(over)
    return payload


class _Assertions(unittest.TestCase):
    def assert_bad_input(self, resp, field):
        self.assertEqual(resp.status_code, 400)
        self.assertIn(field, resp.get_json()["error"])


class CreateArticleInputTypeTests(_Assertions):
    def _post(self, body):
        conn = FakeConn(fetchone=[_session_user()], lastrowid=7)
        with patch_db(conn):
            resp = _authed_client().post("/api/articles", json=body)
        return resp, conn

    def test_non_string_post_fields_return_400_before_anything_is_stored(self):
        for field in ("title", "body_html", "body_markdown", "main_image"):
            for value in NOT_STRINGS:
                with self.subTest(field=field, value=value):
                    resp, conn = self._post({"article": _valid_article(**{field: value})})

                    self.assert_bad_input(resp, field)
                    self.assertFalse(conn.ran("insert into"))

    def test_article_that_is_not_an_object_returns_400(self):
        for value in NOT_OBJECTS:
            with self.subTest(value=value):
                resp, conn = self._post({"article": value})

                self.assert_bad_input(resp, "article")
                self.assertFalse(conn.ran("insert into"))

    def test_body_that_is_not_an_object_returns_400(self):
        resp, conn = self._post([{"article": _valid_article()}])

        self.assert_bad_input(resp, "Request body")
        self.assertFalse(conn.ran("insert into"))

    def test_null_fields_still_count_as_missing(self):
        # null is "not sent", not a wrong type: body_markdown/main_image may be null.
        resp, conn = self._post({"article": _valid_article(body_markdown=None, main_image=None)})

        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(resp.get_json()["cover_image"])
        self.assertTrue(conn.ran("insert into posts"))

    def test_null_title_is_still_title_required(self):
        resp, _conn = self._post({"article": _valid_article(title=None)})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "title is required")


class SignupInputTypeTests(_Assertions):
    def _post(self, body):
        conn = FakeConn(fetchone=[None, None], lastrowid=5)
        with patch_db(conn):
            resp = client().post("/api/users", json=body)
        return resp, conn

    def test_non_string_signup_fields_return_400_before_any_db_work(self):
        for field in ("name", "username", "email", "bio", "password"):
            for value in NOT_STRINGS:
                with self.subTest(field=field, value=value):
                    resp, conn = self._post(_valid_signup(**{field: value}))

                    self.assert_bad_input(resp, field)
                    self.assertEqual(conn.executed, [])

    def test_body_that_is_not_an_object_returns_400(self):
        resp, conn = self._post([_valid_signup()])

        self.assert_bad_input(resp, "Request body")
        self.assertEqual(conn.executed, [])


class LoginInputTypeTests(_Assertions):
    def _post(self, body):
        conn = FakeConn()
        with patch_db(conn):
            resp = client().post("/api/login", json=body)
        return resp, conn

    def test_non_string_login_fields_return_400_before_any_db_work(self):
        for field in ("email", "password"):
            for value in NOT_STRINGS:
                with self.subTest(field=field, value=value):
                    body = {"email": "ada@example.com", "password": "pw", field: value}
                    resp, conn = self._post(body)

                    self.assert_bad_input(resp, field)
                    self.assertEqual(conn.executed, [])

    def test_body_that_is_not_an_object_returns_400(self):
        resp, conn = self._post(["ada@example.com", "pw"])

        self.assert_bad_input(resp, "Request body")
        self.assertEqual(conn.executed, [])


class UpdateMeInputTypeTests(_Assertions):
    def _patch(self, body):
        conn = FakeConn(fetchone=[_session_user()])
        with patch_db(conn):
            resp = _authed_client().patch("/api/me", json=body)
        return resp, conn

    def test_non_string_profile_fields_return_400_without_an_update(self):
        for field in ("name", "bio", "profile_image"):
            for value in NOT_STRINGS:
                with self.subTest(field=field, value=value):
                    resp, conn = self._patch({field: value})

                    self.assert_bad_input(resp, field)
                    self.assertFalse(conn.ran("update users"))

    def test_body_that_is_not_an_object_returns_400(self):
        resp, conn = self._patch(["name"])

        self.assert_bad_input(resp, "Request body")
        self.assertFalse(conn.ran("update users"))

    def test_null_bio_and_image_still_clear_the_field(self):
        resp, conn = self._patch({"bio": None, "profile_image": None})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(conn.params_for("update users"), ["", None, 42])


class LogoutInputTypeTests(unittest.TestCase):
    def test_body_that_is_not_an_object_logs_out_this_device_only(self):
        # The logout body is optional, so a junk body must not stop a logout.
        conn = FakeConn(fetchone=[_session_user()])
        c = _authed_client("this-sid")
        with patch_db(conn):
            resp = c.post("/api/logout", json=["allDevices"])

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(conn.params_for("delete from sessions where session_id"), ("this-sid",))
        self.assertFalse(conn.ran("delete from sessions where user_id"))


if __name__ == "__main__":
    unittest.main()
