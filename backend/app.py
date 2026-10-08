import logging
import os
import re
import html as _html
import requests
from io import BytesIO
from html.parser import HTMLParser

try:
    import markdown as _md
    def to_html(text):
        return _md.markdown(text)
except ImportError:
    def to_html(text):
        paragraphs = text.split('\n\n')
        return ''.join(
            f'<p>{_html.escape(p.strip())}</p>'
            for p in paragraphs if p.strip()
        )
import secrets
from datetime import datetime, timezone
from functools import wraps

import bcrypt
import mysql.connector
from dotenv import load_dotenv
from flask import Flask, g, jsonify, make_response, request, send_from_directory
from flask_cors import CORS
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename
from mock_data import mock_get_articles, mock_get_article_by_id, mock_search_users

import ai_assist
import llm
import mailer
import moderation
import password_reset

# ─── Rich-text sanitization (user-submitted HTML from the WYSIWYG editor) ──────
# Whitelist only the formatting the editor can produce. bleach strips everything
# else (including <script>, event handlers, and javascript: URLs) so stored HTML
# is safe to render with dangerouslySetInnerHTML.
ALLOWED_TAGS = [
    "p", "br", "span", "strong", "em", "b", "i", "u", "s",
    "a", "ul", "ol", "li", "blockquote", "h1", "h2", "h3", "pre", "code",
]
ALLOWED_ATTRS = {"a": ["href", "title", "target", "rel"], "*": ["class"]}
ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def _rel_tokens_with_blank_target_safety(rel_value):
    tokens = (rel_value or "").split()
    seen = {token.lower() for token in tokens}
    for required in ("noopener", "noreferrer"):
        if required not in seen:
            tokens.append(required)
            seen.add(required)
    return " ".join(tokens)


def _add_rel_to_anchor_start_tag(start_tag, rel_value):
    safe_rel = _html.escape(_rel_tokens_with_blank_target_safety(rel_value), quote=True)
    if rel_value is None:
        insert_at = start_tag.rfind("/>") if start_tag.rstrip().endswith("/>") else start_tag.rfind(">")
        if insert_at == -1:
            return start_tag
        return f'{start_tag[:insert_at]} rel="{safe_rel}"{start_tag[insert_at:]}'

    return re.sub(
        r'(\srel\s*=\s*)(["\'])(.*?)\2',
        lambda match: f"{match.group(1)}{match.group(2)}{safe_rel}{match.group(2)}",
        start_tag,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )


class _BlankTargetRelParser(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.html = html
        self.offset = 0
        self.replacements = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return

        attr_map = {name.lower(): value for name, value in attrs if name}
        target = (attr_map.get("target") or "").strip().lower()
        if target != "_blank":
            return

        start_tag = self.get_starttag_text()
        if not start_tag:
            return

        start = self.html.find(start_tag, self.offset)
        if start == -1:
            return

        self.offset = start + len(start_tag)
        updated = _add_rel_to_anchor_start_tag(start_tag, attr_map.get("rel"))
        if updated != start_tag:
            self.replacements.append((start, self.offset, updated))


def _ensure_blank_target_rel(clean_html):
    """Add noopener/noreferrer only to sanitized <a target="_blank"> start tags."""
    parser = _BlankTargetRelParser(clean_html)
    parser.feed(clean_html)
    if not parser.replacements:
        return clean_html

    pieces = []
    cursor = 0
    for start, end, replacement in parser.replacements:
        pieces.append(clean_html[cursor:start])
        pieces.append(replacement)
        cursor = end
    pieces.append(clean_html[cursor:])
    return "".join(pieces)

try:
    import bleach
    def sanitize_html(raw):
        clean = bleach.clean(
            raw or "",
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRS,
            protocols=ALLOWED_PROTOCOLS,
            strip=True,
        )
        return _ensure_blank_target_rel(clean)
except ImportError:
    # bleach missing → safest possible fallback: escape everything (no rich text,
    # but no XSS either). Install bleach (requirements.txt) to enable formatting.
    def sanitize_html(raw):
        return _html.escape(raw or "")


def html_to_text(html):
    """Plain-text excerpt from HTML for the card preview / description column.

    bleach (via html5lib) re-serializes a non-breaking space back to the literal
    "&nbsp;" entity, and editors like Quill emit &nbsp; for spaces — so we unescape
    HTML entities and normalize NBSP to a regular space to get clean plain text."""
    try:
        import bleach
        text = bleach.clean(html or "", tags=[], strip=True)
    except ImportError:
        text = re.sub(r"<[^>]+>", "", html or "")
    return _html.unescape(text).replace("\xa0", " ").strip()

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

app = Flask(__name__)
# supports_credentials lets the browser send/receive the session cookie cross-origin
# from the Vite dev server on :5173.
CORS(app, supports_credentials=True, origins=["http://localhost:5173"])

DEVTO_BASE = "https://dev.to/api"
DICEBEAR_URL = "https://api.dicebear.com/7.x/avataaars/svg"

# ─── Local image uploads (no external services) ────────────────────────────────
UPLOAD_DIR        = os.path.join(BACKEND_DIR, "uploads")
ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
IMAGE_FORMAT_EXTS = {
    "PNG": {"png"},
    "JPEG": {"jpg", "jpeg"},
    "GIF": {"gif"},
    "WEBP": {"webp"},
}
MAX_UPLOAD_BYTES  = 5 * 1024 * 1024  # 5 MB per file
# Hard cap on request size so oversized uploads are rejected before buffering.
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES + (1 * 1024 * 1024)
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ─── DB helpers ───────────────────────────────────────────────────────────────

# Every connection runs in UTC, whatever the server's own time zone (SYSTEM on a
# dev machine, UTC on RDS). TIMESTAMP columns are stored as UTC and converted to
# the session zone on read, so they come back as UTC and NOW() agrees with them;
# _iso() then labels them +00:00 for the browser.
DB_TIME_ZONE = "+00:00"


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        time_zone=DB_TIME_ZONE,
    )


def is_db_available():
    try:
        conn = get_db_connection()
        conn.close()
        return True
    except Exception:
        return False


# ─── LLM service and moderation ───────────────────────────────────────────────

def _build_llm_service(env):
    """The LLM service from the LLM_* settings in ``env`` (backend/llm), or None
    when the LLM is off (LLM_PROVIDER unset) or misconfigured: every feature then
    uses its fallback. ``connect`` is a lambda so get_db_connection is looked up at
    each call, which is also what lets the tests patch it."""
    try:
        return llm.from_env(env, connect=lambda: get_db_connection())
    except llm.LLMConfigError as exc:
        # Unset is a choice; a set but broken setting is a mistake worth a warning.
        # The message names a variable, never its value.
        level = logging.WARNING if (env.get("LLM_PROVIDER") or "").strip() else logging.INFO
        app.logger.log(level, "LLM off: %s", exc)
        return None


llm_service = _build_llm_service(os.environ)
# Posts and comments are checked before they are stored (moderation.py): by the LLM
# when it is on, else by a word list.
moderator = moderation.Moderator(llm_service)


# ─── Mail (the password-reset link) ───────────────────────────────────────────

def _build_mailer(env):
    """(mailer, base URL of the links in mails) from the MAIL_* / SMTP_* settings
    and APP_BASE_URL (mailer.py, password_reset.py), or (None, None) when mail is
    off (MAIL_PROVIDER unset) or misconfigured: the password reset then answers 503."""
    try:
        return mailer.from_env(env), password_reset.base_url(env)
    except mailer.MailConfigError as exc:
        # Like the LLM: unset is a choice, a set but broken setting is a mistake.
        # The message names a variable, never its value.
        level = logging.WARNING if (env.get("MAIL_PROVIDER") or "").strip() else logging.INFO
        app.logger.log(level, "Mail off: %s", exc)
        return None, None


mail_service, reset_base_url = _build_mailer(os.environ)

_MODERATION_REASONS = {
    "harassment": "insulting or harassing",
    "hate": "hateful",
    "threat": "threatening",
}


def _moderation_error(verdict, kind):
    """The 422 for a post or comment (``kind``) that moderation blocked."""
    reason = _MODERATION_REASONS.get(verdict.category, "toxic")
    return jsonify({
        "error": f"This {kind} looks {reason}, so it was not published. Please rephrase it.",
        "category": verdict.category,
    }), 422


# ─── Request input: JSON type checks ─────────────────────────────────────────

class InputError(ValueError):
    """A request field has the wrong JSON type. The errorhandler below turns it
    into a 400, so a number where a string belongs is a client error, not a 500."""


@app.errorhandler(InputError)
def _bad_input(e):
    return jsonify({"error": str(e)}), 400


