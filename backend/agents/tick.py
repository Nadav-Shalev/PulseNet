"""One tick: one agent does at most one thing.

    result = run_tick(llm_service, Moderator(llm_service), connect, max_actions=20)
    print(result.agent, result.skill, result.outcome)

1. Read (one connection): with ``max_actions``, a day that already has that many
   turns (agent_actions) stops here as ``capped``. Then the agents are tried in
   turn order (store.list_agents: never acted first, then the oldest last turn), or
   only the one named; for each, the skills' triggers run in the order
   skills.skill_order() gives for its last turn (replies, a due post, then a comment
   or a like/follow, alternating), and the first that finds something wins. An agent with nothing to do does not
   hold up the next one, and keeps its place at the front of the queue.
   When the LLM is off (``service`` is None), every skill that needs it is skipped
   before its trigger runs, so only like_or_follow is tried. The connection is then
   closed, before any LLM call, so a slow model never holds one open.
2. Think (skills with an LLM): ONE call, ``purpose`` = the skill's (agent_*), for the
   agent's user id. Its JSON reply is checked strictly, then moderated like anything
   a person publishes (moderation.Moderator, which makes its own call and falls back
   to the word list). Any LLMError, a bad reply or a blocked text: nothing is written,
   with no fallback and no retry.
3. Act (a new connection): the INSERTs and one commit. A post or comment deleted
   in the meantime (MySQL 1452, a foreign key) is the outcome target_gone.

Every turn (an outcome in RECORDED) is one agent_actions row: in the same commit as
the write, or on a short connection of its own when nothing was written. So a turn
that failed still sends its agent to the back of the queue and counts against the
cap: its LLM calls were already spent. idle, dry_run, capped and no_agent are not
turns, and leave no row.

The result names the outcome; one pulsenet.agents log line per tick carries ids and
sizes only, never text. No Flask, no app, no DB driver: the caller hands in
``connect``, a callable that returns a new DB-API connection.
"""

import logging
import random
from typing import NamedTuple, Optional

from llm import LLMBadReply, LLMError

from . import store
from .skills import SKILLS, Comment, skill_order

log = logging.getLogger("pulsenet.agents")

FK_TARGET_MISSING = 1452   # MySQL ER_NO_REFERENCED_ROW_2

# The outcomes of a turn: agent_actions.outcome (a unit test holds the two equal).
RECORDED = ("posted", "commented", "replied", "liked", "followed",
            "llm_failed", "bad_reply", "blocked", "target_gone")
OUTCOMES = RECORDED + ("idle", "no_agent", "dry_run", "capped")
_DONE = {"reply_to_human": "replied", "reply_to_agent": "replied",
         "comment_trending": "commented", "write_post": "posted"}


class TickResult(NamedTuple):
    agent: Optional[str]     # username
    skill: Optional[str]
    outcome: str             # one of OUTCOMES
    detail: dict             # ids, sizes, an error class or a moderation category


class _Choice(NamedTuple):
    outcome: Optional[str] = None    # set when the tick stops at the read
    detail: dict = {}
    agent: Optional[store.Agent] = None
    skill: Optional[object] = None
    found: object = None


def run_tick(service, moderator, connect, *, rng=None, agent=None, dry_run=False, max_actions=None):
    """Run one tick and return its TickResult. ``rng`` (a random.Random) picks the
    topic and what to like or follow; ``agent`` (a username) forces the agent;
    ``dry_run`` makes the reads and builds the prompt, with no LLM call and no write;
    ``max_actions`` is the day's cap on turns (None: no cap)."""
    rng = rng or random.Random()
    choice = _choose(service, connect, rng, agent, max_actions)
    me, skill, found = choice.agent, choice.skill, choice.found
    if choice.outcome:
        return _done(me, None, choice.outcome, choice.detail)

    if not skill.needs_llm:
        kind, target_id = found
        if dry_run:
            return _done(me, skill, "dry_run", {kind: target_id})
        return _act(connect, me, skill, lambda cursor: _like_or_follow(cursor, me, kind, target_id),
                    "followed" if kind == "follow" else "liked", {kind: target_id})

    prompt, system = skill.build(me, found)
    sizes = {"prompt_chars": len(prompt) + len(system)}
    if dry_run:
        return _done(me, skill, "dry_run", {**_ids(found), **sizes})
    try:
        reply = service.complete(prompt, system=system, purpose=skill.purpose, user_id=me.id)
        content = skill.parse(reply)
    except LLMBadReply:
        return _failed(connect, me, skill, "bad_reply", _ids(found))
    except LLMError as exc:
        return _failed(connect, me, skill, "llm_failed", {**_ids(found), "error": type(exc).__name__})

    if isinstance(content, Comment):
        verdict = moderator.check_comment(content.text, user_id=me.id)
    else:
        verdict = moderator.check_post(content.title, content.body, content.tags, user_id=me.id)
    if verdict.blocked:
        return _failed(connect, me, skill, "blocked", {**_ids(found), "category": verdict.category})

    return _act(connect, me, skill, lambda cursor: _write(cursor, me, found, content),
                _DONE[skill.name], _ids(found))


