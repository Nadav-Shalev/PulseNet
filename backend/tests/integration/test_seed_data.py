"""seed_data.py tests: DEV.to import script, with HTTP and the DB both faked.

``requests.get`` is mocked so no network is touched, ``time.sleep`` is mocked so the
polite pause between pages costs nothing, and the DB is a ``FakeConn``. The helpers
are checked one by one, then ``seed()`` end to end: dedup of users and posts,
skipping of authorless articles and empty tags, and surviving a failed page.
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import requests

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import seed_data  # noqa: E402
from support import FakeConn  # noqa: E402


def _article(**over):
    """One item of DEV.to's GET /api/articles list."""
    item = {
        "id": 1001, "title": "Hello DEV", "description": "short",
        "cover_image": "https://img/c.png", "url": "https://dev.to/ada/hello",
        "readable_publish_date": "Oct 7", "tag_list": ["react"],
        "user": {"username": "ada", "name": "Ada", "profile_image": "https://img/ada.png"},
    }
    item.update(over)
    return item


def _devto_reply(articles):
    reply = Mock()
    reply.json.return_value = articles
    return reply


class FetchArticlesPageTests(unittest.TestCase):
    def test_requests_one_page_and_returns_its_json(self):
        with patch.object(seed_data.requests, "get", return_value=_devto_reply([_article()])) as get:
            articles = seed_data.fetch_articles_page(3)

        self.assertEqual(articles, [_article()])
        get.assert_called_once_with(
            f"{seed_data.DEVTO_BASE}/articles",
            params={"page": 3, "per_page": seed_data.PER_PAGE},
            timeout=15,
        )
        get.return_value.raise_for_status.assert_called_once_with()

    def test_http_error_propagates(self):
        reply = _devto_reply([])
        reply.raise_for_status.side_effect = requests.HTTPError("503")
        with patch.object(seed_data.requests, "get", return_value=reply):
            with self.assertRaises(requests.HTTPError):
                seed_data.fetch_articles_page(1)


class EnsureUserTests(unittest.TestCase):
    def test_existing_username_returns_its_id_without_insert(self):
        conn = FakeConn(fetchone=[(5,)])

        user_id = seed_data.ensure_user(conn.cursor(), {"username": "ada"})

        self.assertEqual(user_id, 5)
        self.assertFalse(conn.ran("insert into users"))

    def test_new_user_is_inserted_with_devto_fields(self):
        conn = FakeConn(lastrowid=9)

        user_id = seed_data.ensure_user(conn.cursor(), {
            "username": "ada", "name": "Ada", "profile_image": "https://img/ada.png",
        })

        self.assertEqual(user_id, 9)
        self.assertEqual(
            conn.params_for("insert into users"),
            ("Ada", "ada", "ada@dev.to", "", "https://img/ada.png", "https://img/ada.png"),
        )

    def test_missing_name_and_image_fall_back(self):
        conn = FakeConn()

        seed_data.ensure_user(conn.cursor(), {"username": "ghost", "name": None})

        name, _, email, _, avatar, image = conn.params_for("insert into users")
        self.assertEqual(name, "ghost")
        self.assertEqual(email, "ghost@dev.to")
        self.assertEqual(avatar, f"{seed_data.DICEBEAR_URL}?seed=ghost")
        self.assertEqual(image, avatar)


class EnsureTagTests(unittest.TestCase):
    def test_inserts_if_missing_then_returns_id_keeping_case(self):
        conn = FakeConn(fetchone=[(11,)])

        tag_id = seed_data.ensure_tag(conn.cursor(), "  React ")

        self.assertEqual(tag_id, 11)
        # Trimmed but not lowercased: tags.name is case-sensitive (utf8mb4_bin).
        self.assertEqual(conn.params_for("insert ignore into tags"), ("React",))
        self.assertEqual(conn.params_for("select id from tags"), ("React",))