def _json_object(value, name="Request body"):
    """``value`` as a dict: ``{}`` when it is missing/null, InputError when it is
    a list, string, number or bool (``.get()`` on those used to crash)."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InputError(f"{name} must be a JSON object")
    return value


def _str_field(data, key, strip=True):
    """``data[key]`` as a string: ``""`` when missing/null, trimmed unless
    ``strip=False``. Any other JSON type raises InputError."""
    value = data.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InputError(f"{key} must be a string")
    return value.strip() if strip else value


# ─── Auth: session helpers & require_session decorator ───────────────────────

SESSION_COOKIE_NAME    = "session_id"
SESSION_DURATION_DAYS  = 7
SESSION_MAX_AGE_SECONDS = SESSION_DURATION_DAYS * 24 * 60 * 60  # 604800


def _user_shape(row):
    """The logged-in user's own record (/api/me, login, signup). It is the only
    JSON that carries an email, so never use it for another user's data. Must
    NEVER include password_hash. ``role`` only tells the UI whether to show the
    admin page: every admin endpoint checks the role again on the server."""
    return {
        "id":            row["id"],
        "name":          row.get("name"),
        "username":      row["username"],
        "email":         row["email"],
        "bio":           row.get("bio"),
        "avatar":        row.get("avatar"),
        "profile_image": row.get("profile_image"),
        "role":          row.get("role") or "user",
    }


def _hash_password(password):
    # bcrypt input is bytes; the salt is generated inside the hash output.
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password, password_hash):
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


# bcrypt reads at most 72 bytes, and bcrypt 5 raises ValueError on a longer
# password instead of cutting it: the limit is checked first, for a 400.
MAX_PASSWORD_BYTES = 72
PASSWORD_TOO_LONG = f"Password is too long (at most {MAX_PASSWORD_BYTES} bytes)"


def _password_too_long(password):
    return len(password.encode("utf-8")) > MAX_PASSWORD_BYTES


def _password_error(password):
    """Why ``password`` cannot be set (signup, reset), or None. The limit is in
    UTF-8 bytes: 72 ASCII characters, but only 36 Hebrew letters."""
    if not password:
        return "password is required"
    if _password_too_long(password):
        return PASSWORD_TOO_LONG
    return None


def _validate_signup_payload(data):
    """Returns (payload, error message or None). A wrong JSON type raises
    InputError (-> 400) instead."""
    data = _json_object(data)
    payload = {
        "name": _str_field(data, "name"),
        "username": _str_field(data, "username"),
        "email": _str_field(data, "email"),
        "bio": _str_field(data, "bio"),
        "password": _str_field(data, "password", strip=False),
    }

    if not payload["name"] or not payload["username"] or not payload["email"]:
        return payload, "name, username, and email are required"

    password_error = _password_error(payload["password"])
    if password_error:
        return payload, password_error

    if len(payload["name"]) > 100:
        return payload, "Name must be 100 characters or fewer"

    if len(payload["username"]) > 100:
        return payload, "Username must be 100 characters or fewer"

    if len(payload["email"]) > 100:
        return payload, "Email must be 100 characters or fewer"

    if not re.match(r'^[a-zA-Z0-9_.]+$', payload["username"]):
        return payload, "Username may only contain letters, numbers, underscores, and dots"

    if "@" not in payload["email"] or "." not in payload["email"]:
        return payload, "Invalid email format"

    return payload, None


def _validate_login_payload(data):
    """Same contract as _validate_signup_payload."""
    data = _json_object(data)
    payload = {
        "email": _str_field(data, "email"),
        "password": _str_field(data, "password", strip=False),
    }
    if not payload["email"] or not payload["password"]:
        return payload, "email and password are required"
    return payload, None


def _delete_expired_sessions(cursor):
    """Remove expired active sessions.

    Keep this centralized so a future session_history/session_events insert can
    be added here before the delete without changing every auth path.
    """
    cursor.execute("DELETE FROM sessions WHERE expires_at <= NOW()")


def _create_session(cursor, user_id):
    """Insert a new sessions row and return the opaque session_id."""
    _delete_expired_sessions(cursor)
    session_id = secrets.token_urlsafe(32)
    cursor.execute(
        "INSERT INTO sessions (session_id, user_id, expires_at) "
        "VALUES (%s, %s, NOW() + INTERVAL %s DAY)",
        (session_id, user_id, SESSION_DURATION_DAYS),
    )
    return session_id


def _set_session_cookie(resp, session_id):
    # No Secure flag yet: the site is served over plain HTTP (dev and the EC2).
    # Adding it with HTTPS is the final-production hardening in backend/README.md
    # ("Security Notes").
    resp.set_cookie(
        SESSION_COOKIE_NAME, session_id,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True, samesite="Lax", path="/",
    )
    return resp


def _clear_session_cookie(resp):
    resp.set_cookie(
        SESSION_COOKIE_NAME, "",
        max_age=0,
        httponly=True, samesite="Lax", path="/",
    )
    return resp


def require_session(view):
    """Gate write endpoints. Looks up the cookie's session_id and stashes the
    matching user (with their role) on ``g.current_user``; 401 if
    missing/expired/invalid, or if the user is banned (a ban deletes their
    sessions too; the filter is the second lock)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        sid = request.cookies.get(SESSION_COOKIE_NAME)
        if not sid:
            return jsonify({"error": "Authentication required"}), 401
        try:
            conn   = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            _delete_expired_sessions(cursor)
            conn.commit()
            cursor.execute(
                """
                SELECT u.id, u.name, u.username, u.email, u.bio,
                       u.avatar, u.profile_image, u.role
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.session_id = %s AND s.expires_at > NOW() AND NOT u.is_banned
                """,
                (sid,),
            )
            user = cursor.fetchone()
            cursor.close()
            conn.close()
        except Exception as exc:
            return jsonify({"error": "Database unavailable", "detail": str(exc)}), 503
        if not user:
            resp = make_response(jsonify({"error": "Session expired or invalid"}), 401)
            return _clear_session_cookie(resp)
        g.current_user = user
        return view(*args, **kwargs)
    return wrapped


def require_admin(view):
    """Gate admin-only endpoints. Runs require_session itself (401 without a valid
    session, 503 when the DB is down), so it cannot be forgotten, then answers 403
    unless the session user's role is 'admin'. Fails closed: no role is no admin.
    The role is granted only by hand, with backend/manage.py make-admin."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.current_user.get("role") != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return view(*args, **kwargs)
    return require_session(wrapped)


def _current_user_from_cookie():
    """Resolve the logged-in user from the session cookie, or None.

    Unlike ``require_session`` this never aborts the request — it lets public
    endpoints (feed, profile) optionally personalize their response (e.g.
    ``is_following``) when a valid session is present."""
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    if not sid:
        return None
    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        _delete_expired_sessions(cursor)
        conn.commit()
        cursor.execute(
            "SELECT u.id, u.username FROM sessions s "
            "JOIN users u ON u.id = s.user_id "
            "WHERE s.session_id = %s AND s.expires_at > NOW() AND NOT u.is_banned",
            (sid,),
        )
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        return user
    except Exception:
        return None


# ─── Row → DEV.to-shaped dict ─────────────────────────────────────────────────

def _iso(dt):
    """Render a DB datetime as an ISO-8601 string with an explicit UTC offset, so
    every browser parses the same instant for relative time whatever its own zone.

    Connections run in UTC (DB_TIME_ZONE), so a naive datetime from MySQL is UTC.
    Returns None when the value is missing; anything else falls back to str()."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return str(dt)


def _shape_post_row(row):
    """Convert a flat DB row (with username/name/profile_image joined from users) to
    the same JSON shape that DEV.to's /api/articles returns."""
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row.get("description") or "",
        "cover_image": row.get("cover_image"),
        # Raw timestamp for client-side "time ago"; readable_publish_date stays as a fallback.
        "created_at": _iso(row.get("created_at")),
        "readable_publish_date": row.get("readable_publish_date") or str(row.get("created_at", ""))[:10],
        "url": row.get("devto_url"),
        "tag_list": [],
        # Filled in by _attach_counts, one query for the whole page.
        "like_count": 0,
        "liked_by_me": False,
        "comment_count": 0,
        "user": {
            "username": row.get("username", ""),
            "name": row.get("name", ""),
            "profile_image": row.get("profile_image") or row.get("avatar") or
                             f"{DICEBEAR_URL}?seed={row.get('username', '')}",
        },
    }


def _aggregate_tags(rows):
    """Collapse multiple rows per post (one per tag) into one dict per post."""
    posts = {}
    for row in rows:
        pid = row["id"]
        if pid not in posts:
            posts[pid] = _shape_post_row(row)
        if row.get("tag_name"):
            posts[pid]["tag_list"].append(row["tag_name"])
    return list(posts.values())


def _attach_counts(cursor, posts, viewer_id):
    """Set like_count / liked_by_me / comment_count on shaped posts with one query
    for the page.

    ``cursor`` must be a dictionary cursor. ``viewer_id`` is None for a logged-out
    visitor: ``user_id = NULL`` is never true, so liked_by_me stays False. The
    counts are subqueries here rather than joins in the feed queries, which already
    return one row per tag (and joining likes and comments would multiply them)."""
    if not posts:
        return posts                      # "p.id IN ()" is invalid SQL
    ids = [post["id"] for post in posts]
    # Only "%s" placeholders go into the f-string; the ids themselves are bound.
    placeholders = ", ".join(["%s"] * len(ids))
    # Each subquery is an index lookup per post: idx_likes_post, the likes primary
    # key (user_id, post_id) for the viewer's own like (0 or 1 row), idx_comments_post.
    cursor.execute(
        "SELECT p.id AS post_id, "
        "(SELECT COUNT(*) FROM likes l WHERE l.post_id = p.id) AS like_count, "
        "(SELECT COUNT(*) FROM likes l WHERE l.post_id = p.id AND l.user_id = %s) AS liked_by_me, "
        "(SELECT COUNT(*) FROM comments c WHERE c.post_id = p.id) AS comment_count "
        f"FROM posts p WHERE p.id IN ({placeholders})",
        (viewer_id, *ids),
    )
    by_post = {row["post_id"]: row for row in cursor.fetchall()}
    for post in posts:
        row = by_post.get(post["id"])
        if row:
            post["like_count"] = int(row["like_count"])
            post["liked_by_me"] = bool(row["liked_by_me"])
            post["comment_count"] = int(row["comment_count"])
    return posts


# ─── GET /api/articles ────────────────────────────────────────────────────────

