"""run_tick end to end: the reads, the one LLM call, moderation and the write.

The DB is two FakeConns (the read connection, then the write one), the LLM a
ScriptedProvider behind a real LLMService (so every call lands in a
MemoryUsageStore), and moderation the real Moderator. No MySQL, no network.
"""

import json
import logging
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agents import run_tick, skills, store  # noqa: E402
from agents.store import Agent  # noqa: E402
from llm import LLMRateLimited, LLMService, LLMTimeout, MemoryUsageStore  # noqa: E402
from llm_support import ScriptedProvider  # noqa: E402
from moderation import Moderator  # noqa: E402
from support import FakeConn  # noqa: E402

AGENT_ROW = {"id": 131, "username": "leo_ai", "name": "Leo Marchetti", "personality": "You are Leo."}
NOW = datetime(2026, 10, 9, 12, 0, 0)
CLEAN = '{"toxic": false, "category": "none"}'
TOXIC = '{"toxic": true, "category": "harassment"}'
COMMENT = '{"comment": "Thanks, Ada! Hooks keep state next to the code that uses it."}'
POST = json.dumps({"title": "Five CSS tricks", "body_markdown": "Use **grid** for layout. " * 20,
                   "tags": ["css", "webdev"]})


def _waiting(**over):
    row = {"comment_id": 41, "comment_html": "<p>Why hooks?</p>", "comment_author": "ada",
           "thread_id": 40, "thread_html": "<p>Great intro.</p>",
           "post_id": 7, "post_title": "React hooks", "post_body": "Hooks let you..."}
    row.update(over)
    return row


class FirstChoice:
    def choice(self, items):
        return items[0]


class FkError(Exception):
    def __init__(self, errno):
        super().__init__(f"{errno}: Cannot add or update a child row")
        self.errno = errno


class TickTestCase(unittest.TestCase):
    def connections(self, read, write=None):
        """``connect`` that hands out ``read``, then ``write``; ``self.opened`` counts."""
        self.read, self.write = read, write if write is not None else FakeConn(lastrowid=90)
        queue = [self.read, self.write]
        self.opened = 0

        def connect():
            self.opened += 1
            return queue.pop(0)
        return connect

    def llm(self, *replies, daily_limit=100):
        self.service = LLMService(ScriptedProvider(*replies), MemoryUsageStore(), daily_limit=daily_limit)
        return self.service

    def tick(self, connect, service="default", **kwargs):
        service = self.service if service == "default" else service
        return run_tick(service, Moderator(service), connect, rng=FirstChoice(), **kwargs)

    def purposes(self):
        return [(r.purpose, r.user_id, r.status) for r in self.service.store.records]


class ReplyTests(TickTestCase):
    def test_a_reply_to_a_person_joins_their_thread(self):
        connect = self.connections(FakeConn(fetchall=[[AGENT_ROW]], fetchone=[_waiting()]))
        self.llm(COMMENT, CLEAN)
        closed_at_call = []
        original = self.service.provider.complete
        self.service.provider.complete = lambda p, s=None: (closed_at_call.append(self.read.closed),
                                                            original(p, s))[1]

        result = self.tick(connect)

        self.assertEqual((result.agent, result.skill, result.outcome), ("leo_ai", "reply_to_human", "replied"))
        self.assertEqual(result.detail, {"post_id": 7, "comment_id": 90, "thread_id": 40})
        self.assertEqual(closed_at_call, [True, True])     # the read connection closed before the LLM
        self.assertEqual(self.write.params_for("insert into comments"),
                         (7, 131, 40, "Thanks, Ada! Hooks keep state next to the code that uses it."))
        self.assertEqual(self.write.params_for("insert into agent_actions"), (131, "reply_to_human", "replied"))
        self.assertEqual((self.write.commits, self.write.closed), (1, True))
        self.assertEqual(self.purposes(), [("agent_reply_human", 131, "ok"), ("moderation", 131, "ok")])
        prompt, system = self.service.provider.calls[0]
        self.assertIn("<comment>\nWhy hooks?\n</comment>", prompt)
        self.assertTrue(system.startswith("You are Leo."))

    def test_a_reply_to_another_agent_comes_when_no_person_waits(self):
        connect = self.connections(FakeConn(fetchall=[[AGENT_ROW]], fetchone=[None, _waiting()]))
        self.llm(COMMENT, CLEAN)

        result = self.tick(connect)

        self.assertEqual((result.skill, result.outcome), ("reply_to_agent", "replied"))
        # First the people's comments, then the agents', with the turn cap.
        self.assertEqual([params for _, params in self.read.find("from comments c")],
                         [(131, False, 131, 131, 131), (131, True, 131, 131, 131, 3)])
        self.assertEqual(self.purposes()[0][0], "agent_reply_agent")


