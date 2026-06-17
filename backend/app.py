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
from functools import wraps

import bcrypt
import mysql.connector
from dotenv import load_dotenv
from flask import Flask, g, jsonify, make_response, request, send_from_directory
from flask_cors import CORS
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename
from mock_data import mock_get_articles, mock_get_article_by_id, mock_search_users

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

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
    )


def is_db_available():
    try:
        conn = get_db_connection()
        conn.close()
        return True
    except Exception:
        return False


# ─── Auth: session helpers & require_session decorator ───────────────────────

SESSION_COOKIE_NAME    = "session_id"
SESSION_DURATION_DAYS  = 7
SESSION_MAX_AGE_SECONDS = SESSION_DURATION_DAYS * 24 * 60 * 60  # 604800


def _user_shape(row):
    """Public user JSON. Must NEVER include password_hash."""
    return {
        "id":            row["id"],
        "name":          row.get("name"),
        "username":      row["username"],
        "email":         row["email"],
        "bio":           row.get("bio"),
        "avatar":        row.get("avatar"),
        "profile_image": row.get("profile_image"),
    }


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
    # Secure flag is omitted in dev (HTTP localhost); add it for HTTPS prod.
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
    matching user on ``g.current_user``; 401 if missing/expired/invalid."""
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
                       u.avatar, u.profile_image
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.session_id = %s AND s.expires_at > NOW()
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
            "WHERE s.session_id = %s AND s.expires_at > NOW()",
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
    """Render a DB datetime as an ISO-8601 string the client can parse for
    relative time. Returns None when the value is missing/unparseable."""
    if dt is None:
        return None
    try:
        return dt.isoformat()
    except AttributeError:
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
        "user": {
            "username": row.get("username", ""),
            "name": row.get("name", ""),
            "email": row.get("email", ""),
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

        if feed == "following":
            # Only posts authored by people the logged-in user follows.
            current = _current_user_from_cookie()
            if not current:
                cursor.close()
                conn.close()
                return jsonify({"error": "Authentication required"}), 401
            cursor.execute(
                """
                SELECT p.id, p.title, p.description, p.cover_image, p.devto_url,
                       p.readable_publish_date, p.created_at,
                       u.username, u.name, u.email, u.avatar, u.profile_image,
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
                (current["id"], per_page, offset),
            )
        elif tag:
            # Exact-case match — tags.name is stored case-sensitively.
            cursor.execute(
                """
                SELECT p.id, p.title, p.description, p.cover_image, p.devto_url,
                       p.readable_publish_date, p.created_at,
                       u.username, u.name, u.email, u.avatar, u.profile_image,
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
                       u.username, u.name, u.email, u.avatar, u.profile_image,
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
                       u.username, u.name, u.email, u.avatar, u.profile_image,
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
        cursor.close()
        conn.close()
        return jsonify(_aggregate_tags(rows))

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
                   u.username, u.name, u.email, u.avatar, u.profile_image,
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

@app.route("/api/articles", methods=["POST"])
@require_session
def create_article():
    if not is_db_available():
        return jsonify({"error": "Database unavailable. Write actions are disabled."}), 503

    data     = request.get_json() or {}
    article  = data.get("article") or {}
    title    = (article.get("title") or "").strip()
    raw_html = article.get("body_html") or ""
    body_md  = (article.get("body_markdown") or "").strip()
    tags     = article.get("tags") or []
    cover    = (article.get("main_image") or "").strip() or None

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

    if len(title) > 150:
        return jsonify({"error": "Title must be 150 characters or fewer"}), 400

    if not isinstance(tags, list):
        return jsonify({"error": "tags must be a list"}), 400

    if len(tags) > 10:
        return jsonify({"error": "You can add at most 10 tags"}), 400

    # Author is derived from the session, not from the request body.
    user = g.current_user

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
        tag_name = tag_name.strip()
        if not tag_name:
            continue
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
        "body_html": body_html,
        "user": {
            "username": user["username"],
            "name": user["name"],
            "email": user["email"],
            "profile_image": user.get("profile_image") or user.get("avatar") or
                             f"{DICEBEAR_URL}?seed={user['username']}",
        },
    }), 201


# ─── Owner-only post management (delete post, remove a tag) ─────────────────────

def _require_post_owner(cursor, post_id, user_id):
    """Return None if user_id owns post_id, else a (response, status) tuple."""
    cursor.execute("SELECT author_id FROM posts WHERE id = %s", (post_id,))
    row = cursor.fetchone()
    if row is None:
        return jsonify({"error": "Post not found"}), 404
    if row[0] != user_id:
        return jsonify({"error": "You can only manage your own posts"}), 403
    return None


@app.route("/api/articles/<int:post_id>", methods=["DELETE"])
@require_session
def delete_article(post_id):
    conn   = get_db_connection()
    cursor = conn.cursor()
    err = _require_post_owner(cursor, post_id, g.current_user["id"])
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

    data     = request.get_json() or {}
    name     = (data.get("name") or "").strip()
    username = (data.get("username") or "").strip()
    email    = (data.get("email") or "").strip()
    bio      = (data.get("bio") or "").strip()
    password = data.get("password") or ""

    if not name or not username or not email:
        return jsonify({"error": "name, username, and email are required"}), 400

    if not password:
        return jsonify({"error": "password is required"}), 400

    if len(name) > 100:
        return jsonify({"error": "Name must be 100 characters or fewer"}), 400

    if len(username) > 100:
        return jsonify({"error": "Username must be 100 characters or fewer"}), 400

    if len(email) > 100:
        return jsonify({"error": "Email must be 100 characters or fewer"}), 400

    if not re.match(r'^[a-zA-Z0-9_.]+$', username):
        return jsonify({"error": "Username may only contain letters, numbers, underscores, and dots"}), 400

    if "@" not in email or "." not in email:
        return jsonify({"error": "Invalid email format"}), 400

    # bcrypt input is bytes; the salt is generated inside the hash output.
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
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
    }
    resp = make_response(jsonify(user_payload), 201)
    return _set_session_cookie(resp, session_id)


# ─── POST /api/login ──────────────────────────────────────────────────────────

@app.route("/api/login", methods=["POST"])
def login():
    if not is_db_available():
        return jsonify({"error": "Database unavailable. Write actions are disabled."}), 503

    data     = request.get_json() or {}
    email    = (data.get("email") or "").strip()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, name, username, email, bio, avatar, profile_image, password_hash "
        "FROM users WHERE email = %s",
        (email,),
    )
    user = cursor.fetchone()

    # Generic error message — don't leak which of email/password was wrong.
    if user is None or not user["password_hash"]:
        cursor.close()
        conn.close()
        return jsonify({"error": "Invalid email or password"}), 401

    if not bcrypt.checkpw(password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        cursor.close()
        conn.close()
        return jsonify({"error": "Invalid email or password"}), 401

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
    data        = request.get_json(silent=True) or {}   # no body / no JSON header is fine
    all_devices = bool(data.get("allDevices"))
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

    data = request.get_json() or {}
    user = g.current_user

    # Only these three fields are editable; keys below are fixed (never user input).
    fields = {}
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "Name cannot be empty"}), 400
        if len(name) > 100:
            return jsonify({"error": "Name must be 100 characters or fewer"}), 400
        fields["name"] = name
    if "bio" in data:
        fields["bio"] = (data.get("bio") or "").strip()
    if "profile_image" in data:
        img = (data.get("profile_image") or "").strip()
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
        cursor.execute(
            "SELECT id, name, username, email, avatar FROM users "
            "WHERE name LIKE %s OR username LIKE %s OR email LIKE %s "
            "LIMIT %s OFFSET %s",
            (like, like, like, limit, offset),
        )
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(results)
    except Exception:
        return jsonify(mock_search_users(q, limit, offset))


# ─── GET /api/users/by-email ──────────────────────────────────────────────────

@app.route("/api/users/by-email")
def get_user_by_email():
    email = (request.args.get("email") or "").strip()
    if not email:
        return jsonify({"error": "Missing query parameter 'email'"}), 400

    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, name, username, email, bio, avatar, profile_image "
            "FROM users WHERE email = %s",
            (email,),
        )
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        if user is None:
            return jsonify({"error": "User not found"}), 404
        return jsonify(user)
    except Exception as exc:
        return jsonify({"error": "Database unavailable", "detail": str(exc)}), 503


# ─── GET /api/users (list with post counts) ───────────────────────────────────

@app.route("/api/users")
def list_users():
    # Paged user list for the Users page. Optional `q` filters by email (LIKE).
    # `limit`/`offset` drive the "first 10 + Load More" flow.
    q      = (request.args.get("q") or "").strip()
    limit  = request.args.get("limit",  10, type=int)
    offset = request.args.get("offset",  0, type=int)

    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # `where` is a fixed string (never user input); the values are parameterized.
        # Search by username (the requirement), with name/email as a forgiving superset.
        where  = "WHERE (u.username LIKE %s OR u.name LIKE %s OR u.email LIKE %s)" if q else ""
        params = ([f"%{q}%"] * 3 if q else []) + [limit, offset]
        cursor.execute(
            f"""
            SELECT u.id, u.name, u.username, u.email, u.bio,
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
            SELECT u.id, u.name, u.username, u.email, u.bio,
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
            SELECT u.id, u.name, u.username, u.email, u.avatar, u.profile_image
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
    app.run(debug=True)
