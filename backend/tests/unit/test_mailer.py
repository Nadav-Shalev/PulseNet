"""mailer.py: sending email, to a file (development, E2E) or through SMTP.

No network and no real mailbox: ``FakeSmtp`` stands in for smtplib.SMTP and the
file mailer writes to a temporary directory.
"""

import json
import smtplib
import socket
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
for _p in (TESTS_DIR.parent, TESTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import mailer  # noqa: E402
from mailer import (FileMailer, Mail, MailConfigError, MailError, MemoryMailer,  # noqa: E402
                    SmtpMailer)

PASSWORD = "app-pass-zz9"
MAIL = Mail(to="ada@example.com", subject="Hello", text="Hi Ada", html="<p>Hi Ada</p>")


class FakeSmtp:
    """smtplib.SMTP as SmtpMailer uses it: records each call; ``fail`` maps a
    method name to the exception it raises."""

    instances = []

    def __init__(self, host, port, timeout=None, fail=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.fail = fail or {}
        self.calls = []
        self.sent = []
        FakeSmtp.instances.append(self)

    def _step(self, name, *args):
        self.calls.append(name)
        if name in self.fail:
            raise self.fail[name]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append("quit")
        return False

    def starttls(self, context=None):
        self.context = context
        self._step("starttls")

    def login(self, user, password):
        self.login_args = (user, password)
        self._step("login")

    def send_message(self, message):
        self._step("send_message")
        self.sent.append(message)


def smtp_mailer(fail=None, **over):
    FakeSmtp.instances = []
    settings = {"host": "smtp.example.test", "port": 587, "user": "bot@example.test",
                "password": PASSWORD, "sender": "PulseNet <bot@example.test>", "timeout": 10}
    settings.update(over)
    factory = lambda host, port, timeout=None: FakeSmtp(host, port, timeout, fail)  # noqa: E731
    return SmtpMailer(**settings, smtp=factory)


class FromEnvTests(unittest.TestCase):
    SMTP = {"MAIL_PROVIDER": "smtp", "SMTP_HOST": "smtp.gmail.com", "SMTP_USER": "bot@example.test",
            "SMTP_PASSWORD": PASSWORD}

    def assertConfigError(self, env, *needles):
        with self.assertRaises(MailConfigError) as ctx:
            mailer.from_env(env)
        message = str(ctx.exception)
        for needle in needles:
            self.assertIn(needle, message)
        self.assertNotIn(PASSWORD, message)
        return message

    def test_unset_provider_means_mail_is_off(self):
        self.assertConfigError({}, "MAIL_PROVIDER is not set")
        self.assertConfigError({"MAIL_PROVIDER": "  "}, "MAIL_PROVIDER is not set")

    def test_an_unknown_provider_is_refused(self):
        self.assertConfigError({"MAIL_PROVIDER": "sendgrid"}, "file, smtp")

    def test_file_defaults_to_the_backend_outbox(self):
        sender = mailer.from_env({"MAIL_PROVIDER": "file"})

        self.assertIsInstance(sender, FileMailer)
        self.assertEqual(sender.outbox_dir, Path(mailer.__file__).resolve().parent / "outbox")

    def test_file_takes_an_outbox_dir(self):
        sender = mailer.from_env({"MAIL_PROVIDER": " file ", "MAIL_OUTBOX_DIR": "/tmp/box"})

        self.assertEqual(sender.outbox_dir, Path("/tmp/box"))

    def test_smtp_with_its_defaults(self):
        sender = mailer.from_env(self.SMTP)

        self.assertIsInstance(sender, SmtpMailer)
        self.assertEqual(sender.describe(), "smtp smtp.gmail.com:587 as bot@example.test")
        self.assertEqual(sender.sender, "PulseNet <bot@example.test>")
        self.assertEqual(sender.timeout, 10)

    def test_smtp_takes_port_sender_and_timeout(self):
        sender = mailer.from_env({**self.SMTP, "SMTP_PORT": "2525", "MAIL_FROM": "Ops <ops@example.test>",
                                  "SMTP_TIMEOUT_SECONDS": "4.5"})

        self.assertEqual(sender.describe(), "smtp smtp.gmail.com:2525 as bot@example.test")
        self.assertEqual(sender.sender, "Ops <ops@example.test>")
        self.assertEqual(sender.timeout, 4.5)

    def test_smtp_needs_host_user_and_password(self):
        for name in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
            with self.subTest(missing=name):
                env = {**self.SMTP, name: ""}
                self.assertConfigError(env, f"{name} is not set")

    def test_a_bad_port_is_refused(self):
        for port in ("abc", "0", "70000", "-1"):
            with self.subTest(port=port):
                self.assertConfigError({**self.SMTP, "SMTP_PORT": port}, "SMTP_PORT")

    def test_port_465_is_refused_because_only_starttls_is_supported(self):
        self.assertConfigError({**self.SMTP, "SMTP_PORT": "465"}, "587", "STARTTLS")

    def test_a_bad_timeout_is_refused(self):
        for timeout in ("0", "31", "soon", "nan"):
            with self.subTest(timeout=timeout):
                self.assertConfigError({**self.SMTP, "SMTP_TIMEOUT_SECONDS": timeout}, "SMTP_TIMEOUT_SECONDS")

    def test_a_sender_with_a_line_break_is_refused(self):
        self.assertConfigError({**self.SMTP, "MAIL_FROM": "a@b.c\nBcc: x@y.z"}, "MAIL_FROM")


class FileMailerTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.outbox = Path(self._dir.name) / "outbox"   # created on the first send

    def tearDown(self):
        self._dir.cleanup()

    def test_each_mail_is_one_json_file(self):
        sender = FileMailer(self.outbox)

        sender.send(MAIL)
        sender.send(MAIL._replace(to="bob@example.com"))

        files = sorted(self.outbox.glob("*.json"))
        self.assertEqual(len(files), 2)
        first = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(set(first), {"to", "subject", "text", "html", "sent_at"})
        self.assertEqual((first["to"], first["subject"], first["text"], first["html"]),
                         ("ada@example.com", "Hello", "Hi Ada", "<p>Hi Ada</p>"))
        self.assertTrue(first["sent_at"].endswith("+00:00"))
        # Names sort by time, so the newest mail is the last file.
        self.assertEqual(json.loads(files[1].read_text(encoding="utf-8"))["to"], "bob@example.com")

    def test_text_stays_readable_utf8(self):
        FileMailer(self.outbox).send(MAIL._replace(text="שלום Ada"))

        raw = next(self.outbox.glob("*.json")).read_text(encoding="utf-8")
        self.assertIn("שלום Ada", raw)

    def test_a_disk_error_is_a_mail_error(self):
        blocker = Path(self._dir.name) / "taken"
        blocker.write_text("a file where the outbox should be")

        with self.assertRaises(MailError) as ctx:
            FileMailer(blocker).send(MAIL)
        self.assertIn("file:", str(ctx.exception))

    def test_describe_and_repr(self):
        self.assertEqual(FileMailer(self.outbox).describe(), f"file outbox at {self.outbox}")
        self.assertEqual(repr(FileMailer(self.outbox)), f"FileMailer({str(self.outbox)!r})")


class SmtpMailerTests(unittest.TestCase):
    def test_starttls_then_login_then_send(self):
        sender = smtp_mailer()

        sender.send(MAIL)

        smtp = FakeSmtp.instances[0]
        self.assertEqual((smtp.host, smtp.port, smtp.timeout), ("smtp.example.test", 587, 10))
        self.assertEqual(smtp.calls, ["starttls", "login", "send_message", "quit"])
        self.assertIsNotNone(smtp.context)             # a verifying TLS context
        self.assertEqual(smtp.login_args, ("bot@example.test", PASSWORD))

    def test_the_message_has_headers_and_a_text_and_html_part(self):
        smtp_mailer().send(MAIL)

        message = FakeSmtp.instances[0].sent[0]
        self.assertEqual(message["From"], "PulseNet <bot@example.test>")
        self.assertEqual(message["To"], "ada@example.com")
        self.assertEqual(message["Subject"], "Hello")
        self.assertIsNotNone(message["Date"])
        self.assertIsNotNone(message["Message-ID"])
        parts = {part.get_content_type(): part.get_content() for part in message.iter_parts()}
        self.assertEqual(parts["text/plain"].strip(), "Hi Ada")
        self.assertEqual(parts["text/html"].strip(), "<p>Hi Ada</p>")

    def test_a_line_break_in_a_header_is_refused_before_connecting(self):
        # Header injection: a "To" with a newline could add a Bcc.
        for mail in (MAIL._replace(to="ada@example.com\nBcc: eve@example.com"),
                     MAIL._replace(subject="Hi\r\nBcc: eve@example.com")):
            with self.subTest(mail=mail):
                with self.assertRaises(MailError):
                    smtp_mailer().send(mail)
                self.assertEqual(FakeSmtp.instances, [])

    def test_smtp_failures_are_mail_errors_without_the_password_or_address(self):
        failures = {
            "starttls": smtplib.SMTPNotSupportedError("STARTTLS extension not supported"),
            "login": smtplib.SMTPAuthenticationError(535, f"bad credentials {PASSWORD}".encode()),
            "send_message": smtplib.SMTPRecipientsRefused({"ada@example.com": (550, b"no such user")}),
        }
        for step, error in failures.items():
            with self.subTest(step=step):
                with self.assertRaises(MailError) as ctx:
                    smtp_mailer(fail={step: error}).send(MAIL)
                message = str(ctx.exception)
                self.assertTrue(message.startswith("smtp: "), message)
                self.assertIn(type(error).__name__, message)
                self.assertNotIn(PASSWORD, message)
                self.assertNotIn("ada@example.com", message)

    def test_the_smtp_reply_code_is_kept(self):
        error = smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")
        with self.assertRaises(MailError) as ctx:
            smtp_mailer(fail={"login": error}).send(MAIL)

        self.assertEqual(str(ctx.exception), "smtp: SMTPAuthenticationError 535")

    def test_network_failures_are_mail_errors(self):
        for error in (socket.timeout("timed out"), ConnectionRefusedError(111, "refused")):
            with self.subTest(error=type(error).__name__):
                def refuse(host, port, timeout=None, error=error):
                    raise error
                sender = SmtpMailer("smtp.example.test", 587, "bot@example.test", PASSWORD,
                                    "PulseNet <bot@example.test>", 10, smtp=refuse)
                with self.assertRaises(MailError) as ctx:
                    sender.send(MAIL)
                self.assertIn(type(error).__name__, str(ctx.exception))

    def test_repr_never_shows_the_password(self):
        sender = smtp_mailer()

        self.assertNotIn(PASSWORD, repr(sender))
        self.assertNotIn(PASSWORD, sender.describe())
        self.assertIn("smtp.example.test", repr(sender))


class MemoryMailerTests(unittest.TestCase):
    def test_keeps_what_it_sends(self):
        sender = MemoryMailer()

        sender.send(MAIL)

        self.assertEqual(sender.sent, [MAIL])
        self.assertEqual(sender.describe(), "memory (test double)")

    def test_can_fail_like_a_real_mailer(self):
        sender = MemoryMailer(fail=MailError("smtp: SMTPServerDisconnected"))

        with self.assertRaises(MailError):
            sender.send(MAIL)
        self.assertEqual(sender.sent, [])


if __name__ == "__main__":
    unittest.main()