@app.route("/api/articles")
def get_articles():
    page     = request.args.get("page",     1,  type=int)
    per_page = request.args.get("per_page", 10, type=int)
    username = request.args.get("username")
    tag      = request.args.get("tag")
    feed     = request.args.get("feed")          # "following" → only followed authors
    offset   = (page - 1) * per_page

    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # Who is asking (None when logged out): personalizes liked_by_me, and the
        # following feed needs a viewer. Looked up after connecting, so an
        # unreachable DB still falls back to the mock feed below.
        viewer = _current_user_from_cookie()

        if feed == "following":
            # Only posts authored by people the logged-in user follows.
            if not viewer:
                cursor.close()
                conn.close()
                return jsonify({"error": "Authentication required"}), 401
            cursor.execute(
                """
                SELECT p.id, p.title, p.description, p.cover_image, p.devto_url,
                       p.readable_publish_date, p.created_at,
                       u.username, u.name, u.avatar, u.profile_image,
                       t.name AS tag_name
                FROM (
                    SELECT posts.id, posts.title, posts.description, posts.cover_image,
                           posts.devto_url, posts.readable_publish_date, posts.created_at,
                           posts.author_id
                    FROM posts
                    JOIN follows f ON f.following_id = posts.author_id
                    WHERE f.follower_id = %s
                    ORDER BY posts.created_at DESC, posts.id DESC
                    LIMIT %s OFFSET %s
                ) AS p
                JOIN users u ON p.author_id = u.id
                LEFT JOIN posts_tags ON p.id = posts_tags.post_id
                LEFT JOIN tags t     ON posts_tags.tag_id = t.id
                ORDER BY p.created_at DESC, p.id DESC
                """,
                (viewer["id"], per_page, offset),
            )
        elif tag:
            # Exact-case match — tags.name is stored case-sensitively.
            cursor.execute(
                """
                SELECT p.id, p.title, p.description, p.cover_image, p.devto_url,
                       p.readable_publish_date, p.created_at,
                       u.username, u.name, u.avatar, u.profile_image,
                       t.name AS tag_name
                FROM (
                    SELECT posts.id, posts.title, posts.description, posts.cover_image,
                           posts.devto_url, posts.readable_publish_date, posts.created_at,
                           posts.author_id
                    FROM posts
                    JOIN posts_tags pt2 ON posts.id = pt2.post_id
                    JOIN tags       t2  ON pt2.tag_id = t2.id
                    WHERE t2.name = %s
                    ORDER BY posts.created_at DESC, posts.id DESC
                    LIMIT %s OFFSET %s
                ) AS p
                JOIN users u ON p.author_id = u.id
                LEFT JOIN posts_tags ON p.id = posts_tags.post_id
                LEFT JOIN tags t     ON posts_tags.tag_id = t.id
                ORDER BY p.created_at DESC, p.id DESC
                """,
                (tag, per_page, offset),
            )
        elif username:
            cursor.execute(
                """
                SELECT p.id, p.title, p.description, p.cover_image, p.devto_url,
                       p.readable_publish_date, p.created_at,
                       u.username, u.name, u.avatar, u.profile_image,
                       t.name AS tag_name
                FROM (
                    SELECT posts.id, posts.title, posts.description, posts.cover_image,
                           posts.devto_url, posts.readable_publish_date, posts.created_at,
                           posts.author_id
                    FROM posts
                    JOIN users ON posts.author_id = users.id
                    WHERE users.username = %s
                    ORDER BY posts.created_at DESC, posts.id DESC
                    LIMIT %s OFFSET %s
                ) AS p
                JOIN users u ON p.author_id = u.id
                LEFT JOIN posts_tags ON p.id = posts_tags.post_id
                LEFT JOIN tags t     ON posts_tags.tag_id = t.id
                ORDER BY p.created_at DESC, p.id DESC
                """,
                (username, per_page, offset),
            )
        else:
            cursor.execute(
                """
                SELECT p.id, p.title, p.description, p.cover_image, p.devto_url,
                       p.readable_publish_date, p.created_at,
                       u.username, u.name, u.avatar, u.profile_image,
                       t.name AS tag_name
                FROM (
                    SELECT id, title, description, cover_image, devto_url,
                           readable_publish_date, created_at, author_id
                    FROM posts
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s OFFSET %s
                ) AS p
                JOIN users u ON p.author_id = u.id
                LEFT JOIN posts_tags ON p.id = posts_tags.post_id
                LEFT JOIN tags t     ON posts_tags.tag_id = t.id
                ORDER BY p.created_at DESC, p.id DESC
                """,
                (per_page, offset),
            )

        rows = cursor.fetchall()
        posts = _attach_counts(cursor, _aggregate_tags(rows), viewer["id"] if viewer else None)
        cursor.close()
        conn.close()
        return jsonify(posts)

    except Exception:
        return jsonify(mock_get_articles(page, per_page, username))


# ─── GET /api/articles/<id> ───────────────────────────────────────────────────

@app.route("/api/articles/<int:article_id>")
def get_article(article_id):
    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT p.id, p.title, p.description, p.cover_image, p.devto_url,
                   p.readable_publish_date, p.created_at, p.body_html, p.body,
                   p.devto_id,
                   u.username, u.name, u.avatar, u.profile_image,
                   t.name AS tag_name
            FROM posts p
            JOIN users u ON p.author_id = u.id
            LEFT JOIN posts_tags ON p.id = posts_tags.post_id
            LEFT JOIN tags t     ON posts_tags.tag_id = t.id
            WHERE p.id = %s
            """,
            (article_id,),
        )
        rows = cursor.fetchall()

        if not rows:
            cursor.close()
            conn.close()
            return jsonify({"error": "Article not found"}), 404

        post = _shape_post_row(rows[0])
        for row in rows:
            if row.get("tag_name"):
                post["tag_list"].append(row["tag_name"])
        viewer = _current_user_from_cookie()
        _attach_counts(cursor, [post], viewer["id"] if viewer else None)

        body_html = rows[0].get("body_html")
        devto_id  = rows[0].get("devto_id")

        if not body_html and devto_id:
            # Fetch full article HTML from DEV.to and cache it in the DB
            try:
                resp = requests.get(f"{DEVTO_BASE}/articles/{devto_id}", timeout=10)
                if resp.ok:
                    data = resp.json()
                    body_html = sanitize_html(data.get("body_html") or "")
                    update_cur = conn.cursor()
                    update_cur.execute(
                        "UPDATE posts SET body_html = %s WHERE id = %s",
                        (body_html, article_id),
                    )
                    conn.commit()
                    update_cur.close()
            except Exception:
                pass

        if not body_html:
            body_html = to_html(rows[0].get("body") or "")
        body_html = sanitize_html(body_html)

        cursor.close()
        conn.close()
        post["body_html"] = body_html
        return jsonify(post)

    except Exception:
        result = mock_get_article_by_id(article_id)
        if result is None:
            return jsonify({"error": "Article not found"}), 404
        if "body_html" in result:
            result["body_html"] = sanitize_html(result["body_html"])
        return jsonify(result)


# ─── POST /api/articles ───────────────────────────────────────────────────────

MAX_TITLE_CHARS = 150   # posts.title VARCHAR(150)
MAX_TAGS = 10
MAX_TAG_CHARS = 100     # tags.name VARCHAR(100)


def _clean_tags(tags):
    """The request's ``tags`` as trimmed names, blanks dropped (missing or empty is
    no tags). InputError (a 400) unless it is a list of at most MAX_TAGS strings
    that each fit tags.name, so a bad tag never fails halfway through an INSERT."""
    if not tags:
        return []
    if not isinstance(tags, list):
        raise InputError("tags must be a list")
    if len(tags) > MAX_TAGS:
        raise InputError(f"You can add at most {MAX_TAGS} tags")
    if any(not isinstance(tag, str) for tag in tags):
        raise InputError("Each tag must be a string")
    tags = [tag for tag in (t.strip() for t in tags) if tag]
    if any(len(tag) > MAX_TAG_CHARS for tag in tags):
        raise InputError(f"Tags must be {MAX_TAG_CHARS} characters or fewer")
    return tags


@app.route("/api/articles", methods=["POST"])
@require_session
def create_article():
    if not is_db_available():
        return jsonify({"error": "Database unavailable. Write actions are disabled."}), 503

    data     = _json_object(request.get_json())
    article  = _json_object(data.get("article"), "article")
    title    = _str_field(article, "title")
    raw_html = _str_field(article, "body_html", strip=False)
    body_md  = _str_field(article, "body_markdown")
    tags     = article.get("tags")
    cover    = _str_field(article, "main_image") or None

    if not title:
        return jsonify({"error": "title is required"}), 400

    # The WYSIWYG editor submits HTML; older callers may submit markdown.
    # Prefer HTML and ALWAYS sanitize it before it is stored/rendered.
    if raw_html.strip():
        body_html   = sanitize_html(raw_html)
        plain       = html_to_text(body_html)
        if not plain:
            return jsonify({"error": "Post body is required"}), 400
        body        = plain                 # plain-text source kept in `body` (NOT NULL)
        description = plain[:200]
    elif body_md:
        body        = body_md
        body_html   = sanitize_html(to_html(body_md))
        description = body_md[:200]
    else:
        return jsonify({"error": "Post body is required"}), 400

    if len(title) > MAX_TITLE_CHARS:
        return jsonify({"error": f"Title must be {MAX_TITLE_CHARS} characters or fewer"}), 400

    # Every tag is validated before the post is inserted.
    tags = _clean_tags(tags)

    # Author is derived from the session, not from the request body.
    user = g.current_user

    # One moderation check for the whole post, on what readers will see: the text of
    # the sanitized HTML (also for a markdown post), never raw markup. Nothing is
    # stored when it is blocked.
    verdict = moderator.check_post(title, html_to_text(body_html), tags, user_id=user["id"])
    if verdict.blocked:
        return _moderation_error(verdict, "post")

    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor2 = conn.cursor()
    cursor2.execute(
        "INSERT INTO posts (author_id, title, body, body_html, description, cover_image) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (user["id"], title, body, body_html, description, cover),
    )
    post_id = cursor2.lastrowid

    tag_list = []
    for tag_name in tags:
        # Preserve exact casing — tags.name uses utf8mb4_bin so "react" and "React"
        # are distinct rows. INSERT IGNORE + UNIQUE prevents exact-case duplicates.
        cursor2.execute("INSERT IGNORE INTO tags (name) VALUES (%s)", (tag_name,))
        cursor2.execute("SELECT id FROM tags WHERE name = %s", (tag_name,))
        tag_id = cursor2.fetchone()[0]
        cursor2.execute(
            "INSERT IGNORE INTO posts_tags (post_id, tag_id) VALUES (%s, %s)",
            (post_id, tag_id),
        )
        tag_list.append(tag_name)

    conn.commit()
    cursor.close()
    cursor2.close()
    conn.close()

    return jsonify({
        "id": post_id,
        "title": title,
        "description": description,
        "cover_image": cover,
        "readable_publish_date": "Just now",
        "url": None,
        "tag_list": tag_list,
        "like_count": 0,
        "liked_by_me": False,
        "comment_count": 0,
        "body_html": body_html,
        "user": {
            "username": user["username"],
            "name": user["name"],
            "profile_image": user.get("profile_image") or user.get("avatar") or
                             f"{DICEBEAR_URL}?seed={user['username']}",
        },
    }), 201


# ─── Owner-only post management (delete post, remove a tag) ─────────────────────

def _require_post_owner(cursor, post_id, user_id, admin_ok=False):
    """Return None if user_id owns post_id (or ``admin_ok`` and the post exists),
    else a (response, status) tuple."""
    cursor.execute("SELECT author_id FROM posts WHERE id = %s", (post_id,))
    row = cursor.fetchone()
    if row is None:
        return jsonify({"error": "Post not found"}), 404
    if row[0] != user_id and not admin_ok:
        return jsonify({"error": "You can only manage your own posts"}), 403
    return None


@app.route("/api/articles/<int:post_id>", methods=["DELETE"])
@require_session
def delete_article(post_id):
    """Its author, or an admin (moderation), may delete a post. Its likes, comments
    and reports go with it (ON DELETE CASCADE)."""
    me     = g.current_user
    conn   = get_db_connection()
    cursor = conn.cursor()
    err = _require_post_owner(cursor, post_id, me["id"], admin_ok=me.get("role") == "admin")
    if err:
        cursor.close()
        conn.close()
        return err
    # Remove tag links first (FK), then the post. Tag rows stay in the global table.
    cursor.execute("DELETE FROM posts_tags WHERE post_id = %s", (post_id,))
    cursor.execute("DELETE FROM posts WHERE id = %s", (post_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"deleted": True, "id": post_id})


@app.route("/api/articles/<int:post_id>/tags", methods=["DELETE"])
@require_session
def remove_article_tag(post_id):
    tag_name = (request.args.get("name") or "").strip()
    if not tag_name:
        return jsonify({"error": "Missing tag name (query param 'name')"}), 400

    conn   = get_db_connection()
    cursor = conn.cursor()
    err = _require_post_owner(cursor, post_id, g.current_user["id"])
    if err:
        cursor.close()
        conn.close()
        return err

    # Exact-case match (tags.name is utf8mb4_bin). Only the post↔tag link is
    # removed; the tag row remains for other posts.
    cursor.execute("SELECT id FROM tags WHERE name = %s", (tag_name,))
    trow = cursor.fetchone()
    if trow:
        cursor.execute(
            "DELETE FROM posts_tags WHERE post_id = %s AND tag_id = %s",
            (post_id, trow[0]),
        )
        conn.commit()

    cursor.execute(
        "SELECT t.name FROM posts_tags pt JOIN tags t ON t.id = pt.tag_id "
        "WHERE pt.post_id = %s ORDER BY t.name",
        (post_id,),
    )
    remaining = [r[0] for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"tag_list": remaining})


# ─── Like / unlike a post ─────────────────────────────────────────────────────

def _set_like(post_id, liked):
    """Shared body of like / unlike: store or remove the session user's like on
    ``post_id`` and reply with ``{"liked", "like_count"}``, the post's fresh total."""
    if not is_db_available():
        return jsonify({"error": "Database unavailable. Write actions are disabled."}), 503

    me     = g.current_user
    conn   = get_db_connection()
    cursor = conn.cursor()
    # Checked first: INSERT IGNORE would also swallow the foreign-key error of a
    # missing post (as a warning) and report a like that was never stored.
    cursor.execute("SELECT id FROM posts WHERE id = %s", (post_id,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"error": "Post not found"}), 404

    if liked:
        # INSERT IGNORE + composite primary key: liking twice is a no-op (idempotent).
        cursor.execute(
            "INSERT IGNORE INTO likes (user_id, post_id) VALUES (%s, %s)", (me["id"], post_id)
        )
    else:
        cursor.execute(
            "DELETE FROM likes WHERE user_id = %s AND post_id = %s", (me["id"], post_id)
        )
    conn.commit()
    cursor.execute("SELECT COUNT(*) FROM likes WHERE post_id = %s", (post_id,))
    like_count = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return jsonify({"liked": liked, "like_count": like_count})


