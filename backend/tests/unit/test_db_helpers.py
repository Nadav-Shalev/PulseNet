"""Unit tests for app.py's DB connection helpers (``mysql.connector`` is mocked)."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import mysql.connector

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import app  # noqa: E402
from support import FakeConn  # noqa: E402


class GetDbConnectionTests(unittest.TestCase):
    def test_connects_with_settings_from_environment(self):
        env = {"DB_HOST": "db.local", "DB_USER": "pulse",
               "DB_PASSWORD": "not-a-secret", "DB_NAME": "pulsenet_test"}
        with patch.dict(os.environ, env), \
             patch.object(mysql.connector, "connect") as connect:
            conn = app.get_db_connection()

        self.assertIs(conn, connect.return_value)
        connect.assert_called_once_with(
            host="db.local", user="pulse", password="not-a-secret", database="pulsenet_test",
        )


class IsDbAvailableTests(unittest.TestCase):
    def test_true_when_a_connection_opens_and_it_is_closed_again(self):
        conn = FakeConn()
        with patch.object(app, "get_db_connection", return_value=conn):
            self.assertTrue(app.is_db_available())

        self.assertTrue(conn.closed)

    def test_false_when_connecting_fails(self):
        error = mysql.connector.errors.InterfaceError("2003: Can't connect to MySQL server")
        with patch.object(app, "get_db_connection", side_effect=error):
            self.assertFalse(app.is_db_available())


if __name__ == "__main__":
    unittest.main()
