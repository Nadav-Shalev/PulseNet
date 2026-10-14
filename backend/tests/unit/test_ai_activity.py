"""ai_activity: one row of the AI Activity stream as the admin page shows it, and
what a page asks MySQL for (which branches, filters, order and slice). No Flask: a
FakeConn's dictionary cursor."""

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

import ai_activity  # noqa: E402
import ai_assist  # noqa: E402
from support import FakeConn  # noqa: E402

AT = datetime(2026, 10, 15, 19, 0, 0)
MEI = {"id": 11, "username": "mei_ai", "name": "Mei Tanaka", "is_agent": True}
NADAV = {"id": 2, "username": "nadav", "name": "Nadav", "is_agent": False}


def agent_row(kind, **over):
    row = {"source": "agent", "source_id": 41, "created_at": AT, "kind": kind, "status": None,
           "actor_id": 11, "actor_username": "mei_ai", "actor_name": "Mei Tanaka", "actor_is_agent": 1,
           "post_id": None, "post_title": None, "comment_id": None,
           "target_id": None, "target_username": None, "target_name": None, "target_is_agent": None}
    row.update(over)
    return row


def ai_row(purpose, status="ok", **over):
    row = {"source": "ai_assist", "source_id": 17, "created_at": AT, "kind": purpose, "status": status,
           "actor_id": 2, "actor_username": "nadav", "actor_name": "Nadav", "actor_is_agent": 0,
           "post_id": None, "post_title": None, "comment_id": None,
           "target_id": None, "target_username": None, "target_name": None, "target_is_agent": None}
    row.update(over)
    return row


POST = {"post_id": 39, "post_title": "Practical Baselines for ML"}


class EventTests(unittest.TestCase):
    def test_each_kind_of_agent_turn(self):
        cases = {
            "posted":    (POST, {"id": 39, "title": "Practical Baselines for ML"}, None, None),
            "commented": ({**POST, "comment_id": 90}, {"id": 39, "title": "Practical Baselines for ML"}, 90, None),
            "replied":   ({**POST, "comment_id": 91}, {"id": 39, "title": "Practical Baselines for ML"}, 91, None),
            "liked":     (POST, {"id": 39, "title": "Practical Baselines for ML"}, None, None),
            "followed":  ({"target_id": 2, "target_username": "nadav", "target_name": "Nadav", "target_is_agent": 0},
                          None, None, NADAV),
        }
        for kind, (over, post, comment_id, target) in cases.items():
            with self.subTest(kind=kind):
                self.assertEqual(ai_activity.event(agent_row(kind, **over)), {
                    "id": "agent-41", "source": "agent", "type": kind, "created_at": AT,
                    "actor": MEI, "post": post, "comment_id": comment_id, "target_user": target,
                    "status": None,
                })

    def test_a_use_of_an_ai_helper_keeps_its_status_and_has_no_target(self):
        for purpose in ai_assist.PURPOSES:
            for status in ("ok", "error", "timeout", "rate_limited", "over_limit"):
                with self.subTest(purpose=purpose, status=status):
                    self.assertEqual(ai_activity.event(ai_row(purpose, status)), {
                        "id": "ai_assist-17", "source": "ai_assist", "type": purpose, "created_at": AT,
                        "actor": NADAV, "post": None, "comment_id": None, "target_user": None,
                        "status": status,
                    })

    def test_a_deleted_user_is_none_never_a_guessed_name(self):
        # llm_usage.user_id and agent_actions.target_user_id are SET NULL.
        gone = {"actor_id": None, "actor_username": None, "actor_name": None, "actor_is_agent": None}
        self.assertIsNone(ai_activity.event(ai_row("ai_correct", **gone))["actor"])
        self.assertIsNone(ai_activity.event(agent_row("followed"))["target_user"])

    def test_a_turn_without_its_post(self):
        # Logged before 009, or its post deleted since (SET NULL): no link.
        for kind in ("posted", "commented", "replied", "liked"):
            with self.subTest(kind=kind):
                self.assertIsNone(ai_activity.event(agent_row(kind))["post"])

    def test_the_type_order_lists_every_kind_once(self):
        self.assertEqual(ai_activity.TYPE_ORDER, ai_activity.AGENT_TYPES + tuple(ai_assist.PURPOSES))
        self.assertEqual(len(set(ai_activity.TYPE_ORDER)), len(ai_activity.TYPE_ORDER))
        self.assertEqual(ai_activity.TYPES[0], "all")
        self.assertIn("ai_assist", ai_activity.TYPES)


