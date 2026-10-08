"""Password reset API tests (Flask test client, mocked DB seam, in-memory mailer).

POST /api/password/forgot  {email}            mail a one-time link; always the same 200
POST /api/password/reset   {token, password}  set the password, log out everywhere

Only the SHA-256 of a link's token is stored. A link works once, for 30 minutes;
at most 3 links per user per hour, and a link whose mail failed is deleted so it
does not count. The answer to "forgot" never tells whether the address has an
account.
"""

import hashlib
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import bcrypt

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import app  # noqa: E402
from mailer import MailError, MemoryMailer  # noqa: E402
from support import FakeConn, client, db_down, patch_db, patch_mail  # noqa: E402

USER = {"id": 42, "name": "Ada", "email": "ada@example.com"}
LINK = re.compile(r"http://localhost:5173/reset-password#token=([A-Za-z0-9_-]+)")
TOKEN = "tok_valid-0123456789"
TOKEN_HASH = hashlib.sha256(TOKEN.encode("utf-8")).hexdigest()
NEW_PASSWORD = "N3w-pass!"


def _sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _forgot(body, conn, sender=None, cleanup=None, base_url="http://localhost:5173"):
    """POST /api/password/forgot with mail on (``sender``, default a MemoryMailer).
    ``cleanup`` is the second connection, opened only after a failed mail."""
    connections = [conn] + ([cleanup] if cleanup is not None else [])
    with patch_mail(sender, base_url=base_url) as mail, patch_db(conn), \
         patch.object(app, "get_db_connection", side_effect=connections):
        resp = client().post("/api/password/forgot", json=body)
    return resp, mail


def _known(recent=0):
    """The rows forgot reads for a known address: the user, then the hour's count."""
    return FakeConn(fetchone=[dict(USER), {"recent": recent}])


def _all_params(conn):
    return [params for _sql, params in conn.executed]