class InsertPostTests(unittest.TestCase):
    def test_duplicate_devto_id_is_skipped(self):
        conn = FakeConn(fetchone=[(77,)])

        post_id = seed_data.insert_post(conn.cursor(), _article(), author_id=5)

        self.assertIsNone(post_id)
        self.assertEqual(conn.params_for("select id from posts where devto_id"), (1001,))
        self.assertFalse(conn.ran("insert into posts"))

    def test_new_post_is_inserted(self):
        conn = FakeConn(lastrowid=31)

        post_id = seed_data.insert_post(conn.cursor(), _article(), author_id=5)

        self.assertEqual(post_id, 31)
        self.assertEqual(
            conn.params_for("insert into posts"),
            (5, "Hello DEV", "short", "short", "https://img/c.png",
             1001, "https://dev.to/ada/hello", "Oct 7"),
        )

    def test_long_title_is_truncated_and_blank_fields_become_null(self):
        conn = FakeConn()

        seed_data.insert_post(conn.cursor(), _article(
            title="t" * 200, description=None, cover_image="", url=None,
            readable_publish_date="",
        ), author_id=5)

        params = conn.params_for("insert into posts")
        self.assertEqual(len(params[1]), 150)            # posts.title is VARCHAR(150)
        self.assertEqual(params[2:5], ("", "", None))     # body, description, cover_image
        self.assertEqual(params[6:], (None, None))        # devto_url, readable_publish_date


class SeedTests(unittest.TestCase):
    def _seed(self, conn, pages, pages_to_fetch=None):
        """Run seed() against ``conn`` with DEV.to serving ``pages`` (lists or exceptions)."""
        replies = [p if isinstance(p, Exception) else _devto_reply(p) for p in pages]
        out = io.StringIO()
        with patch.object(seed_data, "get_db_connection", return_value=conn), \
             patch.object(seed_data, "PAGES_TO_FETCH", pages_to_fetch or len(pages)), \
             patch.object(seed_data.requests, "get", side_effect=replies), \
             patch.object(seed_data.time, "sleep") as sleep, \
             redirect_stdout(out):
            seed_data.seed()
        return out.getvalue(), sleep

    def test_new_author_post_and_tags_are_inserted(self):
        conn = FakeConn(
            # user_existed check, ensure_user lookup, duplicate-post check, tag ids
            fetchone=[None, None, None, (11,), (12,)],
            lastrowid=31,
        )

        out, sleep = self._seed(conn, [[_article(tag_list=["react", "", "flask"])]])

        self.assertTrue(conn.ran("insert into users"))
        self.assertTrue(conn.ran("insert into posts"))
        links = [params for _, params in conn.find("insert ignore into posts_tags")]
        self.assertEqual(links, [(31, 11), (31, 12)])     # the empty tag is skipped
        self.assertEqual(conn.commits, 1)                 # one commit per page
        self.assertTrue(conn.closed)
        sleep.assert_called_once()
        self.assertIn("Users inserted : 1", out)
        self.assertIn("Posts inserted : 1", out)
        self.assertIn("Tag links added: 2", out)

    def test_existing_author_is_reused(self):
        conn = FakeConn(fetchone=[(5,), (5,), None, (11,)], lastrowid=31)

        out, _ = self._seed(conn, [[_article()]])

        self.assertFalse(conn.ran("insert into users"))
        self.assertEqual(conn.params_for("insert into posts")[0], 5)    # author_id
        self.assertIn("Users inserted : 0", out)

    def test_already_imported_post_adds_no_tags(self):
        conn = FakeConn(fetchone=[(5,), (5,), (77,)])

        out, _ = self._seed(conn, [[_article()]])

        self.assertFalse(conn.ran("insert into posts"))
        self.assertFalse(conn.ran("into tags"))
        self.assertIn("Posts inserted : 0", out)

    def test_articles_without_author_username_are_skipped(self):
        conn = FakeConn()

        out, _ = self._seed(conn, [[_article(user=None), _article(user={"name": "anon"})]])

        self.assertEqual(conn.executed, [])
        self.assertEqual(conn.commits, 1)
        self.assertIn("done (2 articles)", out)

    def test_failed_page_is_reported_and_the_next_page_still_runs(self):
        conn = FakeConn(fetchone=[None, None, None, (11,)])

        out, sleep = self._seed(conn, [requests.ConnectionError("offline"), [_article()]])

        self.assertIn("FAILED (offline)", out)
        self.assertIn("Posts inserted : 1", out)
        self.assertEqual(conn.commits, 1)                 # only the page that loaded
        sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
