"""Admin commands for PulseNet, run by hand (locally, or on the server).

    python backend/manage.py seed-agent-content [--dry-run]  # offline, additive demo posts
    python backend/manage.py make-admin <username> --dry-run   # show what would change
    python backend/manage.py make-admin <username>             # give the user the admin role
    python backend/manage.py llm-check [--prompt TEXT]         # one real call through the LLM service
    python backend/manage.py mail-check --to ADDRESS           # one real mail through the mailer
    python backend/manage.py llm-record [--case NAME] --dry-run  # the recording it would make
    python backend/manage.py llm-record [--case NAME ...]      # record replies for the replay tests
    python backend/manage.py agent-tick [--agent NAME] --dry-run  # what one agent would do
    python backend/manage.py agent-tick [--agent NAME]         # one agent does one thing

The database settings come from backend/.env (DB_HOST, DB_USER, DB_PASSWORD,
DB_NAME); real environment variables win over it. Every command first prints which
server and database it is about to touch (never the user or the password), so a run
against production is never a surprise. Use --dry-run first, especially on the server.

seed-agent-content adds only missing hand-written demo posts to the ten existing
agent accounts. It makes no external calls and does not change existing data.
--dry-run reports missing/existing posts without writes.

make-admin is the only way to grant the admin role: no API request can set it, so the
first admin cannot be created through the app.

llm-check sends one prompt through the LLM service with the LLM_* settings (see
backend/llm/config.py) and prints the provider, model and host it used (never the
key), the reply, the time it took and today's count. The call is logged in llm_usage
and counts against the daily limit like any other.

mail-check sends one test mail with the MAIL_* / SMTP_* settings (see
backend/mailer.py) and prints the mailer it used (never the password) and where
reset links will point (APP_BASE_URL). It needs no database.

llm-record makes one real call per case of llm_replay.py (all eight, or the ones
named with --case) and saves each reply as a fixture of the replay tests. It
first prints today's count and refuses to start unless the daily limit leaves room
for every call, so set LLM_DAILY_LIMIT to today's count plus the number of cases:
the limit is then the hard stop. The first failure stops it, with no retry.
--dry-run shows all of this and makes no call.

agent-tick runs one tick of the AI agents (backend/agents/): one agent, the next in
turn or the one named with --agent, does at most one thing: reply, comment, post,
like or follow. A text action is one LLM call to write it plus the moderation call,
both in llm_usage and under the daily limit; with the LLM off (LLM_PROVIDER unset)
only like and follow can happen. It does nothing unless AGENTS_ENABLED is on, and
stops once the day has AGENTS_MAX_ACTIONS_PER_DAY turns (backend/agents/config.py);
both exit 0, so the timer that runs it (deploy/systemd/) is not marked failed.
--dry-run makes the reads and shows the action and the prompt size, with no LLM
call and no write, even with the agents off.
"""

import argparse
import os
import sys
import time
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

import agents
import llm
import llm_replay
import mailer
import moderation
import password_reset
import seed_data

BACKEND_DIR = Path(__file__).resolve().parent
ENV_FILE    = BACKEND_DIR / ".env"
DEFAULT_HOST = "127.0.0.1"   # what mysql.connector uses when DB_HOST is not set
DB_TIME_ZONE = "+00:00"      # the agents' connections, like app.py's
DEFAULT_CHECK_PROMPT = "In one short sentence, say hello to PulseNet."
MAX_SHOWN_REPLY = 300        # llm-check prints at most this much of the reply


class CommandError(Exception):
    """A problem the CLI reports as a one-line error (exit code 1)."""


def connect(**options):
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        **options,
    )


def connect_utc():
    return connect(time_zone=DB_TIME_ZONE)


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
    rec = commands.add_parser("llm-record", help="record real LLM replies for the replay tests")
    rec.add_argument("--case", action="append", choices=list(llm_replay.CASES_BY_NAME),
                     help="record only this case (repeatable; default: all)")
    rec.add_argument("--dry-run", action="store_true",
                     help="show the target, today's count and the cases, without calling")
    rec.add_argument("--out-dir", default=str(llm_replay.FIXTURES_DIR),
                     help="where the fixtures go (default: backend/tests/fixtures/llm_replies)")
    tick = commands.add_parser("agent-tick", help="one AI agent does one thing")
    tick.add_argument("--agent", help="the agent's username (default: the next in turn)")
    tick.add_argument("--dry-run", action="store_true",
                      help="show the agent, the action and the prompt size, without calling or writing")
    seed = commands.add_parser("seed-agent-content", help="add missing offline agent demo posts")
    seed.add_argument("--dry-run", action="store_true",
                      help="show the target and missing post count without writing")
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


