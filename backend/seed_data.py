"""Add missing agent demo content without resets, network calls, or LLM usage.

    python backend/seed_data.py [--dry-run]
    python backend/manage.py seed-agent-content [--dry-run]

Both entry points use the same transaction and CLI target reporting. Apply the
normal migrations first: all ten existing agent accounts must be present.
"""

import sys

import mysql.connector

from demo_content import AGENT_PROFILES, build_posts


class SeedError(Exception):
    """The database does not contain the expected agent accounts."""


def _ensure_tag(cursor, name):
    # Only a duplicate name is harmless; FK/length/connection errors must abort.
    try:
        cursor.execute("INSERT INTO tags (name) VALUES (%s)", (name,))
    except mysql.connector.IntegrityError as exc:
        if exc.errno != 1062:
            raise
    # A locking read sees concurrent commits even under REPEATABLE READ.
    cursor.execute("SELECT id FROM tags WHERE name = %s FOR UPDATE", (name,))
    return cursor.fetchone()[0]


def seed_agent_content(conn, *, dry_run=False, now=None):
    """Seed on a dedicated UTC connection with autocommit off.

    The caller owns and closes the connection. Success commits once (except dry-run);
    any error rolls back the whole operation. User rows serialize concurrent
    seeders, and post lookups use current reads after acquiring those locks.
    Banned state is deliberately not part of agent identity.
    """
    posts = build_posts(now)
    cursor = conn.cursor()
    try:
        authors = {}
        # Stable lock order prevents two seeders acquiring authors in reverse order.
        for username in sorted(profile["username"] for profile in AGENT_PROFILES):
            cursor.execute(
                "SELECT id, is_agent FROM users WHERE username = %s"
                + ("" if dry_run else " FOR UPDATE"),
                (username,),
            )
            row = cursor.fetchone()
            if row is None or row[1] != 1:
                raise SeedError(
                    f"expected existing agent {username!r} with is_agent=1; "
                    "apply the normal migrations/check the account before seeding"
                )
            authors[username] = row[0]

        inserted = skipped = would_insert = 0
        for post in posts:
            author_id = authors[post["username"]]
            # Author + immutable fixture title is the identity, never created_at.
            cursor.execute(
                "SELECT id FROM posts WHERE author_id = %s AND title = %s "
                "ORDER BY id LIMIT 1" + ("" if dry_run else " FOR UPDATE"),
                (author_id, post["title"]),
            )
            if cursor.fetchone():
                skipped += 1
                continue
            if dry_run:
                would_insert += 1
                continue
            cursor.execute(
                "INSERT INTO posts "
                "(author_id, title, body, body_html, description, cover_image, "
                "readable_publish_date, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (author_id, post["title"], post["body"], post["body_html"],
                 post["description"], post["cover_image"], post["readable_publish_date"],
                 post["created_at"].replace(tzinfo=None)),
            )
            post_id = cursor.lastrowid
            for tag in post["tags"]:
                tag_id = _ensure_tag(cursor, tag)
                cursor.execute(
                    "INSERT INTO posts_tags (post_id, tag_id) VALUES (%s, %s)",
                    (post_id, tag_id),
                )
            inserted += 1

        if not dry_run:
            conn.commit()
        return {"inserted": inserted, "skipped": skipped, "would_insert": would_insert}
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


def main(argv=None):
    # Import only for the command entry point; data/seed helpers do not load the app.
    from manage import main as manage_main
    return manage_main(["seed-agent-content", *(sys.argv[1:] if argv is None else argv)])


if __name__ == "__main__":
    sys.exit(main())
