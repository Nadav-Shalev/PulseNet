"""Comments API tests (Flask test client + mocked DB seam).

GET  /api/articles/<id>/comments   the post's comments as a tree, oldest first
POST /api/articles/<id>/comments   comment (or reply, one level deep) as the session user
DELETE /api/comments/<id>          only by its writer; its replies go with it

The writer always comes from the session. body_html is sanitized on the way in and
on the way out, and a comment never carries an email. Every feed reports
comment_count (with the like fields, in one counts query per page).
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

import app  # noqa: E402
from support import FakeConn, client, db_down, patch_db  # noqa: E402

COUNTS_QUERY = "from posts p where p.id in"
INSERT_COMMENT = "insert into comments"


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


def _comment_row(**over):
    """One comments row joined with its author, as the comment queries read it."""
    row = {
        "id": 1, "post_id": 7, "parent_id": None, "body_html": "<p>hi</p>",
        "created_at": datetime(2026, 10, 8, 9, 30, 0),
        "username": "bob", "name": "Bob", "avatar": None, "profile_image": "b.svg",
    }
    row.update(over)
    return row


def _count(n):
    return {"comment_count": n}


class GetCommentsTests(unittest.TestCase):
    def _get(self, rows, post=True):
        conn = FakeConn(fetchone=[{"id": 7}] if post else [], fetchall=[rows])
        with patch_db(conn):
            resp = client().get("/api/articles/7/comments")
        return resp, conn

    def test_comments_come_back_as_a_tree_oldest_first(self):
        resp, conn = self._get([
            _comment_row(id=1),
            _comment_row(id=2, username="cy"),
            _comment_row(id=3, parent_id=1, username="ada"),
            _comment_row(id=4, parent_id=1),
        ])

        self.assertEqual(resp.status_code, 200)
        tree = resp.get_json()
        self.assertEqual([c["id"] for c in tree], [1, 2])
        self.assertEqual([r["id"] for r in tree[0]["replies"]], [3, 4])
        self.assertEqual(tree[1]["replies"], [])
        self.assertEqual(tree[0]["replies"][0]["parent_id"], 1)
        self.assertNotIn("replies", tree[0]["replies"][0])    # replies have no replies
        sql, params = conn.find("from comments c join users u")[0]
        self.assertEqual(params, (7,))
        self.assertIn("order by c.created_at, c.id", " ".join(sql.split()).lower())

    def test_a_comment_has_its_author_and_time_but_no_email(self):
        resp, _conn = self._get([_comment_row(id=5, email="bob@example.com")])

        comment = resp.get_json()[0]
        self.assertEqual(comment["user"], {"username": "bob", "name": "Bob", "profile_image": "b.svg"})
        self.assertEqual(comment["created_at"], "2026-10-08T09:30:00+00:00")
        self.assertEqual(comment["post_id"], 7)
        self.assertNotIn("email", str(resp.get_json()))

    def test_stored_html_is_sanitized_again_on_the_way_out(self):
        resp, _conn = self._get([_comment_row(body_html='<p>ok</p><script>alert(1)</script>')])

        self.assertEqual(resp.get_json()[0]["body_html"], "<p>ok</p>alert(1)")

    def test_a_post_without_comments_is_an_empty_list(self):
        resp, _conn = self._get([])

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), [])

    def test_unknown_post_returns_404(self):
        resp, conn = self._get([], post=False)

        self.assertEqual(resp.status_code, 404)
        self.assertFalse(conn.ran("from comments"))

    def test_db_down_is_a_503_not_an_empty_thread(self):
        # [] would say the post has no comments; an outage is a different answer.
        with db_down():
            resp = client().get("/api/articles/7/comments")

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.get_json()["error"], "Database unavailable")


class CreateCommentTests(unittest.TestCase):
    def _post(self, body, fetchone=None, lastrowid=9):
        conn = FakeConn(fetchone=[_session_user()] + (fetchone or []), lastrowid=lastrowid)
        with patch_db(conn):
            resp = _authed_client().post("/api/articles/7/comments", json=body)
        return resp, conn

    def test_requires_a_session(self):
        conn = FakeConn()
        with patch_db(conn):
            resp = client().post("/api/articles/7/comments", json={"body_html": "<p>hi</p>"})

        self.assertEqual(resp.status_code, 401)
        self.assertFalse(conn.ran("comments"))

    def test_db_unavailable_returns_503(self):
        conn = FakeConn(fetchone=[_session_user()])
        with patch_db(conn, db_available=False):
            resp = _authed_client().post("/api/articles/7/comments", json={"body_html": "<p>hi</p>"})

        self.assertEqual(resp.status_code, 503)
        self.assertFalse(conn.ran(INSERT_COMMENT))

    def test_comment_is_stored_for_the_session_user_and_returned(self):
        stored = _comment_row(id=9, username="ada", name="Ada", profile_image="p.svg")
        resp, conn = self._post(
            {"body_html": "<p>Nice post</p>", "user_id": 99, "author_id": 99},
            fetchone=[{"id": 7}, stored, _count(3)],
        )

        self.assertEqual(resp.status_code, 201)
        # (post_id, author_id, parent_id, body_html): the author is the session user.
        self.assertEqual(conn.params_for(INSERT_COMMENT), (7, 42, None, "<p>Nice post</p>"))
        body = resp.get_json()
        self.assertEqual(body["comment_count"], 3)
        self.assertEqual(body["comment"]["id"], 9)
        self.assertEqual(body["comment"]["replies"], [])
        self.assertEqual(body["comment"]["user"]["username"], "ada")
        self.assertNotIn("email", str(body))
        self.assertEqual(conn.params_for("where c.id = %s"), (9,))
        self.assertEqual(conn.params_for("select count(*) as comment_count"), (7,))
        # One commit from require_session's expired-session cleanup, one for the comment.
        self.assertEqual(conn.commits, 2)
        self.assertTrue(conn.closed)

    def test_html_is_sanitized_before_it_is_stored(self):
        dirty = ('<p>hi</p><script>alert(1)</script><img src=x onerror="alert(2)">'
                 '<a href="javascript:alert(3)">x</a>')
        _resp, conn = self._post({"body_html": dirty}, fetchone=[{"id": 7}, _comment_row(id=9), _count(1)])

        stored = conn.params_for(INSERT_COMMENT)[3]
        self.assertEqual(stored, "<p>hi</p>alert(1)<a>x</a>")

    def test_a_reply_to_a_top_level_comment_on_the_same_post(self):
        parent = {"post_id": 7, "parent_id": None}
        reply = _comment_row(id=10, parent_id=4)
        resp, conn = self._post({"body_html": "<p>agreed</p>", "parent_id": 4},
                                fetchone=[{"id": 7}, parent, reply, _count(2)])

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(conn.params_for("select post_id, parent_id from comments"), (4,))
        self.assertEqual(conn.params_for(INSERT_COMMENT), (7, 42, 4, "<p>agreed</p>"))
        self.assertEqual(resp.get_json()["comment"]["parent_id"], 4)
        self.assertNotIn("replies", resp.get_json()["comment"])

    def test_a_reply_to_a_reply_is_refused(self):
        # Replies are one level deep; the database cannot enforce that, the API does.
        resp, conn = self._post({"body_html": "<p>deeper</p>", "parent_id": 10},
                                fetchone=[{"id": 7}, {"post_id": 7, "parent_id": 4}])

        self.assertEqual(resp.status_code, 400)
        self.assertIn("one level", resp.get_json()["error"])
        self.assertFalse(conn.ran(INSERT_COMMENT))

    def test_a_parent_that_is_missing_or_on_another_post_is_refused(self):
        for parent in (None, {"post_id": 8, "parent_id": None}):
            with self.subTest(parent=parent):
                resp, conn = self._post({"body_html": "<p>x</p>", "parent_id": 4},
                                        fetchone=[{"id": 7}, parent])

                self.assertEqual(resp.status_code, 400)
                self.assertIn("parent_id", resp.get_json()["error"])
                self.assertFalse(conn.ran(INSERT_COMMENT))

    def test_parent_id_must_be_a_comment_id(self):
        # True is an int in Python: it must not be read as comment 1.
        for value in (True, "4", 4.0, [4], {"id": 4}):
            with self.subTest(value=value):
                resp, conn = self._post({"body_html": "<p>x</p>", "parent_id": value})

                self.assertEqual(resp.status_code, 400)
                self.assertFalse(conn.ran("comments"))

    def test_unknown_post_returns_404_before_the_insert(self):
        # A plain INSERT would fail on the foreign key (1452) as a 500.
        resp, conn = self._post({"body_html": "<p>x</p>"}, fetchone=[None])

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(conn.params_for("select id from posts where id = %s"), (7,))
        self.assertFalse(conn.ran(INSERT_COMMENT))

    def test_empty_comments_are_refused(self):
        for body in ({}, {"body_html": ""}, {"body_html": "   "}, {"body_html": "<p> </p>"},
                     {"body_html": "<p>&nbsp;</p><br>"}, {"body_html": "<img src=x>"}):
            with self.subTest(body=body):
                resp, conn = self._post(body)

                self.assertEqual(resp.status_code, 400)
                self.assertEqual(resp.get_json()["error"], "Comment cannot be empty")
                self.assertFalse(conn.ran("comments"))

    def test_body_html_must_be_a_string(self):
        resp, conn = self._post({"body_html": 123})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "body_html must be a string")
        self.assertFalse(conn.ran("comments"))

    def test_the_body_must_be_a_json_object(self):
        resp, _conn = self._post(["<p>x</p>"])

        self.assertEqual(resp.status_code, 400)

    def test_text_longer_than_the_limit_is_refused(self):
        limit = app.MAX_COMMENT_CHARS
        ok, _conn = self._post({"body_html": "a" * limit},
                               fetchone=[{"id": 7}, _comment_row(id=9), _count(1)])
        too_long, conn = self._post({"body_html": "a" * (limit + 1)})

        self.assertEqual(ok.status_code, 201)
        self.assertEqual(too_long.status_code, 400)
        self.assertIn(str(limit), too_long.get_json()["error"])
        self.assertFalse(conn.ran("comments"))

    def test_the_limit_counts_visible_text_not_markup(self):
        # Escaping and tags make the HTML longer than what the reader sees.
        html = "<p>" + "&lt;" * app.MAX_COMMENT_CHARS + "</p>"
        resp, _conn = self._post({"body_html": html},
                                 fetchone=[{"id": 7}, _comment_row(id=9), _count(1)])

        self.assertEqual(resp.status_code, 201)

    def test_oversized_raw_html_is_refused_before_sanitizing(self):
        html = "<b></b>" * (app.MAX_COMMENT_HTML // 7 + 1) + "x"
        resp, conn = self._post({"body_html": html})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "Comment is too long")
        self.assertFalse(conn.ran("comments"))


class DeleteCommentTests(unittest.TestCase):
    def _delete(self, fetchone, db_available=True):
        conn = FakeConn(fetchone=[_session_user()] + fetchone)
        with patch_db(conn, db_available=db_available):
            resp = _authed_client().delete("/api/comments/5")
        return resp, conn

    def test_requires_a_session(self):
        conn = FakeConn()
        with patch_db(conn):
            resp = client().delete("/api/comments/5")

        self.assertEqual(resp.status_code, 401)
        self.assertFalse(conn.ran("comments"))

    def test_db_unavailable_returns_503(self):
        resp, conn = self._delete([], db_available=False)

        self.assertEqual(resp.status_code, 503)
        self.assertFalse(conn.ran("delete from comments"))

    def test_unknown_comment_returns_404(self):
        resp, conn = self._delete([None])

        self.assertEqual(resp.status_code, 404)
        self.assertFalse(conn.ran("delete from comments"))

    def test_only_the_writer_may_delete(self):
        resp, conn = self._delete([{"author_id": 77, "post_id": 7}])

        self.assertEqual(resp.status_code, 403)
        self.assertFalse(conn.ran("delete from comments"))

    def test_the_writer_deletes_it_and_gets_the_fresh_count(self):
        resp, conn = self._delete([{"author_id": 42, "post_id": 7}, _count(1)])

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"deleted": True, "id": 5, "comment_count": 1})
        self.assertEqual(conn.params_for("select author_id, post_id from comments"), (5,))
        # Its replies go by ON DELETE CASCADE, so one DELETE is enough.
        self.assertEqual(conn.find("delete from comments"),
                         [("DELETE FROM comments WHERE id = %s", (5,))])
        self.assertEqual(conn.params_for("select count(*) as comment_count"), (7,))
        self.assertEqual(conn.commits, 2)


class FeedCommentCountTests(unittest.TestCase):
    def _counts_row(self, post_id, comment_count):
        return {"post_id": post_id, "like_count": 0, "liked_by_me": 0, "comment_count": comment_count}

    def test_every_feed_mode_and_a_single_post_report_comment_count(self):
        post_row = {
            "id": 9, "title": "T", "description": "", "cover_image": None, "devto_url": None,
            "readable_publish_date": "Oct 8", "created_at": None, "username": "bob",
            "name": "Bob", "avatar": None, "profile_image": None, "tag_name": None,
            "body_html": "<p>b</p>", "body": None, "devto_id": None,
        }
        for url in ("/api/articles", "/api/articles?username=bob", "/api/articles?tag=react",
                    "/api/articles?feed=following", "/api/articles/9"):
            with self.subTest(url=url):
                conn = FakeConn(fetchone=[{"id": 42, "username": "ada"}],
                                fetchall=[[post_row], [self._counts_row(9, 4)]])
                with patch_db(conn):
                    body = _authed_client().get(url).get_json()

                post = body[0] if isinstance(body, list) else body
                self.assertEqual(post["comment_count"], 4)
                # Likes and comments are counted in the same single query.
                self.assertEqual(len(conn.find(COUNTS_QUERY)), 1)
                self.assertTrue(conn.ran("from comments c where c.post_id = p.id"))

    def test_a_post_missing_from_the_counts_keeps_zero(self):
        conn = FakeConn(fetchall=[[{"id": 3, "title": "T", "tag_name": None}], []])
        with patch_db(conn):
            post = client().get("/api/articles").get_json()[0]

        self.assertEqual(post["comment_count"], 0)

    def test_a_new_post_and_the_mock_feed_start_with_no_comments(self):
        conn = FakeConn(fetchone=[_session_user()], lastrowid=9)
        with patch_db(conn):
            created = _authed_client().post(
                "/api/articles", json={"article": {"title": "T", "body_html": "<p>b</p>"}}
            )
        self.assertEqual(created.get_json()["comment_count"], 0)

        with db_down():
            for url in ("/api/articles", "/api/articles/1"):
                with self.subTest(url=url):
                    body = client().get(url).get_json()
                    post = body[0] if isinstance(body, list) else body
                    self.assertEqual(post["comment_count"], 0)


if __name__ == "__main__":
    unittest.main()
