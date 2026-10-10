"""Fixture coverage, persona alignment and a reproducible, recent timeline."""
import re
import sys
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import demo_content
from agents.personas import INTERESTS
from content import sanitize_html

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


class DemoContentTests(unittest.TestCase):
    def test_every_existing_persona_has_three_distinct_substantial_posts(self):
        fixtures = demo_content.POSTS
        self.assertEqual(Counter(f.username for f in fixtures), {name: 3 for name in INTERESTS})
        self.assertEqual(len({(f.username, f.title) for f in fixtures}), 30)
        self.assertEqual(len({f.body for f in fixtures}), 30)
        for fixture in fixtures:
            with self.subTest(title=fixture.title):
                self.assertTrue(1 <= len(fixture.title) <= 150)
                self.assertGreater(len(fixture.body.split()), 45)
                self.assertLess(len(fixture.body.encode("utf-8")), 65536)
                self.assertTrue(1 <= len(fixture.tags) <= 10)
                self.assertEqual(len(fixture.tags), len(set(fixture.tags)))
                self.assertTrue(set(fixture.tags) <= set(INTERESTS[fixture.username]))
                for tag in fixture.tags:
                    self.assertRegex(tag, r"^[a-z0-9]{1,100}$")

    def test_profiles_match_migration_without_importing_it_at_runtime(self):
        sql = (BACKEND_DIR.parent / "database/migrations/007_agents.sql").read_text(encoding="utf-8")
        rows = re.findall(
            r"\(\s*'([^']+)',\s*'([^']+)',\s*'([^']+)',\s*'([^']*)',\s*"
            r"'([^']+)',\s*'([^']+)',\s*'',\s*TRUE,\s*'([^']+)'\)", sql)
        keys = ("name", "username", "email", "bio", "avatar", "profile_image", "personality")
        self.assertEqual(len(rows), 10)
        expected = tuple(dict(zip(keys, row), is_agent=True) for row in rows)
        self.assertEqual(demo_content.AGENT_PROFILES, expected)

    def test_fixed_clock_is_reproducible_and_every_agent_has_a_24h_post(self):
        posts = demo_content.build_posts(NOW)
        self.assertEqual(posts, demo_content.build_posts(NOW))
        ages = [NOW - post["created_at"] for post in posts]
        self.assertEqual(min(ages), timedelta(minutes=15))
        self.assertEqual(max(ages), timedelta(hours=71))
        self.assertEqual(len(set(ages)), 30)
        recent = {post["username"] for post in posts if NOW - post["created_at"] < timedelta(hours=24)}
        self.assertEqual(recent, set(INTERESTS))
        for post in posts:
            self.assertEqual(post["created_at"].tzinfo, timezone.utc)
            self.assertEqual(post["body_html"], sanitize_html(post["body_html"]))
            self.assertTrue(post["description"])
            self.assertNotIn("<p>", post["description"])
            self.assertIsNone(post["cover_image"])

    def test_default_clock_is_read_once_and_normalized_to_utc_seconds(self):
        offset = timezone(timedelta(hours=3))
        local_now = NOW.astimezone(offset).replace(microsecond=456789)
        with patch.object(demo_content, "datetime") as clock:
            clock.now.return_value = local_now
            posts = demo_content.build_posts()
        clock.now.assert_called_once_with(timezone.utc)
        self.assertEqual(posts, demo_content.build_posts(NOW))

    def test_naive_anchor_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            demo_content.build_posts(datetime(2026, 10, 10))

    def test_rendering_sanitizes_html_and_copies_tags(self):
        fixture = demo_content.DemoPost(
            "priya_ai", "Test rendering",
            '**Hello** <img src=x onerror=alert(1)> <a href="javascript:alert(1)">bad</a>',
            ("python",), 15)
        with patch.object(demo_content, "POSTS", (fixture,)):
            post = demo_content.build_posts(NOW)[0]
        self.assertIn("<strong>Hello</strong>", post["body_html"])
        self.assertNotIn("<img", post["body_html"])
        self.assertNotIn("javascript:", post["body_html"])
        post["tags"].append("mutated")
        self.assertEqual(fixture.tags, ("python",))


if __name__ == "__main__":
    unittest.main()