@app.route("/api/articles/<int:post_id>/like", methods=["POST"])
@require_session
def like_article(post_id):
    # The liker is the session user, never a user id from the request body.
    return _set_like(post_id, True)


@app.route("/api/articles/<int:post_id>/like", methods=["DELETE"])
@require_session
def unlike_article(post_id):
    return _set_like(post_id, False)


# ─── Comments (replies one level deep) ────────────────────────────────────────

MAX_COMMENT_CHARS = 2000    # visible text: what the comment box counts
# Raw HTML, checked before bleach parses it. Sanitizing grows a character to at most
# 5 ("&" -> "&amp;"), so a stored comment stays under TEXT's 64 KB.
MAX_COMMENT_HTML = 10000

_COMMENT_SELECT = """
    SELECT c.id, c.post_id, c.parent_id, c.body_html, c.created_at,
           u.username, u.name, u.avatar, u.profile_image
    FROM comments c
    JOIN users u ON u.id = c.author_id
"""


def _shape_comment(row):
    """A comments row joined with its author, as the API returns it. The body is
    sanitized again on the way out, like a post's, and the author has no email."""
    return {
        "id": row["id"],
        "post_id": row["post_id"],
        "parent_id": row.get("parent_id"),
        "body_html": sanitize_html(row.get("body_html") or ""),
        "created_at": _iso(row.get("created_at")),
        "user": {
            "username": row.get("username", ""),
            "name": row.get("name", ""),
            "profile_image": row.get("profile_image") or row.get("avatar") or
                             f"{DICEBEAR_URL}?seed={row.get('username', '')}",
        },
    }


def _comment_tree(rows):
    """A post's comments as a thread: the top-level comments, each with its
    ``replies``, both levels in the order of ``rows``. A reply whose parent is not
    a top-level comment here is left out (the API never creates one)."""
    comments = [_shape_comment(row) for row in rows]
    top = {c["id"]: c for c in comments if c["parent_id"] is None}
    for comment in top.values():
        comment["replies"] = []
    for comment in comments:
        if comment["parent_id"] in top:
            top[comment["parent_id"]]["replies"].append(comment)
    return list(top.values())


def _comment_count(cursor, post_id):
    """All of the post's comments, replies included. ``cursor`` is a dictionary cursor."""
    cursor.execute("SELECT COUNT(*) AS comment_count FROM comments WHERE post_id = %s", (post_id,))
    return int(cursor.fetchone()["comment_count"])


def _check_comment_target(cursor, post_id, parent_id):
    """None when a comment may go on ``post_id``, under ``parent_id`` if one is
    given; else the error response. The post is checked before the INSERT, whose
    foreign-key error (1452) would otherwise be a 500."""
    cursor.execute("SELECT id FROM posts WHERE id = %s", (post_id,))
    if not cursor.fetchone():
        return jsonify({"error": "Post not found"}), 404
    if parent_id is None:
        return None
    cursor.execute("SELECT post_id, parent_id FROM comments WHERE id = %s", (parent_id,))
    parent = cursor.fetchone()
    if parent is None or parent["post_id"] != post_id:
        return jsonify({"error": "parent_id must be a comment on this post"}), 400
    # MySQL cannot enforce this (a CHECK may not read another row), so the API does.
    if parent["parent_id"] is not None:
        return jsonify({"error": "Replies are one level deep: reply to the top comment instead"}), 400
    return None


def _require_comment_owner(cursor, comment_id, user_id, admin_ok=False):
    """``(comment row, None)`` when user_id wrote comment_id (or ``admin_ok`` and it
    exists), else ``(None, error response)``. ``cursor`` is a dictionary cursor."""
    cursor.execute("SELECT author_id, post_id FROM comments WHERE id = %s", (comment_id,))
    comment = cursor.fetchone()
    if comment is None:
        return None, (jsonify({"error": "Comment not found"}), 404)
    if comment["author_id"] != user_id and not admin_ok:
        return None, (jsonify({"error": "You can only delete your own comments"}), 403)
    return comment, None


