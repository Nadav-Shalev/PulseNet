"""Migration runner tests against the hand-rolled DB double (no real MySQL).

``migrate.connect`` is patched to return a ``FakeConn`` seeded with what the
runner reads (server version, whether the database exists, its tables, applied
versions); assertions are on the SQL it ran and on the CLI exit code / output.

FakeConn rows are served in order:
  * fetchone: ``SELECT VERSION()``, then the database-exists lookup (main only).
  * fetchall: the table list, then the applied versions (only if tracked).
"""

import io
import sys
import tempfile
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

import migrate  # noqa: E402
from support import FakeConn, FakeCursor  # noqa: E402

PULSENET_TABLES = [("users",), ("sessions",), ("posts",), ("tags",), ("posts_tags",), ("follows",)]


class _FailingCursor(FakeCursor):
    def execute(self, sql, params=None):
        super().execute(sql, params)
        if self._conn.fail_on in " ".join(sql.split()).lower():
            raise mysql.connector.Error("boom")


class FailingConn(FakeConn):
    """FakeConn whose cursors raise on the first statement containing ``fail_on``."""

    def __init__(self, fail_on, **kwargs):
        super().__init__(**kwargs)
        self.fail_on = fail_on.lower()

    def cursor(self, dictionary=False, **_kwargs):
        return _FailingCursor(self)


