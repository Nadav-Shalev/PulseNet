"""Every SQL statement the agents run: the reads their triggers make, and the writes.

Each function takes a cursor from the caller (tick.py owns the connections), so
this module needs no DB driver and the tests hand it a FakeConn's cursor. Reads
use dictionary cursors. Every time window is computed by MySQL (NOW()), so the
connection's time zone never shifts it.

The writes are the same rows the API would write for a user: a post with its tags
(INSERT IGNORE on the exact-case tag name, like create_article), a comment, a like,
a follow. Each turn is also logged in agent_actions, which sets the agents' order
and the daily cap. The caller commits.
"""

from typing import NamedTuple, Optional

import recommend

REPLY_WINDOW_HOURS = 72      # a comment older than this is not answered any more
COMMENT_WINDOW_HOURS = 48    # posts an agent may comment on
COMMENT_CANDIDATES = 50      # of those, the most skills.best_post ranks
TRENDING_DAYS = 7            # trending tags count the posts of this window
TRENDING_LIMIT = 5
LIKE_WINDOW_DAYS = 7
LIKE_CHOICES = 10            # the agent likes one of the newest this many posts
FOLLOW_CHOICES = 10
RECENT_TITLES = 5            # the agent's own titles, so a new post does not repeat one


class Agent(NamedTuple):
    id: int
    username: str
    name: str
    personality: Optional[str]
    # The skill of its last turn of ALTERNATING_SKILLS (skills.skill_order).
    last_skill: Optional[str] = None


# The two skills an agent alternates between when nobody waits for its reply and
# no post is due (skills.skill_order).
ALTERNATING_SKILLS = ("comment_trending", "like_or_follow")

# The skill of the agent's newest turn of ALTERNATING_SKILLS, a correlated subquery
# on users u. Replies and posts in between do not count: when they did, they reset
# the alternation, and the comment came first again (production, 2026-10-14: no
# like_or_follow turn in 25, though every agent had posts to like).
_LAST_SKILL = ("(SELECT la.skill FROM agent_actions la WHERE la.agent_id = u.id "
               "AND la.skill IN (" + ", ".join(f"'{name}'" for name in ALTERNATING_SKILLS) + ") "
               "ORDER BY la.id DESC LIMIT 1) AS last_skill")
_AGENT_SELECT = (f"SELECT u.id, u.username, u.name, u.personality, {_LAST_SKILL} FROM users u "
                 "WHERE u.is_agent AND NOT u.is_banned")


def _agent(row):
    return Agent(row["id"], row["username"], row["name"], row["personality"], row.get("last_skill"))


def list_agents(cursor):
    """The agents that may act, in turn order (round robin): first those that never
    had a turn, by id, then the one whose last turn (agent_actions) is the oldest.
    Turn ids grow with time, so the oldest last turn is the smallest MAX(id). An
    agent an admin banned is left out."""
    cursor.execute(
        f"SELECT u.id, u.username, u.name, u.personality, {_LAST_SKILL} FROM users u "
        "LEFT JOIN agent_actions a ON a.agent_id = u.id "
        "WHERE u.is_agent AND NOT u.is_banned "
        "GROUP BY u.id, u.username, u.name, u.personality "
        "ORDER BY MAX(a.id) IS NOT NULL, MAX(a.id), u.id"
    )
    return [_agent(row) for row in cursor.fetchall()]


def find_agent(cursor, username):
    """The agent named ``username``, or None (no such agent, or banned)."""
    cursor.execute(_AGENT_SELECT + " AND u.username = %s", (username,))
    row = cursor.fetchone()
    return _agent(row) if row else None


def actions_today(cursor):
    """The agents' turns of the current UTC day: what AGENTS_MAX_ACTIONS_PER_DAY
    counts. UTC_DATE() is MySQL's, so the connection's time zone never shifts it."""
    cursor.execute("SELECT COUNT(*) AS turns FROM agent_actions WHERE action_day = UTC_DATE()")
    row = cursor.fetchone()
    return row["turns"] if row else 0


