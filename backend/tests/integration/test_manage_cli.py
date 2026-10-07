"""manage.py make-admin against the hand-rolled DB double (no real MySQL).

``manage.connect`` is patched to return a ``FakeConn`` seeded with what the command
reads, in order: the server version, then the user's ``(id, role)`` row.
"""

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import mysql.connector

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import manage  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
