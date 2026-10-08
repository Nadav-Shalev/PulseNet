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
        for operation in ("count", "record"):
            with self.subTest(operation=operation):
                conn = FailingCursorConn()
                store = self.store(conn)
                with self.assertRaisesRegex(RuntimeError, "1146"):
                    getattr(store, operation)(DAY if operation == "count" else ENTRY)
                self.assertTrue(conn.closed)
                self.assertEqual(conn.commits, 0)


class MemoryUsageStoreTests(unittest.TestCase):
    def test_counts_the_day_without_refused_calls(self):
        store = MemoryUsageStore()
        for day, status in [(DAY, "ok"), (DAY, "error"), (DAY, "over_limit"), (date(2026, 10, 7), "ok")]:
            store.record(ENTRY._replace(usage_day=day, status=status))

        self.assertEqual(store.count(DAY), 2)
        self.assertEqual(len(store.records), 4)


if __name__ == "__main__":
    unittest.main()
