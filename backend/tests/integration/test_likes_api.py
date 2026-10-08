"""Likes API tests (Flask test client + mocked DB seam).

POST / DELETE /api/articles/<id>/like: the liker comes from the session, a missing
post is a 404, and the reply carries the post's fresh like count. Every feed mode
and a single article report like_count and liked_by_me for the viewer, with one
counts query per page (shared with comment_count).
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from support import FakeConn, client, db_down, patch_db  # noqa: E402

COUNTS_QUERY = "from posts p where p.id in"
VIEWER = {"id": 42, "username": "ada"}


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


def _post_row(**over):
    """One joined feed row (one per tag), as get_articles reads it."""
    row = {
        "id": 1, "title": "Hello", "description": "desc", "cover_image": None,
        "devto_url": None, "readable_publish_date": "Oct 7",
        "created_at": datetime(2026, 10, 7, 12, 30, 0),
        "username": "bob", "name": "Bob", "avatar": None, "profile_image": "p.svg",
        "tag_name": None,
    }
    row.update(over)
    return row


def _counts_row(post_id, like_count, liked_by_me, comment_count=0):
    # liked_by_me is COUNT(*) of the viewer's like rows: 0 or 1 (0 for a NULL viewer).
    return {"post_id": post_id, "like_count": like_count, "liked_by_me": liked_by_me,
            "comment_count": comment_count}


class LikeTests(unittest.TestCase):
    def test_like_and_unlike_require_a_session(self):
        conn = FakeConn()
        with patch_db(conn):
            for method in ("post", "delete"):
                with self.subTest(method=method):
                    resp = getattr(client(), method)("/api/articles/7/like")
                    self.assertEqual(resp.status_code, 401)
        self.assertFalse(conn.ran("likes"))

    def test_db_unavailable_returns_503(self):
        conn = FakeConn(fetchone=[_session_user()])
        with patch_db(conn, db_available=False):
            resp = _authed_client().post("/api/articles/7/like")

        self.assertEqual(resp.status_code, 503)
        self.assertFalse(conn.ran("into likes"))

    def test_like_unknown_post_returns_404(self):
        # It must not reach INSERT IGNORE, which turns the foreign-key error into a
        # warning and would report a like that was never stored.
        conn = FakeConn(fetchone=[_session_user(), None])
        with patch_db(conn):
            resp = _authed_client().post("/api/articles/7/like")

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(conn.params_for("select id from posts where id = %s"), (7,))
        self.assertFalse(conn.ran("into likes"))

    def test_unlike_unknown_post_returns_404(self):
        conn = FakeConn(fetchone=[_session_user(), None])
        with patch_db(conn):
            resp = _authed_client().delete("/api/articles/7/like")

        self.assertEqual(resp.status_code, 404)
        self.assertFalse(conn.ran("delete from likes"))

    def test_like_is_stored_for_the_session_user_and_returns_the_count(self):
        conn = FakeConn(fetchone=[_session_user(id=42), (7,), (3,)])
        with patch_db(conn):
            resp = _authed_client().post("/api/articles/7/like")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"liked": True, "like_count": 3})
        insert = conn.find("insert ignore into likes")
        self.assertTrue(insert, "liking must use INSERT IGNORE, so liking twice is a no-op")
        self.assertEqual(insert[0][1], (42, 7))          # (user_id, post_id)
        self.assertEqual(conn.params_for("select count(*) from likes"), (7,))
        # One commit from require_session's expired-session cleanup, one for the like.
        self.assertEqual(conn.commits, 2)
        self.assertTrue(conn.closed)

    def test_a_user_id_in_the_body_is_ignored(self):
        conn = FakeConn(fetchone=[_session_user(id=42), (7,), (1,)])
        with patch_db(conn):
            _authed_client().post("/api/articles/7/like", json={"user_id": 99})

        self.assertEqual(conn.params_for("insert ignore into likes"), (42, 7))

    def test_unlike_deletes_only_the_session_users_like(self):
        conn = FakeConn(fetchone=[_session_user(id=42), (7,), (2,)])
        with patch_db(conn):
            resp = _authed_client().delete("/api/articles/7/like")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"liked": False, "like_count": 2})
        self.assertEqual(conn.params_for("delete from likes where user_id = %s and post_id = %s"), (42, 7))
        self.assertFalse(conn.ran("insert"))
        self.assertEqual(conn.commits, 2)


class FeedLikesTests(unittest.TestCase):
    def _get(self, url, posts, likes, viewer=None):
        conn = FakeConn(fetchone=[viewer] if viewer else [], fetchall=[posts, likes])
        with patch_db(conn):
            resp = (_authed_client() if viewer else client()).get(url)
        return resp, conn

    def test_feed_reports_like_count_and_liked_by_me_for_the_viewer(self):
        resp, conn = self._get(
            "/api/articles",
            posts=[_post_row(id=2, tag_name="react"), _post_row(id=2, tag_name="flask"), _post_row(id=1)],
            likes=[_counts_row(2, 3, 1)],
            viewer=VIEWER,
        )

        posts = {post["id"]: post for post in resp.get_json()}
        self.assertEqual((posts[2]["like_count"], posts[2]["liked_by_me"]), (3, True))
        self.assertEqual((posts[1]["like_count"], posts[1]["liked_by_me"]), (0, False))
        # One query for the whole page: the viewer's id, then each post id once.
        self.assertEqual(conn.params_for(COUNTS_QUERY), (42, 2, 1))
        self.assertEqual(len(conn.find(COUNTS_QUERY)), 1)

    def test_a_logged_out_visitor_sees_counts_but_never_liked_by_me(self):
        resp, conn = self._get("/api/articles", posts=[_post_row(id=2)], likes=[_counts_row(2, 5, 0)])

        post = resp.get_json()[0]
        self.assertEqual((post["like_count"], post["liked_by_me"]), (5, False))
        self.assertEqual(conn.params_for(COUNTS_QUERY), (None, 2))

    def test_every_feed_mode_reports_likes(self):
        for url in ("/api/articles?username=bob", "/api/articles?tag=react", "/api/articles?feed=following"):
            with self.subTest(url=url):
                resp, conn = self._get(url, posts=[_post_row(id=9)],
                                       likes=[_counts_row(9, 1, 1)], viewer=VIEWER)

                self.assertEqual(resp.status_code, 200)
                post = resp.get_json()[0]
                self.assertEqual((post["like_count"], post["liked_by_me"]), (1, True))
                self.assertEqual(conn.params_for(COUNTS_QUERY), (42, 9))

    def test_an_empty_page_skips_the_counts_query(self):
        # "p.id IN ()" is invalid SQL.
        resp, conn = self._get("/api/articles?username=nobody", posts=[], likes=[])

        self.assertEqual(resp.get_json(), [])
        self.assertFalse(conn.ran(COUNTS_QUERY))

    def test_single_article_reports_likes(self):
        row = _post_row(id=5, body_html="<p>hi</p>", body=None, devto_id=None)
        resp, conn = self._get("/api/articles/5", posts=[row],
                               likes=[_counts_row(5, 2, 0)], viewer=VIEWER)

        post = resp.get_json()
        self.assertEqual((post["like_count"], post["liked_by_me"]), (2, False))
        self.assertEqual(conn.params_for(COUNTS_QUERY), (42, 5))

    def test_mock_fallback_posts_carry_the_like_fields(self):
        with db_down():
            for url in ("/api/articles", "/api/articles/1"):
                with self.subTest(url=url):
                    body = client().get(url).get_json()
                    post = body[0] if isinstance(body, list) else body
                    self.assertEqual((post["like_count"], post["liked_by_me"]), (0, False))

    def test_a_new_post_starts_with_no_likes(self):
        conn = FakeConn(fetchone=[_session_user()], lastrowid=9)
        with patch_db(conn):
            resp = _authed_client().post(
                "/api/articles", json={"article": {"title": "T", "body_html": "<p>b</p>"}}
            )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual((resp.get_json()["like_count"], resp.get_json()["liked_by_me"]), (0, False))


if __name__ == "__main__":
    unittest.main()