@app.route("/api/articles/<int:post_id>/comments")
def get_comments(post_id):
    """The post's comments as a tree, oldest first. There is no mock fallback: an
    unreachable DB is a 503, since an empty list would say the post has no comments."""
    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM posts WHERE id = %s", (post_id,))
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"error": "Post not found"}), 404
        # created_at has one-second resolution; id breaks ties in insertion order.
        cursor.execute(
            _COMMENT_SELECT + "WHERE c.post_id = %s ORDER BY c.created_at, c.id", (post_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(_comment_tree(rows))
    except Exception as exc:
        return jsonify({"error": "Database unavailable", "detail": str(exc)}), 503


@app.route("/api/articles/<int:post_id>/comments", methods=["POST"])
@require_session
def create_comment(post_id):
    if not is_db_available():
        return jsonify({"error": "Database unavailable. Write actions are disabled."}), 503

    data      = _json_object(request.get_json())
    raw_html  = _str_field(data, "body_html", strip=False)
    parent_id = data.get("parent_id")
    # bool is an int in Python: "parent_id": true must not mean comment 1.
    if parent_id is not None and (isinstance(parent_id, bool) or not isinstance(parent_id, int)):
        return jsonify({"error": "parent_id must be a comment id"}), 400
    if len(raw_html) > MAX_COMMENT_HTML:
        return jsonify({"error": "Comment is too long"}), 400
    # Sanitized before it is stored (and again when it is read).
    body_html = sanitize_html(raw_html)
    text = html_to_text(body_html)
    if not text:
        return jsonify({"error": "Comment cannot be empty"}), 400
    if len(text) > MAX_COMMENT_CHARS:
        return jsonify({"error": f"Comment must be {MAX_COMMENT_CHARS} characters or fewer"}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    err = _check_comment_target(cursor, post_id, parent_id)
    if err:
        cursor.close()
        conn.close()
        return err

    # After the target checks, so a missing post is a 404 and costs no LLM call.
    verdict = moderator.check_comment(text, user_id=g.current_user["id"])
    if verdict.blocked:
        cursor.close()
        conn.close()
        return _moderation_error(verdict, "comment")

    # The writer is the session user, never an id from the request body.
    cursor.execute(
        "INSERT INTO comments (post_id, author_id, parent_id, body_html) VALUES (%s, %s, %s, %s)",
        (post_id, g.current_user["id"], parent_id, body_html),
    )
    comment_id = cursor.lastrowid
    conn.commit()
    cursor.execute(_COMMENT_SELECT + "WHERE c.id = %s", (comment_id,))
    comment = _shape_comment(cursor.fetchone())
    if parent_id is None:
        comment["replies"] = []
    comment_count = _comment_count(cursor, post_id)
    cursor.close()
    conn.close()
    return jsonify({"comment": comment, "comment_count": comment_count}), 201


@app.route("/api/comments/<int:comment_id>", methods=["DELETE"])
@require_session
def delete_comment(comment_id):
    if not is_db_available():
        return jsonify({"error": "Database unavailable. Write actions are disabled."}), 503

    # Its writer, or an admin (moderation).
    me     = g.current_user
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    comment, err = _require_comment_owner(cursor, comment_id, me["id"],
                                          admin_ok=me.get("role") == "admin")
    if err:
        cursor.close()
        conn.close()
        return err
    # ON DELETE CASCADE (comments.parent_id) removes its replies with it.
    cursor.execute("DELETE FROM comments WHERE id = %s", (comment_id,))
    conn.commit()
    comment_count = _comment_count(cursor, comment["post_id"])
    cursor.close()
    conn.close()
    return jsonify({"deleted": True, "id": comment_id, "comment_count": comment_count})


# ─── Reports: a user flags a post or a comment for the admins ─────────────────

REPORT_REASONS = ("spam", "harassment", "hate", "misinformation", "other")
MAX_REPORT_DETAILS = 500      # reports.details VARCHAR(500)
DUPLICATE_KEY = 1062          # MySQL ER_DUP_ENTRY
# The fixed SQL per target kind (never built from the request).
_REPORT_TARGETS = {
    "post_id":    ("post", "SELECT author_id FROM posts WHERE id = %s",
                   "INSERT INTO reports (reporter_id, post_id, reason, details) VALUES (%s, %s, %s, %s)"),
    "comment_id": ("comment", "SELECT author_id FROM comments WHERE id = %s",
                   "INSERT INTO reports (reporter_id, comment_id, reason, details) VALUES (%s, %s, %s, %s)"),
}


@app.route("/api/reports", methods=["POST"])
@require_session
def create_report():
    """Report one post or one comment: ``{post_id | comment_id, reason, details?}``.
    One report per user and target: a second one is answered as already reported."""
    if not is_db_available():
        return jsonify({"error": "Database unavailable. Write actions are disabled."}), 503

    data = _json_object(request.get_json())
    given = [key for key in _REPORT_TARGETS if data.get(key) is not None]
    if len(given) != 1:
        return jsonify({"error": "Report exactly one of post_id or comment_id"}), 400
    key = given[0]
    target_id = data[key]
    if not _is_id(target_id):
        return jsonify({"error": f"{key} must be an id"}), 400
    reason = _str_field(data, "reason")
    if reason not in REPORT_REASONS:
        return jsonify({"error": f"reason must be one of: {', '.join(REPORT_REASONS)}"}), 400
    details = _str_field(data, "details")
    if len(details) > MAX_REPORT_DETAILS:
        return jsonify({"error": f"details must be {MAX_REPORT_DETAILS} characters or fewer"}), 400

    kind, select_sql, insert_sql = _REPORT_TARGETS[key]
    me     = g.current_user
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(select_sql, (target_id,))
        target = cursor.fetchone()
        if target is None:
            return jsonify({"error": f"{kind.capitalize()} not found"}), 404
        if target["author_id"] == me["id"]:
            return jsonify({"error": f"You cannot report your own {kind}"}), 400
        # The reporter is the session user, never an id from the request body.
        try:
            cursor.execute(insert_sql, (me["id"], target_id, reason, details or None))
            conn.commit()
        except mysql.connector.IntegrityError as exc:
            # Only the unique keys (one report per user and target) mean "already
            # reported". Any other error (a target deleted meanwhile: 1452) is a real
            # failure and goes up as one.
            if exc.errno != DUPLICATE_KEY:
                raise
            conn.rollback()
            return jsonify({"reported": True, "already": True})
        return jsonify({"reported": True, "already": False, "id": cursor.lastrowid}), 201
    finally:
        cursor.close()
        conn.close()


# ─── Admin: the reports list ──────────────────────────────────────────────────

REPORT_STATUSES = ("open", "resolved")
ADMIN_REPORT_LIMIT = 100
REPORT_EXCERPT_CHARS = 200

# A report with its target (the post, or the comment and its post), the target's
# author, the reporter and the admin who resolved it. The body is cut in SQL so a
# long post is not read whole; html_to_text copes with a tag cut in half.
_REPORT_SELECT = """
    SELECT r.id, r.post_id, r.comment_id, r.reason, r.details, r.status,
           r.created_at, r.resolved_at,
           reporter.username AS reporter_username,
           resolver.username AS resolved_by_username,
           p.id AS target_post_id, p.title AS post_title,
           LEFT(COALESCE(c.body_html, p.body_html, p.body), 3000) AS target_html,
           author.id AS author_id, author.username AS author_username,
           author.is_banned AS author_is_banned
    FROM reports r
    JOIN users reporter ON reporter.id = r.reporter_id
    LEFT JOIN users resolver ON resolver.id = r.resolved_by
    LEFT JOIN comments c ON c.id = r.comment_id
    JOIN posts p ON p.id = COALESCE(r.post_id, c.post_id)
    JOIN users author ON author.id = COALESCE(c.author_id, p.author_id)
"""


def _excerpt(text, limit=REPORT_EXCERPT_CHARS):
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _shape_report(row):
    """A report as the admin page shows it. No email; ``details`` is the reporter's
    plain text, which the UI shows as text, never as HTML."""
    kind = "post" if row.get("post_id") is not None else "comment"
    return {
        "id":          row["id"],
        "reason":      row["reason"],
        "details":     row.get("details"),
        "status":      row["status"],
        "created_at":  _iso(row.get("created_at")),
        "resolved_at": _iso(row.get("resolved_at")),
        "resolved_by": row.get("resolved_by_username"),
        "reporter":    {"username": row.get("reporter_username")},
        "target": {
            "type":       kind,
            "id":         row["post_id"] if kind == "post" else row["comment_id"],
            "post_id":    row.get("target_post_id"),
            "post_title": row.get("post_title"),
            "excerpt":    _excerpt(html_to_text(row.get("target_html") or "")),
        },
        "author": {
            "id":        row.get("author_id"),
            "username":  row.get("author_username"),
            "is_banned": bool(row.get("author_is_banned")),
        },
    }


@app.route("/api/admin/reports")
@require_admin
def admin_list_reports():
    """The newest ADMIN_REPORT_LIMIT reports with ``status`` (default open)."""
    status = request.args.get("status", "open")
    if status not in REPORT_STATUSES:
        return jsonify({"error": "status must be open or resolved"}), 400
    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            _REPORT_SELECT + "WHERE r.status = %s ORDER BY r.created_at DESC, r.id DESC LIMIT %s",
            (status, ADMIN_REPORT_LIMIT),
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception as exc:
        return jsonify({"error": "Database unavailable", "detail": str(exc)}), 503
    return jsonify([_shape_report(row) for row in rows])


@app.route("/api/admin/reports/<int:report_id>/resolve", methods=["POST"])
@require_admin
def resolve_report(report_id):
    """Dismiss a report: the content stays. Resolving twice keeps the first admin
    and time. (Deleting the content instead removes its reports: CASCADE.)"""
    if not is_db_available():
        return jsonify({"error": "Database unavailable. Write actions are disabled."}), 503

    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT status FROM reports WHERE id = %s", (report_id,))
    report = cursor.fetchone()
    if report is None:
        cursor.close()
        conn.close()
        return jsonify({"error": "Report not found"}), 404
    if report["status"] == "open":
        cursor.execute(
            "UPDATE reports SET status = 'resolved', resolved_by = %s, resolved_at = NOW() "
            "WHERE id = %s AND status = 'open'",
            (g.current_user["id"], report_id),
        )
        conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"id": report_id, "status": "resolved"})


# ─── Admin: users (find, ban, unban) ──────────────────────────────────────────
# A ban only shuts the account out (login and every session); the user's posts and
# comments stay until an admin deletes them, and reports about them stay open.

ADMIN_USER_LIMIT = 20


def _admin_user_shape(row):
    """A user as the admin page lists it: no email, like every other user list."""
    return {
        "id":        row["id"],
        "username":  row["username"],
        "name":      row.get("name"),
        "role":      row.get("role") or "user",
        "is_banned": bool(row.get("is_banned")),
    }


@app.route("/api/admin/users")
@require_admin
def admin_list_users():
    """Up to ADMIN_USER_LIMIT users by username: those matching ``q`` (username or
    name, never email), or only the banned ones with ``banned=1``."""
    q = (request.args.get("q") or "").strip()
    banned_only = request.args.get("banned") == "1"
    # The conditions are fixed strings; only the values come from the request.
    where, params = [], []
    if q:
        where.append("(username LIKE %s OR name LIKE %s)")
        params += [f"%{q}%"] * 2
    if banned_only:
        where.append("is_banned")
    sql = "SELECT id, username, name, role, is_banned FROM users"
    if where:
        sql += " WHERE " + " AND ".join(where)
    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql + " ORDER BY username LIMIT %s", params + [ADMIN_USER_LIMIT])
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception as exc:
        return jsonify({"error": "Database unavailable", "detail": str(exc)}), 503
    return jsonify([_admin_user_shape(row) for row in rows])


