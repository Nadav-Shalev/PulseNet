"""Versioned schema migrations for PulseNet, in Python (no `mysql` CLI needed).

    python backend/migrate.py                             # migrate DB_NAME from backend/.env
    python backend/migrate.py --db pulsenet_e2e           # another database (created if missing)
    python backend/migrate.py --db pulsenet_e2e --reset   # drop + rebuild (*_e2e / *_test only)
    python backend/migrate.py --status                    # list applied / pending, change nothing

Migrations are ``database/migrations/NNN_<name>.sql`` files applied in number order.
Each applied version is recorded in the ``schema_migrations`` table, so every run
applies only what is still pending — the same command works on a fresh database,
the local dev database and RDS.

``000_baseline.sql`` is the schema as it was when migrations were introduced. It
runs only on an empty database; a database that already has the PulseNet tables
but no ``schema_migrations`` (built from ``schema.sql`` earlier) is stamped as being
at the baseline instead, and only later migrations run on it.

MySQL commits DDL implicitly, so a migration that fails halfway cannot be rolled
back: keep each migration small, and fix the database by hand if one fails.
"""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

import mysql.connector
from dotenv import load_dotenv

BACKEND_DIR    = Path(__file__).resolve().parent
ENV_FILE       = BACKEND_DIR / ".env"
MIGRATIONS_DIR = BACKEND_DIR.parent / "database" / "migrations"

BASELINE         = "000_baseline"
MIGRATIONS_TABLE = "schema_migrations"
MIGRATION_FILE_RE = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
# Database names are interpolated into SQL inside backticks (identifiers cannot be
# bound as query params), so only a safe charset is accepted.
DB_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
# --reset drops the database: allowed only for throwaway test databases.
RESETTABLE_DB_RE = re.compile(r"_(e2e|test)$")

CREATE_MIGRATIONS_TABLE = (
    f"CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} ("
    " version    VARCHAR(100) NOT NULL PRIMARY KEY,"
    " applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
    ")"
)
RECORD_VERSION = f"INSERT INTO {MIGRATIONS_TABLE} (version) VALUES (%s)"


class MigrationError(Exception):
    """A migration problem the CLI reports as a one-line error (exit code 1)."""


class Migration(NamedTuple):
    version: str  # file name without .sql, e.g. "001_add_likes"
    path: Path


# ─── Pure helpers ─────────────────────────────────────────────────────────────

def split_sql(text):
    """Split a SQL script into statements, dropping comments and empty statements.

    mysql.connector runs one statement per ``execute()``, so the script is split on
    ``;`` — except inside quotes ('...', "...", `...`) and comments (``-- ``, ``#``,
    ``/* */``). Stored-procedure ``DELIMITER`` blocks are not supported.
    """
    statements, current = [], []
    i, n = 0, len(text)
    quote = None

    def flush():
        statement = "".join(current).strip()
        if statement:
            statements.append(statement)
        current.clear()

    while i < n:
        ch = text[i]
        if quote:
            current.append(ch)
            if ch == "\\" and quote != "`" and i + 1 < n:
                current.append(text[i + 1])  # backslash escape: keep the next char as-is
                i += 2
                continue
            if ch == quote:
                quote = None  # a doubled quote ('') just closes and reopens
            i += 1
        elif ch in "'\"`":
            quote = ch
            current.append(ch)
            i += 1
        elif ch == "#" or (text.startswith("--", i) and (i + 2 == n or text[i + 2].isspace())):
            end = text.find("\n", i)
            i = n if end == -1 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end == -1:
                raise MigrationError("unterminated /* comment */")
            current.append(" ")
            i = end + 2
        elif ch == ";":
            flush()
            i += 1
        else:
            current.append(ch)
            i += 1

    if quote:
        raise MigrationError(f"unterminated {quote}-quoted string")
    flush()
    return statements


def discover_migrations(directory):
    """Return the ``NNN_name.sql`` files in ``directory`` sorted by number.

    Badly named ``.sql`` files and duplicate numbers are errors (two branches that
    both added 001 must not merge silently), and ``000_baseline.sql`` must exist.
    """
    by_number = {}
    for path in sorted(Path(directory).glob("*.sql")):
        match = MIGRATION_FILE_RE.match(path.name)
        if not match:
            raise MigrationError(f"bad migration file name '{path.name}' (expected NNN_lower_snake.sql)")
        number = match.group(1)
        if number in by_number:
            raise MigrationError(
                f"duplicate migration number {number}: {by_number[number].path.name} and {path.name}"
            )
        by_number[number] = Migration(path.stem, path)

    migrations = [by_number[number] for number in sorted(by_number)]
    if not migrations or migrations[0].version != BASELINE:
        raise MigrationError(f"{BASELINE}.sql must be the first migration in {directory}")
    return migrations


def validate_db_name(name):
    if not isinstance(name, str) or not DB_NAME_RE.match(name):
        raise MigrationError(f"invalid database name {name!r} (letters, digits and _ only)")


def is_resettable(name):
    return bool(RESETTABLE_DB_RE.search(name))


# ─── DB access ────────────────────────────────────────────────────────────────