# A comment that waits for this agent's answer: on its post, or in a thread its own
# comment started, written by someone else in the last REPLY_WINDOW_HOURS, with no
# reply of this agent in that thread since. Replies are one level deep, so a thread
# is a top-level comment t and the comments whose parent is t; ids grow with time,
# so "since" is a larger id. The oldest such comment comes first.
_WAITING_COMMENT = """
SELECT c.id AS comment_id, c.body_html AS comment_html, cu.username AS comment_author,
       t.id AS thread_id, t.body_html AS thread_html,
       p.id AS post_id, p.title AS post_title, p.body AS post_body
FROM comments c
JOIN comments t ON t.id = COALESCE(c.parent_id, c.id)
JOIN posts p ON p.id = c.post_id
JOIN users cu ON cu.id = c.author_id
WHERE c.author_id <> %s
  AND cu.is_agent = %s AND NOT cu.is_banned
  AND c.created_at >= NOW() - INTERVAL {window} HOUR
  AND (p.author_id = %s OR t.author_id = %s)
  AND NOT EXISTS (SELECT 1 FROM comments mine
                  WHERE mine.parent_id = t.id AND mine.author_id = %s AND mine.id > c.id)
"""

# Agent conversations stop after this many agent comments in one thread: two agents
# would otherwise answer each other for ever.
_AGENT_TURNS = """
  AND (SELECT COUNT(*) FROM comments ac JOIN users au ON au.id = ac.author_id
       WHERE (ac.id = t.id OR ac.parent_id = t.id) AND au.is_agent) < %s
"""


def waiting_comment(cursor, agent_id, *, by_agent, max_agent_turns=None):
    """The oldest comment that waits for ``agent_id``'s reply, as a dict, or None.
    ``by_agent`` picks comments by agents (True) or by people (False); with
    ``max_agent_turns``, a thread that already has that many agent comments is
    left alone."""
    sql = _WAITING_COMMENT.format(window=REPLY_WINDOW_HOURS)
    params = [agent_id, bool(by_agent), agent_id, agent_id, agent_id]
    if max_agent_turns is not None:
        sql += _AGENT_TURNS
        params.append(max_agent_turns)
    cursor.execute(sql + "ORDER BY c.id LIMIT 1", tuple(params))
    return cursor.fetchone()


def trending_tags(cursor):
    """The names of the TRENDING_LIMIT tags on the most posts of the last
    TRENDING_DAYS days: the home page's "trending" (recommend.py), over a week."""
    return [row["name"] for row in recommend.trending_tags(cursor, TRENDING_DAYS * 24, TRENDING_LIMIT)]


def posts_to_comment(cursor, agent_id, topics, interests):
    """The recent posts the agent may comment on, as dicts (skills.best_post picks
    one): by someone else (not banned), from the last COMMENT_WINDOW_HOURS, tagged
    with one of ``topics``, and not commented on by the agent yet. Each carries what
    the ranking needs: interest_hit (1 when it has one of ``interests``), its age in
    minutes by MySQL's clock, its likes, and its comments by people and by agents.
    At most COMMENT_CANDIDATES: those on an interest first, then the newest (ids do
    not follow time for posts seeded with an age, demo_content)."""
    if not topics:
        return []
    marks = ", ".join(["%s"] * len(topics))
    score = f"MAX(t.name IN ({', '.join(['%s'] * len(interests))}))" if interests else "0"
    cursor.execute(
        f"SELECT p.id AS post_id, p.title AS post_title, p.body AS post_body, "
        f"u.username AS post_author, {score} AS interest_hit, "
        "TIMESTAMPDIFF(MINUTE, p.created_at, NOW()) AS age_minutes, "
        "(SELECT COUNT(*) FROM likes l WHERE l.post_id = p.id) AS likes, "
        "(SELECT COUNT(*) FROM comments hc JOIN users hu ON hu.id = hc.author_id "
        "WHERE hc.post_id = p.id AND NOT hu.is_agent) AS human_comments, "
        "(SELECT COUNT(*) FROM comments ac JOIN users au ON au.id = ac.author_id "
        "WHERE ac.post_id = p.id AND au.is_agent) AS agent_comments "
        "FROM posts p JOIN users u ON u.id = p.author_id "
        "JOIN posts_tags pt ON pt.post_id = p.id JOIN tags t ON t.id = pt.tag_id "
        f"WHERE p.created_at >= NOW() - INTERVAL {COMMENT_WINDOW_HOURS} HOUR "
        "AND p.author_id <> %s AND NOT u.is_banned "
        f"AND t.name IN ({marks}) "
        "AND NOT EXISTS (SELECT 1 FROM comments mine WHERE mine.post_id = p.id AND mine.author_id = %s) "
        "GROUP BY p.id, p.title, p.body, u.username, p.created_at "
        "ORDER BY interest_hit DESC, p.created_at DESC, p.id DESC LIMIT %s",
        (*interests, agent_id, *topics, agent_id, COMMENT_CANDIDATES),
    )
    return cursor.fetchall()


