"""run_tick end to end: the reads, the one LLM call, moderation and the write.

The DB is two FakeConns (the read connection, then the write one), the LLM a
ScriptedProvider behind a real LLMService (so every call lands in a
MemoryUsageStore), and moderation the real Moderator. No MySQL, no network.
"""

import json
import logging
import sys
import unittest
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agents import run_tick  # noqa: E402
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
        connect = self.connections(FakeConn(fetchall=[[AGENT_ROW], [{"name": "css"}]],
                                            fetchone=[None, None, found]))
        self.llm(COMMENT, CLEAN)

        result = self.tick(connect)

        self.assertEqual((result.skill, result.outcome), ("comment_trending", "commented"))
        self.assertEqual(result.detail, {"post_id": 9, "comment_id": 90})
        self.assertIsNone(self.write.params_for("insert into comments")[2])     # top-level
        self.assertEqual(self.purposes()[0][0], "agent_comment")

    def test_a_first_post_with_its_tags(self):
        read = FakeConn(fetchall=[[AGENT_ROW], [], [], [], []],
                        fetchone=[None, None, None, {"last_post": None, "now": NOW}])
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
                                            fetchone=[None, None, None, {"last_post": NOW, "now": NOW}]))
        self.llm()

        result = self.tick(connect)

        self.assertEqual((result.skill, result.outcome, result.detail), ("like_or_follow", "followed", {"follow": 3}))
        self.assertEqual(self.write.params_for("insert ignore into follows"), (131, 3))
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
                         ["reply_to_human", "reply_to_agent", "comment_trending", "write_post"])
        self.assertEqual(self.opened, 1)


class NothingWrittenTests(TickTestCase):
    def reply_tick(self, *replies, daily_limit=100):
        connect = self.connections(FakeConn(fetchall=[[AGENT_ROW]], fetchone=[_waiting()]))
        self.llm(*replies, daily_limit=daily_limit)
        return self.tick(connect)

    def test_blocked_by_the_llm(self):
        result = self.reply_tick(COMMENT, TOXIC)

        self.assertEqual((result.outcome, result.detail["category"]), ("blocked", "harassment"))
        self.assertEqual(self.opened, 1)          # no write connection at all

    def test_blocked_by_the_word_list_when_the_verdict_is_unreadable(self):
        result = self.reply_tick('{"comment": "you idiot, read the docs"}', "I think it is fine")

        self.assertEqual((result.outcome, result.detail["category"]), ("blocked", "harassment"))
        self.assertEqual(self.opened, 1)

    def test_a_bad_reply_is_not_moderated_or_written(self):
        result = self.reply_tick("Sure, here is my reply!")

        self.assertEqual(result.outcome, "bad_reply")
        self.assertEqual(self.purposes(), [("agent_reply_human", 131, "ok")])
        self.assertEqual(self.opened, 1)

    def test_llm_failures(self):
        for error, name in ((LLMRateLimited("429", retry_after=30), "LLMRateLimited"),
                            (LLMTimeout("slow"), "LLMTimeout")):
            with self.subTest(name):
                result = self.reply_tick(error)
                self.assertEqual((result.outcome, result.detail["error"]), ("llm_failed", name))
                self.assertEqual(self.opened, 1)
                self.assertEqual(len(self.service.provider.calls), 1)       # no retry

    def test_the_daily_limit(self):
        result = self.reply_tick(daily_limit=0)

        self.assertEqual((result.outcome, result.detail["error"]), ("llm_failed", "LLMLimitReached"))
        self.assertEqual(self.purposes(), [("agent_reply_human", 131, "over_limit")])
        self.assertEqual(self.opened, 1)

    def test_a_target_deleted_meanwhile(self):
        write = FakeConn(raise_on={"insert into comments": FkError(1452)})
        connect = self.connections(FakeConn(fetchall=[[AGENT_ROW]], fetchone=[_waiting()]), write)
        self.llm(COMMENT, CLEAN)

        result = self.tick(connect)

        self.assertEqual(result.outcome, "target_gone")
        self.assertEqual((write.commits, write.rollbacks, write.closed), (0, 1, True))

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
        self.assertIn("NOT is_banned", self.read.find("username = %s")[0][0])
        self.assertFalse(self.read.ran("order by id"))   # the list is never read

    def test_a_named_agent_acts(self):
        connect = self.connections(FakeConn(fetchone=[AGENT_ROW, _waiting()]))
        self.llm(COMMENT, CLEAN)

        result = self.tick(connect, agent="leo_ai")

        self.assertEqual((result.agent, result.outcome), ("leo_ai", "replied"))

    def test_idle_when_nothing_is_found(self):
        connect = self.connections(FakeConn(fetchall=[[AGENT_ROW]],
                                            fetchone=[None, None, None, {"last_post": NOW, "now": NOW}]))
        self.llm()

        result = self.tick(connect)

        self.assertEqual((result.outcome, result.detail), ("idle", {}))
        self.assertEqual(self.opened, 1)


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


if __name__ == "__main__":
    unittest.main()