class CommentAndPostTests(TickTestCase):
    def test_a_comment_on_a_trending_post_starts_a_thread(self):
        found = {"post_id": 9, "post_title": "CSS grid", "post_body": "Grid is...", "post_author": "ada",
                 "interest_hit": 1}
        # Not due to post (posted just now), so it goes on to the trending search.
        connect = self.connections(FakeConn(fetchall=[[AGENT_ROW], [{"name": "css"}]],
                                            fetchone=[None, None, {"last_post": NOW, "now": NOW}, found]))
        self.llm(COMMENT, CLEAN)

        result = self.tick(connect)

        self.assertEqual((result.skill, result.outcome), ("comment_trending", "commented"))
        self.assertEqual(result.detail, {"post_id": 9, "comment_id": 90})
        self.assertIsNone(self.write.params_for("insert into comments")[2])     # top-level
        self.assertEqual(self.purposes()[0][0], "agent_comment")

    def test_a_first_post_with_its_tags(self):
        read = FakeConn(fetchall=[[AGENT_ROW], [], []],
                        fetchone=[None, None, {"last_post": None, "now": NOW}])
        write = FakeConn(fetchone=[(5,), (6,)], lastrowid=77)
        connect = self.connections(read, write)
        self.llm(POST, CLEAN)

        result = self.tick(connect)

        self.assertEqual((result.skill, result.outcome, result.detail), ("write_post", "posted", {"post_id": 77}))
        sql, params = write.find("insert into posts")[0]
        self.assertEqual(params[:2], (131, "Five CSS tricks"))
        self.assertIn("<strong>grid</strong>", params[3])
        self.assertEqual([p for _, p in write.find("insert ignore into posts_tags")], [(77, 5), (77, 6)])
        self.assertEqual(self.purposes(), [("agent_post", 131, "ok"), ("moderation", 131, "ok")])
        # The post is moderated as a post: title, tags and its visible text.
        moderation_prompt = self.service.provider.calls[1][0]
        self.assertIn("<post_title>\nFive CSS tricks\n</post_title>", moderation_prompt)
        self.assertIn("<post_tags>\ncss, webdev\n</post_tags>", moderation_prompt)
        self.assertIn("Use grid for layout.", moderation_prompt)
        topic_prompt = self.service.provider.calls[0][0]
        self.assertIn("<topic>\nreact\n</topic>", topic_prompt)


class LikeFollowTests(TickTestCase):
    def test_follow_needs_no_llm(self):
        connect = self.connections(FakeConn(fetchall=[[AGENT_ROW], [], [{"author_id": 3}]],
                                            fetchone=[None, None, {"last_post": NOW, "now": NOW}, None]))
        self.llm()

        result = self.tick(connect)

        self.assertEqual((result.skill, result.outcome, result.detail), ("like_or_follow", "followed", {"follow": 3}))
        self.assertEqual(self.write.params_for("insert ignore into follows"), (131, 3))
        self.assertEqual(self.write.params_for("insert into agent_actions"), (131, "like_or_follow", "followed"))
        self.assertEqual((self.write.commits, self.write.closed), (1, True))
        self.assertEqual(self.service.store.records, [])

    def test_the_llm_off_skips_every_llm_skill_and_still_likes(self):
        # Something waits for every LLM skill, but with the LLM off their triggers do
        # not even run: the next read after the agent list is like_or_follow's.
        read = FakeConn(fetchall=[[AGENT_ROW], [], [{"id": 12}]],
                        fetchone=[_waiting(), _waiting(), {"post_id": 9}, {"last_post": None, "now": NOW}])
        connect = self.connections(read)

        result = self.tick(connect, service=None)

        self.assertEqual((result.skill, result.outcome, result.detail), ("like_or_follow", "liked", {"like": 12}))
        self.assertEqual(self.write.params_for("insert ignore into likes"), (131, 12))
        for needle in ("from comments c", "from posts_tags pt", "max(created_at)"):
            with self.subTest(needle=needle):
                self.assertFalse(read.ran(needle))

    def test_the_llm_off_with_nothing_to_like_is_idle_and_says_what_it_skipped(self):
        connect = self.connections(FakeConn(fetchall=[[AGENT_ROW]]))

        result = self.tick(connect, service=None)

        self.assertEqual(result.outcome, "idle")
        self.assertEqual(result.detail["skipped"],
                         ["reply_to_human", "reply_to_agent", "write_post", "comment_trending"])
        self.assertEqual(self.opened, 1)


