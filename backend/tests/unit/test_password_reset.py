"""password_reset.py: the token, its hash, the link and the email.

Pure functions; the endpoints are tested in tests/integration/test_password_reset_api.py.
"""

import hashlib
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
for _p in (TESTS_DIR.parent, TESTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import password_reset  # noqa: E402
from mailer import Mail, MailConfigError  # noqa: E402


class TokenTests(unittest.TestCase):
    def test_a_token_is_random_url_safe_and_long(self):
        tokens = {password_reset.new_token()[0] for _ in range(50)}

        self.assertEqual(len(tokens), 50)
        for token in tokens:
            self.assertRegex(token, r"\A[A-Za-z0-9_-]{43}\Z")   # 32 random bytes
            self.assertLessEqual(len(token), password_reset.MAX_TOKEN_CHARS)

    def test_the_hash_is_the_sha256_hex_of_the_token(self):
        token, token_hash = password_reset.new_token()

        self.assertEqual(token_hash, hashlib.sha256(token.encode("utf-8")).hexdigest())
        self.assertEqual(password_reset.hash_token(token), token_hash)
        self.assertEqual(len(token_hash), 64)                # fits CHAR(64)
        self.assertNotIn(token, token_hash)


class BaseUrlTests(unittest.TestCase):
    def test_file_mail_defaults_to_the_vite_dev_server(self):
        for env in ({}, {"MAIL_PROVIDER": "file"}, {"MAIL_PROVIDER": "file", "APP_BASE_URL": " "}):
            with self.subTest(env=env):
                self.assertEqual(password_reset.base_url(env), "http://localhost:5173")

    def test_smtp_needs_it_set(self):
        # A real email must not point at localhost: production sets the site's URL.
        with self.assertRaises(MailConfigError) as ctx:
            password_reset.base_url({"MAIL_PROVIDER": "smtp"})

        self.assertIn("APP_BASE_URL is not set", str(ctx.exception))

    def test_a_set_url_is_used_without_its_trailing_slash(self):
        env = {"MAIL_PROVIDER": "smtp", "APP_BASE_URL": " http://63.179.249.8:8080/ "}

        self.assertEqual(password_reset.base_url(env), "http://63.179.249.8:8080")

    def test_a_path_prefix_is_kept(self):
        env = {"APP_BASE_URL": "https://example.test/pulsenet/"}

        self.assertEqual(password_reset.base_url(env), "https://example.test/pulsenet")

    def test_anything_but_a_plain_http_url_is_refused(self):
        for value in ("localhost:5173", "ftp://example.test", "https://", "javascript:alert(1)",
                      "http://example.test/?next=x", "http://example.test/#x", "http://example.test:port"):
            with self.subTest(value=value):
                with self.assertRaises(MailConfigError) as ctx:
                    password_reset.base_url({"APP_BASE_URL": value})
                self.assertIn("APP_BASE_URL must be", str(ctx.exception))


class LinkAndMailTests(unittest.TestCase):
    def test_the_token_travels_in_the_fragment(self):
        # A fragment is never sent to a server: not to nginx's access log, and not
        # in a Referer header to an image host.
        link = password_reset.reset_link("http://localhost:5173", "tok_EN-1")

        self.assertEqual(link, "http://localhost:5173/reset-password#token=tok_EN-1")

    def test_the_mail_carries_the_link_and_how_long_it_works(self):
        link = "http://localhost:5173/reset-password#token=abc"

        mail = password_reset.reset_mail("ada@example.com", "Ada", link)

        self.assertIsInstance(mail, Mail)
        self.assertEqual(mail.to, "ada@example.com")
        self.assertEqual(mail.subject, "Reset your PulseNet password")
        for body in (mail.text, mail.html):
            self.assertIn(link, body)
            self.assertIn("30 minutes", body)
            self.assertIn("Ada", body)
        self.assertIn(f'href="{link}"', mail.html)

    def test_the_name_is_escaped_in_the_html(self):
        mail = password_reset.reset_mail("eve@example.com", '<img src=x onerror="alert(1)">',
                                         "http://localhost:5173/reset-password#token=abc")

        self.assertNotIn("<img", mail.html)
        self.assertIn("&lt;img", mail.html)
        self.assertIn("<img", mail.text)                    # plain text shows it as is

    def test_no_name_still_greets(self):
        mail = password_reset.reset_mail("ada@example.com", None, "http://x.test/reset-password#token=a")

        self.assertTrue(mail.text.startswith("Hi,"))
        self.assertIsNone(re.search(r"Hi None", mail.text + mail.html))


if __name__ == "__main__":
    unittest.main()
