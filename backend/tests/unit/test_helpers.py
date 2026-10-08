"""Unit tests for pure helper functions in app.py (no DB)."""

import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
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

    def test_user_shape_role_defaults_to_user(self):
        # Fail closed: a row without a role is shown the UI of a regular user.
        self.assertEqual(app._user_shape({"id": 1, "username": "u", "email": "u@x.com"})["role"], "user")
        self.assertEqual(app._user_shape({"id": 1, "username": "u", "email": "u@x.com",
                                          "role": "admin"})["role"], "admin")


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

    def test_without_bleach_tags_are_stripped_by_regex(self):
        # html_to_text imports bleach lazily; a None entry in sys.modules makes that import fail.
        with patch.dict(sys.modules, {"bleach": None}):
            text = app.html_to_text("<p>a &amp; <b>b</b></p>")

        self.assertEqual(text, "a & b")


class ToHtmlTests(unittest.TestCase):
    def test_plain_text_wrapped_in_paragraph(self):
        self.assertIn("<p>Hello</p>", app.to_html("Hello"))

    def test_markdown_bold_is_rendered(self):
        # markdown is installed, so the rich path is active.
        self.assertIn("<strong>bold</strong>", app.to_html("**bold**"))


class IsoTests(unittest.TestCase):
    def test_none_returns_none(self):
        self.assertIsNone(app._iso(None))

    def test_naive_datetime_is_labelled_utc(self):
        # Connections run in UTC, so a naive DB value is UTC. Without the offset a
        # browser would read it as its own local time (3 hours off in Israel).
        dt = datetime(2025, 5, 1, 10, 30, 0)
        self.assertEqual(app._iso(dt), "2025-05-01T10:30:00+00:00")

    def test_aware_datetime_is_converted_to_utc(self):
        israel_summer = timezone(timedelta(hours=3))
        dt = datetime(2025, 5, 1, 13, 30, 0, tzinfo=israel_summer)
        self.assertEqual(app._iso(dt), "2025-05-01T10:30:00+00:00")

    def test_date_without_time_is_left_as_a_date(self):
        self.assertEqual(app._iso(date(2025, 5, 1)), "2025-05-01")

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
        self.assertEqual(post["created_at"], "2025-05-01T09:00:00+00:00")
        self.assertEqual(post["user"]["username"], "ada")

    def test_profile_image_falls_back_to_dicebear(self):
        post = app._shape_post_row(self._row(profile_image=None, avatar=None))

        self.assertIn("seed=ada", post["user"]["profile_image"])

    def test_shape_starts_with_no_likes_or_comments(self):
        # _attach_counts fills these in from one query per page.
        post = app._shape_post_row(self._row())

        self.assertEqual(post["like_count"], 0)
        self.assertIs(post["liked_by_me"], False)
        self.assertEqual(post["comment_count"], 0)


class ShapeCommentTests(unittest.TestCase):
    def _row(self, **over):
        row = {
            "id": 3, "post_id": 7, "parent_id": None, "body_html": "<p>hi</p>",
            "created_at": datetime(2026, 10, 8, 9, 30, 0), "email": "ada@x.com",
            "username": "ada", "name": "Ada", "avatar": "a.svg", "profile_image": "p.svg",
        }
        row.update(over)
        return row

    def test_shape_maps_fields_without_the_email(self):
        comment = app._shape_comment(self._row())

        self.assertEqual(comment, {
            "id": 3, "post_id": 7, "parent_id": None, "body_html": "<p>hi</p>",
            "created_at": "2026-10-08T09:30:00+00:00",
            "user": {"username": "ada", "name": "Ada", "profile_image": "p.svg"},
        })

    def test_profile_image_falls_back_to_avatar_then_dicebear(self):
        self.assertEqual(app._shape_comment(self._row(profile_image=None))["user"]["profile_image"], "a.svg")
        fallback = app._shape_comment(self._row(profile_image=None, avatar=None))["user"]["profile_image"]
        self.assertIn("seed=ada", fallback)

    def test_body_is_sanitized(self):
        comment = app._shape_comment(self._row(body_html='<p onclick="x()">hi</p><script>1</script>'))

        self.assertEqual(comment["body_html"], "<p>hi</p>1")


class CommentTreeTests(unittest.TestCase):
    def _row(self, cid, parent_id=None):
        return {"id": cid, "post_id": 7, "parent_id": parent_id, "body_html": f"<p>{cid}</p>",
                "created_at": None, "username": "u", "name": "U", "avatar": None, "profile_image": None}

    def test_replies_hang_under_their_top_level_comment_in_order(self):
        tree = app._comment_tree([self._row(1), self._row(2), self._row(3, 1), self._row(4, 2),
                                  self._row(5, 1)])

        self.assertEqual([(c["id"], [r["id"] for r in c["replies"]]) for c in tree],
                         [(1, [3, 5]), (2, [4])])

    def test_a_reply_listed_before_its_parent_still_finds_it(self):
        # Same-second timestamps cannot put a reply first (ties go by id), but the
        # tree does not depend on that.
        tree = app._comment_tree([self._row(3, 1), self._row(1)])

        self.assertEqual([r["id"] for r in tree[0]["replies"]], [3])

    def test_a_reply_without_a_top_level_parent_is_left_out(self):
        # A reply to a reply (the API refuses those) or to a missing comment.
        tree = app._comment_tree([self._row(1), self._row(2, 1), self._row(3, 2), self._row(4, 99)])

        self.assertEqual([c["id"] for c in tree], [1])
        self.assertEqual([r["id"] for r in tree[0]["replies"]], [2])

    def test_no_rows_is_an_empty_tree(self):
        self.assertEqual(app._comment_tree([]), [])


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


class JsonObjectTests(unittest.TestCase):
    def test_missing_body_is_an_empty_object(self):
        self.assertEqual(app._json_object(None), {})

    def test_an_object_is_returned_as_is(self):
        data = {"a": 1}

        self.assertIs(app._json_object(data), data)

    def test_any_other_json_type_raises_input_error_naming_the_value(self):
        for value in (["a"], [], "text", "", 0, 123, True, False):
            with self.subTest(value=value):
                with self.assertRaises(app.InputError) as ctx:
                    app._json_object(value, "article")

                self.assertEqual(str(ctx.exception), "article must be a JSON object")


class StrFieldTests(unittest.TestCase):
    def test_missing_and_null_read_as_empty_string(self):
        self.assertEqual(app._str_field({}, "title"), "")
        self.assertEqual(app._str_field({"title": None}, "title"), "")

    def test_strings_are_trimmed_by_default(self):
        self.assertEqual(app._str_field({"title": "  Hi  "}, "title"), "Hi")

    def test_strip_false_keeps_the_value_exactly(self):
        # Passwords and raw HTML must reach their checks untouched.
        self.assertEqual(app._str_field({"password": " pw "}, "password", strip=False), " pw ")

    def test_non_string_raises_input_error_naming_the_field(self):
        # 0, False and [] are falsy: the old `(x or "")` let them through as "".
        for value in (0, 123, 1.5, True, False, [], ["a"], {}, {"a": 1}):
            with self.subTest(value=value):
                with self.assertRaises(app.InputError) as ctx:
                    app._str_field({"title": value}, "title")

                self.assertEqual(str(ctx.exception), "title must be a string")

    def test_input_error_is_a_400_with_the_message(self):
        with app.app.test_request_context():
            resp, status = app._bad_input(app.InputError("title must be a string"))

        self.assertEqual(status, 400)
        self.assertEqual(resp.get_json(), {"error": "title must be a string"})


if __name__ == "__main__":
    unittest.main()
