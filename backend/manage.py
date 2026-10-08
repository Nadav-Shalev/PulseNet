"""Admin commands for PulseNet, run by hand (locally, or on the server).

    python backend/manage.py make-admin <username> --dry-run   # show what would change
    python backend/manage.py make-admin <username>             # give the user the admin role
    python backend/manage.py llm-check [--prompt TEXT]         # one real call through the LLM service
    python backend/manage.py mail-check --to ADDRESS           # one real mail through the mailer

The database settings come from backend/.env (DB_HOST, DB_USER, DB_PASSWORD,
DB_NAME); real environment variables win over it. Every command first prints which
server and database it is about to touch (never the user or the password), so a run
against production is never a surprise. Use --dry-run first, especially on the server.

make-admin is the only way to grant the admin role: no API request can set it, so the
first admin cannot be created through the app.

llm-check sends one prompt through the LLM service with the LLM_* settings (see
backend/llm/config.py) and prints the provider, model and host it used (never the
key), the reply, the time it took and today's count. The call is logged in llm_usage
and counts against the daily limit like any other.

mail-check sends one test mail with the MAIL_* / SMTP_* settings (see
backend/mailer.py) and prints the mailer it used (never the password) and where
reset links will point (APP_BASE_URL). It needs no database.
"""

import argparse
import os
import sys
import time
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

import llm
import mailer
import password_reset

BACKEND_DIR = Path(__file__).resolve().parent
ENV_FILE    = BACKEND_DIR / ".env"
DEFAULT_HOST = "127.0.0.1"   # what mysql.connector uses when DB_HOST is not set
DEFAULT_CHECK_PROMPT = "In one short sentence, say hello to PulseNet."
MAX_SHOWN_REPLY = 300        # llm-check prints at most this much of the reply


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


def _shorten(text):
    text = " ".join(text.split())
    return text if len(text) <= MAX_SHOWN_REPLY else text[:MAX_SHOWN_REPLY].rstrip() + "..."


def _parse_args(argv):
    parser = argparse.ArgumentParser(prog="manage.py", description="PulseNet admin commands.")
    commands = parser.add_subparsers(dest="command", metavar="command")
    commands.required = True
    admin = commands.add_parser("make-admin", help="give a user the admin role")
    admin.add_argument("username")
    admin.add_argument("--dry-run", action="store_true",
                       help="show the target and what would change, without changing it")
    check = commands.add_parser("llm-check", help="send one prompt through the LLM service")
    check.add_argument("--prompt", default=DEFAULT_CHECK_PROMPT,
                       help="what to ask (default: a one-sentence hello)")
    mail = commands.add_parser("mail-check", help="send one test mail through the mailer")
    mail.add_argument("--to", required=True, help="the address to send it to")
    return parser.parse_args(argv)


def _run_make_admin(args):
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


def _run_llm_check(args):
    try:
        service = llm.from_env(os.environ, connect=connect)
    except llm.LLMConfigError as exc:
        print(f"manage: {exc}", file=sys.stderr)
        return 2
    if hasattr(sys.stdout, "reconfigure"):
        # A reply may hold emoji or Hebrew; a Windows pipe would otherwise raise
        # UnicodeEncodeError on them.
        sys.stdout.reconfigure(errors="backslashreplace")
    conn = None
    try:
        conn = connect()
        print(f"manage: {describe_target(conn.cursor())}", flush=True)
        print(f"manage: LLM {service.describe()}", flush=True)
        started = time.monotonic()
        reply = service.complete(args.prompt, purpose="check")
        elapsed_ms = int((time.monotonic() - started) * 1000)
        print(f"manage: reply in {elapsed_ms} ms: {_shorten(reply)}")
        used, limit = service.usage_today()
        print(f"manage: today {used}/{limit} LLM calls")
        return 0
    except llm.LLMError as exc:
        print(f"manage: LLM FAILED: {exc}", file=sys.stderr)
        return 1
    except mysql.connector.Error as exc:
        print(f"manage: FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


def _run_mail_check(args):
    try:
        sender = mailer.from_env(os.environ)
        base = password_reset.base_url(os.environ)
    except mailer.MailConfigError as exc:
        print(f"manage: {exc}", file=sys.stderr)
        return 2
    print(f"manage: mail {sender.describe()}", flush=True)
    print(f"manage: reset links point to {base}", flush=True)
    check = mailer.Mail(
        to=args.to,
        subject="PulseNet mail check",
        text=f"This is a test mail from manage.py mail-check.\n\nReset links will point to {base}.\n",
        html=f"<p>This is a test mail from manage.py mail-check.</p><p>Reset links will point to {base}.</p>",
    )
    try:
        sender.send(check)
    except mailer.MailError as exc:
        print(f"manage: MAIL FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"manage: sent a test mail to {args.to}")
    return 0


def main(argv=None):
    args = _parse_args(argv)
    load_dotenv(ENV_FILE)  # real env vars (e.g. DB_NAME=pulsenet_e2e ...) win over .env
    if args.command == "mail-check":
        return _run_mail_check(args)      # no database involved
    if not os.getenv("DB_NAME"):
        print("manage: no database: set DB_NAME in backend/.env", file=sys.stderr)
        return 2
    if args.command == "llm-check":
        return _run_llm_check(args)
    return _run_make_admin(args)


if __name__ == "__main__":
    sys.exit(main())