def connect():
    """Server-level connection (no database selected) so we can CREATE/DROP one."""
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def database_exists(cursor, name):
    cursor.execute(
        "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s", (name,)
    )
    return cursor.fetchone() is not None


def list_tables(cursor):
    cursor.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'"
    )
    return {row[0] for row in cursor.fetchall()}


def migration_state(cursor):
    """Return ``(tracked, applied_versions)`` for the selected database.

    * tracked (has ``schema_migrations``) → the versions recorded there.
    * empty                               → nothing applied yet.
    * PulseNet tables, untracked          → built before migrations: at the baseline.
    """
    tables = list_tables(cursor)
    if MIGRATIONS_TABLE in tables:
        cursor.execute(f"SELECT version FROM {MIGRATIONS_TABLE}")
        return True, {row[0] for row in cursor.fetchall()}
    if not tables:
        return False, set()
    if "users" not in tables:
        raise MigrationError(
            "database is not empty but has no PulseNet tables; refusing to migrate it"
        )
    return False, {BASELINE}


def pending_migrations(cursor, migrations):
    _tracked, applied = migration_state(cursor)
    return [m for m in migrations if m.version not in applied]


def apply_migration(cursor, migration):
    """Run every statement of one migration file; return how many ran."""
    statements = split_sql(migration.path.read_text(encoding="utf-8"))
    for number, statement in enumerate(statements, 1):
        try:
            cursor.execute(statement)
        except mysql.connector.Error as exc:
            preview = " ".join(statement.split())[:120]
            raise MigrationError(
                f"{migration.version}: statement {number} failed: {exc}\n    {preview}"
            ) from exc
    return len(statements)


def migrate(conn, migrations, log=print):
    """Apply the pending ``migrations`` to the selected database; return their versions.

    Each version is recorded (and committed) right after its statements succeed,
    so a failed run resumes from the failed migration next time.
    """
    cursor = conn.cursor()
    tracked, applied = migration_state(cursor)
    if not tracked:
        cursor.execute(CREATE_MIGRATIONS_TABLE)
        for version in sorted(applied):  # untracked PulseNet DB: stamp, don't re-run
            cursor.execute(RECORD_VERSION, (version,))
            log(f"existing schema stamped as {version}")
        conn.commit()

    newly_applied = []
    for migration in migrations:
        if migration.version in applied:
            continue
        count = apply_migration(cursor, migration)
        cursor.execute(RECORD_VERSION, (migration.version,))
        conn.commit()
        log(f"applied {migration.version} ({count} statement{'' if count == 1 else 's'})")
        newly_applied.append(migration.version)

    cursor.close()
    if not newly_applied:
        log(f"up to date (latest: {migrations[-1].version})")
    return newly_applied


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="migrate.py", description="Apply pending PulseNet schema migrations."
    )
    parser.add_argument("--db", help="database name (default: DB_NAME from backend/.env)")
    parser.add_argument("--reset", action="store_true",
                        help="drop and rebuild the database first (only *_e2e / *_test names)")
    parser.add_argument("--status", action="store_true",
                        help="list applied and pending migrations without changing anything")
    return parser.parse_args(argv)


def _print_status(cursor, migrations, db):
    if not database_exists(cursor, db):
        print(f"migrate: database {db} does not exist")
        pending = migrations
    else:
        cursor.execute(f"USE `{db}`")
        pending = pending_migrations(cursor, migrations)
    for migration in migrations:
        state = "pending" if migration in pending else "applied"
        print(f"  {state:8} {migration.version}")


def main(argv=None):
    args = _parse_args(argv)
    load_dotenv(ENV_FILE)  # real env vars (e.g. set by the e2e runner) win over .env
    db = args.db or os.getenv("DB_NAME")

    def usage_error(message):
        print(f"migrate: {message}", file=sys.stderr)
        return 2

    if not db:
        return usage_error("no database given: pass --db or set DB_NAME in backend/.env")
    try:
        validate_db_name(db)
    except MigrationError as exc:
        return usage_error(str(exc))
    if args.reset and not is_resettable(db):
        return usage_error(f"--reset refused for '{db}': only *_e2e / *_test databases may be dropped")

    def log(message):
        print(f"migrate: {message}")

    conn = None
    try:
        migrations = discover_migrations(MIGRATIONS_DIR)
        conn = connect()
        cursor = conn.cursor()
        cursor.execute("SELECT VERSION()")
        log(f"MySQL {cursor.fetchone()[0]}, database {db}")

        if args.status:
            _print_status(cursor, migrations, db)
            return 0

        if args.reset:
            cursor.execute(f"DROP DATABASE IF EXISTS `{db}`")
            log(f"dropped {db} (--reset)")
            exists = False
        else:
            exists = database_exists(cursor, db)
        if not exists:
            cursor.execute(f"CREATE DATABASE `{db}`")
            log(f"created database {db}")
        cursor.execute(f"USE `{db}`")
        cursor.close()

        migrate(conn, migrations, log=log)
        return 0
    except (MigrationError, mysql.connector.Error) as exc:
        print(f"migrate: FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