class NothingWrittenTests(TickTestCase):
    """The text is not written, but the turn is: on a connection of its own, so the
    agent goes to the back of the queue and the turn counts against the cap."""

    def reply_tick(self, *replies, daily_limit=100):
        connect = self.connections(FakeConn(fetchall=[[AGENT_ROW]], fetchone=[_waiting()]))
        self.llm(*replies, daily_limit=daily_limit)
        return self.tick(connect)

    def assertOnlyTheTurn(self, outcome):
        self.assertEqual(self.opened, 2)
        self.assertEqual([params for _, params in self.write.executed],
                         [(131, "reply_to_human", outcome)])
        self.assertTrue(self.write.ran("insert into agent_actions"))
        self.assertEqual((self.write.commits, self.write.closed), (1, True))

    def test_blocked_by_the_llm(self):
        result = self.reply_tick(COMMENT, TOXIC)

        self.assertEqual((result.outcome, result.detail["category"]), ("blocked", "harassment"))
        self.assertOnlyTheTurn("blocked")

    def test_blocked_by_the_word_list_when_the_verdict_is_unreadable(self):
        result = self.reply_tick('{"comment": "you idiot, read the docs"}', "I think it is fine")

        self.assertEqual((result.outcome, result.detail["category"]), ("blocked", "harassment"))
        self.assertOnlyTheTurn("blocked")

    def test_a_bad_reply_is_not_moderated_or_written(self):
        result = self.reply_tick("Sure, here is my reply!")

        self.assertEqual(result.outcome, "bad_reply")
        self.assertEqual(self.purposes(), [("agent_reply_human", 131, "ok")])
        self.assertOnlyTheTurn("bad_reply")

    def test_llm_failures(self):
        for error, name in ((LLMRateLimited("429", retry_after=30), "LLMRateLimited"),
                            (LLMTimeout("slow"), "LLMTimeout")):
            with self.subTest(name):
                result = self.reply_tick(error)
                self.assertEqual((result.outcome, result.detail["error"]), ("llm_failed", name))
                self.assertOnlyTheTurn("llm_failed")
                self.assertEqual(len(self.service.provider.calls), 1)       # no retry

    def test_the_daily_limit(self):
        result = self.reply_tick(daily_limit=0)

        self.assertEqual((result.outcome, result.detail["error"]), ("llm_failed", "LLMLimitReached"))
        self.assertEqual(self.purposes(), [("agent_reply_human", 131, "over_limit")])
        self.assertOnlyTheTurn("llm_failed")

    def test_a_target_deleted_meanwhile(self):
        write = FakeConn(raise_on={"insert into comments": FkError(1452)})
        connect = self.connections(FakeConn(fetchall=[[AGENT_ROW]], fetchone=[_waiting()]), write)
        self.llm(COMMENT, CLEAN)

        result = self.tick(connect)

        self.assertEqual(result.outcome, "target_gone")
        # Rolled back, then the turn alone, committed.
        self.assertEqual((write.commits, write.rollbacks, write.closed), (1, 1, True))
        self.assertEqual(write.params_for("insert into agent_actions"), (131, "reply_to_human", "target_gone"))
        sqls = [" ".join(sql.split()).lower() for sql, _ in write.executed]
        self.assertTrue(sqls[0].startswith("insert into comments"))
        self.assertTrue(sqls[1].startswith("insert into agent_actions"))

    def test_any_other_db_error_is_raised_and_the_connection_closed(self):
        write = FakeConn(raise_on={"insert into comments": FkError(1205)})
        connect = self.connections(FakeConn(fetchall=[[AGENT_ROW]], fetchone=[_waiting()]), write)
        self.llm(COMMENT, CLEAN)

        with self.assertRaises(FkError):
            self.tick(connect)
        self.assertTrue(write.closed)