class ForgotTests(unittest.TestCase):
    def test_a_known_address_gets_a_link_and_only_its_hash_is_stored(self):
        conn = _known()

        resp, mail = _forgot({"email": "ada@example.com"}, conn)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"message": app.FORGOT_MESSAGE})
        self.assertEqual(len(mail.sent), 1)
        sent = mail.sent[0]
        self.assertEqual(sent.to, "ada@example.com")
        token = LINK.search(sent.text).group(1)
        self.assertEqual(LINK.search(sent.html).group(1), token)
        user_id, stored_hash, ttl = conn.params_for("insert into password_resets")
        self.assertEqual((user_id, ttl), (42, 30))
        self.assertEqual(stored_hash, _sha256(token))
        self.assertNotIn(token, str(_all_params(conn)))     # the token itself never reaches the DB
        self.assertTrue(conn.ran("now() + interval %s minute"))
        self.assertEqual(conn.commits, 1)
        self.assertTrue(conn.closed)

    def test_an_unknown_address_gets_the_same_answer_and_nothing_else(self):
        conn = FakeConn(fetchone=[None])

        resp, mail = _forgot({"email": "nobody@example.com"}, conn)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"message": app.FORGOT_MESSAGE})
        self.assertEqual(mail.sent, [])
        self.assertFalse(conn.ran("insert into password_resets"))
        self.assertFalse(conn.ran("count(*)"))

    def test_the_lookup_skips_agents_but_not_banned_users(self):
        # An agent has no password and must not get one. A banned user may reset;
        # their login still answers 403.
        conn = FakeConn(fetchone=[None])

        _forgot({"email": " ada@example.com "}, conn)

        sql, params = conn.find("from users")[0]
        self.assertIn("not is_agent", " ".join(sql.split()).lower())
        self.assertNotIn("is_banned", sql)
        self.assertEqual(params, ("ada@example.com",))

    def test_the_mail_goes_to_the_stored_address(self):
        conn = FakeConn(fetchone=[dict(USER, email="ada@example.com"), {"recent": 0}])

        _resp, mail = _forgot({"email": "ADA@Example.com"}, conn)

        self.assertEqual(mail.sent[0].to, "ada@example.com")

    def test_three_links_an_hour_is_the_limit(self):
        for recent, sent in ((2, 1), (3, 0), (7, 0)):
            with self.subTest(recent=recent):
                conn = _known(recent=recent)

                resp, mail = _forgot({"email": "ada@example.com"}, conn)

                self.assertEqual(resp.get_json(), {"message": app.FORGOT_MESSAGE})
                self.assertEqual(len(mail.sent), sent)
                self.assertEqual(conn.ran("insert into password_resets"), bool(sent))
                count_sql, params = conn.find("count(*)")[0]
                self.assertIn("interval 1 hour", count_sql.lower())
                self.assertEqual(params, (42,))

    def test_links_expired_a_day_ago_are_cleaned_up(self):
        conn = FakeConn(fetchone=[None])

        _forgot({"email": "ada@example.com"}, conn)

        self.assertTrue(conn.ran("delete from password_resets where expires_at < now() - interval 1 day"))
        self.assertEqual(conn.commits, 1)

    def test_the_link_points_at_app_base_url(self):
        conn = _known()

        _resp, mail = _forgot({"email": "ada@example.com"}, conn, base_url="http://63.179.249.8:8080")

        self.assertIn("http://63.179.249.8:8080/reset-password#token=", mail.sent[0].text)

    def test_with_mail_off_every_address_gets_503(self):
        conn = FakeConn(fetchone=[dict(USER)])
        with patch_db(conn):
            resp = client().post("/api/password/forgot", json={"email": "ada@example.com"})

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.get_json(), {"error": "Password reset is not available on this server."})
        self.assertEqual(conn.executed, [])

    def test_with_the_db_down_it_is_503(self):
        with patch_mail() as mail, db_down():
            resp = client().post("/api/password/forgot", json={"email": "ada@example.com"})

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(mail.sent, [])

    def test_a_missing_or_oversized_address_is_400_before_the_db(self):
        for body, error in (({}, "email is required"),
                            ({"email": "  "}, "email is required"),
                            ({"email": "a" * 95 + "@x.com"}, "Email must be 100 characters or fewer")):
            with self.subTest(body=body):
                conn = FakeConn()
                resp, _mail = _forgot(body, conn)
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(resp.get_json(), {"error": error})
                self.assertEqual(conn.executed, [])

    def test_wrong_json_types_are_400(self):
        for body in (["ada@example.com"], {"email": 7}):
            with self.subTest(body=body):
                resp, _mail = _forgot(body, FakeConn())
                self.assertEqual(resp.status_code, 400)


class FailedMailTests(unittest.TestCase):
    def test_a_failed_mail_deletes_its_link_and_still_answers_200(self):
        conn, cleanup = _known(), FakeConn()
        sender = MemoryMailer(fail=MailError("smtp: SMTPServerDisconnected"))

        with self.assertLogs(app.app.logger, "WARNING") as logs:
            resp, _mail = _forgot({"email": "ada@example.com"}, conn, sender, cleanup)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"message": app.FORGOT_MESSAGE})
        # The link the mail would have carried goes, in a commit of its own, so it
        # neither counts toward the hourly limit nor stays valid unseen.
        _user_id, stored_hash, _ttl = conn.params_for("insert into password_resets")
        self.assertEqual(cleanup.params_for("delete from password_resets where token_hash = %s"),
                         (stored_hash,))
        self.assertEqual(cleanup.commits, 1)
        self.assertTrue(cleanup.closed)
        log = "\n".join(logs.output)
        self.assertIn("user 42", log)
        self.assertIn("SMTPServerDisconnected", log)
        self.assertNotIn("ada@example.com", log)

    def test_a_failed_cleanup_is_logged_and_still_answers_200(self):
        conn = _known()
        cleanup = FakeConn(raise_on={"delete from password_resets": RuntimeError("db gone")})
        sender = MemoryMailer(fail=MailError("smtp: SMTPServerDisconnected"))

        with self.assertLogs(app.app.logger, "WARNING") as logs:
            resp, _mail = _forgot({"email": "ada@example.com"}, conn, sender, cleanup)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"message": app.FORGOT_MESSAGE})
        self.assertEqual(len(logs.output), 2)
        self.assertIn("not removed", logs.output[1])
        self.assertTrue(cleanup.closed)

    def test_a_sent_mail_keeps_its_link(self):
        conn = _known()

        _forgot({"email": "ada@example.com"}, conn)

        self.assertFalse(conn.ran("where token_hash"))