def _choose(service, connect, rng, username, max_actions):
    """The agent, skill and candidate of this tick, or the outcome it stops with,
    from one read-only connection, closed before returning."""
    conn = connect()
    try:
        cursor = conn.cursor(dictionary=True)
        if max_actions is not None:
            turns = store.actions_today(cursor)
            if turns >= max_actions:
                return _Choice("capped", {"today": turns, "max": max_actions})
        if username:
            me = store.find_agent(cursor, username)
            agents = [me] if me else []
        else:
            agents = store.list_agents(cursor)
        if not agents:
            return _Choice("no_agent", {"asked": username} if username else {})
        # LLM off: those skills' triggers do not even run.
        skipped = [skill.name for skill in SKILLS if skill.needs_llm and service is None]
        for me in agents:
            for skill in skill_order(me.last_skill):
                if skill.name in skipped:
                    continue
                found = skill.find(cursor, me, rng)
                if found is not None:
                    return _Choice(agent=me, skill=skill, found=found)
        detail = {"tried": len(agents), **({"skipped": skipped} if skipped else {})}
        return _Choice("idle", detail, agent=agents[0] if username else None)
    finally:
        conn.close()


def _act(connect, me, skill, write, outcome, detail):
    """Run ``write(cursor)`` and log the turn in a new connection, in one commit;
    1452 -> target_gone (rolled back, then logged)."""
    conn = connect()
    try:
        cursor = conn.cursor()
        try:
            new_ids = write(cursor) or {}
            store.record_action(cursor, me.id, skill.name, outcome)
            conn.commit()
        except Exception as exc:
            if getattr(exc, "errno", None) != FK_TARGET_MISSING:
                raise
            conn.rollback()
            store.record_action(cursor, me.id, skill.name, "target_gone")
            conn.commit()
            return _done(me, skill, "target_gone", detail)
        return _done(me, skill, outcome, {**detail, **new_ids})
    finally:
        conn.close()


def _failed(connect, me, skill, outcome, detail):
    """A turn that wrote nothing: log it on a short connection of its own."""
    conn = connect()
    try:
        store.record_action(conn.cursor(), me.id, skill.name, outcome)
        conn.commit()
    finally:
        conn.close()
    return _done(me, skill, outcome, detail)


def _like_or_follow(cursor, me, kind, target_id):
    if kind == "follow":
        store.follow(cursor, me.id, target_id)
    else:
        store.like(cursor, me.id, target_id)


def _write(cursor, me, found, content):
    if isinstance(content, Comment):
        # A reply joins the thread (replies are one level deep); a comment on a post
        # starts one.
        parent_id = found.get("thread_id")
        comment_id = store.insert_comment(cursor, found["post_id"], me.id, parent_id, content.body_html)
        return {"comment_id": comment_id}
    post_id = store.insert_post(cursor, me.id, content.title, content.body, content.body_html,
                                content.description, content.tags)
    return {"post_id": post_id}


def _ids(found):
    return {key: found[key] for key in ("post_id", "comment_id", "thread_id") if key in found}


def _done(me, skill, outcome, detail):
    result = TickResult(me.username if me else None, skill.name if skill else None, outcome, detail)
    log.log(logging.WARNING if outcome in ("llm_failed", "bad_reply", "target_gone") else logging.INFO,
            "agent tick: agent=%s skill=%s outcome=%s detail=%s",
            result.agent, result.skill, outcome, detail)
    return result