class AgentChoiceTests(TickTestCase):
    def test_no_agents(self):
        connect = self.connections(FakeConn())
        self.llm()

        result = self.tick(connect)

        self.assertEqual((result.agent, result.outcome), (None, "no_agent"))
        self.assertTrue(self.read.closed)

    def test_a_named_agent_that_does_not_exist_or_is_banned(self):
        connect = self.connections(FakeConn(fetchone=[None]))
        self.llm()

        result = self.tick(connect, agent="rex_ai")

        self.assertEqual((result.outcome, result.detail), ("no_agent", {"asked": "rex_ai"}))
        self.assertIn("NOT u.is_banned", self.read.find("username = %s")[0][0])
        self.assertFalse(self.read.ran("left join agent_actions"))   # the list is never read

    def test_a_named_agent_acts(self):
        connect = self.connections(FakeConn(fetchone=[AGENT_ROW, _waiting()]))
        self.llm(COMMENT, CLEAN)

        result = self.tick(connect, agent="leo_ai")

        self.assertEqual((result.agent, result.outcome), ("leo_ai", "replied"))

    def test_idle_when_nothing_is_found(self):
        connect = self.connections(FakeConn(fetchall=[[AGENT_ROW]],
                                            fetchone=[None, None, {"last_post": NOW, "now": NOW}, None]))
        self.llm()

        result = self.tick(connect)

        self.assertEqual((result.agent, result.outcome, result.detail), (None, "idle", {"tried": 1}))
        self.assertEqual(self.opened, 1)          # an idle tick is not a turn: no row

    def test_a_named_agent_with_nothing_to_do_is_named(self):
        connect = self.connections(FakeConn(fetchone=[AGENT_ROW]))

        result = self.tick(connect, service=None, agent="leo_ai")

        self.assertEqual((result.agent, result.outcome), ("leo_ai", "idle"))
        self.assertEqual(result.detail["tried"], 1)


DANA_ROW = {"id": 133, "username": "dana_ai", "name": "Dana Levin", "personality": "You are Dana."}


class TurnOrderTests(TickTestCase):
    """Round robin: store.list_agents gives the order (its SQL is in
    test_agents_skills); the tick acts with the first agent that finds something."""

    def test_the_first_agent_in_turn_acts(self):
        # Both could like a post: only the first one in the order does.
        read = FakeConn(fetchall=[[DANA_ROW, AGENT_ROW], [], [{"id": 12}], [], [{"id": 14}]])
        connect = self.connections(read)

        result = self.tick(connect, service=None)

        self.assertEqual((result.agent, result.outcome, result.detail), ("dana_ai", "liked", {"like": 12}))
        self.assertEqual(self.write.params_for("insert into agent_actions"), (133, "like_or_follow", "liked"))
        self.assertTrue(read.ran("order by max(a.id) is not null, max(a.id), u.id"))

    def test_an_agent_with_nothing_to_do_lets_the_next_one_act(self):
        # Dana has no one to follow and nothing to like; Leo likes post 14.
        read = FakeConn(fetchall=[[DANA_ROW, AGENT_ROW], [], [], [], [{"id": 14}]])
        connect = self.connections(read)

        result = self.tick(connect, service=None)

        self.assertEqual((result.agent, result.outcome), ("leo_ai", "liked"))
        # Dana's triggers ran first, with her id; nothing is logged for her.
        like_reads = [params for _, params in read.find("from posts p join users u")]
        self.assertEqual([params[0] for params in like_reads], [133, 131])
        self.assertEqual([params for _, params in self.write.find("insert into agent_actions")],
                         [(131, "like_or_follow", "liked")])

    def test_idle_only_when_no_agent_finds_anything(self):
        read = FakeConn(fetchall=[[DANA_ROW, AGENT_ROW]])
        connect = self.connections(read)

        result = self.tick(connect, service=None)

        self.assertEqual((result.agent, result.outcome), (None, "idle"))
        self.assertEqual(result.detail["tried"], 2)
        self.assertEqual(self.opened, 1)

    def test_the_turn_is_logged_in_the_same_commit_as_the_write(self):
        class CommitLog(FakeConn):
            def commit(self):
                self.at_commit = [" ".join(sql.split()).lower()[:30] for sql, _ in self.executed]
                super().commit()

        write = CommitLog()
        connect = self.connections(FakeConn(fetchall=[[AGENT_ROW], [], [{"id": 12}]]), write)

        self.tick(connect, service=None)

        self.assertEqual(write.commits, 1)
        self.assertEqual(write.at_commit, ["insert ignore into likes (user", "insert into agent_actions (age"])


