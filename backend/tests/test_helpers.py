"""Unit tests for pure helper functions in app.py (no DB, no mocks)."""

import sys
import unittest
from datetime import datetime
from pathlib import Path

# sys.path bootstrap (mirrors the other test files so this runs standalone too).
HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import app  # noqa: E402


class UserShapeTests(unittest.TestCase):
    def test_user_shape_never_leaks_password_hash(self):
        row = {
            "id": 7, "name": "Ada", "username": "ada", "email": "ada@x.com",
            "bio": "hi", "avatar": "a.svg", "profile_image": "p.svg",
            "password_hash": "$2b$super-secret-hash",
        }
        shaped = app._user_shape(row)

        self.assertNotIn("password_hash", shaped)
        self.assertEqual(shaped["id"], 7)
        self.assertEqual(shaped["username"], "ada")
        self.assertEqual(shaped["email"], "ada@x.com")

    def test_user_shape_tolerates_missing_optional_fields(self):
        # name/bio/avatar/profile_image are looked up with .get() and may be absent.
        shaped = app._user_shape({"id": 1, "username": "u", "email": "u@x.com"})

        self.assertIsNone(shaped["name"])
        self.assertIsNone(shaped["bio"])


class HtmlToTextTests(unittest.TestCase):
    def test_strips_tags(self):
        self.assertEqual(app.html_to_text("<p>Hello <b>world</b></p>"), "Hello world")

    def test_unescapes_entities(self):
        self.assertEqual(app.html_to_text("<p>a &amp; b</p>"), "a & b")

    def test_normalizes_nbsp_to_space(self):
        self.assertEqual(app.html_to_text("<p>Hello&nbsp;world</p>"), "Hello world")

    def test_empty_input(self):
        self.assertEqual(app.html_to_text(""), "")
        self.assertEqual(app.html_to_text(None), "")


class ToHtmlTests(unittest.TestCase):
    def test_plain_text_wrapped_in_paragraph(self):
        self.assertIn("<p>Hello</p>", app.to_html("Hello"))

    def test_markdown_bold_is_rendered(self):
        # markdown is installed, so the rich path is active.
        self.assertIn("<strong>bold</strong>", app.to_html("**bold**"))


class IsoTests(unittest.TestCase):
    def test_none_returns_none(self):
        self.assertIsNone(app._iso(None))

    def test_datetime_returns_isoformat(self):
        dt = datetime(2025, 5, 1, 10, 30, 0)
        self.assertEqual(app._iso(dt), "2025-05-01T10:30:00")

    def test_non_datetime_falls_back_to_str(self):
        self.assertEqual(app._iso("2025-05-01"), "2025-05-01")


class ShapePostRowTests(unittest.TestCase):
    def _row(self, **over):
        row = {
            "id": 11, "title": "T", "description": "desc",
            "cover_image": None, "devto_url": "http://d/x",
            "readable_publish_date": "May 1",
            "created_at": datetime(2025, 5, 1, 9, 0, 0),
            "username": "ada", "name": "Ada", "email": "ada@x.com",
            "avatar": "a.svg", "profile_image": "p.svg",
        }
        row.update(over)
        return row

    def test_shape_maps_core_fields(self):
        post = app._shape_post_row(self._row())

        self.assertEqual(post["id"], 11)
        self.assertEqual(post["title"], "T")
        self.assertEqual(post["url"], "http://d/x")
        self.assertEqual(post["tag_list"], [])
        self.assertEqual(post["created_at"], "2025-05-01T09:00:00")
        self.assertEqual(post["user"]["username"], "ada")

    def test_profile_image_falls_back_to_dicebear(self):
        post = app._shape_post_row(self._row(profile_image=None, avatar=None))

        self.assertIn("seed=ada", post["user"]["profile_image"])


class AggregateTagsTests(unittest.TestCase):
    def _row(self, pid, tag):
        return {
            "id": pid, "title": f"post{pid}", "description": "",
            "cover_image": None, "devto_url": None,
            "readable_publish_date": "May 1", "created_at": None,
            "username": "u", "name": "U", "email": "u@x.com",
            "avatar": None, "profile_image": None, "tag_name": tag,
        }

    def test_collapses_multiple_tag_rows_into_one_post(self):
        rows = [self._row(1, "react"), self._row(1, "python"), self._row(2, "go")]
        posts = app._aggregate_tags(rows)

        self.assertEqual(len(posts), 2)
        by_id = {p["id"]: p for p in posts}
        self.assertEqual(by_id[1]["tag_list"], ["react", "python"])
        self.assertEqual(by_id[2]["tag_list"], ["go"])

    def test_null_tag_name_yields_empty_tag_list(self):
        posts = app._aggregate_tags([self._row(1, None)])

        self.assertEqual(posts[0]["tag_list"], [])


class FileExtTests(unittest.TestCase):
    def test_file_ext_lowercases(self):
        self.assertEqual(app._file_ext("Photo.PNG"), "png")

    def test_file_ext_missing_dot(self):
        self.assertEqual(app._file_ext("noextension"), "")

    def test_ext_ok_for_allowed_and_disallowed(self):
        self.assertTrue(app._ext_ok("a.jpeg"))
        self.assertTrue(app._ext_ok("a.gif"))
        self.assertFalse(app._ext_ok("a.svg"))
        self.assertFalse(app._ext_ok("a.txt"))


if __name__ == "__main__":
    unittest.main()