def _reset(body, conn):
    with patch_db(conn):
        return client().post("/api/password/reset", json=body)


def _valid_link():
    return FakeConn(fetchone=[{"id": 5, "user_id": 42}])


class ResetTests(unittest.TestCase):
    def test_a_valid_link_sets_the_password_and_logs_out_everywhere(self):
        conn = _valid_link()

        resp = _reset({"token": TOKEN, "password": NEW_PASSWORD}, conn)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"message": "Your password was changed. Log in with the new one."})
        self.assertEqual(conn.params_for("from password_resets pr"), (TOKEN_HASH,))
        new_hash, user_id = conn.params_for("update users set password_hash")
        self.assertEqual(user_id, 42)
        self.assertTrue(bcrypt.checkpw(NEW_PASSWORD.encode(), new_hash.encode()))
        self.assertEqual(conn.params_for("update password_resets set used_at = now()"), (42,))
        self.assertEqual(conn.params_for("delete from sessions where user_id = %s"), (42,))
        # One transaction: the three writes commit together, after the lookup.
        order = [" ".join(sql.split()).lower()[:30] for sql, _ in conn.executed]
        self.assertEqual(order, ["select pr.id, pr.user_id from ", "update users set password_hash",
                                 "update password_resets set use", "delete from sessions where use"])
        self.assertEqual(conn.commits, 1)
        self.assertTrue(conn.closed)

    def test_the_lookup_locks_the_link_and_checks_use_expiry_and_agents(self):
        conn = _valid_link()

        _reset({"token": TOKEN, "password": NEW_PASSWORD}, conn)

        sql = " ".join(conn.find("from password_resets pr")[0][0].split()).lower()
        for needle in ("pr.token_hash = %s", "pr.used_at is null", "pr.expires_at > now()",
                       "not u.is_agent", "for update"):
            with self.subTest(needle=needle):
                self.assertIn(needle, sql)

    def test_every_open_link_of_the_user_is_used_up(self):
        conn = _valid_link()

        _reset({"token": TOKEN, "password": NEW_PASSWORD}, conn)

        sql = " ".join(conn.find("update password_resets")[0][0].split()).lower()
        self.assertIn("where user_id = %s and used_at is null", sql)

    def test_an_unknown_used_or_expired_link_is_400_and_changes_nothing(self):
        conn = FakeConn(fetchone=[None])

        with patch.object(app, "_hash_password", wraps=app._hash_password) as hashing:
            resp = _reset({"token": TOKEN, "password": NEW_PASSWORD}, conn)

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json(), {"error": app.RESET_LINK_INVALID})
        self.assertFalse(conn.ran("update users"))
        self.assertFalse(conn.ran("update password_resets"))
        self.assertFalse(conn.ran("delete"))
        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)              # releases the lock at once
        hashing.assert_not_called()                      # no bcrypt for a guess
        self.assertTrue(conn.closed)

    def test_the_token_is_only_ever_compared_hashed(self):
        conn = _valid_link()

        _reset({"token": TOKEN, "password": NEW_PASSWORD}, conn)

        self.assertNotIn(TOKEN, str(_all_params(conn)))

    def test_a_missing_or_oversized_token_is_400_before_the_db(self):
        for token in ("", "   ", "x" * 101):
            with self.subTest(length=len(token)):
                conn = FakeConn()
                resp = _reset({"token": token, "password": NEW_PASSWORD}, conn)
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(resp.get_json(), {"error": app.RESET_LINK_INVALID})
                self.assertEqual(conn.executed, [])

    def test_the_signup_password_rule_applies(self):
        for password, error in (("", "password is required"), ("x" * 73, app.PASSWORD_TOO_LONG)):
            with self.subTest(error=error):
                conn = _valid_link()
                resp = _reset({"token": TOKEN, "password": password}, conn)
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(resp.get_json(), {"error": error})
                self.assertEqual(conn.executed, [])

    def test_wrong_json_types_are_400(self):
        for body in ([TOKEN], {"token": 5, "password": NEW_PASSWORD}, {"token": TOKEN, "password": 5}):
            with self.subTest(body=body):
                self.assertEqual(_reset(body, FakeConn()).status_code, 400)

    def test_with_the_db_down_it_is_503(self):
        with db_down():
            resp = client().post("/api/password/reset", json={"token": TOKEN, "password": NEW_PASSWORD})

        self.assertEqual(resp.status_code, 503)

    def test_reset_works_with_mail_off_and_does_not_log_in(self):
        # Links already mailed keep working if mail is turned off later.
        conn = _valid_link()

        resp = _reset({"token": TOKEN, "password": NEW_PASSWORD}, conn)

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("session_id=", " ".join(resp.headers.getlist("Set-Cookie")))
        self.assertFalse(conn.ran("insert into sessions"))

    def test_a_banned_user_can_reset_but_still_cannot_log_in(self):
        conn = _valid_link()
        _reset({"token": TOKEN, "password": NEW_PASSWORD}, conn)
        new_hash, _user_id = conn.params_for("update users set password_hash")
        self.assertFalse(conn.ran("is_banned"))           # the reset leaves the ban alone

        row = {"id": 42, "name": "Ada", "username": "ada", "email": "ada@example.com", "bio": "",
               "avatar": None, "profile_image": None, "role": "user", "is_banned": 1,
               "password_hash": new_hash}
        login = FakeConn(fetchone=[row])
        with patch_db(login):
            resp = client().post("/api/login", json={"email": "ada@example.com", "password": NEW_PASSWORD})

        self.assertEqual(resp.status_code, 403)