def _set_banned(user_id, banned):
    """Shared body of ban / unban. A ban also deletes every session of the user, in
    the same transaction, so they are logged out everywhere at once."""
    if not is_db_available():
        return jsonify({"error": "Database unavailable. Write actions are disabled."}), 503
    if banned and user_id == g.current_user["id"]:
        return jsonify({"error": "You cannot ban yourself"}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, username, name, role, is_banned FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    if user is None:
        cursor.close()
        conn.close()
        return jsonify({"error": "User not found"}), 404
    # One admin cannot lock another out; a role change is a job for manage.py.
    if banned and user.get("role") == "admin":
        cursor.close()
        conn.close()
        return jsonify({"error": "An admin cannot be banned"}), 403

    cursor.execute("UPDATE users SET is_banned = %s WHERE id = %s", (banned, user_id))
    if banned:
        cursor.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify(_admin_user_shape({**user, "is_banned": banned}))


@app.route("/api/admin/users/<int:user_id>/ban", methods=["POST"])
@require_admin
def ban_user(user_id):
    return _set_banned(user_id, True)


@app.route("/api/admin/users/<int:user_id>/ban", methods=["DELETE"])
@require_admin
def unban_user(user_id):
    return _set_banned(user_id, False)


# ─── AI assistance: correct a draft, draft a post, propose a comment ──────────
# Suggestions only: nothing is stored, and whatever the user publishes from them
# goes through moderation like anything else. The prompts live in ai_assist.py.

AI_USER_DAILY_LIMIT = ai_assist.user_daily_limit(os.environ)


def _ai_error(exc):
    """The response for an LLMError, worded for the person waiting on it."""
    if isinstance(exc, llm.LLMRateLimited):
        resp = make_response(jsonify({"error": "The AI service is busy right now. Try again in a minute."}), 429)
        if exc.retry_after:
            resp.headers["Retry-After"] = str(exc.retry_after)
        return resp
    if isinstance(exc, llm.LLMLimitReached):
        return jsonify({"error": "PulseNet has used up today's AI quota. Try again tomorrow."}), 429
    if isinstance(exc, llm.LLMTimeout):
        return jsonify({"error": "The AI service took too long to answer. Try again."}), 503
    return jsonify({"error": "AI assistance is unavailable right now. Try again later."}), 503


def _ask_ai(purpose, prompt, system):
    """``(reply, None)``, or ``(None, error response)``: AI assistance is off, the
    session user has used today's AI_USER_DAILY_LIMIT requests, or the LLM failed."""
    if llm_service is None:
        return None, (jsonify({"error": "AI assistance is turned off on this server."}), 503)
    user_id = g.current_user["id"]
    try:
        # Soft, like the daily limit: the count is read before the call.
        if llm_service.user_usage_today(user_id, ai_assist.PURPOSES) >= AI_USER_DAILY_LIMIT:
            return None, (jsonify({
                "error": f"You have used today's {AI_USER_DAILY_LIMIT} AI requests. "
                         "They renew at midnight UTC.",
            }), 429)
        return llm_service.complete(prompt, system=system, purpose=purpose, user_id=user_id), None
    except llm.LLMError as exc:
        return None, _ai_error(exc)


def _empty_suggestion():
    return _ai_error(llm.LLMBadReply("the suggestion is empty"))


@app.route("/api/ai/correct", methods=["POST"])
@require_session
def ai_correct():
    """Correct a draft's spelling and grammar: the post editor's HTML
    (``"format": "html"``) or a comment's plain text (``"text"``, the default)."""
    data = _json_object(request.get_json())
    text = _str_field(data, "text", strip=False)
    fmt  = _str_field(data, "format") or "text"
    if fmt not in ai_assist.FORMATS:
        return jsonify({"error": "format must be text or html"}), 400
    if len(text) > ai_assist.MAX_INPUT_CHARS:
        return jsonify({"error": f"AI correction takes up to {ai_assist.MAX_INPUT_CHARS} characters"}), 400
    if fmt == "html":
        text = sanitize_html(text)       # the model sees what would be stored, nothing more
    if not (html_to_text(text) if fmt == "html" else text.strip()):
        return jsonify({"error": "There is no text to correct"}), 400

    reply, err = _ask_ai("ai_correct", *ai_assist.correct_request(text, fmt))
    if err:
        return err
    corrected = ai_assist.clean_reply(reply, "draft")
    if fmt == "html":
        # Model output is untrusted HTML: sanitized like anything a user submits.
        corrected = sanitize_html(corrected)
    if not (html_to_text(corrected) if fmt == "html" else corrected.strip()):
        return _empty_suggestion()
    return jsonify({"text": corrected})


@app.route("/api/ai/suggest-post", methods=["POST"])
@require_session
def ai_suggest_post():
    """Draft a post body from its title (and tags), as sanitized HTML for the editor."""
    data  = _json_object(request.get_json())
    title = _str_field(data, "title")
    tags  = _clean_tags(data.get("tags"))
    if not title:
        return jsonify({"error": "Write a title first: the draft is written from it"}), 400
    if len(title) > MAX_TITLE_CHARS:
        return jsonify({"error": f"Title must be {MAX_TITLE_CHARS} characters or fewer"}), 400

    reply, err = _ask_ai("ai_suggest_post", *ai_assist.suggest_post_request(title, tags))
    if err:
        return err
    # The model writes Markdown; the HTML is sanitized like a markdown post's.
    body_html = sanitize_html(to_html(ai_assist.clean_reply(reply)))
    if not html_to_text(body_html):
        return _empty_suggestion()
    return jsonify({"body_html": body_html})


def _is_id(value):
    # bool is an int in Python: true must not mean id 1.
    return isinstance(value, int) and not isinstance(value, bool)


def _suggestion_context(post_id, parent_id):
    """``((title, post text, parent), None)`` for proposing a comment, read from the
    DB and never taken from the request (``parent`` is (username, text) or None);
    else ``(None, error response)``."""
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT title, body, body_html FROM posts WHERE id = %s", (post_id,))
        post = cursor.fetchone()
        if not post:
            return None, (jsonify({"error": "Post not found"}), 404)
        parent = None
        if parent_id is not None:
            cursor.execute(
                "SELECT c.post_id, c.body_html, u.username FROM comments c "
                "JOIN users u ON u.id = c.author_id WHERE c.id = %s",
                (parent_id,),
            )
            row = cursor.fetchone()
            if row is None or row["post_id"] != post_id:
                return None, (jsonify({"error": "parent_id must be a comment on this post"}), 400)
            parent = (row["username"], html_to_text(row["body_html"] or ""))
        text = html_to_text(post["body_html"]) if post.get("body_html") else (post.get("body") or "")
        return (post["title"], text, parent), None
    finally:
        cursor.close()
        conn.close()


@app.route("/api/ai/suggest-comment", methods=["POST"])
@require_session
def ai_suggest_comment():
    """Propose a comment on a post, or a reply to one of its comments, from what
    they say. Plain text, for the comment box."""
    data      = _json_object(request.get_json())
    post_id   = data.get("post_id")
    parent_id = data.get("parent_id")
    if not _is_id(post_id):
        return jsonify({"error": "post_id must be a post id"}), 400
    if parent_id is not None and not _is_id(parent_id):
        return jsonify({"error": "parent_id must be a comment id"}), 400
    try:
        context, err = _suggestion_context(post_id, parent_id)
    except Exception as exc:
        return jsonify({"error": "Database unavailable", "detail": str(exc)}), 503
    if err:
        return err

    # The DB connection is closed before the LLM call, which can take seconds.
    reply, err = _ask_ai("ai_suggest_comment", *ai_assist.suggest_comment_request(*context))
    if err:
        return err
    text = ai_assist.clean_reply(reply, unquote=True)[:MAX_COMMENT_CHARS].strip()
    if not text:
        return _empty_suggestion()
    return jsonify({"text": text})


# ─── Image upload (local storage, no external services) ────────────────────────

def _file_ext(filename):
    return filename.rsplit(".", 1)[1].lower() if "." in filename else ""


def _ext_ok(filename):
    return _file_ext(filename) in ALLOWED_IMAGE_EXT


def _validate_image_upload(filename, data):
    ext = _file_ext(filename)
    if ext not in ALLOWED_IMAGE_EXT:
        raise ValueError("Unsupported file type. Use PNG, JPG, GIF, or WEBP.")
    if len(data) == 0 or len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("File is empty or larger than 5 MB")

    try:
        with Image.open(BytesIO(data)) as image:
            detected_format = (image.format or "").upper()
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("Uploaded file is not a valid image") from exc

    allowed_exts = IMAGE_FORMAT_EXTS.get(detected_format)
    if allowed_exts is None:
        raise ValueError("Unsupported image content. Use PNG, JPG, GIF, or WEBP.")
    if ext not in allowed_exts:
        raise ValueError("File extension does not match image content")
    return detected_format


@app.route("/api/upload", methods=["POST"])
@require_session
def upload_image():
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"error": "No file provided (form field must be named 'file')"}), 400
    if not _ext_ok(file.filename):
        return jsonify({"error": "Unsupported file type. Use PNG, JPG, GIF, or WEBP."}), 400

    data = file.read(MAX_UPLOAD_BYTES + 1)
    try:
        _validate_image_upload(file.filename, data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    ext   = _file_ext(file.filename)
    # Random server-side name avoids collisions and path tricks; secure_filename
    # is a belt-and-suspenders pass over our own generated name.
    fname = secure_filename(f"{secrets.token_hex(16)}.{ext}")
    path  = os.path.join(UPLOAD_DIR, fname)
    with open(path, "wb") as saved:
        saved.write(data)

    url = request.host_url.rstrip("/") + f"/uploads/{fname}"
    return jsonify({"url": url}), 201


@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    # Serves locally stored images for <img> tags (same-origin file fetch, no CORS).
    return send_from_directory(UPLOAD_DIR, filename)


@app.errorhandler(413)
def _too_large(_e):
    return jsonify({"error": "File too large (max 5 MB)"}), 413


# ─── POST /api/users ──────────────────────────────────────────────────────────

@app.route("/api/users", methods=["POST"])
def create_user():
    if not is_db_available():
        return jsonify({"error": "Database unavailable. Write actions are disabled."}), 503

    payload, validation_error = _validate_signup_payload(request.get_json())
    if validation_error:
        return jsonify({"error": validation_error}), 400

    name     = payload["name"]
    username = payload["username"]
    email    = payload["email"]
    bio      = payload["bio"]
    password = payload["password"]

    password_hash = _hash_password(password)
    avatar = f"{DICEBEAR_URL}?seed={username}"

    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
    if cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"error": "Username already taken"}), 400

    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
    if cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"error": "Email already registered"}), 400

    cursor.execute(
        "INSERT INTO users (name, username, email, bio, avatar, profile_image, password_hash) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (name, username, email, bio, avatar, avatar, password_hash),
    )
    user_id = cursor.lastrowid

    # Auto-login: create a session row + set the cookie on the response.
    session_id = _create_session(cursor, user_id)
    conn.commit()
    cursor.close()
    conn.close()

    user_payload = {
        "id":            user_id,
        "name":          name,
        "username":      username,
        "email":         email,
        "bio":           bio,
        "avatar":        avatar,
        "profile_image": avatar,
        "role":          "user",          # the column default: signup never sets a role
    }
    resp = make_response(jsonify(user_payload), 201)
    return _set_session_cookie(resp, session_id)


