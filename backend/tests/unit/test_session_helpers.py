"""Unit tests for authentication/session helper functions."""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import app  # noqa: E402
from support import FakeConn  # noqa: E402


class SessionHelperTests(unittest.TestCase):
    def test_delete_expired_sessions_issues_cleanup_delete(self):
        # Arrange
        conn = FakeConn()

        # Act
        app._delete_expired_sessions(conn.cursor())

        # Assert
        self.assertTrue(conn.ran("delete from sessions where expires_at <= now()"))

    def test_create_session_inserts_row_and_returns_token(self):
        # Arrange
        conn = FakeConn()

        # Act
        token = app._create_session(conn.cursor(), 42)

        # Assert
        self.assertIsInstance(token, str)
        self.assertTrue(token)
        insert = conn.find("insert into sessions")
        self.assertTrue(insert)
        params = insert[0][1]
        self.assertEqual(params[0], token)
        self.assertEqual(params[1], 42)


if __name__ == "__main__":
    unittest.main()
