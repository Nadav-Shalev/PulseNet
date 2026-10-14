"""The admin's AI Activity stream (GET /api/admin/ai-activity): what the AI agents
did on PulseNet, and when people used the AI helpers.

    events, total = page_of_events(cursor, kind="all", sort="newest", page=1, per_page=25)

Two sources, merged into one stream (UNION ALL), a page at a time:
  - agent_actions: the agents' turns that did something (posted, commented,
    replied, liked, followed), with what they acted on (migration 009). Failed
    turns are left out. Turns logged before 009 have no target, and a deleted
    target is NULL too (SET NULL): the event stays, without a link.
  - llm_usage: the calls of the AI-assist buttons (ai_assist.PURPOSES). A row only
    proves that the helper was called, never that its suggestion was applied or
    published; its status says whether the call worked ("ok"), failed, or was
    refused by a limit before reaching the model (over_limit). Moderation and the
    agents' own calls are not here: the agents' turns already are.

No query reads a prompt, a reply, an email or a provider: llm_usage keeps no text,
and the columns below are all the page shows. Like recommend.py, every function
takes a dictionary cursor from the caller, with no Flask and no DB driver.
"""

import ai_assist

AGENT_TYPES = ("posted", "commented", "replied", "liked", "followed")
AI_ASSIST = "ai_assist"                         # the filter for the three helpers
TYPES = ("all",) + AGENT_TYPES + (AI_ASSIST,)   # the ``kind`` filter
SORTS = ("newest", "oldest", "type")
# sort=type: grouped in this order, the newest first in each group.
TYPE_ORDER = AGENT_TYPES + tuple(ai_assist.PURPOSES)
DEFAULT_PER_PAGE, MAX_PER_PAGE = 25, 100

# Both branches give the same columns, so one ORDER BY and LIMIT page the union.
# The agent is never NULL (agent_actions CASCADEs with it); the user of an
# llm_usage row is, once deleted (SET NULL), hence the LEFT JOIN.
_AGENT_EVENTS = """
SELECT 'agent' AS source, a.id AS source_id, a.created_at, a.outcome AS kind, NULL AS status,
       u.id AS actor_id, u.username AS actor_username, u.name AS actor_name,
       u.is_agent AS actor_is_agent,
       p.id AS post_id, p.title AS post_title, a.comment_id,
       tu.id AS target_id, tu.username AS target_username, tu.name AS target_name,
       tu.is_agent AS target_is_agent
FROM agent_actions a
JOIN users u ON u.id = a.agent_id
LEFT JOIN posts p ON p.id = a.post_id
LEFT JOIN users tu ON tu.id = a.target_user_id
WHERE a.outcome IN ({marks})
"""
_AI_EVENTS = """
SELECT 'ai_assist' AS source, l.id AS source_id, l.created_at, l.purpose AS kind, l.status,
       u.id AS actor_id, u.username AS actor_username, u.name AS actor_name,
       u.is_agent AS actor_is_agent,
       NULL AS post_id, NULL AS post_title, NULL AS comment_id,
       NULL AS target_id, NULL AS target_username, NULL AS target_name, NULL AS target_is_agent
FROM llm_usage l
LEFT JOIN users u ON u.id = l.user_id
WHERE l.purpose IN ({marks})
"""
# Ties on created_at (one second) are broken by source and id, so a row never moves
# between two pages that are read one after the other.
_ORDER = {
    "newest": "ev.created_at DESC, ev.source, ev.source_id DESC",
    "oldest": "ev.created_at, ev.source, ev.source_id",
    "type":   "FIELD(ev.kind, {marks}), ev.created_at DESC, ev.source, ev.source_id DESC",
}


def _marks(values):
    return ", ".join(["%s"] * len(values))


def _branches(kind):
    """(agent outcomes, llm_usage purposes) that ``kind`` (one of TYPES) selects."""
    outcomes = AGENT_TYPES if kind == "all" else (kind,) if kind in AGENT_TYPES else ()
    purposes = tuple(ai_assist.PURPOSES) if kind in ("all", AI_ASSIST) else ()
    return outcomes, purposes


def page_of_events(cursor, kind="all", sort="newest", page=1, per_page=DEFAULT_PER_PAGE):
    """(the events of page ``page``, the number of events of ``kind`` in all), each
    event shaped by event(). ``kind`` is one of TYPES and ``sort`` one of SORTS
    (the caller checks both)."""
    outcomes, purposes = _branches(kind)
    branches, params, total = [], [], 0
    for sql, table, column, values in ((_AGENT_EVENTS, "agent_actions", "outcome", outcomes),
                                       (_AI_EVENTS, "llm_usage", "purpose", purposes)):
        if not values:
            continue
        cursor.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {column} IN ({_marks(values)})", values)
        total += cursor.fetchone()["n"]
        branches.append(sql.format(marks=_marks(values)))
        params += values
    if not total:
        return [], 0

    order = _ORDER[sort]
    if sort == "type":
        order = order.format(marks=_marks(TYPE_ORDER))
        params += TYPE_ORDER
    cursor.execute(
        f"SELECT * FROM ({' UNION ALL '.join(branches)}) AS ev ORDER BY {order} LIMIT %s OFFSET %s",
        (*params, per_page, (page - 1) * per_page),
    )
    return [event(row) for row in cursor.fetchall()], total


def _user(row, prefix):
    """The user ``prefix`` (actor or target) of a row, or None when there is none:
    deleted (SET NULL), or not part of this kind of event."""
    if row.get(f"{prefix}_id") is None:
        return None
    return {
        "id":       row[f"{prefix}_id"],
        "username": row[f"{prefix}_username"],
        "name":     row.get(f"{prefix}_name"),
        "is_agent": bool(row.get(f"{prefix}_is_agent")),
    }


def event(row):
    """One row of the stream as the admin page shows it. ``actor`` and
    ``target_user`` may be None (a deleted user), and so may ``post`` (a turn with
    no post, or whose post is gone or was never recorded); ``created_at`` stays a
    datetime for the caller to format. ``status`` is llm_usage's for an AI helper
    and None for an agent's turn."""
    return {
        "id":          f"{row['source']}-{row['source_id']}",
        "source":      row["source"],
        "type":        row["kind"],
        "created_at":  row["created_at"],
        "actor":       _user(row, "actor"),
        "post":        ({"id": row["post_id"], "title": row["post_title"]}
                        if row.get("post_id") is not None else None),
        "comment_id":  row.get("comment_id"),
        "target_user": _user(row, "target"),
        "status":      row.get("status"),
    }
