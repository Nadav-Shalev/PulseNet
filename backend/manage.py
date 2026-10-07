"""Admin commands for PulseNet, run by hand (locally, or on the server).

    python backend/manage.py make-admin <username> --dry-run   # show what would change
    python backend/manage.py make-admin <username>             # give the user the admin role

The database settings come from backend/.env (DB_HOST, DB_USER, DB_PASSWORD,
DB_NAME); real environment variables win over it. Every command first prints which
server and database it is about to touch (never the user or the password), so a run
against production is never a surprise. Use --dry-run first, especially on the server.

This is the only way to grant the admin role: no API request can set it, so the
first admin cannot be created through the app.
"""

import argparse
import os
import sys
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
ENV_FILE    = BACKEND_DIR / ".env"
DEFAULT_HOST = "127.0.0.1"   # what mysql.connector uses when DB_HOST is not set


class CommandError(Exception):
    """A problem the CLI reports as a one-line error (exit code 1)."""


def connect():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
    )


def describe_target(cursor):
    """Which server and database this run touches: no credentials, just the
    MySQL version (8.4.x on RDS, 9.x locally), the host and the database name."""
    cursor.execute("SELECT VERSION()")
    version = cursor.fetchone()[0]
    host = os.getenv("DB_HOST") or DEFAULT_HOST
    return f"MySQL {version} at {host}, database {os.getenv('DB_NAME')}"


def make_admin(conn, username, dry_run=False):
    """Give ``username`` the admin role and return what happened, as a sentence.
    Raises CommandError if there is no such user. ``dry_run`` only reads."""
    cursor = conn.cursor()
    cursor.execute("SELECT id, role FROM users WHERE username = %s", (username,))
    row = cursor.fetchone()
    if row is None:
        raise CommandError(f"no user named {username!r}")
    user_id, role = row
    if role == "admin":
        return f"{username} (id {user_id}) is already an admin; nothing changed"
    if dry_run:
        return f"dry run: would make {username} (id {user_id}, now {role!r}) an admin; nothing changed"
    cursor.execute("UPDATE users SET role = 'admin' WHERE id = %s", (user_id,))
    conn.commit()
    return f"{username} (id {user_id}) is now an admin"


def _parse_args(argv):
    parser = argparse.ArgumentParser(prog="manage.py", description="PulseNet admin commands.")
    commands = parser.add_subparsers(dest="command", metavar="command")
    commands.required = True
    admin = commands.add_parser("make-admin", help="give a user the admin role")
    admin.add_argument("username")
    admin.add_argument("--dry-run", action="store_true",
                       help="show the target and what would change, without changing it")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    load_dotenv(ENV_FILE)  # real env vars (e.g. DB_NAME=pulsenet_e2e ...) win over .env
    if not os.getenv("DB_NAME"):
        print("manage: no database: set DB_NAME in backend/.env", file=sys.stderr)
        return 2

    conn = None
    try:
        conn = connect()
        # Flushed, so the target comes first even when stdout is a pipe and an
        # error follows on (unbuffered) stderr.
        print(f"manage: {describe_target(conn.cursor())}", flush=True)
        print(f"manage: {make_admin(conn, args.username, dry_run=args.dry_run)}")
        return 0
    except CommandError as exc:
        print(f"manage: {exc}", file=sys.stderr)
        return 1
    except mysql.connector.Error as exc:
        print(f"manage: FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
