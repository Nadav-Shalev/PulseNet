"""llm/usage.py DbUsageStore against the hand-rolled DB double (no real MySQL).

Asserts the SQL and parameters it runs, that every write is committed, and that
each operation's own connection is closed even when the query fails. The SQL
itself runs on real MySQL through ``manage.py llm-check`` (see backend/README.md).
"""

import sys
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
for _p in (TESTS_DIR.parent, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from llm import DbUsageStore, MemoryUsageStore, UsageRecord  # noqa: E402
from support import FakeConn  # noqa: E402

DAY = date(2026, 10, 8)
ENTRY = UsageRecord(DAY, "openai_compat", "flash-model", "check", 42, "ok", 812, 30, 120)


class FailingCursorConn(FakeConn):
    """A connection whose queries fail, like a missing llm_usage table."""

    def cursor(self, dictionary=False, **_kwargs):
        cursor = super().cursor(dictionary=dictionary)

        def execute(sql, params=None):
            raise RuntimeError("1146: Table 'pulsenet_db.llm_usage' doesn't exist")

        cursor.execute = execute
        return cursor


class DbUsageStoreTests(unittest.TestCase):
    def store(self, *conns):
        """A DbUsageStore whose connect() hands out ``conns`` in order."""
        handed = list(conns)
        self.connects = 0

        def connect():
            self.connects += 1
            return handed.pop(0)

        return DbUsageStore(connect)

    def test_count_reads_the_day_without_refused_calls(self):
        conn = FakeConn(fetchone=[(7,)])

        self.assertEqual(self.store(conn).count(DAY), 7)

        self.assertEqual(conn.params_for("select count(*) from llm_usage"), (DAY,))
        self.assertTrue(conn.ran("where usage_day = %s and status <> 'over_limit'"))
        self.assertTrue(conn.closed)
        self.assertEqual(conn.commits, 0)

    def test_count_of_no_row_is_zero(self):
        self.assertEqual(self.store(FakeConn()).count(DAY), 0)

    def test_count_for_user_reads_one_users_day_for_the_given_purposes(self):
        conn = FakeConn(fetchone=[(3,)])

        count = self.store(conn).count_for_user(DAY, 42, ["ai_correct", "ai_suggest_post"])

        self.assertEqual(count, 3)
        sql, params = conn.find("select count(*) from llm_usage")[0]
        self.assertIn("WHERE user_id = %s AND usage_day = %s AND status <> 'over_limit' "
                      "AND purpose IN (%s, %s)", " ".join(sql.split()))
        self.assertEqual(params, (42, DAY, "ai_correct", "ai_suggest_post"))
        self.assertTrue(conn.closed)
        self.assertEqual(conn.commits, 0)

    def test_count_for_user_has_one_placeholder_per_purpose(self):
        conn = FakeConn(fetchone=[(0,)])

        self.assertEqual(self.store(conn).count_for_user(DAY, 1, ("ai_correct",)), 0)

        sql, params = conn.find("select count(*) from llm_usage")[0]
        self.assertIn("purpose IN (%s)", " ".join(sql.split()))
        self.assertEqual(params, (1, DAY, "ai_correct"))

    def test_count_for_user_without_purposes_is_refused_before_connecting(self):
        store = self.store()
        for empty in ([], ()):
            with self.subTest(purposes=empty):
                with self.assertRaisesRegex(ValueError, "at least one purpose"):
                    store.count_for_user(DAY, 1, empty)
        self.assertEqual(self.connects, 0)

    def test_record_inserts_every_column_in_order_and_commits(self):
        conn = FakeConn()

        self.store(conn).record(ENTRY)

        sql, params = conn.find("insert into llm_usage")[0]
        self.assertIn("(usage_day, provider, model, purpose, user_id, status, latency_ms, "
                      "prompt_chars, reply_chars)", " ".join(sql.split()))
        self.assertEqual(params, (DAY, "openai_compat", "flash-model", "check", 42, "ok", 812, 30, 120))
        self.assertEqual(conn.commits, 1)
        self.assertTrue(conn.closed)

    def test_each_operation_opens_its_own_connection(self):
        # Its own commit, so a call stays logged even if the request that made it fails.
        first, second = FakeConn(fetchone=[(0,)]), FakeConn()
        store = self.store(first, second)

        store.count(DAY)
        store.record(ENTRY)

        self.assertEqual(self.connects, 2)
        self.assertTrue(first.closed and second.closed)

    def test_the_connection_is_closed_when_a_query_fails(self):
        calls = {
            "count": lambda store: store.count(DAY),
            "count_for_user": lambda store: store.count_for_user(DAY, 1, ["ai_correct"]),
            "record": lambda store: store.record(ENTRY),
        }
        for operation, call in calls.items():
            with self.subTest(operation=operation):
                conn = FailingCursorConn()
                with self.assertRaisesRegex(RuntimeError, "1146"):
                    call(self.store(conn))
                self.assertTrue(conn.closed)
                self.assertEqual(conn.commits, 0)


class MemoryUsageStoreTests(unittest.TestCase):
    def test_counts_the_day_without_refused_calls(self):
        store = MemoryUsageStore()
        for day, status in [(DAY, "ok"), (DAY, "error"), (DAY, "over_limit"), (date(2026, 10, 7), "ok")]:
            store.record(ENTRY._replace(usage_day=day, status=status))

        self.assertEqual(store.count(DAY), 2)
        self.assertEqual(len(store.records), 4)

    def test_counts_one_users_purposes_without_refused_calls(self):
        store = MemoryUsageStore()
        for user_id, purpose, status in [(42, "ai_correct", "ok"), (42, "ai_correct", "over_limit"),
                                         (42, "moderation", "ok"), (7, "ai_correct", "ok")]:
            store.record(ENTRY._replace(user_id=user_id, purpose=purpose, status=status))

        self.assertEqual(store.count_for_user(DAY, 42, ["ai_correct"]), 1)
        with self.assertRaises(ValueError):
            store.count_for_user(DAY, 42, [])


if __name__ == "__main__":
    unittest.main()