# ─── POST /api/login ──────────────────────────────────────────────────────────

@app.route("/api/login", methods=["POST"])
def login():
    if not is_db_available():
        return jsonify({"error": "Database unavailable. Write actions are disabled."}), 503

    payload, validation_error = _validate_login_payload(request.get_json())
    if validation_error:
        return jsonify({"error": validation_error}), 400
    email    = payload["email"]
    password = payload["password"]

    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, name, username, email, bio, avatar, profile_image, role, is_banned, "
        "password_hash FROM users WHERE email = %s",
        (email,),
    )
    user = cursor.fetchone()

    # Generic error message — don't leak which of email/password was wrong.
    if user is None or not user["password_hash"]:
        cursor.close()
        conn.close()
        return jsonify({"error": "Invalid email or password"}), 401

    # A password bcrypt cannot take matches no account (signup refuses it), and
    # checking it would raise: it is just a wrong password.
    if _password_too_long(password) or not _verify_password(password, user["password_hash"]):
        cursor.close()
        conn.close()
        return jsonify({"error": "Invalid email or password"}), 401

    # After the password check, so only the account's owner learns it is banned.
    if user.get("is_banned"):
        cursor.close()
        conn.close()
        return jsonify({"error": "This account has been suspended"}), 403

    session_id = _create_session(cursor, user["id"])
    conn.commit()
    cursor.close()
    conn.close()

    resp = make_response(jsonify(_user_shape(user)))
    return _set_session_cookie(resp, session_id)


# ─── POST /api/logout ─────────────────────────────────────────────────────────

@app.route("/api/logout", methods=["POST"])
@require_session
def logout():
    """Log out the current session, or every session for the user.

    Body ``{"allDevices": true}`` deletes all of the user's sessions ("log out
    everywhere"); an empty/false body deletes only the current session row
    ("log out this device"). ``require_session`` gates both — an absent/expired
    cookie yields 401 after expired rows have been purged."""
    sid         = request.cookies.get(SESSION_COOKIE_NAME)
    data        = request.get_json(silent=True)   # no body / no JSON header is fine
    # A junk body (a list, a string) must not block a logout: read it as {}.
    all_devices = isinstance(data, dict) and bool(data.get("allDevices"))
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        if all_devices:
            # Invalidate every session for this user (idx_sessions_user covers this).
            cursor.execute("DELETE FROM sessions WHERE user_id = %s", (g.current_user["id"],))
        else:
            cursor.execute("DELETE FROM sessions WHERE session_id = %s", (sid,))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception:
        # Even if the DB delete fails, still clear the cookie client-side.
        pass

    msg  = "Logged out from all devices" if all_devices else "Logged out"
    resp = make_response(jsonify({"message": msg}))
    return _clear_session_cookie(resp)


# ─── Password reset: POST /api/password/forgot and /api/password/reset ────────
# A one-time link by email (password_reset.py builds the token, link and mail).
# Only the token's SHA-256 is stored; the link works once, for TOKEN_TTL_MINUTES.

FORGOT_MESSAGE = (
    "If an account uses that email, we sent it a link to reset the password. "
    f"The link works for {password_reset.TOKEN_TTL_MINUTES} minutes."
)
RESET_LINK_INVALID = "This reset link is invalid or has expired."


@app.route("/api/password/forgot", methods=["POST"])
def forgot_password():
    """Mail a reset link to the account with this email, if there is one. The
    answer is the same 200 either way, so it cannot tell whether an address has an
    account. At most MAX_REQUESTS_PER_HOUR links per user; agents get none (they
    have no password and must never get one). A banned user does get one: their
    login still answers 403."""
    if mail_service is None:
        return jsonify({"error": "Password reset is not available on this server."}), 503
    data  = _json_object(request.get_json())
    email = _str_field(data, "email")
    if not email:
        return jsonify({"error": "email is required"}), 400
    if len(email) > 100:
        return jsonify({"error": "Email must be 100 characters or fewer"}), 400
    if not is_db_available():
        return jsonify({"error": "Database unavailable. Write actions are disabled."}), 503

    user, token, token_hash = None, None, None
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Links past their expiry by a day are of no use, even to the hourly count.
        cursor.execute("DELETE FROM password_resets WHERE expires_at < NOW() - INTERVAL 1 DAY")
        cursor.execute("SELECT id, name, email FROM users WHERE email = %s AND NOT is_agent", (email,))
        user = cursor.fetchone()
        if user is not None:
            cursor.execute(
                "SELECT COUNT(*) AS recent FROM password_resets "
                "WHERE user_id = %s AND created_at > NOW() - INTERVAL 1 HOUR",
                (user["id"],),
            )
            if cursor.fetchone()["recent"] < password_reset.MAX_REQUESTS_PER_HOUR:
                token, token_hash = password_reset.new_token()
                cursor.execute(
                    "INSERT INTO password_resets (user_id, token_hash, expires_at) "
                    "VALUES (%s, %s, NOW() + INTERVAL %s MINUTE)",
                    (user["id"], token_hash, password_reset.TOKEN_TTL_MINUTES),
                )
            else:
                app.logger.info("password reset: user %s is over the hourly limit", user["id"])
        # The link is stored before its mail goes out, so a mailed link always exists.
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    # The connection is closed before the send, which can take seconds.
    if token is not None:
        _send_reset_mail(user, token, token_hash)
    return jsonify({"message": FORGOT_MESSAGE})


