import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import sanitize_html, to_html  # noqa: E402


class _AnchorAttrsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.attrs = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a" and self.attrs is None:
            self.attrs = {name: value for name, value in attrs}


def _first_anchor_attrs(html):
    parser = _AnchorAttrsParser()
    parser.feed(html)
    return parser.attrs or {}


class SanitizeHtmlTests(unittest.TestCase):
    def test_script_tags_are_removed(self):
        html = sanitize_html("<p>Hello</p><script>alert(1)</script>")

        self.assertIn("<p>Hello</p>", html)
        self.assertNotIn("<script", html.lower())
        self.assertNotIn("</script", html.lower())

    def test_javascript_href_is_blocked(self):
        html = sanitize_html('<a href="javascript:alert(1)">bad</a>')
        attrs = _first_anchor_attrs(html)

        self.assertNotIn("javascript:", html.lower())
        self.assertNotIn("href", attrs)

    def test_blank_target_gets_noopener_and_noreferrer(self):
        html = sanitize_html('<a href="https://example.com" target="_blank">link</a>')
        attrs = _first_anchor_attrs(html)
        rel_tokens = set((attrs.get("rel") or "").split())

        self.assertEqual(attrs.get("target"), "_blank")
        self.assertIn("noopener", rel_tokens)
        self.assertIn("noreferrer", rel_tokens)

    def test_existing_rel_values_are_preserved(self):
        html = sanitize_html(
            '<a href="https://example.com" target="_blank" rel="nofollow">link</a>'
        )
        attrs = _first_anchor_attrs(html)
        rel_tokens = set((attrs.get("rel") or "").split())

        self.assertIn("nofollow", rel_tokens)
        self.assertIn("noopener", rel_tokens)
        self.assertIn("noreferrer", rel_tokens)

    def test_normal_links_are_not_changed(self):
        html = sanitize_html('<a href="https://example.com">link</a>')
        attrs = _first_anchor_attrs(html)

        self.assertEqual(attrs.get("href"), "https://example.com")
        self.assertNotIn("target", attrs)
        self.assertNotIn("rel", attrs)


class SanitizeHtmlEdgeCaseTests(unittest.TestCase):
    def test_event_handler_attribute_is_stripped(self):
        # Only "class" is allowed on arbitrary tags, so on* handlers are removed.
        html = sanitize_html('<p onclick="steal()">hi</p>')

        self.assertNotIn("onclick", html.lower())
        self.assertIn("hi", html)

    def test_mailto_href_is_preserved(self):
        html = sanitize_html('<a href="mailto:dev@example.com">mail</a>')
        attrs = _first_anchor_attrs(html)

        self.assertEqual(attrs.get("href"), "mailto:dev@example.com")

    def test_data_uri_href_is_dropped(self):
        # data: is not in ALLOWED_PROTOCOLS — a common XSS/exfil vector.
        html = sanitize_html('<a href="data:text/html,<script>1</script>">x</a>')
        attrs = _first_anchor_attrs(html)

        self.assertNotIn("data:", html.lower())
        self.assertNotIn("href", attrs)

    def test_disallowed_tag_removed_but_siblings_kept(self):
        html = sanitize_html('<p>keep me</p><iframe src="evil"></iframe>')

        self.assertIn("<p>keep me</p>", html)
        self.assertNotIn("<iframe", html.lower())

    def test_img_onerror_payload_is_removed(self):
        # <img> is not an allowed tag at all, so the whole element is stripped.
        html = sanitize_html('<img src="x" onerror="alert(1)">')

        self.assertNotIn("<img", html.lower())
        self.assertNotIn("onerror", html.lower())

    def test_markdown_fallback_output_is_sanitized(self):
        # Mirrors create_article's markdown branch: to_html() then sanitize_html().
        # markdown passes raw inline HTML through, so sanitization must catch it.
        html = sanitize_html(to_html("intro text\n\n<script>alert(1)</script>"))

        self.assertNotIn("<script", html.lower())
        self.assertIn("intro text", html)


if __name__ == "__main__":
    unittest.main()
