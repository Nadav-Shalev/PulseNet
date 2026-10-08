"""Sending email: the password-reset link, for now.

    sender = mailer.from_env(os.environ)        # MailConfigError when mail is off
    sender.send(Mail(to="ada@example.com", subject="...", text="...", html="..."))

MAIL_PROVIDER picks how a mail goes out:

    file   one JSON file per mail in MAIL_OUTBOX_DIR (default backend/outbox/):
           development and the E2E run. Nothing leaves the machine, and a test
           reads the link from the file.
    smtp   a real send through SMTP_HOST:SMTP_PORT (default 587) with STARTTLS,
           logging in as SMTP_USER with SMTP_PASSWORD (production: Google
           Workspace, smtp.gmail.com, an App Password). From: MAIL_FROM (default
           "PulseNet <SMTP_USER>"); SMTP_TIMEOUT_SECONDS 1 to 30 (default 10).

Unset MAIL_PROVIDER means mail is off: the password reset answers 503 rather than
pretend it sent something. Like llm/, this module imports neither Flask nor the
app. Error messages name a variable, never its value, and a send error carries
the SMTP reply code at most: never the password, and never an address.
"""

import json
import secrets
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import NamedTuple

DEFAULT_OUTBOX_DIR = Path(__file__).resolve().parent / "outbox"
DEFAULT_SMTP_PORT = 587
DEFAULT_TIMEOUT_SECONDS = 10
MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS = 1, 30
IMPLICIT_TLS_PORT = 465


class MailError(Exception):
    """A mail could not be sent. The message is safe to log."""


class MailConfigError(MailError):
    """A MAIL_* / SMTP_* setting is missing or invalid (or MAIL_PROVIDER is unset)."""


class Mail(NamedTuple):
    to: str
    subject: str
    text: str
    html: str


def _check_headers(mail):
    # Header injection: a line break in "To" or "Subject" could add a header (Bcc).
    for value in (mail.to, mail.subject):
        if "\r" in value or "\n" in value:
            raise MailError("a mail header holds a line break")


class FileMailer:
    """Writes each mail to ``outbox_dir`` as ``<UTC time>-<random>.json``, so the
    names sort by time and the newest mail is the last file."""

    name = "file"

    def __init__(self, outbox_dir):
        self.outbox_dir = Path(outbox_dir)

    def __repr__(self):
        return f"FileMailer({str(self.outbox_dir)!r})"

    def describe(self):
        return f"file outbox at {self.outbox_dir}"

    def send(self, mail):
        _check_headers(mail)
        now = datetime.now(timezone.utc)
        record = {**mail._asdict(), "sent_at": now.isoformat()}
        path = self.outbox_dir / f"{now:%Y%m%dT%H%M%S%f}Z-{secrets.token_hex(4)}.json"
        try:
            self.outbox_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            raise MailError(f"file: {type(exc).__name__}") from None


class SmtpMailer:
    """Sends through an SMTP server: STARTTLS with a verifying TLS context, then
    login, then the message (a plain-text part and an HTML alternative). One
    connection per mail: there are few, and none is kept open between requests."""

    name = "smtp"

    def __init__(self, host, port, user, password, sender, timeout, smtp=smtplib.SMTP):
        self.host = host
        self.port = port
        self.user = user
        self._password = password
        self.sender = sender
        self.timeout = timeout
        self._smtp = smtp

    def __repr__(self):  # never the password
        return f"SmtpMailer(host={self.host!r}, port={self.port}, user={self.user!r})"

    def describe(self):
        return f"smtp {self.host}:{self.port} as {self.user}"

    def send(self, mail):
        _check_headers(mail)
        message = self._message(mail)
        try:
            with self._smtp(self.host, self.port, timeout=self.timeout) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(self.user, self._password)
                server.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise MailError(f"smtp: {_describe_failure(exc)}") from None

    def _message(self, mail):
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = mail.to
        message["Subject"] = mail.subject
        message["Date"] = formatdate(localtime=False)
        message["Message-ID"] = make_msgid(domain=_domain_of(self.user))
        message.set_content(mail.text)
        message.add_alternative(mail.html, subtype="html")
        return message


class MemoryMailer:
    """For tests: keeps each mail in ``sent``, or raises ``fail`` instead."""

    name = "memory"

    def __init__(self, fail=None):
        self.sent = []
        self.fail = fail

    def describe(self):
        return "memory (test double)"

    def send(self, mail):
        if self.fail is not None:
            raise self.fail
        self.sent.append(mail)


def _describe_failure(exc):
    """The type of a failure and, for an SMTP reply, its code: the reply text and
    a refused recipient's address stay out of the message."""
    code = getattr(exc, "smtp_code", None)
    return f"{type(exc).__name__} {code}" if code else type(exc).__name__


def _domain_of(address):
    return address.rsplit("@", 1)[-1] if "@" in address else None


def from_env(env):
    """The mailer the environment asks for. MailConfigError when mail is off
    (MAIL_PROVIDER unset) or a setting is missing or invalid."""
    name = _get(env, "MAIL_PROVIDER")
    if not name:
        raise MailConfigError("MAIL_PROVIDER is not set, so mail is off "
                              f"(set it to one of: {', '.join(_BUILDERS)})")
    if name not in _BUILDERS:
        raise MailConfigError(f"MAIL_PROVIDER must be one of: {', '.join(_BUILDERS)}")
    return _BUILDERS[name](env)


def _get(env, name):
    return (env.get(name) or "").strip()


def _required(env, name):
    value = _get(env, name)
    if not value:
        raise MailConfigError(f"{name} is not set (MAIL_PROVIDER=smtp needs it)")
    return value


def _port(env):
    raw = _get(env, "SMTP_PORT")
    if not raw:
        return DEFAULT_SMTP_PORT
    try:
        port = int(raw)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        raise MailConfigError("SMTP_PORT must be a port number from 1 to 65535")
    if port == IMPLICIT_TLS_PORT:
        raise MailConfigError("SMTP_PORT 465 (implicit TLS) is not supported: use 587 (STARTTLS)")
    return port


def _timeout(env):
    raw = _get(env, "SMTP_TIMEOUT_SECONDS")
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        seconds = float(raw)
    except ValueError:
        seconds = None
    # NaN fails both comparisons, so it is refused too.
    if seconds is None or not MIN_TIMEOUT_SECONDS <= seconds <= MAX_TIMEOUT_SECONDS:
        raise MailConfigError(f"SMTP_TIMEOUT_SECONDS must be a number of seconds from "
                              f"{MIN_TIMEOUT_SECONDS} to {MAX_TIMEOUT_SECONDS}")
    return seconds


def _file(env):
    outbox = _get(env, "MAIL_OUTBOX_DIR")
    return FileMailer(Path(outbox) if outbox else DEFAULT_OUTBOX_DIR)


def _smtp(env):
    user = _required(env, "SMTP_USER")
    sender = _get(env, "MAIL_FROM") or f"PulseNet <{user}>"
    if "\r" in sender or "\n" in sender:
        raise MailConfigError("MAIL_FROM must be one line")
    return SmtpMailer(
        host=_required(env, "SMTP_HOST"),
        port=_port(env),
        user=user,
        password=_required(env, "SMTP_PASSWORD"),
        sender=sender,
        timeout=_timeout(env),
    )


# MAIL_PROVIDER -> how to build that mailer from the environment.
_BUILDERS = {
    FileMailer.name: _file,
    SmtpMailer.name: _smtp,
}
