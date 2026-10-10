"""Article read API tests: GET /api/articles and GET /api/articles/<id>.

Focus: each feed mode (latest, by author, by tag, following) runs its own query
with the right params, joined rows collapse into one post per id with its tags,
an unreachable DB falls back to mock_data, and a single article's body is lazily
fetched from DEV.to, cached back into the row, and always sanitized.
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import requests

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from support import FakeConn, client, db_down, patch_db  # noqa: E402

import app  # noqa: E402


def _post_row(**over):
    """One joined row as the feed/article queries return it (one row per tag)."""
    row = {
        "id": 1, "title": "Hello", "description": "desc", "cover_image": None,
        "devto_url": None, "readable_publish_date": "Oct 7",
        "created_at": datetime(2026, 10, 7, 12, 30, 0),
        "username": "ada", "name": "Ada", "email": "ada@example.com",
        "avatar": None, "profile_image": "p.svg", "tag_name": None,
    }
    row.update(over)
    return row


def _article_row(**over):
    """A GET /api/articles/<id> row: the feed columns plus the body fields."""
    row = _post_row(body_html=None, body=None, devto_id=None)
    row.update(over)
    return row


def _authed_client(sid="valid-sid"):
    c = client()
    c.set_cookie("session_id", sid)
    return c


class ArticleListTests(unittest.TestCase):
    def _get(self, url, rows=(), client_=None):
        conn = FakeConn(fetchall=[list(rows)])
        with patch_db(conn):
            resp = (client_ or client()).get(url)
        return resp, conn

    def test_latest_feed_groups_tag_rows_into_posts(self):
        resp, conn = self._get("/api/articles", rows=[
            _post_row(id=2, title="Second", tag_name="react"),
            _post_row(id=2, title="Second", tag_name="flask"),
            _post_row(id=1, title="First"),
        ])

        self.assertEqual(resp.status_code, 200)
        posts = resp.get_json()
        self.assertEqual([p["id"] for p in posts], [2, 1])
        self.assertEqual(posts[0]["tag_list"], ["react", "flask"])
        self.assertEqual(posts[1]["tag_list"], [])
        self.assertEqual(posts[0]["created_at"], "2026-10-07T12:30:00+00:00")
        self.assertEqual(posts[0]["user"]["username"], "ada")
        # Default page 1 of 10, newest first.
        self.assertEqual(conn.params_for("from posts order by created_at desc"), (10, 0))

    def test_page_and_per_page_become_limit_and_offset(self):
        _, conn = self._get("/api/articles?page=3&per_page=5")

        self.assertEqual(conn.params_for("from posts order by created_at desc"), (5, 10))

    def test_username_filters_by_author(self):
        resp, conn = self._get("/api/articles?username=ada", rows=[_post_row()])

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(conn.params_for("where users.username = %s"), ("ada", 10, 0))

    def test_tag_filter_is_passed_exact_case(self):
        _, conn = self._get("/api/articles?tag=React")

        # tags.name is utf8mb4_bin, so the value must reach SQL unchanged.
        self.assertEqual(conn.params_for("where t2.name = %s"), ("React", 10, 0))

    def test_missing_profile_image_falls_back_to_dicebear(self):
        resp, _ = self._get("/api/articles", rows=[_post_row(profile_image=None)])

        image = resp.get_json()[0]["user"]["profile_image"]
        self.assertEqual(image, f"{app.DICEBEAR_URL}?seed=ada")

    def test_empty_result_is_an_empty_list(self):
        resp, _ = self._get("/api/articles?username=nobody")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), [])


class FollowingFeedTests(unittest.TestCase):
    def test_following_feed_requires_login(self):
        conn = FakeConn()
        with patch_db(conn):
            resp = client().get("/api/articles?feed=following")

        self.assertEqual(resp.status_code, 401)
        self.assertFalse(conn.ran("join follows"))

    def test_following_feed_rejects_invalid_session(self):
        conn = FakeConn(fetchone=[None])         # cookie present, no matching session
        with patch_db(conn):
            resp = _authed_client("stale-sid").get("/api/articles?feed=following")

        self.assertEqual(resp.status_code, 401)
        self.assertFalse(conn.ran("join follows"))

    def test_following_feed_uses_the_session_user(self):
        conn = FakeConn(
            fetchone=[{"id": 42, "username": "ada"}],
            fetchall=[[_post_row(id=9, username="bob")]],
        )
        with patch_db(conn):
            resp = _authed_client().get("/api/articles?feed=following&per_page=20")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual([p["id"] for p in resp.get_json()], [9])
        self.assertEqual(conn.params_for("where f.follower_id = %s"), (42, 20, 0))

    def test_following_feed_wins_over_tag_and_username(self):
        conn = FakeConn(fetchone=[{"id": 42, "username": "ada"}])
        with patch_db(conn):
            _authed_client().get("/api/articles?feed=following&tag=react&username=bob")

        self.assertTrue(conn.ran("join follows"))
        self.assertFalse(conn.ran("where t2.name"))
        self.assertFalse(conn.ran("where users.username"))


class ArticleListFallbackTests(unittest.TestCase):
    def test_db_down_serves_mock_articles(self):
        with db_down():
            resp = client().get("/api/articles")

        self.assertEqual(resp.status_code, 200)
        # The first page contains each agent's most recent demo post.
        self.assertEqual([p["id"] for p in resp.get_json()], list(range(1, 31, 3)))

    def test_db_down_still_filters_by_username(self):
        with db_down():
            resp = client().get("/api/articles?username=priya_ai")

        posts = resp.get_json()
        self.assertEqual(sorted(p["id"] for p in posts), [1, 2, 3])
        self.assertTrue(all(p["user"]["username"] == "priya_ai" for p in posts))

    def test_db_down_paginates_mock_articles(self):
        with db_down():
            resp = client().get("/api/articles?page=2&per_page=3")

        self.assertEqual([p["id"] for p in resp.get_json()], [10, 13, 16])


class ArticleDetailTests(unittest.TestCase):
    def _get(self, article_id, rows):
        conn = FakeConn(fetchall=[rows])
        with patch_db(conn), patch.object(app.requests, "get") as devto:
            resp = client().get(f"/api/articles/{article_id}")
        return resp, conn, devto

    def test_returns_post_with_tags_and_stored_body(self):
        resp, _, devto = self._get(5, [
            _article_row(id=5, tag_name="python", body_html="<p>stored</p>"),
            _article_row(id=5, tag_name="flask", body_html="<p>stored</p>"),
        ])

        self.assertEqual(resp.status_code, 200)
        post = resp.get_json()
        self.assertEqual(post["id"], 5)
        self.assertEqual(post["tag_list"], ["python", "flask"])
        self.assertEqual(post["body_html"], "<p>stored</p>")
        devto.assert_not_called()          # a cached body never hits DEV.to

    def test_unknown_id_returns_404(self):
        resp, _, _ = self._get(404, [])

        self.assertEqual(resp.status_code, 404)

    def test_stored_body_is_sanitized_on_the_way_out(self):
        resp, _, _ = self._get(5, [
            _article_row(id=5, body_html="<p>ok</p><script>alert(1)</script>"),
        ])

        body = resp.get_json()["body_html"]
        self.assertIn("<p>ok</p>", body)
        self.assertNotIn("<script", body.lower())

    def test_markdown_body_is_rendered_when_no_html(self):
        resp, _, devto = self._get(5, [
            _article_row(id=5, body="# Title\n\nSome *text*"),
        ])

        body = resp.get_json()["body_html"]
        self.assertIn("<h1>Title</h1>", body)
        self.assertIn("<em>text</em>", body)
        devto.assert_not_called()          # no devto_id → nothing to fetch


class ArticleDevtoFetchTests(unittest.TestCase):
    """A post imported from DEV.to has a devto_id and no body_html until first read."""

    def _get(self, devto_response=None, devto_error=None):
        conn = FakeConn(fetchall=[[
            _article_row(id=5, devto_id=123, body="markdown fallback"),
        ]])
        with patch_db(conn), patch.object(app.requests, "get") as devto:
            if devto_error is not None:
                devto.side_effect = devto_error
            else:
                devto.return_value = devto_response
            resp = client().get("/api/articles/5")
        return resp, conn, devto

    def test_body_is_fetched_from_devto_and_cached(self):
        reply = Mock(ok=True)
        reply.json.return_value = {"body_html": "<p>from dev.to</p><script>x()</script>"}

        resp, conn, devto = self._get(devto_response=reply)

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()["body_html"]
        self.assertIn("<p>from dev.to</p>", body)
        self.assertNotIn("<script", body.lower())
        self.assertEqual(devto.call_args.args[0], f"{app.DEVTO_BASE}/articles/123")
        self.assertIn("timeout", devto.call_args.kwargs)
        # The sanitized HTML is written back so the next read skips DEV.to.
        self.assertEqual(conn.params_for("update posts set body_html"), (body, 5))
        self.assertEqual(conn.commits, 1)

    def test_devto_error_status_falls_back_to_markdown(self):
        resp, conn, _ = self._get(devto_response=Mock(ok=False))

        self.assertIn("markdown fallback", resp.get_json()["body_html"])
        self.assertFalse(conn.ran("update posts set body_html"))

    def test_devto_network_error_falls_back_to_markdown(self):
        resp, conn, _ = self._get(devto_error=requests.ConnectionError("offline"))

        self.assertEqual(resp.status_code, 200)
        self.assertIn("markdown fallback", resp.get_json()["body_html"])
        self.assertFalse(conn.ran("update posts set body_html"))


class ArticleDetailFallbackTests(unittest.TestCase):
    def test_db_down_serves_mock_article(self):
        with db_down():
            resp = client().get("/api/articles/1")

        self.assertEqual(resp.status_code, 200)
        post = resp.get_json()
        self.assertEqual(post["title"], "A regression test before the two-line fix")
        self.assertTrue(post["body_html"].startswith("<p>A parser"))

    def test_db_down_unknown_id_returns_404(self):
        with db_down():
            resp = client().get("/api/articles/999")

        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
