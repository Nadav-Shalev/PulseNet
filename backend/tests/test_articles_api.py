"""Article create/delete API tests (Flask test client + mocked DB seam).

Focus: the auth gate, that stored body_html is always sanitized (both the HTML and
the markdown-fallback branches), input validation, and owner-only deletion.
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent):
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


class CreateArticleAuthTests(unittest.TestCase):
    def test_create_requires_session(self):
        # No cookie → require_session aborts before any DB work.
        resp = client().post("/api/articles", json={"article": {"title": "T"}})

        self.assertEqual(resp.status_code, 401)

    def test_create_in_mock_mode_returns_503(self):
        conn = FakeConn(fetchone=[_session_user()])
        with patch_db(conn, db_available=False):
            resp = _authed_client().post(
                "/api/articles",
                json={"article": {"title": "T", "body_html": "<p>hi</p>"}},
            )

        self.assertEqual(resp.status_code, 503)


class CreateArticleSanitizationTests(unittest.TestCase):
    def test_created_body_html_is_sanitized(self):
        conn = FakeConn(fetchone=[_session_user()], lastrowid=7)
        with patch_db(conn):
            resp = _authed_client().post(
                "/api/articles",
                json={"article": {
                    "title": "My Post",
                    "body_html": "<p>hello</p><script>alert(1)</script>",
                    "tags": [],
                }},
            )

        self.assertEqual(resp.status_code, 201)
        self.assertNotIn("<script", resp.get_json()["body_html"].lower())
        # The value handed to the INSERT is sanitized too (not just the response).
        insert = conn.find("insert into posts")
        self.assertTrue(insert)
        stored_body_html = insert[0][1][3]      # (author_id, title, body, body_html, ...)
        self.assertNotIn("<script", stored_body_html.lower())

    def test_markdown_fallback_is_sanitized(self):
        conn = FakeConn(fetchone=[_session_user()], lastrowid=8)
        with patch_db(conn):
            resp = _authed_client().post(
                "/api/articles",
                json={"article": {
                    "title": "Markdown Post",
                    "body_markdown": "intro text\n\n<script>alert(1)</script>",
                    "tags": [],
                }},
            )

        self.assertEqual(resp.status_code, 201)
        self.assertNotIn("<script", resp.get_json()["body_html"].lower())


class CreateArticleValidationTests(unittest.TestCase):
    def _post(self, article):
        conn = FakeConn(fetchone=[_session_user()])
        with patch_db(conn):
            return _authed_client().post("/api/articles", json={"article": article})

    def test_empty_title_returns_400(self):
        self.assertEqual(self._post({"title": "  ", "body_html": "<p>x</p>"}).status_code, 400)

    def test_missing_body_returns_400(self):
        self.assertEqual(self._post({"title": "T"}).status_code, 400)

    def test_title_too_long_returns_400(self):
        resp = self._post({"title": "x" * 151, "body_html": "<p>hi</p>"})
        self.assertEqual(resp.status_code, 400)

    def test_tags_not_a_list_returns_400(self):
        resp = self._post({"title": "T", "body_html": "<p>hi</p>", "tags": "react"})
        self.assertEqual(resp.status_code, 400)

    def test_too_many_tags_returns_400(self):
        resp = self._post({"title": "T", "body_html": "<p>hi</p>", "tags": ["t"] * 11})
        self.assertEqual(resp.status_code, 400)


class DeleteArticleTests(unittest.TestCase):
    def test_delete_requires_session(self):
        resp = client().delete("/api/articles/5")

        self.assertEqual(resp.status_code, 401)

    def test_owner_can_delete(self):
        # require_session row, then _require_post_owner's SELECT author_id → owner (42).
        conn = FakeConn(fetchone=[_session_user(id=42), (42,)])
        with patch_db(conn):
            resp = _authed_client().delete("/api/articles/5")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"deleted": True, "id": 5})
        self.assertTrue(conn.ran("delete from posts where id"))

    def test_non_owner_is_forbidden(self):
        conn = FakeConn(fetchone=[_session_user(id=42), (99,)])
        with patch_db(conn):
            resp = _authed_client().delete("/api/articles/5")

        self.assertEqual(resp.status_code, 403)
        self.assertFalse(conn.ran("delete from posts where id"))

    def test_missing_post_returns_404(self):
        conn = FakeConn(fetchone=[_session_user(id=42), None])
        with patch_db(conn):
            resp = _authed_client().delete("/api/articles/5")

        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