class PageTests(unittest.TestCase):
    def page(self, counts, rows=(), **kwargs):
        self.conn = FakeConn(fetchone=[{"n": n} for n in counts], fetchall=[list(rows)])
        return ai_activity.page_of_events(self.conn.cursor(dictionary=True), **kwargs)

    def select(self):
        return self.conn.find("select * from (")[0]

    def test_all_counts_and_merges_both_sources(self):
        events, total = self.page([3, 2], [agent_row("liked", **POST), ai_row("ai_suggest_post")])

        self.assertEqual(total, 5)
        self.assertEqual([e["id"] for e in events], ["agent-41", "ai_assist-17"])
        self.assertEqual(self.conn.params_for("from agent_actions where outcome in"), ai_activity.AGENT_TYPES)
        self.assertEqual(self.conn.params_for("from llm_usage where purpose in"), tuple(ai_assist.PURPOSES))
        sql, params = self.select()
        self.assertIn(" UNION ALL ", sql)
        self.assertEqual(params, (*ai_activity.AGENT_TYPES, *ai_assist.PURPOSES, 25, 0))

    def test_moderation_and_the_agents_own_calls_are_never_asked_for(self):
        self.page([1, 1])

        asked = [value for _sql, params in self.conn.executed for value in params]
        for purpose in ("moderation", "check", "agent_post", "agent_comment", "agent_reply_human"):
            with self.subTest(purpose=purpose):
                self.assertNotIn(purpose, asked)
        # Nor a failed turn.
        for outcome in ("llm_failed", "bad_reply", "blocked", "target_gone"):
            with self.subTest(outcome=outcome):
                self.assertNotIn(outcome, asked)

    def test_an_agent_type_reads_only_agent_actions(self):
        self.page([4], kind="followed")

        self.assertFalse(self.conn.ran("llm_usage"))
        self.assertEqual(self.select()[1], ("followed", 25, 0))

    def test_ai_assist_reads_only_llm_usage(self):
        self.page([4], kind="ai_assist")

        self.assertFalse(self.conn.ran("agent_actions"))
        self.assertEqual(self.select()[1], (*ai_assist.PURPOSES, 25, 0))

    def test_the_orders(self):
        orders = {
            "newest": "order by ev.created_at desc, ev.source, ev.source_id desc limit %s offset %s",
            "oldest": "order by ev.created_at, ev.source, ev.source_id limit %s offset %s",
            "type":   "order by field(ev.kind, %s, %s, %s, %s, %s, %s, %s, %s), ev.created_at desc, "
                      "ev.source, ev.source_id desc limit %s offset %s",
        }
        for sort, clause in orders.items():
            with self.subTest(sort=sort):
                self.page([1, 1], sort=sort)
                self.assertTrue(self.conn.ran(clause))
        # FIELD's values come after the branches' and before LIMIT.
        self.assertEqual(self.select()[1],
                         (*ai_activity.AGENT_TYPES, *ai_assist.PURPOSES, *ai_activity.TYPE_ORDER, 25, 0))

    def test_a_later_page_is_an_offset(self):
        self.page([30, 0], page=3, per_page=10)

        self.assertEqual(self.select()[1][-2:], (10, 20))

    def test_nothing_to_show_reads_no_page(self):
        self.assertEqual(self.page([0, 0]), ([], 0))
        self.assertFalse(self.conn.ran("select * from ("))

    def test_no_email_text_or_provider_is_read(self):
        self.page([1, 1])

        sql = self.select()[0].lower()
        for column in ("email", "prompt", "reply_chars", "provider", "model", "body", "password"):
            with self.subTest(column=column):
                self.assertNotIn(column, sql)


if __name__ == "__main__":
    unittest.main()
