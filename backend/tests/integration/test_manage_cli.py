"""manage.py make-admin and llm-check against the hand-rolled DB double (no real MySQL).

``manage.connect`` is patched to return a ``FakeConn`` seeded with what the command
reads, in order. make-admin: the server version, then the user's ``(id, role)`` row.
llm-check: the server version, then the usage counts the LLM service reads (before
the call and after it). llm-check never touches the network: the fake provider, or
``requests.post`` patched to a canned reply.
"""

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import mysql.connector
import requests

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import manage  # noqa: E402
from llm_support import FakeResponse  # noqa: E402
from support import FakeConn  # noqa: E402

ENV = {
    "DB_HOST": "db.example.internal",
    "DB_USER": "dbuser_secret_x",
    "DB_PASSWORD": "s3cret-password-x",
    "DB_NAME": "pulsenet_db",
}


class MakeAdminTests(unittest.TestCase):
    def run_main(self, argv, conn, env=None):
        """Run ``manage.main(argv)`` with the DB seam patched; returns (code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with patch.object(manage, "connect", return_value=conn) as connect, \
             patch.object(manage, "load_dotenv"), \
             patch.dict(manage.os.environ, ENV if env is None else env, clear=True), \
             redirect_stdout(out), redirect_stderr(err):
            code = manage.main(argv)
        self.connect = connect
        return code, out.getvalue(), err.getvalue()

    def test_promotes_a_user(self):
        conn = FakeConn(fetchone=[("8.4.8",), (5, "user")])

        code, out, _ = self.run_main(["make-admin", "ada"], conn)

        self.assertEqual(code, 0)
        self.assertEqual(conn.params_for("select id, role from users where username = %s"), ("ada",))
        self.assertEqual(conn.params_for("update users set role = 'admin' where id = %s"), (5,))
        self.assertEqual(conn.commits, 1)
        self.assertIn("ada (id 5) is now an admin", out)
        self.assertTrue(conn.closed)

    def test_shows_the_target_first_and_never_the_credentials(self):
        conn = FakeConn(fetchone=[("8.4.8",), (5, "user")])

        _, out, err = self.run_main(["make-admin", "ada"], conn)

        self.assertEqual(out.splitlines()[0], "manage: MySQL 8.4.8 at db.example.internal, database pulsenet_db")
        for secret in (ENV["DB_PASSWORD"], ENV["DB_USER"]):
            self.assertNotIn(secret, out + err)

    def test_an_unset_host_is_shown_as_the_driver_default(self):
        conn = FakeConn(fetchone=[("9.7.0",), (5, "user")])

        _, out, _ = self.run_main(["make-admin", "ada"], conn, env={"DB_NAME": "pulsenet_db"})

        self.assertIn("at 127.0.0.1, database pulsenet_db", out.splitlines()[0])

    def test_dry_run_reads_but_changes_nothing(self):
        conn = FakeConn(fetchone=[("8.4.8",), (5, "user")])

        code, out, _ = self.run_main(["make-admin", "ada", "--dry-run"], conn)

        self.assertEqual(code, 0)
        self.assertTrue(conn.ran("select id, role from users"))
        self.assertFalse(conn.ran("update"))
        self.assertEqual(conn.commits, 0)
        self.assertIn("dry run: would make ada (id 5, now 'user') an admin; nothing changed", out)

    def test_an_admin_is_left_as_is(self):
        conn = FakeConn(fetchone=[("9.7.0",), (5, "admin")])

        code, out, _ = self.run_main(["make-admin", "ada"], conn)

        self.assertEqual(code, 0)
        self.assertFalse(conn.ran("update"))
        self.assertEqual(conn.commits, 0)
        self.assertIn("ada (id 5) is already an admin", out)

    def test_unknown_user_exits_1(self):
        conn = FakeConn(fetchone=[("9.7.0",), None])

        code, _, err = self.run_main(["make-admin", "ghost"], conn)

        self.assertEqual(code, 1)
        self.assertIn("no user named 'ghost'", err)
        self.assertFalse(conn.ran("update"))
        self.assertTrue(conn.closed)

    def test_the_username_is_a_bound_parameter(self):
        conn = FakeConn(fetchone=[("9.7.0",), None])
        sneaky = "x' OR '1'='1"

        self.run_main(["make-admin", sneaky], conn)

        sql, params = conn.find("from users where username")[0]
        self.assertNotIn(sneaky, sql)
        self.assertEqual(params, (sneaky,))

    def test_missing_db_name_is_a_usage_error(self):
        code, _, err = self.run_main(["make-admin", "ada"], FakeConn(), env={})

        self.assertEqual(code, 2)
        self.assertIn("DB_NAME", err)
        self.connect.assert_not_called()

    def test_a_database_error_exits_1(self):
        err = io.StringIO()
        with patch.object(manage, "connect", side_effect=mysql.connector.Error("refused")), \
             patch.object(manage, "load_dotenv"), \
             patch.dict(manage.os.environ, ENV, clear=True), \
             redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = manage.main(["make-admin", "ada"])

        self.assertEqual(code, 1)
        self.assertIn("refused", err.getvalue())

    def test_a_command_is_required(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit_:
            manage.main([])

        self.assertEqual(exit_.exception.code, 2)


LLM_KEY = "check-key-5"
GEMINI_ENV = {
    **ENV,
    "LLM_PROVIDER": "openai_compat",
    "LLM_BASE_URL": "https://generativelanguage.example.test/v1beta/openai",
    "LLM_MODEL": "flash-model",
    "LLM_API_KEY": LLM_KEY,
}


class LlmCheckTests(unittest.TestCase):
    def run_main(self, argv, conn, env, stdout=None):
        """Run ``manage.main(argv)`` with the DB seam patched; returns (code, stdout, stderr)."""
        out, err = stdout or io.StringIO(), io.StringIO()
        with patch.object(manage, "connect", return_value=conn) as connect, \
             patch.object(manage, "load_dotenv"), \
             patch.dict(manage.os.environ, env, clear=True), \
             redirect_stdout(out), redirect_stderr(err):
            code = manage.main(argv)
        self.connect = connect
        return code, (out.getvalue() if stdout is None else ""), err.getvalue()

    def test_fake_check_prints_the_target_the_provider_the_reply_and_the_count(self):
        conn = FakeConn(fetchone=[("8.4.8",), (0,), (1,)])

        code, out, err = self.run_main(["llm-check"], conn, {**ENV, "LLM_PROVIDER": "fake"})

        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertEqual(lines[0], "manage: MySQL 8.4.8 at db.example.internal, database pulsenet_db")
        self.assertEqual(lines[1], "manage: LLM fake (canned replies, no network)")
        self.assertRegex(lines[2], r"^manage: reply in \d+ ms: \(fake reply\) In one short sentence, say hello to PulseNet\.$")
        self.assertEqual(lines[3], "manage: today 1/100 LLM calls")
        sql, params = conn.find("insert into llm_usage")[0]
        self.assertEqual(params[1:6], ("fake", None, "check", None, "ok"))
        self.assertTrue(conn.closed)

    def test_a_custom_prompt(self):
        conn = FakeConn(fetchone=[("9.7.0",), (0,), (1,)])

        _, out, _ = self.run_main(["llm-check", "--prompt", "ping"], conn, {**ENV, "LLM_PROVIDER": "fake"})

        self.assertIn(": (fake reply) ping", out)

    def test_a_long_reply_is_cut(self):
        conn = FakeConn(fetchone=[("9.7.0",), (0,), (1,)])
        long_reply = "word " * 200

        with patch.object(requests, "post", return_value=FakeResponse(200, {
                "choices": [{"message": {"content": long_reply}}]})):
            _, out, _ = self.run_main(["llm-check"], conn, GEMINI_ENV)

        shown = out.splitlines()[2].split(" ms: ", 1)[1]
        self.assertEqual(shown, " ".join(["word"] * 60) + "...")  # 300 characters, then trimmed

    def test_bad_llm_settings_exit_2_before_connecting(self):
        code, out, err = self.run_main(["llm-check"], FakeConn(), dict(ENV))

        self.assertEqual(code, 2)
        self.assertIn("manage: LLM_PROVIDER is not set", err)
        self.assertEqual(out, "")
        self.connect.assert_not_called()

    def test_missing_db_name_is_a_usage_error(self):
        code, _, err = self.run_main(["llm-check"], FakeConn(), {"LLM_PROVIDER": "fake"})

        self.assertEqual(code, 2)
        self.assertIn("DB_NAME", err)

    def test_rate_limited_exits_1_logs_the_status_and_never_shows_a_secret(self):
        conn = FakeConn(fetchone=[("8.4.8",), (0,)])
        quota = FakeResponse(429, {"error": {"message": f"Quota exceeded for key {LLM_KEY}"}})

        with patch.object(requests, "post", return_value=quota) as post:
            code, out, err = self.run_main(["llm-check"], conn, GEMINI_ENV)

        self.assertEqual(code, 1)
        self.assertIn("manage: LLM FAILED: openai_compat: rate limited (HTTP 429): Quota exceeded for key ***", err)
        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": f"Bearer {LLM_KEY}"})
        self.assertIn("manage: LLM openai_compat, model flash-model at generativelanguage.example.test", out)
        self.assertEqual(conn.find("insert into llm_usage")[0][1][5], "rate_limited")
        for secret in (LLM_KEY, ENV["DB_PASSWORD"], ENV["DB_USER"]):
            self.assertNotIn(secret, out + err)
        self.assertTrue(conn.closed)

    def test_the_daily_limit_refuses_without_calling(self):
        conn = FakeConn(fetchone=[("8.4.8",), (0,)])

        with patch.object(requests, "post") as post:
            code, _, err = self.run_main(["llm-check"], conn, {**GEMINI_ENV, "LLM_DAILY_LIMIT": "0"})

        self.assertEqual(code, 1)
        self.assertIn("manage: LLM FAILED: daily LLM limit reached (0/0)", err)
        post.assert_not_called()
        self.assertEqual(conn.find("insert into llm_usage")[0][1][5], "over_limit")

    def test_a_database_error_exits_1(self):
        err = io.StringIO()
        with patch.object(manage, "connect", side_effect=mysql.connector.Error("refused")), \
             patch.object(manage, "load_dotenv"), \
             patch.dict(manage.os.environ, {**ENV, "LLM_PROVIDER": "fake"}, clear=True), \
             redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = manage.main(["llm-check"])

        self.assertEqual(code, 1)
        self.assertIn("manage: FAILED: refused", err.getvalue())

    def test_a_reply_the_console_cannot_encode_is_escaped_not_a_crash(self):
        # A Windows pipe is cp1252: emoji or Hebrew in a reply used to raise UnicodeEncodeError.
        conn = FakeConn(fetchone=[("9.7.0",), (0,), (1,)])
        raw = io.BytesIO()
        console = io.TextIOWrapper(raw, encoding="cp1252")

        code, _, err = self.run_main(["llm-check", "--prompt", "hi \U0001F44B שלום"],
                                     conn, {**ENV, "LLM_PROVIDER": "fake"}, stdout=console)
        console.flush()

        self.assertEqual(code, 0, err)
        printed = raw.getvalue().decode("cp1252")
        self.assertIn("(fake reply) hi \\U0001f44b \\u05e9\\u05dc\\u05d5\\u05dd", printed)


if __name__ == "__main__":
    unittest.main()