class DailyCapTests(TickTestCase):
    def test_a_day_with_max_turns_is_capped_before_any_agent_is_read(self):
        read = FakeConn(fetchone=[{"turns": 20}], fetchall=[[AGENT_ROW]])
        connect = self.connections(read)
        self.llm(COMMENT, CLEAN)

        result = self.tick(connect, max_actions=20)

        self.assertEqual((result.agent, result.skill, result.outcome), (None, None, "capped"))
        self.assertEqual(result.detail, {"today": 20, "max": 20})
        self.assertTrue(read.ran("from agent_actions where action_day = utc_date()"))
        self.assertFalse(read.ran("left join agent_actions"))
        self.assertEqual((self.service.provider.calls, self.opened), ([], 1))

    def test_one_turn_left_runs(self):
        connect = self.connections(FakeConn(fetchone=[{"turns": 19}], fetchall=[[AGENT_ROW], [], [{"id": 12}]]))

        result = self.tick(connect, service=None, max_actions=20)

        self.assertEqual(result.outcome, "liked")

    def test_a_named_agent_is_capped_too(self):
        read = FakeConn(fetchone=[{"turns": 3}, AGENT_ROW])
        connect = self.connections(read)

        result = self.tick(connect, service=None, agent="leo_ai", max_actions=3)

        self.assertEqual(result.outcome, "capped")
        self.assertFalse(read.ran("username = %s"))

    def test_without_a_cap_the_count_is_not_read(self):
        read = FakeConn(fetchall=[[AGENT_ROW], [], [{"id": 12}]])

        self.tick(self.connections(read), service=None)

        self.assertFalse(read.ran("count(*)"))


class DryRunTests(TickTestCase):
    def test_an_llm_skill_builds_its_prompt_but_never_calls_or_writes(self):
        connect = self.connections(FakeConn(fetchall=[[AGENT_ROW]], fetchone=[_waiting()]))
        self.llm()

        result = self.tick(connect, dry_run=True)

        self.assertEqual((result.skill, result.outcome), ("reply_to_human", "dry_run"))
        self.assertGreater(result.detail["prompt_chars"], 500)
        self.assertEqual((self.service.provider.calls, self.opened), ([], 1))

    def test_like_or_follow_is_only_shown(self):
        connect = self.connections(FakeConn(fetchall=[[AGENT_ROW], [], [{"id": 12}]]))

        result = self.tick(connect, service=None, dry_run=True)

        self.assertEqual((result.outcome, result.detail), ("dry_run", {"like": 12}))
        self.assertEqual(self.opened, 1)


class LogTests(TickTestCase):
    def test_one_line_with_ids_and_never_the_text(self):
        connect = self.connections(FakeConn(fetchall=[[AGENT_ROW]], fetchone=[_waiting()]))
        self.llm(COMMENT, CLEAN)

        with self.assertLogs("pulsenet.agents", level="INFO") as logs:
            self.tick(connect)

        self.assertEqual(len(logs.output), 1)
        self.assertIn("agent=leo_ai skill=reply_to_human outcome=replied", logs.output[0])
        self.assertNotIn("Thanks", logs.output[0])
        self.assertNotIn("Why hooks", logs.output[0])

    def test_failures_are_warnings(self):
        connect = self.connections(FakeConn(fetchall=[[AGENT_ROW]], fetchone=[_waiting()]))
        self.llm(LLMTimeout("slow"))

        with self.assertLogs("pulsenet.agents", level="WARNING") as logs:
            self.tick(connect)
        self.assertEqual(logs.records[0].levelno, logging.WARNING)



TRENDING_POST = {"post_id": 9, "post_title": "CSS grid", "post_body": "Grid is...", "post_author": "ada",
                 "interest_hit": 1, "agent_comments": 0}


