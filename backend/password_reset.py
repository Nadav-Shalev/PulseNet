"""The pieces of a password reset (requirement a.i): the token, its hash, the link
and the email. app.py's /api/password/forgot and /api/password/reset use them.

    token, token_hash = new_token()     # the token goes in the email, the hash in the DB
    link = reset_link(base_url(os.environ), token)
    mailer.send(reset_mail(user_email, user_name, link))

Pure functions, without Flask or the app, like ai_assist.py.

The link is built from APP_BASE_URL, the site's public address, and never from the
request's Host or Origin header: anyone can send those, so a "forgot" request with
Host: evil.example would mail the victim a real token on the attacker's domain
("password reset poisoning"). The token travels in the link's fragment (#token=...),
which the browser never sends to a server: it stays out of nginx's access log and
out of the Referer header that images from other hosts would receive.
"""

import hashlib
import html
import secrets
from urllib.parse import urlsplit

from mailer import Mail, MailConfigError

TOKEN_TTL_MINUTES = 30
MAX_REQUESTS_PER_HOUR = 3        # links per user; a link whose mail failed is not counted
TOKEN_BYTES = 32                 # 256 random bits: 43 URL-safe characters
MAX_TOKEN_CHARS = 100            # anything longer is not one of ours
DEV_BASE_URL = "http://localhost:5173"   # the Vite dev server, for MAIL_PROVIDER=file


def new_token():
    """(token, its SHA-256 hex). Only the hash is stored."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    return token, hash_token(token)


def hash_token(token):
    """SHA-256, not bcrypt: a random 256-bit token cannot be guessed from its hash,
    so a slow hash adds nothing, and the lookup needs the same hash every time."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def base_url(env):
    """APP_BASE_URL without a trailing slash: the address the links in emails point
    to. MAIL_PROVIDER=smtp needs it set, since a real email must not point at a
    developer's machine; otherwise it defaults to the Vite dev server.
    MailConfigError, naming the variable, when it is missing or not an http URL."""
    raw = (env.get("APP_BASE_URL") or "").strip()
    if not raw:
        if (env.get("MAIL_PROVIDER") or "").strip() == "smtp":
            raise MailConfigError("APP_BASE_URL is not set (MAIL_PROVIDER=smtp needs it "
                                  "for the links in emails)")
        return DEV_BASE_URL
    parts = urlsplit(raw)
    try:
        parts.port  # a port that is not a number raises ValueError
    except ValueError:
        parts = None
    if (parts is None or parts.scheme not in ("http", "https") or not parts.hostname
            or parts.query or parts.fragment):
        raise MailConfigError("APP_BASE_URL must be an http:// or https:// URL "
                              "without a query or fragment")
    return raw.rstrip("/")


def reset_link(base, token):
    return f"{base}/reset-password#token={token}"


def reset_mail(to, name, link):
    """The email with the reset link. ``name`` is the user's display name: escaped
    in the HTML part, since anyone chooses their own."""
    greeting = f"Hi {name}," if name else "Hi,"
    text = (
        f"{greeting}\n\n"
        "Someone, hopefully you, asked to reset the password of your PulseNet account. "
        "Open this link to choose a new one:\n\n"
        f"{link}\n\n"
        f"The link works once, for {TOKEN_TTL_MINUTES} minutes. If you did not ask, ignore "
        "this email: your password stays as it is.\n\n"
        "PulseNet\n"
    )
    safe_link = html.escape(link, quote=True)
    body = (
        f"<p>{html.escape(greeting)}</p>"
        "<p>Someone, hopefully you, asked to reset the password of your PulseNet account.</p>"
        f'<p><a href="{safe_link}">Choose a new password</a></p>'
        f"<p>Or open this link: {safe_link}</p>"
        f"<p>The link works once, for {TOKEN_TTL_MINUTES} minutes. If you did not ask, "
        "ignore this email: your password stays as it is.</p>"
        "<p>PulseNet</p>"
    )
    return Mail(to=to, subject="Reset your PulseNet password", text=text, html=body)
