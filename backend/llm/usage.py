"""Where the LLM service logs its calls, and reads back today's count.

DbUsageStore writes the llm_usage table (migration 004). It opens its own short
connection for each operation and commits it, so a call is logged even when the
request that made it fails later, and every process that calls the LLM (the API
workers, later the agents' timer) shares one log and one daily count.
MemoryUsageStore keeps the same rows in a list, for tests.
"""

import datetime
from typing import NamedTuple, Optional, Protocol, Tuple

STATUSES = ("ok", "error", "timeout", "rate_limited", "over_limit")


class UsageRecord(NamedTuple):
    """One llm_usage row. Sizes only: the prompt and reply text are never kept."""

    usage_day: datetime.date    # the UTC day the call counts against
    provider: str
    model: Optional[str]
    purpose: str                # what the call was for: 'check', 'moderation', ...
    user_id: Optional[int]      # who it was for, if anyone
    status: str                 # one of STATUSES
    latency_ms: Optional[int]   # None when no request was sent (over_limit)
    prompt_chars: int           # prompt and system text together
    reply_chars: int


class UsageStore(Protocol):
    """What LLMService needs from a usage log."""

    def count(self, usage_day: datetime.date) -> int:
        """Calls on ``usage_day`` that reached a provider: every status but over_limit."""

    def count_for_user(self, usage_day: datetime.date, user_id: int, purposes: Tuple[str, ...]) -> int:
        """The same, for one user and only the calls made for one of ``purposes``."""

    def record(self, entry: UsageRecord) -> None:
        """Log one call."""


_COUNT_SQL = """
    SELECT COUNT(*) FROM llm_usage
    WHERE usage_day = %s AND status <> 'over_limit'
"""
# idx_llm_usage_user (user_id, usage_day) finds the user's day; the purposes and
# statuses are filtered among those few rows.
_USER_COUNT_SQL = """
    SELECT COUNT(*) FROM llm_usage
    WHERE user_id = %s AND usage_day = %s AND status <> 'over_limit'
      AND purpose IN ({placeholders})
"""
_INSERT_SQL = """
    INSERT INTO llm_usage (usage_day, provider, model, purpose, user_id, status,
                           latency_ms, prompt_chars, reply_chars)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


class DbUsageStore:
    """The llm_usage table, through ``connect``: a callable that returns a new DB
    connection. It is called for every operation, so pass the factory itself (or a
    lambda around it), not a connection."""

    def __init__(self, connect):
        self._connect = connect

    def count(self, usage_day):
        return self._count(_COUNT_SQL, (usage_day,))

    def count_for_user(self, usage_day, user_id, purposes):
        purposes = _purposes(purposes)
        sql = _USER_COUNT_SQL.format(placeholders=", ".join(["%s"] * len(purposes)))
        return self._count(sql, (user_id, usage_day, *purposes))

    def _count(self, sql, params):
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            row = cursor.fetchone()
            cursor.close()
            return int(row[0]) if row else 0
        finally:
            conn.close()

    def record(self, entry):
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(_INSERT_SQL, tuple(entry))
            conn.commit()
            cursor.close()
        finally:
            conn.close()


class MemoryUsageStore:
    """The same log in a list (``records``), for tests."""

    def __init__(self):
        self.records = []

    def count(self, usage_day):
        return sum(1 for entry in self.records
                   if entry.usage_day == usage_day and entry.status != "over_limit")

    def count_for_user(self, usage_day, user_id, purposes):
        purposes = _purposes(purposes)
        return sum(1 for entry in self.records
                   if entry.usage_day == usage_day and entry.status != "over_limit"
                   and entry.user_id == user_id and entry.purpose in purposes)

    def record(self, entry):
        self.records.append(entry)


def _purposes(purposes):
    """``purposes`` as a non-empty tuple: SQL has no empty IN ()."""
    purposes = tuple(purposes)
    if not purposes:
        raise ValueError("purposes must name at least one purpose")
    return purposes
