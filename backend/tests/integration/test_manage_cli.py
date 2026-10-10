"""manage.py make-admin, llm-check, mail-check, llm-record and agent-tick against the hand-rolled DB double (no real MySQL).

``manage.connect`` is patched to return a ``FakeConn`` seeded with what the command
reads, in order. make-admin: the server version, then the user's ``(id, role)`` row.
llm-check: the server version, then the usage counts the LLM service reads (before
the call and after it). llm-check never touches the network: the fake provider, or
``requests.post`` patched to a canned reply.
"""

import io
import json
import sys
import tempfile
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

import mailer  # noqa: E402
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



class MailCheckTests(unittest.TestCase):
    def run_main(self, argv, env):
        """Run ``manage.main(argv)``; returns (code, stdout, stderr). No DB seam: the
        command must not connect."""
        out, err = io.StringIO(), io.StringIO()
        with patch.object(manage, "connect", side_effect=AssertionError("mail-check connected")), \
             patch.object(manage, "load_dotenv"), \
             patch.dict(manage.os.environ, env, clear=True), \
             redirect_stdout(out), redirect_stderr(err):
            code = manage.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_file_mail_is_written_and_needs_no_database(self):
        with tempfile.TemporaryDirectory() as outbox:
            code, out, err = self.run_main(["mail-check", "--to", "ops@example.com"],
                                           {"MAIL_PROVIDER": "file", "MAIL_OUTBOX_DIR": outbox})

            self.assertEqual(code, 0, err)
            files = list(Path(outbox).glob("*.json"))
            self.assertEqual(len(files), 1)
            mail = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(mail["to"], "ops@example.com")
        self.assertEqual(mail["subject"], "PulseNet mail check")
        self.assertIn("http://localhost:5173", mail["text"])
        self.assertEqual(out.splitlines(), [
            f"manage: mail file outbox at {outbox}",
            "manage: reset links point to http://localhost:5173",
            "manage: sent a test mail to ops@example.com",
        ])

    def test_smtp_settings_are_shown_without_the_password(self):
        env = {"MAIL_PROVIDER": "smtp", "SMTP_HOST": "smtp.gmail.com", "SMTP_USER": "bot@example.test",
               "SMTP_PASSWORD": "secret-app-pass", "APP_BASE_URL": "http://63.179.249.8:8080"}
        with patch.object(mailer.SmtpMailer, "send") as send:
            code, out, err = self.run_main(["mail-check", "--to", "ops@example.com"], env)

        self.assertEqual(code, 0, err)
        self.assertEqual(send.call_args.args[0].to, "ops@example.com")
        self.assertIn("manage: mail smtp smtp.gmail.com:587 as bot@example.test", out)
        self.assertIn("manage: reset links point to http://63.179.249.8:8080", out)
        self.assertNotIn("secret-app-pass", out + err)

    def test_mail_off_or_broken_exits_2(self):
        for env, needle in (({}, "MAIL_PROVIDER is not set"),
                            ({"MAIL_PROVIDER": "smtp", "SMTP_HOST": "h", "SMTP_USER": "u",
                              "SMTP_PASSWORD": "p"}, "APP_BASE_URL is not set")):
            with self.subTest(needle=needle):
                code, _out, err = self.run_main(["mail-check", "--to", "ops@example.com"], env)
                self.assertEqual(code, 2)
                self.assertIn(needle, err)

    def test_a_failed_send_exits_1(self):
        env = {"MAIL_PROVIDER": "smtp", "SMTP_HOST": "smtp.gmail.com", "SMTP_USER": "bot@example.test",
               "SMTP_PASSWORD": "secret-app-pass", "APP_BASE_URL": "http://63.179.249.8:8080"}
        failure = mailer.MailError("smtp: SMTPAuthenticationError 535")
        with patch.object(mailer.SmtpMailer, "send", side_effect=failure):
            code, _out, err = self.run_main(["mail-check", "--to", "ops@example.com"], env)

        self.assertEqual(code, 1)
        self.assertIn("manage: MAIL FAILED: smtp: SMTPAuthenticationError 535", err)

    def test_an_address_is_required(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            manage.main(["mail-check"])

        self.assertEqual(ctx.exception.code, 2)


class LlmRecordTests(unittest.TestCase):
    run_main = LlmCheckTests.run_main

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.out = Path(self._dir.name)

    def tearDown(self):
        self._dir.cleanup()

    def record(self, *extra, count=0, env=None):
        conn = FakeConn(fetchone=[("9.7.0",), (count,)])
        argv = ["llm-record", "--out-dir", str(self.out), *extra]
        code, out, err = self.run_main(argv, conn, {**ENV, "LLM_PROVIDER": "fake", **(env or {})})
        return code, out, err, conn

    def test_dry_run_shows_the_plan_and_makes_no_call(self):
        code, out, err, conn = self.record("--dry-run", count=5)

        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertEqual(lines[0], "manage: MySQL 9.7.0 at db.example.internal, database pulsenet_db")
        self.assertEqual(lines[1], "manage: LLM fake (canned replies, no network)")
        self.assertEqual(lines[2], "manage: today 5/100 LLM calls")
        self.assertTrue(lines[3].startswith("manage: 8 real call(s): moderation_clean, moderation_toxic"))
        self.assertEqual(lines[4], "manage: dry run: no call made")
        self.assertFalse(conn.ran("insert into llm_usage"))
        self.assertEqual(list(self.out.iterdir()), [])
        self.assertTrue(conn.closed)

    def test_it_refuses_to_start_when_the_limit_has_no_room_for_every_call(self):
        code, _out, err, conn = self.record(count=5, env={"LLM_DAILY_LIMIT": "12"})

        self.assertEqual(code, 1)
        self.assertIn("refused: the daily limit leaves room for 7 call(s), and 8 are needed", err)
        self.assertFalse(conn.ran("insert into llm_usage"))
        self.assertEqual(list(self.out.iterdir()), [])

    def test_the_named_cases_are_recorded_once_each(self):
        code, out, err, conn = self.record("--case", "moderation_clean", "--case", "correct_text",
                                           "--case", "moderation_clean", count=3,
                                           env={"LLM_DAILY_LIMIT": "5"})

        self.assertEqual(code, 0, err)
        self.assertIn("manage: 2 real call(s): moderation_clean, correct_text", out)
        self.assertEqual(sorted(p.name for p in (self.out / "fake").iterdir()),
                         ["correct_text.json", "moderation_clean.json"])
        purposes = [params[3] for _sql, params in conn.find("insert into llm_usage")]
        self.assertEqual(purposes, ["moderation", "ai_correct"])
        self.assertIn(f"manage: saved 2 fixture(s) in {self.out / 'fake'}", out)

    def test_an_unknown_case_is_a_usage_error(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            manage.main(["llm-record", "--case", "nope"])

        self.assertEqual(ctx.exception.code, 2)

    def test_a_failed_call_stops_the_run(self):
        timeout = requests.exceptions.ReadTimeout("read timed out")
        with patch.object(requests, "post", side_effect=timeout):
            conn = FakeConn(fetchone=[("9.7.0",), (0,)])
            code, _out, err = self.run_main(["llm-record", "--out-dir", str(self.out)], conn, GEMINI_ENV)

        self.assertEqual(code, 1)
        self.assertIn("manage: LLM FAILED:", err)
        self.assertIn("(stopped, no retry)", err)
        self.assertEqual(len(conn.find("insert into llm_usage")), 1)   # one call, then stop
        self.assertEqual(list(self.out.iterdir()), [])

    def test_bad_llm_settings_exit_2(self):
        code, _out, err = self.run_main(["llm-record"], FakeConn(), {**ENV, "LLM_PROVIDER": "nope"})

        self.assertEqual(code, 2)
        self.assertIn("LLM_PROVIDER must be one of", err)

    def test_a_database_error_exits_1(self):
        with patch.object(manage, "connect", side_effect=manage.mysql.connector.Error("refused")), \
             patch.object(manage, "load_dotenv"), \
             patch.dict(manage.os.environ, {**ENV, "LLM_PROVIDER": "fake"}, clear=True), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            code = manage.main(["llm-record", "--dry-run"])

        self.assertEqual(code, 1)
        self.assertIn("FAILED", err.getvalue())


AGENT_ROW = {"id": 131, "username": "leo_ai", "name": "Leo Marchetti", "personality": "You are Leo."}
ON = {**ENV, "AGENTS_ENABLED": "1"}


class AgentTickTests(unittest.TestCase):
    """agent-tick: every connection is the same FakeConn, seeded with the server
    version, the day's turns (read by manage.py for its status line, then by the
    tick for the cap), then the agent list and what the triggers read."""

    def run_main(self, argv, conn, env):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(manage, "connect", return_value=conn) as connect, \
             patch.object(manage, "load_dotenv"), \
             patch.dict(manage.os.environ, env, clear=True), \
             redirect_stdout(out), redirect_stderr(err):
            code = manage.main(argv)
        self.connect = connect
        return code, out.getvalue(), err.getvalue()

    def likeable(self, turns=4):
        # The version; the turns, twice; the agent; nobody to follow, post 12 to like.
        # (The LLM is off, so no trigger of an LLM skill reads anything.)
        return FakeConn(fetchone=[("9.7.0",), {"turns": turns}, {"turns": turns}],
                        fetchall=[[AGENT_ROW], [], [{"id": 12}]])

    def test_dry_run_with_the_llm_off_shows_the_action_and_writes_nothing(self):
        conn = self.likeable()

        code, out, err = self.run_main(["agent-tick", "--dry-run"], conn, ENV)

        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertRegex(lines[0], r"^manage: LLM off \(LLM_PROVIDER is not set.*\): only like and follow$")
        self.assertEqual(lines[1], "manage: MySQL 9.7.0 at db.example.internal, database pulsenet_db")
        # The agents are off (no AGENTS_ENABLED), and a dry run still shows the tick.
        self.assertEqual(lines[2], "manage: agents off (dry run only), today 4/20 turns")
        self.assertEqual(lines[3], "manage: agent leo_ai, skill like_or_follow: dry_run (like 12)")
        self.assertFalse(conn.ran("insert"))
        self.assertEqual(conn.commits, 0)
        for secret in (ENV["DB_USER"], ENV["DB_PASSWORD"]):
            self.assertNotIn(secret, out + err)

    def test_a_tick_likes_logs_its_turn_and_its_connections_are_utc(self):
        conn = self.likeable()

        code, out, err = self.run_main(["agent-tick"], conn, ON)

        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines()[-2], "manage: agents on, today 4/20 turns")
        self.assertEqual(out.splitlines()[-1], "manage: agent leo_ai, skill like_or_follow: liked (like 12)")
        self.assertEqual(conn.params_for("insert ignore into likes"), (131, 12))
        self.assertEqual(conn.params_for("insert into agent_actions"), (131, "like_or_follow", "liked"))
        self.assertEqual(conn.commits, 1)
        # The first connection only names the target and counts; the tick's read and
        # write are UTC.
        self.assertEqual([c.kwargs for c in self.connect.call_args_list],
                         [{}, {"time_zone": "+00:00"}, {"time_zone": "+00:00"}])
        self.assertTrue(conn.closed)

    def test_off_does_nothing_and_exits_0_for_the_timer(self):
        for env in (ENV, {**ENV, "AGENTS_ENABLED": "0"}, {**ENV, "AGENTS_ENABLED": "off"}):
            with self.subTest(enabled=env.get("AGENTS_ENABLED")):
                conn = self.likeable()

                code, out, err = self.run_main(["agent-tick"], conn, env)

                self.assertEqual((code, err), (0, ""))
                self.assertEqual(out, "manage: agents off (AGENTS_ENABLED is not on): nothing done\n")
                self.connect.assert_not_called()     # no database, no LLM

    def test_an_invalid_setting_exits_2_before_any_connection(self):
        for env, name in (({**ENV, "AGENTS_ENABLED": "maybe"}, "AGENTS_ENABLED"),
                          ({**ON, "AGENTS_MAX_ACTIONS_PER_DAY": "0"}, "AGENTS_MAX_ACTIONS_PER_DAY")):
            with self.subTest(name):
                code, out, err = self.run_main(["agent-tick"], self.likeable(), env)

                self.assertEqual((code, out), (2, ""))
                self.assertIn(f"manage: {name} must be", err)
                self.connect.assert_not_called()

    def test_the_cap_comes_from_the_setting_and_stops_the_tick(self):
        conn = self.likeable(turns=5)

        code, out, err = self.run_main(["agent-tick"], conn, {**ON, "AGENTS_MAX_ACTIONS_PER_DAY": "5"})

        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines()[-2], "manage: agents on, today 5/5 turns")
        self.assertEqual(out.splitlines()[-1], "manage: agent -, skill -: capped (today 5, max 5)")
        self.assertFalse(conn.ran("insert"))

    def test_a_named_agent_that_is_not_there(self):
        conn = FakeConn(fetchone=[("9.7.0",), {"turns": 0}, {"turns": 0}, None])

        code, out, _ = self.run_main(["agent-tick", "--agent", "rex_ai"], conn, ON)

        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[-1], "manage: agent -, skill -: no_agent (asked rex_ai)")
        self.assertEqual(conn.params_for("username = %s"), ("rex_ai",))

    def test_with_the_llm_on_it_names_the_provider(self):
        conn = FakeConn(fetchone=[("9.7.0",), {"turns": 0}, {"turns": 0}], fetchall=[[AGENT_ROW]])

        code, out, err = self.run_main(["agent-tick", "--dry-run"], conn, {**ON, "LLM_PROVIDER": "fake"})

        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines()[1], "manage: LLM fake (canned replies, no network)")
        # Nothing to answer or comment on, and no post yet (MAX(created_at) is NULL):
        # the agent would write its first post. The dry run only sizes the prompt.
        self.assertRegex(out.splitlines()[-1],
                         r"^manage: agent leo_ai, skill write_post: dry_run \(prompt_chars \d+\)$")
        self.assertFalse(conn.ran("insert"))

    def test_a_db_error_exits_1(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(manage, "connect", side_effect=mysql.connector.Error("2003: Can't connect")), \
             patch.object(manage, "load_dotenv"), \
             patch.dict(manage.os.environ, ON, clear=True), \
             redirect_stdout(out), redirect_stderr(err):
            code = manage.main(["agent-tick"])

        self.assertEqual(code, 1)
        self.assertIn("manage: FAILED: 2003: Can't connect", err.getvalue())

    def test_a_db_error_after_the_target_line_closes_that_connection(self):
        conn = FakeConn(raise_on={"select version()": mysql.connector.Error("2013: Lost connection")})

        code, _, err = self.run_main(["agent-tick"], conn, ON)

        self.assertEqual(code, 1)
        self.assertIn("Lost connection", err)
        self.assertTrue(conn.closed)

    def test_no_agent_actions_table_yet_exits_1(self):
        # 008 not applied: the count fails like any DB error, before the tick.
        conn = FakeConn(fetchone=[("9.7.0",)],
                        raise_on={"from agent_actions": mysql.connector.Error("1146: Table doesn't exist")})

        code, _, err = self.run_main(["agent-tick"], conn, ON)

        self.assertEqual(code, 1)
        self.assertIn("1146", err)
        self.assertTrue(conn.closed)


if __name__ == "__main__":
    unittest.main()
