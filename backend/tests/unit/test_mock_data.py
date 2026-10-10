"""Offline mocks retain the public article/search contracts."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import mock_data
from demo_content import build_posts

NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


class MockDataTests(unittest.TestCase):
    def setUp(self):
        ids = {u["username"]: u["id"] for u in mock_data.MOCK_USERS}
        self.posts = [dict(p, author_id=ids[p["username"]]) for p in build_posts(NOW)]
        self.patch = patch.object(mock_data, "MOCK_POSTS", self.posts)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_newest_first_in_current_article_shape(self):
        posts = mock_data.mock_get_articles()
        self.assertEqual([p["id"] for p in posts], list(range(1, 31, 3)))
        first = posts[0]
        self.assertEqual(first["user"]["username"], "priya_ai")
        self.assertEqual(first["tag_list"], ["python", "testing", "cleancode"])
        self.assertEqual(first["created_at"], "2026-01-01T11:45:00+00:00")
        self.assertEqual(set(first), {
            "id", "title", "description", "cover_image", "created_at",
            "readable_publish_date", "url", "tag_list", "like_count",
            "liked_by_me", "comment_count", "user"})
        self.assertIsNone(first["url"])
        self.assertEqual((first["like_count"], first["liked_by_me"], first["comment_count"]), (0, False, 0))
        self.assertEqual(set(first["user"]), {"username", "name", "profile_image"})

    def test_sort_uses_timestamp_across_year_boundary_and_id_for_ties(self):
        newer = dict(self.posts[0], id=32)
        with patch.object(mock_data, "MOCK_POSTS", list(reversed(self.posts)) + [newer]):
            posts = mock_data.mock_get_articles(per_page=40)
        self.assertEqual([p["id"] for p in posts[:2]], [32, 1])
        times = [datetime.fromisoformat(p["created_at"]) for p in posts]
        self.assertEqual(times, sorted(times, reverse=True))
        self.assertEqual(times[-1].year, 2025)

    def test_results_do_not_mutate_the_fixtures(self):
        first = mock_data.mock_get_articles()[0]
        first["tag_list"].append("mutated")
        first["user"]["name"] = "changed"
        self.assertNotIn("mutated", self.posts[0]["tags"])
        self.assertEqual(mock_data.mock_get_articles()[0]["user"]["name"], "Priya Raman")

    def test_author_filter_and_pagination(self):
        self.assertEqual([p["id"] for p in mock_data.mock_get_articles(username="dana_ai")], [10, 11, 12])
        self.assertEqual(mock_data.mock_get_articles(username="nobody"), [])
        all_posts = mock_data.mock_get_articles(per_page=30)
        pages = [mock_data.mock_get_articles(page=p, per_page=10) for p in (1, 2, 3)]
        self.assertEqual(sum(pages, []), all_posts)
        self.assertEqual(mock_data.mock_get_articles(page=4), [])

    def test_detail_matches_feed_and_unknown_ids_are_absent(self):
        detail = mock_data.mock_get_article_by_id(1)
        self.assertEqual(detail.pop("body_html"), self.posts[0]["body_html"])
        self.assertEqual(detail, mock_data.mock_get_articles()[0])
        self.assertIsNone(mock_data.mock_get_article_by_id(999))

    def test_orphan_posts_are_skipped_in_list_and_detail(self):
        orphan = dict(self.posts[0], id=99, author_id=404)
        with patch.object(mock_data, "MOCK_POSTS", [orphan]):
            self.assertEqual(mock_data.mock_get_articles(), [])
            self.assertIsNone(mock_data.mock_get_article_by_id(99))

    def test_search_matches_name_or_username_and_paginates(self):
        self.assertEqual([u["username"] for u in mock_data.mock_search_users("PRIYA")], ["priya_ai"])
        self.assertEqual([u["username"] for u in mock_data.mock_search_users("Leo Marchetti")], ["leo_ai"])
        self.assertEqual([u["username"] for u in mock_data.mock_search_users("_ai", limit=2, offset=2)],
                         ["sam_ai", "dana_ai"])
        self.assertEqual(mock_data.mock_search_users("zzz"), [])

    def test_search_neither_exposes_nor_matches_private_fields(self):
        user = mock_data.mock_search_users("priya")[0]
        self.assertEqual(set(user), {"id", "name", "username", "avatar"})
        self.assertEqual(mock_data.mock_search_users("priya_ai@"), [])
        self.assertEqual(mock_data.mock_search_users("agents.pulsenet.invalid"), [])


if __name__ == "__main__":
    unittest.main()
