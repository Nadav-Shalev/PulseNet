"""Shared test helpers for the backend suite.

This module is intentionally NOT named ``test_*`` so ``unittest discover`` never
collects it as a test case.

It provides:
  * ``sys.path`` bootstrap so ``import app`` works no matter where the tests run.
  * ``flask_app`` / ``client()`` — the Flask app and a fresh test client.
  * ``FakeConn`` / ``FakeCursor`` — a tiny stand-in for a ``mysql.connector``
    connection so API tests run with **no real database**. Queries are recorded
    (for assertions) and result rows are served from queues you seed per test.
  * ``patch_db(...)`` — patches ``app.get_db_connection`` / ``app.is_db_available``
    for the duration of a test.

Why a hand-rolled fake instead of MagicMock: the endpoints issue a small, ordered
sequence of ``execute``/``fetchone``/``fetchall`` calls, and several open more
than one cursor per request. A purpose-built double keeps each test readable —
seed the rows a request will read, then assert on the SQL/params it ran.
"""

import sys
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

# ── Make ``import app`` work regardless of CWD / how the tests are launched ──────
_TESTS_DIR  = Path(__file__).resolve().parent
_BACKEND_DIR = _TESTS_DIR.parent
for _p in (_BACKEND_DIR, _TESTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import app  # noqa: E402  (must follow the sys.path bootstrap above)

flask_app = app.app


def client():
    """A fresh Flask test client."""
    return flask_app.test_client()


def _norm(sql):
    """Collapse whitespace/newlines so substring matching on multi-line SQL works."""
    return " ".join(sql.split()).lower()


class FakeCursor:
    """Records executed statements and serves queued rows from its connection.

    All cursors created from the same ``FakeConn`` share that connection's
    ``executed`` log and result queues, so a request that opens two cursors is
    handled transparently.
    """

    def __init__(self, conn):
        self._conn = conn

    # mysql.connector cursors accept ``execute(sql)`` or ``execute(sql, params)``.
    def execute(self, sql, params=None):
        self._conn.executed.append((sql, params))

    def executemany(self, sql, seq_params):
        self._conn.executed.append((sql, list(seq_params)))

    def fetchone(self):
        if self._conn.fetchone_results:
            return self._conn.fetchone_results.popleft()
        return None

    def fetchall(self):
        if self._conn.fetchall_results:
            return self._conn.fetchall_results.popleft()
        return []

    @property
    def lastrowid(self):
        return self._conn.lastrowid

    def close(self):
        self._conn.cursors_closed += 1

    # Support ``with conn.cursor() as cur:`` if a future endpoint uses it.
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FakeConn:
    """Stand-in for a ``mysql.connector`` connection.

    Seed the rows a request will read:
      * ``fetchone`` — list of values returned by successive ``fetchone()`` calls
        (``None`` once exhausted, i.e. "no row").
      * ``fetchall`` — list of lists returned by successive ``fetchall()`` calls
        (``[]`` once exhausted).
      * ``lastrowid`` — value reported after an INSERT.

    Then assert on what ran via ``ran()`` / ``find()`` / ``executed``.
    """

    def __init__(self, fetchone=None, fetchall=None, lastrowid=1):
        self.executed = []                       # list[(sql, params)]
        self.fetchone_results = deque(fetchone or [])
        self.fetchall_results = deque(fetchall or [])
        self.lastrowid = lastrowid
        self.commits = 0
        self.closed = False
        self.cursors_closed = 0
        self.last_dictionary = None

    def cursor(self, dictionary=False, **_kwargs):
        self.last_dictionary = dictionary
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True

    # ── assertion helpers ──────────────────────────────────────────────────────
    def find(self, needle):
        """All (sql, params) whose normalized SQL contains ``needle`` (case-insensitive)."""
        n = needle.lower()
        return [(sql, params) for sql, params in self.executed if n in _norm(sql)]

    def ran(self, needle):
        """True if any executed statement contains ``needle``."""
        return bool(self.find(needle))

    def params_for(self, needle):
        """Params of the first statement matching ``needle`` (or None)."""
        matches = self.find(needle)
        return matches[0][1] if matches else None


@contextmanager
def patch_db(conn, *, db_available=True):
    """Patch the DB seam so endpoints use ``conn`` and see the given availability.

    Usage::

        conn = FakeConn(fetchone=[user_row])
        with patch_db(conn):
            resp = client().get("/api/me")
    """
    with patch.object(app, "get_db_connection", return_value=conn), \
         patch.object(app, "is_db_available", return_value=db_available):
        yield conn
