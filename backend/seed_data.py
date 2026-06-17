"""
Seed the pulsenet_db database with articles fetched from the DEV.to public API.

Usage:
    python seed_data.py

What it does:
  1. Fetches up to 5 pages of articles (30 per page = ~150 articles) from DEV.to.
  2. For each article inserts the author into `users` (INSERT IGNORE on username).
  3. Inserts the article into `posts` (skips duplicates via devto_id UNIQUE constraint).
  4. Inserts tags and links them to the post via `posts_tags`.

Environment variables are read from a .env file in this directory.
"""

import os
import time
import requests  # type: ignore[reportMissingModuleSource]
import mysql.connector
from dotenv import load_dotenv

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

DEVTO_BASE = "https://dev.to/api"
DICEBEAR_URL = "https://api.dicebear.com/7.x/avataaars/svg"
PAGES_TO_FETCH = 5
PER_PAGE = 30


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
    )


def fetch_articles_page(page):
    url = f"{DEVTO_BASE}/articles"
    params = {"page": page, "per_page": PER_PAGE}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def ensure_user(cursor, devto_user):
    """Insert user if not already present (keyed on username). Returns user id."""
    username = devto_user.get("username", "")
    name = devto_user.get("name") or username
    email = f"{username}@dev.to"
    profile_image = devto_user.get("profile_image") or f"{DICEBEAR_URL}?seed={username}"

    cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute(
        "INSERT INTO users (name, username, email, bio, avatar, profile_image) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (name, username, email, "", profile_image, profile_image),
    )
    return cursor.lastrowid


def ensure_tag(cursor, tag_name):
    """Insert tag if not present. Returns tag id.

    Tag names preserve exact casing — tags.name uses utf8mb4_bin so 'react' and
    'React' are stored as distinct rows.
    """
    tag_name = tag_name.strip()
    cursor.execute("INSERT IGNORE INTO tags (name) VALUES (%s)", (tag_name,))
    cursor.execute("SELECT id FROM tags WHERE name = %s", (tag_name,))
    return cursor.fetchone()[0]


def insert_post(cursor, article, author_id):
    """Insert post. Returns new post id, or None if already exists (duplicate devto_id)."""
    devto_id = article.get("id")
    cursor.execute("SELECT id FROM posts WHERE devto_id = %s", (devto_id,))
    if cursor.fetchone():
        return None

    title = (article.get("title") or "")[:150]
    description = article.get("description") or ""
    cover_image = article.get("cover_image") or None
    devto_url = article.get("url") or None
    readable_publish_date = article.get("readable_publish_date") or None

    cursor.execute(
        "INSERT INTO posts "
        "(author_id, title, body, description, cover_image, devto_id, devto_url, readable_publish_date) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (author_id, title, description, description, cover_image,
         devto_id, devto_url, readable_publish_date),
    )
    return cursor.lastrowid


def seed():
    conn = get_db_connection()
    cursor = conn.cursor()

    users_added = 0
    posts_added = 0
    tags_linked = 0

    print(f"Fetching {PAGES_TO_FETCH} pages from DEV.to ({PER_PAGE} articles each)...\n")

    for page in range(1, PAGES_TO_FETCH + 1):
        print(f"  Page {page}/{PAGES_TO_FETCH}...", end=" ", flush=True)
        try:
            articles = fetch_articles_page(page)
        except Exception as exc:
            print(f"FAILED ({exc})")
            continue

        for article in articles:
            devto_user = article.get("user") or {}
            if not devto_user.get("username"):
                continue

            user_existed = cursor.execute("SELECT id FROM users WHERE username = %s",
                                          (devto_user["username"],)) or cursor.fetchone()
            author_id = ensure_user(cursor, devto_user)
            if not user_existed:
                users_added += 1

            post_id = insert_post(cursor, article, author_id)
            if post_id is None:
                continue
            posts_added += 1

            for tag_name in (article.get("tag_list") or []):
                if not tag_name:
                    continue
                tag_id = ensure_tag(cursor, tag_name)
                cursor.execute(
                    "INSERT IGNORE INTO posts_tags (post_id, tag_id) VALUES (%s, %s)",
                    (post_id, tag_id),
                )
                tags_linked += 1

        conn.commit()
        print(f"done ({len(articles)} articles)")
        time.sleep(0.3)

    cursor.close()
    conn.close()

    print(f"\nSeeding complete:")
    print(f"  Users inserted : {users_added}")
    print(f"  Posts inserted : {posts_added}")
    print(f"  Tag links added: {tags_linked}")


if __name__ == "__main__":
    seed()