def _run_llm_record(args):
    try:
        service = llm.from_env(os.environ, connect=connect)
    except llm.LLMConfigError as exc:
        print(f"manage: {exc}", file=sys.stderr)
        return 2
    names = args.case or list(llm_replay.CASES_BY_NAME)
    cases = [llm_replay.CASES_BY_NAME[name] for name in dict.fromkeys(names)]
    conn = None
    try:
        conn = connect()
        print(f"manage: {describe_target(conn.cursor())}", flush=True)
        print(f"manage: LLM {service.describe()}", flush=True)
        used, limit = service.usage_today()
        print(f"manage: today {used}/{limit} LLM calls", flush=True)
        print(f"manage: {len(cases)} real call(s): {', '.join(case.name for case in cases)}", flush=True)
        if args.dry_run:
            print("manage: dry run: no call made")
            return 0
        # Start only if every call fits: a half-made recording would need a second run.
        if used + len(cases) > limit:
            print(f"manage: refused: the daily limit leaves room for {max(limit - used, 0)} call(s), "
                  f"and {len(cases)} are needed (LLM_DAILY_LIMIT)", file=sys.stderr)
            return 1
        written = llm_replay.record(service, cases, args.out_dir,
                                    log=lambda line: print(f"manage: {line}", flush=True))
        print(f"manage: saved {len(written)} fixture(s) in "
              f"{Path(args.out_dir) / service.provider.name}")
        return 0
    except llm.LLMError as exc:
        print(f"manage: LLM FAILED: {exc} (stopped, no retry)", file=sys.stderr)
        return 1
    except mysql.connector.Error as exc:
        print(f"manage: FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


def _run_agent_tick(args):
    try:
        settings = agents.config.from_env(os.environ)
    except agents.config.AgentsConfigError as exc:
        print(f"manage: {exc}", file=sys.stderr)
        return 2
    if not settings.enabled and not args.dry_run:
        print("manage: agents off (AGENTS_ENABLED is not on): nothing done")
        return 0
    try:
        service = llm.from_env(os.environ, connect=connect)
    except llm.LLMConfigError as exc:
        service = None   # off or misconfigured: the agents can still like and follow
        print(f"manage: LLM off ({exc}): only like and follow", flush=True)
    conn = None
    try:
        conn = connect()
        print(f"manage: {describe_target(conn.cursor())}", flush=True)
        if service is not None:
            print(f"manage: LLM {service.describe()}", flush=True)
        turns = agents.store.actions_today(conn.cursor(dictionary=True))
        print(f"manage: agents {'on' if settings.enabled else 'off (dry run only)'}, "
              f"today {turns}/{settings.max_actions_per_day} turns", flush=True)
        conn.close()
        conn = None
        result = agents.run_tick(service, moderation.Moderator(service), connect_utc,
                                 agent=args.agent, dry_run=args.dry_run,
                                 max_actions=settings.max_actions_per_day)
        detail = ", ".join(f"{key} {value}" for key, value in result.detail.items())
        print(f"manage: agent {result.agent or '-'}, skill {result.skill or '-'}: "
              f"{result.outcome}" + (f" ({detail})" if detail else ""))
        return 0
    except mysql.connector.Error as exc:
        print(f"manage: FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


def _run_seed_agent_content(args):
    conn = None
    try:
        conn = connect_utc()
        with conn.cursor() as cursor:
            print(f"manage: {describe_target(cursor)}", flush=True)
        result = seed_data.seed_agent_content(conn, dry_run=args.dry_run)
        if args.dry_run:
            print(f"manage: dry run: would insert {result['would_insert']}, "
                  f"skipped {result['skipped']}; nothing changed")
        else:
            print(f"manage: agent demo posts: inserted {result['inserted']}, "
                  f"skipped {result['skipped']}")
        return 0
    except seed_data.SeedError as exc:
        print(f"manage: {exc}", file=sys.stderr)
        return 1
    except mysql.connector.Error as exc:
        print(f"manage: FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


def main(argv=None):
    args = _parse_args(argv)
    load_dotenv(ENV_FILE)  # real env vars (e.g. DB_NAME=pulsenet_e2e ...) win over .env
    if args.command == "mail-check":
        return _run_mail_check(args)      # no database involved
    if not os.getenv("DB_NAME"):
        print("manage: no database: set DB_NAME in backend/.env", file=sys.stderr)
        return 2
    if args.command == "seed-agent-content":
        return _run_seed_agent_content(args)
    if args.command == "llm-check":
        return _run_llm_check(args)
    if args.command == "llm-record":
        return _run_llm_record(args)
    if args.command == "agent-tick":
        return _run_agent_tick(args)
    return _run_make_admin(args)


if __name__ == "__main__":
    sys.exit(main())