class MailWiringTests(unittest.TestCase):
    """_build_mailer: what app.py builds at startup from the environment."""

    def test_unset_provider_means_mail_off_with_an_info_line(self):
        with self.assertLogs(app.app.logger, level="INFO") as logs:
            built = app._build_mailer({})

        self.assertEqual(built, (None, None))
        self.assertEqual(logs.records[0].levelname, "INFO")
        self.assertIn("Mail off: MAIL_PROVIDER is not set", logs.output[0])

    def test_a_broken_setting_is_off_with_a_warning_that_names_no_value(self):
        env = {"MAIL_PROVIDER": "smtp", "SMTP_HOST": "smtp.gmail.com", "SMTP_USER": "bot@example.test",
               "SMTP_PASSWORD": "secret-app-pass"}       # APP_BASE_URL missing
        with self.assertLogs(app.app.logger, level="INFO") as logs:
            built = app._build_mailer(env)

        self.assertEqual(built, (None, None))
        self.assertEqual(logs.records[0].levelname, "WARNING")
        self.assertIn("APP_BASE_URL is not set", logs.output[0])
        self.assertNotIn("secret-app-pass", logs.output[0])

    def test_file_mail_links_to_the_dev_server(self):
        sender, base = app._build_mailer({"MAIL_PROVIDER": "file", "MAIL_OUTBOX_DIR": "/tmp/box"})

        self.assertEqual(sender.name, "file")
        self.assertEqual(base, "http://localhost:5173")

    def test_smtp_mail_links_to_app_base_url(self):
        env = {"MAIL_PROVIDER": "smtp", "SMTP_HOST": "smtp.gmail.com", "SMTP_USER": "bot@example.test",
               "SMTP_PASSWORD": "secret-app-pass", "APP_BASE_URL": "http://63.179.249.8:8080/"}

        sender, base = app._build_mailer(env)

        self.assertEqual(sender.describe(), "smtp smtp.gmail.com:587 as bot@example.test")
        self.assertEqual(base, "http://63.179.249.8:8080")

    def test_the_suite_runs_with_mail_off(self):
        self.assertIsNone(app.mail_service)
        self.assertIsNone(app.reset_base_url)


if __name__ == "__main__":
    unittest.main()