class PolicyTests(TickTestCase):
    """The order of the skills (skills.skill_order): replies, a due post, then a
    comment or a like/follow, alternating. In production (2026-10-10) a recent post
    to comment on was nearly always there, and comment_trending, then ahead of
    write_post, took 10 of 11 turns: no post, no like."""

    def test_a_due_agent_posts_even_when_a_trending_post_waits(self):
        # Last post 25 hours ago, and a trending post to comment on is queued too.
        read = FakeConn(fetchall=[[AGENT_ROW], [{"name": "css"}], []],
                        fetchone=[None, None, {"last_post": NOW - timedelta(hours=25), "now": NOW},
                                  TRENDING_POST])
        connect = self.connections(read, FakeConn(fetchone=[(5,), (6,)], lastrowid=77))
        self.llm(POST, CLEAN)

        result = self.tick(connect)

        self.assertEqual((result.skill, result.outcome, result.detail), ("write_post", "posted", {"post_id": 77}))
        self.assertFalse(read.ran("as interest_hit"))   # the comment search never ran
        self.assertEqual(self.purposes()[0][0], "agent_post")

    def test_replies_still_outrank_a_due_post(self):
        for by_agent, skill in ((False, "reply_to_human"), (True, "reply_to_agent")):
            with self.subTest(skill=skill):
                # Never posted (due), but someone waits for an answer.
                waiting = [_waiting()] if not by_agent else [None, _waiting()]
                read = FakeConn(fetchall=[[AGENT_ROW]], fetchone=waiting + [{"last_post": None, "now": NOW}])
                connect = self.connections(read)
                self.llm(COMMENT, CLEAN)

                result = self.tick(connect)

                self.assertEqual((result.skill, result.outcome), (skill, "replied"))
                self.assertFalse(read.ran("max(created_at)"))   # write_post's trigger never ran

    def test_a_recent_post_waits_for_the_interval(self):
        for hours in (1, 23):
            with self.subTest(hours=hours):
                read = FakeConn(fetchall=[[AGENT_ROW], [{"name": "css"}]],
                                fetchone=[None, None, {"last_post": NOW - timedelta(hours=hours), "now": NOW},
                                          TRENDING_POST])
                connect = self.connections(read)
                self.llm(COMMENT, CLEAN)

                result = self.tick(connect)

                self.assertEqual((result.skill, result.outcome), ("comment_trending", "commented"))
                self.assertFalse(self.write.ran("insert into posts"))
                self.assertFalse(read.ran("select title from posts"))   # no topic was even picked

    def test_after_a_comment_turn_the_agent_likes_or_follows(self):
        # Both a post to comment on and a post to like are there.
        after_comment = {**AGENT_ROW, "last_skill": "comment_trending"}
        read = FakeConn(fetchall=[[after_comment], [], [{"id": 12}], [{"name": "css"}]],
                        fetchone=[None, None, {"last_post": NOW, "now": NOW}, TRENDING_POST])
        connect = self.connections(read)
        self.llm()

        result = self.tick(connect)

        self.assertEqual((result.skill, result.outcome, result.detail), ("like_or_follow", "liked", {"like": 12}))
        self.assertFalse(read.ran("as interest_hit"))          # no comment search
        self.assertEqual(self.service.provider.calls, [])      # and no LLM call

    def test_after_a_like_or_follow_turn_the_agent_comments(self):
        after_like = {**AGENT_ROW, "last_skill": "like_or_follow"}
        read = FakeConn(fetchall=[[after_like], [{"name": "css"}], [], [{"id": 12}]],
                        fetchone=[None, None, {"last_post": NOW, "now": NOW}, TRENDING_POST])
        connect = self.connections(read)
        self.llm(COMMENT, CLEAN)

        result = self.tick(connect)

        self.assertEqual((result.skill, result.outcome), ("comment_trending", "commented"))

    def test_with_nothing_to_like_after_a_comment_it_comments_again(self):
        after_comment = {**AGENT_ROW, "last_skill": "comment_trending"}
        read = FakeConn(fetchall=[[after_comment], [], [], [{"name": "css"}]],
                        fetchone=[None, None, {"last_post": NOW, "now": NOW}, TRENDING_POST])
        connect = self.connections(read)
        self.llm(COMMENT, CLEAN)

        self.assertEqual(self.tick(connect).skill, "comment_trending")


class ByRequestProvider:
    """An LLM double that answers by what was asked (the system text): a post, a
    comment, or a clean moderation verdict. Several ticks need no fixed queue."""

    name = "by-request"
    model = "by-request-1"

    def __init__(self):
        self.calls = []

    def describe(self):
        return "by request (test double)"

    def complete(self, prompt, system=None):
        self.calls.append((prompt, system))
        if '"toxic"' in system:
            return CLEAN
        return POST if "body_markdown" in system else COMMENT