class MigrationsDirMixin:
    """A temp migrations folder: a 2-statement baseline and one follow-up migration."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        (self.folder / "000_baseline.sql").write_text(
            "-- baseline\nCREATE TABLE users (id INT);\nCREATE TABLE posts (id INT);\n",
            encoding="utf-8",
        )
        (self.folder / "001_add_likes.sql").write_text(
            "CREATE TABLE likes (user_id INT, post_id INT);\n", encoding="utf-8",
        )
        self.migrations = migrate.discover_migrations(self.folder)
        self.log = []

    def recorded_versions(self, conn):
        return [params[0] for _sql, params in conn.find("INSERT INTO schema_migrations")]


class MigrateTests(MigrationsDirMixin, unittest.TestCase):
    def test_empty_database_runs_baseline_then_pending(self):
        conn = FakeConn(fetchall=[[]])

        applied = migrate.migrate(conn, self.migrations, log=self.log.append)

        self.assertEqual(applied, ["000_baseline", "001_add_likes"])
        self.assertTrue(conn.ran("CREATE TABLE IF NOT EXISTS schema_migrations"))
        self.assertTrue(conn.ran("CREATE TABLE users"))
        self.assertTrue(conn.ran("CREATE TABLE likes"))
        self.assertEqual(self.recorded_versions(conn), ["000_baseline", "001_add_likes"])
        # One commit after creating the tracking table, then one per migration.
        self.assertEqual(conn.commits, 3)

    def test_statements_run_in_file_order_before_the_version_is_recorded(self):
        conn = FakeConn(fetchall=[[]])
        migrate.migrate(conn, self.migrations, log=self.log.append)

        sqls = [" ".join(sql.split()) for sql, _ in conn.executed]
        self.assertLess(sqls.index("CREATE TABLE users (id INT)"),
                        sqls.index("CREATE TABLE posts (id INT)"))
        first_insert = next(i for i, s in enumerate(sqls) if s.startswith("INSERT INTO schema_migrations"))
        self.assertGreater(first_insert, sqls.index("CREATE TABLE posts (id INT)"))

    def test_existing_pulsenet_db_is_stamped_at_baseline_without_rerunning_it(self):
        # Local pulsenet_db and RDS were built from schema.sql before migrations existed.
        conn = FakeConn(fetchall=[PULSENET_TABLES])

        applied = migrate.migrate(conn, self.migrations, log=self.log.append)

        self.assertEqual(applied, ["001_add_likes"])
        self.assertFalse(conn.ran("CREATE TABLE users"))
        self.assertTrue(conn.ran("CREATE TABLE likes"))
        self.assertEqual(self.recorded_versions(conn), ["000_baseline", "001_add_likes"])
        self.assertTrue(any("stamped" in line for line in self.log))

    def test_tracked_database_applies_only_unrecorded_versions(self):
        conn = FakeConn(fetchall=[PULSENET_TABLES + [("schema_migrations",)], [("000_baseline",)]])

        applied = migrate.migrate(conn, self.migrations, log=self.log.append)

        self.assertEqual(applied, ["001_add_likes"])
        self.assertFalse(conn.ran("CREATE TABLE IF NOT EXISTS schema_migrations"))
        self.assertEqual(self.recorded_versions(conn), ["001_add_likes"])

    def test_up_to_date_database_runs_nothing(self):
        conn = FakeConn(fetchall=[
            PULSENET_TABLES + [("schema_migrations",)],
            [("000_baseline",), ("001_add_likes",)],
        ])

        applied = migrate.migrate(conn, self.migrations, log=self.log.append)

        self.assertEqual(applied, [])
        self.assertFalse(conn.ran("CREATE TABLE"))
        self.assertEqual(self.recorded_versions(conn), [])
        self.assertIn("up to date", self.log[-1])

    def test_non_pulsenet_database_is_refused(self):
        conn = FakeConn(fetchall=[[("wp_posts",), ("wp_users",)]])

        with self.assertRaisesRegex(migrate.MigrationError, "not empty"):
            migrate.migrate(conn, self.migrations, log=self.log.append)
        self.assertFalse(conn.ran("CREATE TABLE"))

    def test_failed_statement_names_the_migration_and_is_not_recorded(self):
        conn = FailingConn("create table likes", fetchall=[PULSENET_TABLES])

        with self.assertRaisesRegex(migrate.MigrationError, r"001_add_likes.*statement 1.*boom"):
            migrate.migrate(conn, self.migrations, log=self.log.append)
        self.assertEqual(self.recorded_versions(conn), ["000_baseline"])

    def test_pending_migrations_reports_without_writing(self):
        conn = FakeConn(fetchall=[PULSENET_TABLES])
        cursor = conn.cursor()

        pending = migrate.pending_migrations(cursor, self.migrations)

        self.assertEqual([m.version for m in pending], ["001_add_likes"])
        self.assertFalse(conn.ran("CREATE"))
        self.assertFalse(conn.ran("INSERT"))


class MainCliTests(MigrationsDirMixin, unittest.TestCase):
    def run_main(self, argv, conn, env=None):
        """Run ``migrate.main(argv)`` with the DB seam patched; returns (code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        env = {"DB_NAME": "pulsenet_db"} if env is None else env
        with patch.object(migrate, "connect", return_value=conn) as connect, \
             patch.object(migrate, "MIGRATIONS_DIR", self.folder), \
             patch.object(migrate, "load_dotenv"), \
             patch.dict(migrate.os.environ, env, clear=True), \
             redirect_stdout(out), redirect_stderr(err):
            code = migrate.main(argv)
        self.connect = connect
        return code, out.getvalue(), err.getvalue()

    def test_reset_drops_creates_and_builds_the_e2e_database(self):
        conn = FakeConn(fetchone=[("9.7.0",)], fetchall=[[]])

        code, out, _ = self.run_main(["--db", "pulsenet_e2e", "--reset"], conn)

        self.assertEqual(code, 0)
        self.assertTrue(conn.ran("DROP DATABASE IF EXISTS `pulsenet_e2e`"))
        self.assertTrue(conn.ran("CREATE DATABASE `pulsenet_e2e`"))
        self.assertTrue(conn.ran("USE `pulsenet_e2e`"))
        self.assertEqual(self.recorded_versions(conn), ["000_baseline", "001_add_likes"])
        self.assertIn("MySQL 9.7.0", out)
        self.assertTrue(conn.closed)

    def test_reset_is_refused_for_a_real_database(self):
        conn = FakeConn()

        code, _, err = self.run_main(["--db", "pulsenet_db", "--reset"], conn)

        self.assertEqual(code, 2)
        self.assertIn("--reset", err)
        self.connect.assert_not_called()

    def test_defaults_to_db_name_from_env_and_creates_it_if_missing(self):
        conn = FakeConn(fetchone=[("8.0.39",), None], fetchall=[[]])

        code, _, _ = self.run_main([], conn, env={"DB_NAME": "pulsenet_db"})

        self.assertEqual(code, 0)
        self.assertEqual(conn.params_for("information_schema.schemata"), ("pulsenet_db",))
        self.assertTrue(conn.ran("CREATE DATABASE `pulsenet_db`"))
        self.assertFalse(conn.ran("DROP DATABASE"))

    def test_existing_database_is_not_recreated(self):
        conn = FakeConn(fetchone=[("8.0.39",), ("pulsenet_db",)], fetchall=[PULSENET_TABLES])

        code, out, _ = self.run_main([], conn)

        self.assertEqual(code, 0)
        self.assertFalse(conn.ran("CREATE DATABASE"))
        self.assertIn("001_add_likes", out)

    def test_missing_db_name_is_a_usage_error(self):
        code, _, err = self.run_main([], FakeConn(), env={})

        self.assertEqual(code, 2)
        self.assertIn("DB_NAME", err)
        self.connect.assert_not_called()

    def test_unsafe_db_name_is_a_usage_error(self):
        code, _, err = self.run_main(["--db", "x`; DROP DATABASE y"], FakeConn())

        self.assertEqual(code, 2)
        self.assertIn("invalid database name", err)
        self.connect.assert_not_called()

    def test_status_lists_applied_and_pending_without_writing(self):
        conn = FakeConn(
            fetchone=[("8.0.39",), ("pulsenet_db",)],
            fetchall=[PULSENET_TABLES + [("schema_migrations",)], [("000_baseline",)]],
        )

        code, out, _ = self.run_main(["--status"], conn)

        self.assertEqual(code, 0)
        self.assertRegex(out, r"applied\s+000_baseline")
        self.assertRegex(out, r"pending\s+001_add_likes")
        self.assertFalse(conn.ran("CREATE"))
        self.assertFalse(conn.ran("INSERT"))

    def test_status_of_missing_database_lists_everything_pending(self):
        conn = FakeConn(fetchone=[("8.0.39",), None])

        code, out, _ = self.run_main(["--status"], conn)

        self.assertEqual(code, 0)
        self.assertIn("does not exist", out)
        self.assertRegex(out, r"pending\s+000_baseline")
        self.assertFalse(conn.ran("CREATE"))
        self.assertFalse(conn.ran("USE `"))

    def test_connection_failure_exits_1(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(migrate, "connect", side_effect=mysql.connector.Error("refused")), \
             patch.object(migrate, "load_dotenv"), \
             patch.dict(migrate.os.environ, {"DB_NAME": "pulsenet_db"}, clear=True), \
             redirect_stdout(out), redirect_stderr(err):
            code = migrate.main([])

        self.assertEqual(code, 1)
        self.assertIn("refused", err.getvalue())

    def test_failed_migration_exits_1_and_closes_the_connection(self):
        conn = FailingConn("create table likes", fetchone=[("8.0.39",), ("pulsenet_db",)],
                           fetchall=[PULSENET_TABLES])

        code, _, err = self.run_main([], conn)

        self.assertEqual(code, 1)
        self.assertIn("001_add_likes", err)
        self.assertTrue(conn.closed)

    def test_real_migrations_folder_builds_a_fresh_database(self):
        # Not run_main: that points MIGRATIONS_DIR at the temp folder.
        conn = FakeConn(fetchone=[("9.7.0",)], fetchall=[[]])
        out, err = io.StringIO(), io.StringIO()
        with patch.object(migrate, "connect", return_value=conn), \
             patch.object(migrate, "load_dotenv"), \
             patch.dict(migrate.os.environ, {}, clear=True), \
             redirect_stdout(out), redirect_stderr(err):
            code = migrate.main(["--db", "pulsenet_test", "--reset"])

        self.assertEqual(code, 0, err.getvalue())
        for table in ("users", "sessions", "posts", "tags", "posts_tags", "follows"):
            with self.subTest(table=table):
                self.assertTrue(conn.ran(f"CREATE TABLE IF NOT EXISTS {table}"))
        # Later migrations have no IF NOT EXISTS: a table that already exists is drift.
        self.assertTrue(conn.ran("CREATE TABLE likes ("))
        self.assertTrue(conn.ran("CREATE TABLE comments ("))
        self.assertTrue(conn.ran("CREATE TABLE llm_usage ("))
        self.assertTrue(conn.ran("CREATE TABLE reports ("))
        self.assertTrue(conn.ran("CREATE TABLE password_resets ("))
        # 007 is data: the ten agent accounts.
        self.assertTrue(conn.ran("INSERT INTO users (name, username, email, bio, avatar, "
                                 "profile_image, password_hash, is_agent, personality) VALUES"))
        # Every migration file ran and was recorded, in number order.
        everything = [m.version for m in migrate.discover_migrations(migrate.MIGRATIONS_DIR)]
        self.assertEqual(self.recorded_versions(conn), everything)


if __name__ == "__main__":
    unittest.main()