def _send_reset_mail(user, token, token_hash):
    """Mail the link. If the mail fails, its link is deleted: nobody received it, so
    it must neither stay valid nor count toward the user's hourly limit. Either way
    the request still answers 200, so a failure says nothing about the address."""
    link = password_reset.reset_link(reset_base_url, token)
    try:
        mail_service.send(password_reset.reset_mail(user["email"], user["name"], link))
        return
    except mailer.MailError as exc:
        # The user id, never the address; MailError messages carry no address.
        app.logger.warning("password reset mail for user %s not sent (%s)", user["id"], exc)
    conn = cursor = None
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM password_resets WHERE token_hash = %s", (token_hash,))
        conn.commit()
    except Exception as exc:
        # It expires in TOKEN_TTL_MINUTES anyway; until then it counts toward the limit.
        app.logger.warning("password reset link of user %s not removed after the failed mail (%s)",
                           user["id"], type(exc).__name__)
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@app.route("/api/password/reset", methods=["POST"])
def reset_password():
    """Set a new password with a link from /api/password/forgot. The link is used
    up, with every other open link of the user, and all their sessions are deleted
    (logged out everywhere, as a ban does), in one transaction. It does not log in."""
    data     = _json_object(request.get_json())
    token    = _str_field(data, "token")
    password = _str_field(data, "password", strip=False)
    if not token or len(token) > password_reset.MAX_TOKEN_CHARS:
        return jsonify({"error": RESET_LINK_INVALID}), 400
    password_error = _password_error(password)
    if password_error:
        return jsonify({"error": password_error}), 400
    if not is_db_available():
        return jsonify({"error": "Database unavailable. Write actions are disabled."}), 503

    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # FOR UPDATE: two requests with the same link queue here, and the second
        # then sees used_at set. Only the hash is compared; the token is never stored.
        cursor.execute(
            """
            SELECT pr.id, pr.user_id FROM password_resets pr
            JOIN users u ON u.id = pr.user_id
            WHERE pr.token_hash = %s AND pr.used_at IS NULL AND pr.expires_at > NOW()
              AND NOT u.is_agent
            FOR UPDATE
            """,
            (password_reset.hash_token(token),),
        )
        link = cursor.fetchone()
        if link is None:
            conn.rollback()
            return jsonify({"error": RESET_LINK_INVALID}), 400
        user_id = link["user_id"]
        # bcrypt only for a real link, so guessing links costs the server nothing.
        cursor.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                       (_hash_password(password), user_id))
        cursor.execute("UPDATE password_resets SET used_at = NOW() "
                       "WHERE user_id = %s AND used_at IS NULL", (user_id,))
        cursor.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return jsonify({"message": "Your password was changed. Log in with the new one."})


# ─── GET /api/me ──────────────────────────────────────────────────────────────

@app.route("/api/me")
@require_session
def get_me():
    return jsonify(_user_shape(g.current_user))


# ─── PATCH /api/me (update own profile) ────────────────────────────────────────

@app.route("/api/me", methods=["PATCH"])
@require_session
def update_me():
    if not is_db_available():
        return jsonify({"error": "Database unavailable. Write actions are disabled."}), 503

    data = _json_object(request.get_json())
    user = g.current_user

    # Only these three fields are editable; keys below are fixed (never user input).
    fields = {}
    if "name" in data:
        name = _str_field(data, "name")
        if not name:
            return jsonify({"error": "Name cannot be empty"}), 400
        if len(name) > 100:
            return jsonify({"error": "Name must be 100 characters or fewer"}), 400
        fields["name"] = name
    if "bio" in data:
        fields["bio"] = _str_field(data, "bio")
    if "profile_image" in data:
        img = _str_field(data, "profile_image")
        if len(img) > 500:
            return jsonify({"error": "Image URL is too long"}), 400
        fields["profile_image"] = img or None

    if not fields:
        return jsonify({"error": "No updatable fields provided"}), 400

    conn   = get_db_connection()
    cursor = conn.cursor()
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    cursor.execute(
        f"UPDATE users SET {set_clause} WHERE id = %s",
        list(fields.values()) + [user["id"]],
    )
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify(_user_shape({**user, **fields}))


# ─── GET /api/users/search ────────────────────────────────────────────────────

@app.route("/api/users/search")
def search_users():
    q      = request.args.get("q")
    limit  = request.args.get("limit",  10, type=int)
    offset = request.args.get("offset",  0, type=int)

    if not q:
        return jsonify({"error": "Missing query parameter 'q'"}), 400

    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        like   = f"%{q}%"
        # Emails are private: not returned, and not matched either, or searching
        # for an address would reveal whose it is.
        cursor.execute(
            "SELECT id, name, username, avatar FROM users "
            "WHERE name LIKE %s OR username LIKE %s "
            "LIMIT %s OFFSET %s",
            (like, like, limit, offset),
        )
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(results)
    except Exception:
        return jsonify(mock_search_users(q, limit, offset))


# ─── GET /api/users (list with post counts) ───────────────────────────────────

@app.route("/api/users")
def list_users():
    # Paged user list for the Users page. Optional `q` filters by username or name
    # (LIKE). `limit`/`offset` drive the "first 10 + Load More" flow.
    q      = (request.args.get("q") or "").strip()
    limit  = request.args.get("limit",  10, type=int)
    offset = request.args.get("offset",  0, type=int)

    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # `where` is a fixed string (never user input); the values are parameterized.
        # Search by username (the requirement), with name as a forgiving superset.
        # Never by email: it is private, and matching on it would leak it.
        where  = "WHERE (u.username LIKE %s OR u.name LIKE %s)" if q else ""
        params = ([f"%{q}%"] * 2 if q else []) + [limit, offset]
        cursor.execute(
            f"""
            SELECT u.id, u.name, u.username, u.bio,
                   u.avatar, u.profile_image,
                   COUNT(p.id) AS post_count
            FROM users u
            LEFT JOIN posts p ON p.author_id = u.id
            {where}
            GROUP BY u.id
            ORDER BY post_count DESC, u.username
            LIMIT %s OFFSET %s
            """,
            params,
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(rows)
    except Exception as exc:
        return jsonify({"error": "Database unavailable", "detail": str(exc)}), 503


# ─── GET /api/users/<username> ────────────────────────────────────────────────

@app.route("/api/users/<username>")
def get_user_by_username(username):
    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT u.id, u.name, u.username, u.bio,
                   u.avatar, u.profile_image,
                   (SELECT COUNT(*) FROM posts   WHERE author_id   = u.id) AS post_count,
                   (SELECT COUNT(*) FROM follows WHERE following_id = u.id) AS followers_count,
                   (SELECT COUNT(*) FROM follows WHERE follower_id  = u.id) AS following_count
            FROM users u WHERE u.username = %s
            """,
            (username,),
        )
        user = cursor.fetchone()
        if user is None:
            cursor.close()
            conn.close()
            return jsonify({"error": "User not found"}), 404

        # Personalize for the viewer: are they this user / already following them?
        current = _current_user_from_cookie()
        user["is_self"]      = bool(current and current["id"] == user["id"])
        user["is_following"] = False
        if current and not user["is_self"]:
            cursor.execute(
                "SELECT 1 FROM follows WHERE follower_id = %s AND following_id = %s",
                (current["id"], user["id"]),
            )
            user["is_following"] = cursor.fetchone() is not None

        cursor.close()
        conn.close()
        return jsonify(user)
    except Exception as exc:
        return jsonify({"error": "Database unavailable", "detail": str(exc)}), 503


# ─── Follow / unfollow ────────────────────────────────────────────────────────

@app.route("/api/users/<int:user_id>/follow", methods=["POST"])
@require_session
def follow_user(user_id):
    me = g.current_user
    if me["id"] == user_id:
        return jsonify({"error": "You cannot follow yourself"}), 400

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"error": "User not found"}), 404

    # INSERT IGNORE: following someone you already follow is a no-op (idempotent).
    cursor.execute(
        "INSERT IGNORE INTO follows (follower_id, following_id) VALUES (%s, %s)",
        (me["id"], user_id),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"following": True})


@app.route("/api/users/<int:user_id>/follow", methods=["DELETE"])
@require_session
def unfollow_user(user_id):
    me = g.current_user
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM follows WHERE follower_id = %s AND following_id = %s",
        (me["id"], user_id),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"following": False})


def _follow_list(username, column):
    """Shared helper: list users on one side of <username>'s follow edges.

    column='follower_id'  → people who follow <username> (their followers)
    column='following_id' → people <username> follows
    The opposite column is matched against <username>."""
    other = "following_id" if column == "follower_id" else "follower_id"
    limit  = request.args.get("limit",  50, type=int)
    offset = request.args.get("offset",  0, type=int)
    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
        target = cursor.fetchone()
        if target is None:
            cursor.close()
            conn.close()
            return jsonify({"error": "User not found"}), 404
        cursor.execute(
            f"""
            SELECT u.id, u.name, u.username, u.avatar, u.profile_image
            FROM follows f
            JOIN users u ON u.id = f.{column}
            WHERE f.{other} = %s
            ORDER BY f.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (target["id"], limit, offset),
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(rows)
    except Exception as exc:
        return jsonify({"error": "Database unavailable", "detail": str(exc)}), 503


@app.route("/api/users/<username>/followers")
def get_followers(username):
    return _follow_list(username, "follower_id")


@app.route("/api/users/<username>/following")
def get_following(username):
    return _follow_list(username, "following_id")


# ─── GET /api/tags/search ─────────────────────────────────────────────────────

@app.route("/api/tags/search")
def search_tags():
    # Case-insensitive prefix match. Returns every case variant of the typed prefix.
    q     = (request.args.get("q") or "").strip()
    limit = request.args.get("limit", 20, type=int)
    if not q:
        return jsonify([])

    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT name FROM tags "
            "WHERE LOWER(name) LIKE LOWER(%s) "
            "ORDER BY name LIMIT %s",
            (q + "%", limit),
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(rows)
    except Exception as exc:
        return jsonify({"error": "Database unavailable", "detail": str(exc)}), 503


# ─── GET /api/test-db ─────────────────────────────────────────────────────────

@app.route("/api/test-db")
def test_db():
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        conn.close()
        return jsonify({"status": "ok"})
    except Exception as exc:
        return jsonify({"status": "error", "detail": str(exc)}), 500


if __name__ == "__main__":
    # Bind to IPv6 loopback: on Windows "localhost" resolves to ::1 first, and the
    # browser (and the Vite dev server) use ::1 — so the dev server must listen
    # there or browser fetch() calls to http://localhost:5000 fail to connect.
    #
    # NOTE: host="::1" is a LOCAL-DEVELOPMENT / Cypress fix only — it binds IPv6
    # loopback on this machine. For AWS/EC2 (or any real deployment) do NOT use
    # "::1": serve behind a production WSGI server (Gunicorn) + Nginx, or bind
    # host="0.0.0.0" to accept external traffic.
    app.run(debug=True, host="::1", port=5000)
