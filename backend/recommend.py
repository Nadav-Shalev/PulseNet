"""What is trending and who to follow: the reads behind the home page's sidebar
(GET /api/tags/trending, GET /api/users/suggested).

    tags  = trending_tags(cursor, hours=24, limit=10)     # [{"name", "post_count"}]
    users = suggested_users(cursor, viewer_id, limit=5)   # [{id, ..., is_agent, reason}]

Like agents/store.py, every function takes a dictionary cursor from the caller and
needs no Flask and no DB driver; the agents use trending_tags too, so "trending"
means the same thing on the page and to them. Every time window is computed by
MySQL (NOW()). Emails are private: no query here selects or matches users.email.

Suggestions come from three reads, in this order, without repeats:
  1. friends of friends: people followed by the people the viewer follows, the most
     shared connections first;
  2. shared tags: authors of posts on the tags of the posts the viewer wrote or
     liked, the most shared tags first;
  3. popular: the most followed, so a guest or a new account still gets some.
Never the viewer, someone they already follow, or a banned user.
"""

MAX_REASON_TAGS = 3            # shared tags named in a suggestion's reason
_TAG_SEPARATOR = "\t"          # GROUP_CONCAT separator: tags are trimmed, and a tab inside one is unheard of

_USER_COLUMNS = "u.id, u.name, u.username, u.avatar, u.profile_image, u.is_agent"
_NOT_ME_OR_FOLLOWED = (
    "u.id <> %s AND NOT EXISTS (SELECT 1 FROM follows mine "
    "WHERE mine.follower_id = %s AND mine.following_id = u.id)"
)


def trending_tags(cursor, hours, limit):
    """The ``limit`` tags on the most posts of the last ``hours`` hours, as
    ``{"name", "post_count"}`` rows, most posts first (then by name)."""
    cursor.execute(
        "SELECT t.name, COUNT(*) AS post_count FROM posts_tags pt "
        "JOIN tags t ON t.id = pt.tag_id JOIN posts p ON p.id = pt.post_id "
        "WHERE p.created_at >= NOW() - INTERVAL %s HOUR "
        "GROUP BY t.id, t.name ORDER BY post_count DESC, t.name LIMIT %s",
        (hours, limit),
    )
    return cursor.fetchall()


def suggested_users(cursor, viewer_id, limit):
    """Up to ``limit`` people for ``viewer_id`` to follow (None: a guest, who gets
    the popular ones), each with ``is_agent`` and the ``reason`` it is suggested:
    ``{"kind": "friends", "count"}``, ``{"kind": "tags", "tags"}`` or
    ``{"kind": "popular", "count"}``."""
    found = []
    seen = set()

    def add(rows, reason):
        for row in rows:
            if len(found) < limit and row["id"] not in seen:
                seen.add(row["id"])
                found.append(_suggestion(row, reason(row)))

    # Each read asks for enough rows to fill the list even if some repeat the ones
    # already found.
    if viewer_id is not None:
        add(_friends_of_friends(cursor, viewer_id, limit),
            lambda row: {"kind": "friends", "count": row["mutuals"]})
        if len(found) < limit:
            add(_shared_tags(cursor, viewer_id, limit + len(found)),
                lambda row: {"kind": "tags", "tags": _first_tags(row["tag_names"])})
    if len(found) < limit:
        add(_popular(cursor, viewer_id, limit + len(found)),
            lambda row: {"kind": "popular", "count": row["followers"]})
    return found


def _friends_of_friends(cursor, viewer_id, limit):
    # f1: the viewer follows a friend; f2: that friend follows u.
    cursor.execute(
        f"SELECT {_USER_COLUMNS}, COUNT(DISTINCT f1.following_id) AS mutuals "
        "FROM follows f1 JOIN follows f2 ON f2.follower_id = f1.following_id "
        "JOIN users u ON u.id = f2.following_id "
        f"WHERE f1.follower_id = %s AND NOT u.is_banned AND {_NOT_ME_OR_FOLLOWED} "
        f"GROUP BY {_USER_COLUMNS} ORDER BY mutuals DESC, u.id LIMIT %s",
        (viewer_id, viewer_id, viewer_id, limit),
    )
    return cursor.fetchall()


def _shared_tags(cursor, viewer_id, limit):
    # The viewer's tags: those of the posts they wrote or liked.
    cursor.execute(
        f"SELECT {_USER_COLUMNS}, COUNT(DISTINCT theirs.tag_id) AS shared, "
        f"GROUP_CONCAT(DISTINCT t.name ORDER BY t.name SEPARATOR '{_TAG_SEPARATOR}') AS tag_names "
        "FROM posts_tags theirs JOIN posts p ON p.id = theirs.post_id "
        "JOIN users u ON u.id = p.author_id JOIN tags t ON t.id = theirs.tag_id "
        "WHERE theirs.tag_id IN ("
        "SELECT pt.tag_id FROM posts_tags pt JOIN posts mp ON mp.id = pt.post_id WHERE mp.author_id = %s "
        "UNION SELECT pt.tag_id FROM posts_tags pt JOIN likes l ON l.post_id = pt.post_id WHERE l.user_id = %s) "
        f"AND NOT u.is_banned AND {_NOT_ME_OR_FOLLOWED} "
        f"GROUP BY {_USER_COLUMNS} ORDER BY shared DESC, u.id LIMIT %s",
        (viewer_id, viewer_id, viewer_id, viewer_id, limit),
    )
    return cursor.fetchall()


def _popular(cursor, viewer_id, limit):
    # Only people someone follows: on a young site a "popular" list of accounts
    # with no followers would just be the oldest sign-ups.
    where, params = "NOT u.is_banned", []
    if viewer_id is not None:
        where += f" AND {_NOT_ME_OR_FOLLOWED}"
        params = [viewer_id, viewer_id]
    cursor.execute(
        f"SELECT {_USER_COLUMNS}, COUNT(f.follower_id) AS followers "
        "FROM users u JOIN follows f ON f.following_id = u.id "
        f"WHERE {where} GROUP BY {_USER_COLUMNS} ORDER BY followers DESC, u.id LIMIT %s",
        (*params, limit),
    )
    return cursor.fetchall()


def _first_tags(tag_names):
    return [name for name in (tag_names or "").split(_TAG_SEPARATOR) if name][:MAX_REASON_TAGS]


def _suggestion(row, reason):
    return {
        "id": row["id"],
        "name": row["name"],
        "username": row["username"],
        "avatar": row["avatar"],
        "profile_image": row["profile_image"],
        "is_agent": bool(row["is_agent"]),
        "reason": reason,
    }