def last_post(cursor, agent_id):
    """(when the agent last posted or None, the DB's NOW()), both in the
    connection's time zone, so comparing them never depends on it."""
    cursor.execute("SELECT MAX(created_at) AS last_post, NOW() AS now FROM posts WHERE author_id = %s",
                   (agent_id,))
    row = cursor.fetchone() or {}
    return row.get("last_post"), row.get("now")


def recent_titles(cursor, agent_id):
    cursor.execute("SELECT title FROM posts WHERE author_id = %s ORDER BY id DESC LIMIT %s",
                   (agent_id, RECENT_TITLES))
    return [row["title"] for row in cursor.fetchall()]


def posts_to_like(cursor, agent_id):
    """Ids of the newest posts by others (not banned) the agent has not liked."""
    cursor.execute(
        "SELECT p.id FROM posts p JOIN users u ON u.id = p.author_id "
        "WHERE p.author_id <> %s AND NOT u.is_banned "
        f"AND p.created_at >= NOW() - INTERVAL {LIKE_WINDOW_DAYS} DAY "
        "AND NOT EXISTS (SELECT 1 FROM likes l WHERE l.post_id = p.id AND l.user_id = %s) "
        "ORDER BY p.id DESC LIMIT %s",
        (agent_id, agent_id, LIKE_CHOICES),
    )
    return [row["id"] for row in cursor.fetchall()]


def authors_to_follow(cursor, agent_id):
    """Ids of authors (not banned) of posts the agent liked, that it does not follow."""
    cursor.execute(
        "SELECT DISTINCT p.author_id FROM likes l "
        "JOIN posts p ON p.id = l.post_id JOIN users u ON u.id = p.author_id "
        "WHERE l.user_id = %s AND p.author_id <> %s AND NOT u.is_banned "
        "AND NOT EXISTS (SELECT 1 FROM follows f WHERE f.follower_id = %s AND f.following_id = p.author_id) "
        "ORDER BY p.author_id LIMIT %s",
        (agent_id, agent_id, agent_id, FOLLOW_CHOICES),
    )
    return [row["author_id"] for row in cursor.fetchall()]


# ─── Writes (the caller commits) ────────────────────────────────────────────────

def insert_post(cursor, agent_id, title, body, body_html, description, tags):
    """The new post's id. ``cursor`` is a plain (tuple) cursor."""
    cursor.execute(
        "INSERT INTO posts (author_id, title, body, body_html, description, cover_image) "
        "VALUES (%s, %s, %s, %s, %s, NULL)",
        (agent_id, title, body, body_html, description),
    )
    post_id = cursor.lastrowid
    for name in tags:
        cursor.execute("INSERT IGNORE INTO tags (name) VALUES (%s)", (name,))
        cursor.execute("SELECT id FROM tags WHERE name = %s", (name,))
        tag_id = cursor.fetchone()[0]
        cursor.execute("INSERT IGNORE INTO posts_tags (post_id, tag_id) VALUES (%s, %s)", (post_id, tag_id))
    return post_id


def insert_comment(cursor, post_id, agent_id, parent_id, body_html):
    """The new comment's id. A post or parent deleted since the read is MySQL error
    1452 (a foreign key): the caller reports it as target_gone."""
    cursor.execute(
        "INSERT INTO comments (post_id, author_id, parent_id, body_html) VALUES (%s, %s, %s, %s)",
        (post_id, agent_id, parent_id, body_html),
    )
    return cursor.lastrowid


def like(cursor, agent_id, post_id):
    cursor.execute("INSERT IGNORE INTO likes (user_id, post_id) VALUES (%s, %s)", (agent_id, post_id))


def follow(cursor, agent_id, user_id):
    cursor.execute("INSERT IGNORE INTO follows (follower_id, following_id) VALUES (%s, %s)",
                   (agent_id, user_id))


def record_action(cursor, agent_id, skill, outcome, *, post_id=None, comment_id=None, target_user_id=None):
    """One agent turn, counted against the UTC day it happened on, with what it acted
    on (migration 009): the post, the comment it wrote, the user it followed. A turn
    that wrote nothing passes none of them."""
    cursor.execute(
        "INSERT INTO agent_actions (agent_id, action_day, skill, outcome, post_id, comment_id, target_user_id) "
        "VALUES (%s, UTC_DATE(), %s, %s, %s, %s, %s)",
        (agent_id, skill, outcome, post_id, comment_id, target_user_id),
    )
