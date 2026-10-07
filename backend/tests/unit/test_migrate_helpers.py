"""Unit tests for the pure helpers in migrate.py (no DB, no mocks).

Covers SQL statement splitting, migration-file discovery/validation, database-name
rules, and guards on the real ``database/migrations`` folder (baseline frozen,
every table in ``schema.sql`` created by some migration).
"""

import hashlib
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import migrate  # noqa: E402

SCHEMA_SQL = BACKEND_DIR.parent / "database" / "schema.sql"

# sha256 of 000_baseline.sql with LF line endings. The baseline is what RDS and the
# local DB were stamped with; editing it would silently desync fresh DBs from them.
BASELINE_SHA256 = "d3c1cc2bad98c8b69dce5af9e1936a260fdf7be4806c4302cfbaf05ba10988ef"


class SplitSqlTests(unittest.TestCase):
    def test_splits_on_semicolons_and_strips_whitespace(self):
        sql = "CREATE TABLE a (id INT);\n\n  CREATE INDEX i ON a(id) ;\n"
        self.assertEqual(
            migrate.split_sql(sql),
            ["CREATE TABLE a (id INT)", "CREATE INDEX i ON a(id)"],
        )

    def test_last_statement_without_semicolon_is_kept(self):
        self.assertEqual(migrate.split_sql("SELECT 1; SELECT 2"), ["SELECT 1", "SELECT 2"])

    def test_line_and_block_comments_are_removed(self):
        sql = (
            "-- leading comment; with a semicolon\n"
            "CREATE TABLE a (id INT); # hash comment; too\n"
            "/* block; comment */ DROP TABLE b;\n"
            "-- trailing comment only\n"
        )
        self.assertEqual(migrate.split_sql(sql), ["CREATE TABLE a (id INT)", "DROP TABLE b"])

    def test_double_dash_without_space_is_not_a_comment(self):
        # MySQL only treats "-- " (dash dash + whitespace) as a comment; "1--1" is math.
        self.assertEqual(migrate.split_sql("SELECT 1--1;"), ["SELECT 1--1"])

    def test_semicolons_inside_quotes_do_not_split(self):
        sql = (
            "INSERT INTO t VALUES ('a;b', \"c;d\");\n"
            "INSERT INTO t VALUES ('it''s; fine', 'esc\\'; still');\n"
            "SELECT `odd;name` FROM t;"
        )
        self.assertEqual(migrate.split_sql(sql), [
            "INSERT INTO t VALUES ('a;b', \"c;d\")",
            "INSERT INTO t VALUES ('it''s; fine', 'esc\\'; still')",
            "SELECT `odd;name` FROM t",
        ])

    def test_comment_markers_inside_quotes_are_kept(self):
        sql = "INSERT INTO t VALUES ('-- not a comment', '# nor this', '/* nor */');"
        self.assertEqual(migrate.split_sql(sql), [sql[:-1]])

    def test_blank_and_comment_only_input_yields_nothing(self):
        self.assertEqual(migrate.split_sql("  \n-- nothing here\n/* x */ ;;\n"), [])

    def test_unterminated_quote_is_an_error(self):
        with self.assertRaises(migrate.MigrationError):
            migrate.split_sql("INSERT INTO t VALUES ('oops);")

    def test_unterminated_block_comment_is_an_error(self):
        with self.assertRaises(migrate.MigrationError):
            migrate.split_sql("SELECT 1; /* never closed")


class DiscoverMigrationsTests(unittest.TestCase):
    def _dir_with(self, *names):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name in names:
            Path(tmp.name, name).write_text("SELECT 1;", encoding="utf-8")
        return Path(tmp.name)

    def test_returns_migrations_in_numeric_order(self):
        folder = self._dir_with("010_ten.sql", "000_baseline.sql", "002_two.sql")
        found = migrate.discover_migrations(folder)
        self.assertEqual([m.version for m in found], ["000_baseline", "002_two", "010_ten"])
        self.assertEqual(found[0].path, folder / "000_baseline.sql")

    def test_non_sql_files_are_ignored(self):
        folder = self._dir_with("000_baseline.sql", "README.md")
        self.assertEqual([m.version for m in migrate.discover_migrations(folder)], ["000_baseline"])

    def test_badly_named_sql_file_is_rejected(self):
        for bad in ("1_short.sql", "001-dash.sql", "001_Upper.sql", "add_likes.sql"):
            with self.subTest(bad=bad):
                folder = self._dir_with("000_baseline.sql", bad)
                with self.assertRaisesRegex(migrate.MigrationError, re.escape(bad)):
                    migrate.discover_migrations(folder)

    def test_duplicate_number_is_rejected(self):
        # Two branches that both picked 001 must not merge silently.
        folder = self._dir_with("000_baseline.sql", "001_likes.sql", "001_roles.sql")
        with self.assertRaisesRegex(migrate.MigrationError, "001"):
            migrate.discover_migrations(folder)

    def test_baseline_must_be_first(self):
        folder = self._dir_with("001_likes.sql")
        with self.assertRaisesRegex(migrate.MigrationError, "000_baseline"):
            migrate.discover_migrations(folder)


class DatabaseNameTests(unittest.TestCase):
    def test_valid_names_pass(self):
        for name in ("pulsenet_db", "pulsenet_e2e", "Db_1"):
            with self.subTest(name=name):
                migrate.validate_db_name(name)

    def test_names_that_could_escape_backticks_are_rejected(self):
        # Identifiers cannot be bound as query params, so only a safe charset is allowed.
        for name in ("", "bad-name", "x`; DROP DATABASE y; --", "a b", "x" * 65, None):
            with self.subTest(name=name):
                with self.assertRaises(migrate.MigrationError):
                    migrate.validate_db_name(name)

    def test_only_e2e_and_test_databases_may_be_reset(self):
        self.assertTrue(migrate.is_resettable("pulsenet_e2e"))
        self.assertTrue(migrate.is_resettable("pulsenet_test"))
        for name in ("pulsenet_db", "e2e_pulsenet", "pulsenet_e2e_copy"):
            with self.subTest(name=name):
                self.assertFalse(migrate.is_resettable(name))


class RealMigrationsFolderTests(unittest.TestCase):
    """Guards on the committed ``database/migrations`` folder."""

    def test_folder_is_valid(self):
        found = migrate.discover_migrations(migrate.MIGRATIONS_DIR)
        self.assertEqual(found[0].version, migrate.BASELINE)
        for m in found:
            with self.subTest(migration=m.version):
                self.assertTrue(migrate.split_sql(m.path.read_text(encoding="utf-8")))

    def test_baseline_is_frozen(self):
        text = (migrate.MIGRATIONS_DIR / "000_baseline.sql").read_text(encoding="utf-8")
        digest = hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()
        self.assertEqual(
            digest, BASELINE_SHA256,
            "000_baseline.sql changed. Never edit it: add a new numbered migration instead.",
        )

    def test_every_schema_table_is_created_by_a_migration(self):
        # schema.sql is the readable full schema; migrations are what actually build
        # databases. A table in one but not the other means they drifted apart.
        create_re = re.compile(r"CREATE TABLE (?:IF NOT EXISTS )?`?(\w+)`?", re.IGNORECASE)
        schema_tables = set(create_re.findall(SCHEMA_SQL.read_text(encoding="utf-8")))
        migration_tables = set()
        for m in migrate.discover_migrations(migrate.MIGRATIONS_DIR):
            migration_tables |= set(create_re.findall(m.path.read_text(encoding="utf-8")))
        self.assertEqual(schema_tables, migration_tables)


if __name__ == "__main__":
    unittest.main()
