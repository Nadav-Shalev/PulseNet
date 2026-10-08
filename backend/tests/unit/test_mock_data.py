"""Unit tests for mock_data.py, the offline data the API serves when MySQL is down."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import mock_data  # noqa: E402

# A post whose author is not in MOCK_USERS (a broken reference).
ORPHAN_POST = dict(mock_data.MOCK_POSTS[0], id=99, author_id=404)


class MockArticlesTests(unittest.TestCase):
    def test_newest_first_in_devto_shape(self):
        posts = mock_data.mock_get_articles()

        self.assertEqual([p["id"] for p in posts], [4, 3, 2, 1])
        first = posts[0]
        self.assertEqual(first["user"]["username"], "alicedev")
        self.assertEqual(first["tag_list"], ["python", "flask", "api"])
        self.assertIn("url", first)
        self.assertNotIn("author_id", first)
        # Same like and comment fields as the DB feed, so the UI needs no special case.
        self.assertEqual((first["like_count"], first["liked_by_me"]), (0, False))
        self.assertEqual(first["comment_count"], 0)

    def test_tag_list_is_a_copy(self):
        mock_data.mock_get_articles()[0]["tag_list"].append("mutated")

        self.assertNotIn("mutated", mock_data.MOCK_POSTS[3]["tags"])

    def test_filters_by_author(self):
        posts = mock_data.mock_get_articles(username="bobcoder")

        self.assertEqual([p["id"] for p in posts], [2])

    def test_unknown_author_has_no_posts(self):
        self.assertEqual(mock_data.mock_get_articles(username="nobody"), [])

    def test_pages(self):
        self.assertEqual([p["id"] for p in mock_data.mock_get_articles(page=2, per_page=3)], [1])
        self.assertEqual(mock_data.mock_get_articles(page=3, per_page=3), [])

    def test_posts_with_unknown_author_are_dropped(self):
        with patch.object(mock_data, "MOCK_POSTS", mock_data.MOCK_POSTS + [ORPHAN_POST]):
            posts = mock_data.mock_get_articles()

        self.assertNotIn(99, [p["id"] for p in posts])


class MockArticleByIdTests(unittest.TestCase):
    def test_returns_post_with_body_as_html(self):
        post = mock_data.mock_get_article_by_id(2)

        self.assertEqual(post["title"], "MySQL vs PostgreSQL: Which Should You Choose?")
        self.assertEqual(post["body_html"], f"<p>{mock_data.MOCK_POSTS[1]['body']}</p>")

    def test_unknown_id_is_none(self):
        self.assertIsNone(mock_data.mock_get_article_by_id(999))

    def test_post_with_unknown_author_is_none(self):
        with patch.object(mock_data, "MOCK_POSTS", [ORPHAN_POST]):
            self.assertIsNone(mock_data.mock_get_article_by_id(99))


class MockSearchUsersTests(unittest.TestCase):
    def _usernames(self, *args, **kwargs):
        return [u["username"] for u in mock_data.mock_search_users(*args, **kwargs)]

    def test_matches_name_or_username_case_insensitively(self):
        self.assertEqual(self._usernames("CAROL"), ["carolscript"])       # name / username
        self.assertEqual(self._usernames("Bob Coder"), ["bobcoder"])      # name only

    def test_email_is_not_searched(self):
        # Emails are private; matching on one would reveal whose address it is.
        self.assertEqual(self._usernames("alicedev@"), [])
        self.assertEqual(self._usernames("dev.to"), [])

    def test_result_has_search_fields_only(self):
        user = mock_data.mock_search_users("alice")[0]

        self.assertEqual(set(user), {"id", "name", "username", "avatar"})

    def test_limit_and_offset(self):
        # "c" is in every mock username (alicedev, bobcoder, carolscript).
        self.assertEqual(self._usernames("c", limit=2), ["alicedev", "bobcoder"])
        self.assertEqual(self._usernames("c", limit=2, offset=2), ["carolscript"])

    def test_no_match_is_empty(self):
        self.assertEqual(mock_data.mock_search_users("zzz"), [])


if __name__ == "__main__":
    unittest.main()