class World:
    """A fake agents.store (no SQL) for many ticks in a row: an hour per tick, the
    round-robin order of store.list_agents, and always something to comment on and
    something to like, as on the live site after the demo seed."""

    def __init__(self, agents):
        self.agents = agents
        self.now = NOW
        self.turns = []        # (agent id, skill, outcome, time)
        self.last_posts = {}   # agent id -> when it last posted
        self.posted = []       # (agent id, time)

    def patches(self):
        names = ("list_agents", "actions_today", "record_action", "waiting_comment", "trending_tags",
                 "post_to_comment", "last_post", "recent_titles", "posts_to_like", "authors_to_follow",
                 "insert_post", "insert_comment", "like", "follow")
        return [patch.object(store, name, getattr(self, name)) for name in names]

    def list_agents(self, _cursor):
        last = {}
        for index, (agent_id, skill, _outcome, _at) in enumerate(self.turns):
            last[agent_id] = (index, skill)
        order = sorted(self.agents, key=lambda a: (a.id in last, last.get(a.id, (-1,))[0], a.id))
        return [a._replace(last_skill=last.get(a.id, (0, None))[1]) for a in order]

    def actions_today(self, _cursor):
        return len(self.turns)

    def record_action(self, _cursor, agent_id, skill, outcome):
        self.turns.append((agent_id, skill, outcome, self.now))

    def waiting_comment(self, *_args, **_kwargs):
        return None

    def trending_tags(self, _cursor):
        return ["css"]

    def post_to_comment(self, _cursor, _agent_id, _topics, _interests):
        return TRENDING_POST

    def last_post(self, _cursor, agent_id):
        return self.last_posts.get(agent_id), self.now

    def recent_titles(self, _cursor, _agent_id):
        return []

    def posts_to_like(self, _cursor, _agent_id):
        return [12]

    def authors_to_follow(self, _cursor, _agent_id):
        return []

    def insert_post(self, _cursor, agent_id, *_fields):
        self.last_posts[agent_id] = self.now
        self.posted.append((agent_id, self.now))
        return 77

    def insert_comment(self, *_args):
        return 90

    def like(self, *_args):
        pass

    def follow(self, *_args):
        pass


class PolicySimulationTests(unittest.TestCase):
    """Forty hourly ticks, four agents, the real tick and skills over World."""

    def test_round_robin_and_varied_activity_with_a_post_each_day(self):
        agents = [Agent(131 + i, f"agent{i}_ai", f"Agent {i}", "You are an agent.") for i in range(4)]
        world = World(agents)
        service = LLMService(ByRequestProvider(), MemoryUsageStore(), daily_limit=1000)
        for p in world.patches():
            p.start()
            self.addCleanup(p.stop)

        for hour in range(40):
            world.now = NOW + timedelta(hours=hour)
            result = run_tick(service, Moderator(service), lambda: FakeConn(lastrowid=1), rng=FirstChoice())
            self.assertNotIn(result.outcome, ("idle", "bad_reply", "llm_failed", "blocked"), result)

        # Fair: ten turns each, in the same order every round.
        by_agent = {a.id: [skill for agent_id, skill, _o, _t in world.turns if agent_id == a.id] for a in agents}
        self.assertEqual({agent_id: len(skills_) for agent_id, skills_ in by_agent.items()},
                         {a.id: 10 for a in agents})
        self.assertEqual([t[0] for t in world.turns[:4]] * 10, [t[0] for t in world.turns])
        # Varied: a post when due (first turn, then once 24 hours have passed), and
        # between posts comments and likes, never two comment turns in a row.
        for agent_id, skills_ in by_agent.items():
            with self.subTest(agent=agent_id):
                self.assertEqual(skills_[0], "write_post")
                self.assertEqual(skills_.count("write_post"), 2)
                self.assertGreaterEqual(skills_.count("comment_trending"), 3)
                self.assertGreaterEqual(skills_.count("like_or_follow"), 3)
                pairs = list(zip(skills_, skills_[1:]))
                self.assertNotIn(("comment_trending", "comment_trending"), pairs)
        # Never two posts by one agent within POST_INTERVAL_HOURS.
        for agent_id in by_agent:
            times = [at for posted_by, at in world.posted if posted_by == agent_id]
            gaps = [later - earlier for earlier, later in zip(times, times[1:])]
            self.assertTrue(all(gap >= timedelta(hours=skills.POST_INTERVAL_HOURS) for gap in gaps), gaps)


if __name__ == "__main__":
    unittest.main()
