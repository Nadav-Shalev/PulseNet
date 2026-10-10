"""Offline, additive seeding against a stateful SQL store and the real CLI."""
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import mysql.connector

BACKEND_DIR = Path(__file__).resolve().parents[2]
for directory in (BACKEND_DIR, BACKEND_DIR / "tests"):
    sys.path.insert(0, str(directory))

import demo_content
import manage
import seed_data
from seed_support import SeedDatabase
from support import FakeConn

NOW = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.db = SeedDatabase()
        self.addCleanup(self.db.raw.close)
        fixed_clock = patch.object(demo_content, "datetime")
        fixed_clock.start().now.return_value = NOW
        self.addCleanup(fixed_clock.stop)
        # Fail before anything can reach an HTTP transport or model, even if .env
        # enables real providers. Every test in this module inherits these guards.
        for target in (
            "requests.sessions.Session.request",
            "socket.create_connection",
            "llm.LLMService.complete",
            "llm.from_env",
        ):
            guard = patch(target, side_effect=AssertionError("external call forbidden"))
            guard.start()
            self.addCleanup(guard.stop)

    def seed(self, **kwargs):
        kwargs.setdefault("now", NOW)
        return seed_data.seed_agent_content(self.db, **kwargs)


class SeedTests(OfflineTests):
    def test_inserts_30_posts_for_database_ids_with_tags_and_no_devto_fields(self):
        result = self.seed()
        self.assertEqual(result, {"inserted": 30, "skipped": 0, "would_insert": 0})
        rows = self.db.raw.execute(
            "SELECT u.username, COUNT(*) FROM posts p JOIN users u ON u.id=p.author_id GROUP BY u.username"
        ).fetchall()
        self.assertEqual(dict(rows), {p["username"]: 3 for p in demo_content.AGENT_PROFILES})
        self.assertEqual(self.db.raw.execute(
            "SELECT COUNT(*) FROM posts WHERE devto_id IS NOT NULL OR devto_url IS NOT NULL"
        ).fetchone()[0], 0)
        for post in demo_content.build_posts(NOW):
            saved = self.db.raw.execute(
                "SELECT p.id, p.body, p.body_html, p.description, p.created_at FROM posts p "
                "JOIN users u ON u.id=p.author_id WHERE u.username=? AND p.title=?",
                (post["username"], post["title"]),
            ).fetchone()
            self.assertEqual(saved[1:4], (post["body"], post["body_html"], post["description"]))
            self.assertEqual(datetime.fromisoformat(saved[4]), post["created_at"].replace(tzinfo=None))
            tags = self.db.raw.execute(
                "SELECT t.name FROM posts_tags pt JOIN tags t ON t.id=pt.tag_id WHERE pt.post_id=?", (saved[0],)
            ).fetchall()
            self.assertEqual({t[0] for t in tags}, set(post["tags"]))
        self.assertEqual(self.db.commits, 1)
        self.assertEqual(self.db.cursors_closed, 1)

    def test_second_run_with_new_clock_is_a_noop_including_tags_and_timestamps(self):
        self.seed()
        snapshot = self.db.snapshot()
        result = self.seed(now=NOW + timedelta(days=7))
        self.assertEqual(result, {"inserted": 0, "skipped": 30, "would_insert": 0})
        self.assertEqual(self.db.snapshot(), snapshot)

    def test_partial_dataset_and_existing_edited_content_are_preserved(self):
        fixture = demo_content.POSTS[0]
        author = self.db.raw.execute("SELECT id FROM users WHERE username=?", (fixture.username,)).fetchone()[0]
        self.db.raw.execute(
            "INSERT INTO posts (id,author_id,title,body,body_html,created_at) VALUES (900,?,?,?,?,?)",
            (author, fixture.title, "Edited existing content", "<p>Edited</p>", "2024-01-01 00:00:00"),
        )
        self.db.raw.execute(
            "INSERT INTO posts (id,author_id,title,body,devto_id,devto_url) VALUES (901,?,?,?,?,?)",
            (author, "Existing legacy article", "Keep me", 12345, "https://dev.to/legacy"),
        )
        self.db.raw.execute("INSERT INTO tags (id,name) VALUES (900,'React')")
        self.db.raw.execute("INSERT INTO posts_tags VALUES (900,900)")
        self.db.raw.commit()
        before = self.db.snapshot()
        result = self.seed()
        self.assertEqual(result["inserted"], 29)
        self.assertEqual(result["skipped"], 1)
        after = self.db.snapshot()
        for table, rows in before.items():
            for row in rows:
                self.assertIn(row, after[table], table)
        self.assertEqual(self.db.raw.execute("SELECT COUNT(*) FROM posts_tags WHERE post_id=900").fetchone()[0], 1)
        self.assertEqual(self.seed(now=NOW + timedelta(days=1))["inserted"], 0)

    def test_dry_run_is_read_only_on_empty_and_partially_seeded_databases(self):
        before = self.db.snapshot()
        result = self.seed(dry_run=True)
        self.assertEqual(result, {"inserted": 0, "skipped": 0, "would_insert": 30})
        self.assertEqual(before, self.db.snapshot())
        self.assertEqual(self.db.commits, 0)
        self.assertTrue(all(sql.startswith("SELECT ") and "FOR UPDATE" not in sql
                            for sql, _ in self.db.executed))
        self.seed()
        self.db.raw.execute("DELETE FROM posts_tags WHERE post_id=1")
        self.db.raw.execute("DELETE FROM posts WHERE id=1")
        self.db.raw.commit()
        self.assertEqual(self.seed(dry_run=True), {"inserted": 0, "skipped": 29, "would_insert": 1})

    def test_missing_or_non_agent_account_aborts_before_any_write(self):
        for invalid in ("missing", "not_agent"):
            with self.subTest(invalid=invalid):
                if invalid == "missing":
                    self.db.raw.execute("DELETE FROM users WHERE username='viktor_ai'")
                else:
                    self.db.raw.execute("INSERT INTO users VALUES (999,'viktor_ai',0,0)")
                self.db.raw.commit()
                before = self.db.snapshot()
                with self.assertRaisesRegex(seed_data.SeedError, "viktor_ai"):
                    self.seed()
                self.assertEqual(before, self.db.snapshot())
        self.assertFalse(any(sql.startswith("INSERT") for sql, _ in self.db.executed))
        self.assertEqual(self.db.rollbacks, 2)

    def test_banned_agents_are_seeded_without_changing_account_flags(self):
        self.db.raw.execute("UPDATE users SET is_banned=1 WHERE username='priya_ai'")
        self.db.raw.commit()
        before = self.db.snapshot()["users"]
        self.assertEqual(self.seed()["inserted"], 30)
        self.assertEqual(before, self.db.snapshot()["users"])

    def test_tag_link_failure_rolls_back_the_entire_batch(self):
        before = self.db.snapshot()
        self.db.raise_on["insert into posts_tags"] = mysql.connector.Error("link failure")
        with self.assertRaisesRegex(mysql.connector.Error, "link failure"):
            self.seed()
        self.assertEqual(before, self.db.snapshot())
        self.assertEqual(self.db.commits, 0)
        self.assertEqual(self.db.rollbacks, 1)
        self.assertEqual(self.db.cursors_closed, 1)
        self.db.raise_on.clear()
        self.assertEqual(self.seed()["inserted"], 30)

    def test_non_duplicate_integrity_error_and_commit_failure_roll_back(self):
        before = self.db.snapshot()
        self.db.raise_on["insert into tags"] = mysql.connector.IntegrityError("bad tag", errno=1452)
        with self.assertRaises(mysql.connector.IntegrityError):
            self.seed()
        self.assertEqual(before, self.db.snapshot())
        self.db.raise_on.clear()
        with patch.object(self.db, "commit", side_effect=mysql.connector.Error("commit failed")):
            with self.assertRaisesRegex(mysql.connector.Error, "commit failed"):
                self.seed()
        self.assertEqual(before, self.db.snapshot())

    def test_user_locks_precede_writes_and_duplicate_reads_see_current_data(self):
        self.seed()
        queries = self.db.executed
        users = [(sql, params) for sql, params in queries if "FROM users" in sql]
        self.assertEqual([p[0] for _, p in users], sorted(p["username"] for p in demo_content.AGENT_PROFILES))
        self.assertTrue(all(sql.endswith("FOR UPDATE") for sql, _ in users))
        first_write = next(i for i, (sql, _) in enumerate(queries) if sql.startswith("INSERT"))
        self.assertGreaterEqual(first_write, 10)
        self.assertTrue(all(sql.endswith("FOR UPDATE") for sql, _ in queries if "FROM posts WHERE" in sql))
        self.assertFalse(any(sql.startswith(("UPDATE", "DELETE", "REPLACE", "TRUNCATE")) for sql, _ in queries))

    def test_existing_exact_case_tags_are_reused_and_other_case_is_preserved(self):
        self.db.raw.executemany("INSERT INTO tags (name) VALUES (?)", [("python",), ("Python",)])
        self.db.raw.commit()
        self.seed()
        self.assertEqual(self.db.raw.execute(
            "SELECT name FROM tags WHERE lower(name)='python' ORDER BY name").fetchall(), [("Python",), ("python",)])


