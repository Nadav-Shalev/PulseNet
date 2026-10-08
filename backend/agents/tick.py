"""One tick: one agent does at most one thing.

    result = run_tick(llm_service, Moderator(llm_service), connect)
    print(result.agent, result.skill, result.outcome)

1. Read (one connection): pick an agent (at random, or the one named), then run the
   skills' triggers in order (skills.SKILLS); the first that finds something wins.
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

The result names the outcome; one pulsenet.agents log line per tick carries ids and
sizes only, never text. No Flask, no app, no DB driver: the caller hands in
``connect``, a callable that returns a new DB-API connection.
"""

import logging
import random
from typing import NamedTuple, Optional

from llm import LLMBadReply, LLMError

from . import store
from .skills import SKILLS, Comment

log = logging.getLogger("pulsenet.agents")

FK_TARGET_MISSING = 1452   # MySQL ER_NO_REFERENCED_ROW_2

OUTCOMES = ("posted", "commented", "replied", "liked", "followed", "idle", "no_agent",
            "dry_run", "llm_failed", "bad_reply", "blocked", "target_gone")
_DONE = {"reply_to_human": "replied", "reply_to_agent": "replied",
         "comment_trending": "commented", "write_post": "posted"}


class TickResult(NamedTuple):
    agent: Optional[str]     # username
    skill: Optional[str]
    outcome: str             # one of OUTCOMES
    detail: dict             # ids, sizes, an error class or a moderation category


def run_tick(service, moderator, connect, *, rng=None, agent=None, dry_run=False):
    """Run one tick and return its TickResult. ``rng`` (a random.Random) picks the
    agent and the topic; ``agent`` (a username) forces the agent; ``dry_run`` makes
    the reads and builds the prompt, with no LLM call and no write."""
    rng = rng or random.Random()
    me, skill, found, skipped = _choose(service, connect, rng, agent)
    if me is None:
        return _done(None, None, "no_agent", {"asked": agent} if agent else {})
    if skill is None:
        return _done(me, None, "idle", {"skipped": skipped} if skipped else {})

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
        return _done(me, skill, "bad_reply", _ids(found))
    except LLMError as exc:
        return _done(me, skill, "llm_failed", {**_ids(found), "error": type(exc).__name__})

    if isinstance(content, Comment):
        verdict = moderator.check_comment(content.text, user_id=me.id)
    else:
        verdict = moderator.check_post(content.title, content.body, content.tags, user_id=me.id)
    if verdict.blocked:
        return _done(me, skill, "blocked", {**_ids(found), "category": verdict.category})

    return _act(connect, me, skill, lambda cursor: _write(cursor, me, found, content),
                _DONE[skill.name], _ids(found))


def _choose(service, connect, rng, username):
    """(agent, skill, candidate, skipped skill names) from one read-only connection,
    closed before returning."""
    conn = connect()
    try:
        cursor = conn.cursor(dictionary=True)
        if username:
            me = store.find_agent(cursor, username)
        else:
            agents = store.list_agents(cursor)
            me = rng.choice(agents) if agents else None
        if me is None:
            return None, None, None, []
        skipped = []
        for skill in SKILLS:
            if skill.needs_llm and service is None:
                skipped.append(skill.name)    # LLM off: not even its trigger runs
                continue
            found = skill.find(cursor, me, rng)
            if found is not None:
                return me, skill, found, skipped
        return me, None, None, skipped
    finally:
        conn.close()


def _act(connect, me, skill, write, outcome, detail):
    """Run ``write(cursor)`` in a new connection and commit; 1452 -> target_gone."""
    conn = connect()
    try:
        cursor = conn.cursor()
        try:
            new_ids = write(cursor) or {}
            conn.commit()
        except Exception as exc:
            if getattr(exc, "errno", None) != FK_TARGET_MISSING:
                raise
            conn.rollback()
            return _done(me, skill, "target_gone", detail)
        return _done(me, skill, outcome, {**detail, **new_ids})
    finally:
        conn.close()


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