class SeedCliTests(OfflineTests):
    def run_cli(self, args, entry=manage.main, db=None, env=None):
        out, err = io.StringIO(), io.StringIO()
        settings = {"DB_HOST": "seed-db", "DB_NAME": "seed_test",
                    "DB_USER": "secret-user", "DB_PASSWORD": "secret-password"}
        with patch.object(manage, "connect", return_value=self.db if db is None else db) as connect, \
             patch.object(manage, "load_dotenv"), \
             patch.dict(manage.os.environ, settings if env is None else env, clear=True), \
             redirect_stdout(out), redirect_stderr(err):
            result = entry(args)
        self.connect = connect
        return result, out.getvalue(), err.getvalue()

    def test_command_prints_target_and_summary_and_uses_utc(self):
        code, out, err = self.run_cli(["seed-agent-content"])
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines()[0], "manage: MySQL test-store at seed-db, database seed_test")
        self.assertIn("inserted 30, skipped 0", out)
        self.assertNotIn("secret-user", out + err)
        self.assertNotIn("secret-password", out + err)
        self.connect.assert_called_once_with(time_zone="+00:00")
        self.assertTrue(self.db.closed)
        self.assertEqual(self.db.cursors_closed, 2)

    def test_dry_run_and_repeat_cli_summaries(self):
        code, out, _ = self.run_cli(["seed-agent-content", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("would insert 30, skipped 0; nothing changed", out)
        self.assertEqual(len(self.db.snapshot()["posts"]), 0)
        self.run_cli(["seed-agent-content"])
        code, out, _ = self.run_cli(["seed-agent-content"])
        self.assertEqual(code, 0)
        self.assertIn("inserted 0, skipped 30", out)

    def test_seed_script_delegates_arguments_including_sys_argv(self):
        code, out, _ = self.run_cli(["--dry-run"], entry=seed_data.main)
        self.assertEqual(code, 0)
        self.assertIn("would insert 30", out)
        with patch.object(sys, "argv", ["seed_data.py", "--dry-run"]):
            code, out, _ = self.run_cli(None, entry=seed_data.main)
        self.assertEqual(code, 0)
        self.assertIn("would insert 30", out)

    def test_missing_database_configuration_returns_usage_error(self):
        code, _, err = self.run_cli(["seed-agent-content"], env={})
        self.assertEqual(code, 2)
        self.assertIn("DB_NAME", err)
        self.connect.assert_not_called()

    def test_invalid_agent_and_sql_failure_report_errors_and_close(self):
        self.db.raw.execute("UPDATE users SET is_agent=0 WHERE username='rex_ai'")
        self.db.raw.commit()
        code, _, err = self.run_cli(["seed-agent-content"])
        self.assertEqual(code, 1)
        self.assertIn("rex_ai", err)
        self.assertTrue(self.db.closed)
        conn = FakeConn(raise_on={"select version()": mysql.connector.Error("unavailable")})
        code, _, err = self.run_cli(["seed-agent-content"], db=conn)
        self.assertEqual(code, 1)
        self.assertIn("FAILED: unavailable", err)
        self.assertTrue(conn.closed)

    def test_connection_failure_reports_without_cleanup_error(self):
        with patch.object(manage, "connect_utc", side_effect=mysql.connector.Error("refused")):
            code, _, err = self.run_cli(["seed-agent-content"])
        self.assertEqual(code, 1)
        self.assertIn("refused", err)


if __name__ == "__main__":
    unittest.main()
