"""Stateful in-memory SQL store for seed tests; never connects to MySQL.

SQLite enforces rows, unique keys, foreign keys and rollback. The adapter only
translates MySQL parameter/locking syntax; tests separately assert locking reads.
It does not claim to emulate InnoDB's concurrency implementation.
"""
import sqlite3

import mysql.connector

from demo_content import AGENT_PROFILES


class SeedCursor:
    def __init__(self, conn):
        self.conn = conn
        self.raw = conn.raw.cursor()

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        normalized = " ".join(sql.lower().split())
        for needle, error in self.conn.raise_on.items():
            if needle in normalized:
                raise error
        if normalized == "select version()":
            return self.raw.execute("SELECT 'test-store'")
        adapted = sql.replace("%s", "?").replace(" FOR UPDATE", "")
        try:
            self.raw.execute(adapted, params or ())
        except sqlite3.IntegrityError as exc:
            errno = 1062 if "UNIQUE constraint failed" in str(exc) else 1452
            raise mysql.connector.IntegrityError(str(exc), errno=errno) from exc

    def fetchone(self):
        return self.raw.fetchone()

    @property
    def lastrowid(self):
        return self.raw.lastrowid

    def close(self):
        self.raw.close()
        self.conn.cursors_closed += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class SeedDatabase:
    def __init__(self):
        self.raw = sqlite3.connect(":memory:")
        self.raw.execute("PRAGMA foreign_keys = ON")
        self.raw.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE,
                                is_agent INTEGER, is_banned INTEGER DEFAULT 0);
            CREATE TABLE posts (
                id INTEGER PRIMARY KEY, author_id INTEGER NOT NULL REFERENCES users(id),
                title TEXT NOT NULL, body TEXT NOT NULL, body_html TEXT,
                description TEXT, cover_image TEXT, devto_id INTEGER UNIQUE, devto_url TEXT,
                readable_publish_date TEXT, created_at TIMESTAMP);
            CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT COLLATE BINARY UNIQUE);
            CREATE TABLE posts_tags (
                post_id INTEGER REFERENCES posts(id), tag_id INTEGER REFERENCES tags(id),
                PRIMARY KEY (post_id, tag_id));
        """)
        self.raw.executemany(
            "INSERT INTO users (id, username, is_agent) VALUES (?, ?, 1)",
            [(100 + i * 7, p["username"]) for i, p in enumerate(AGENT_PROFILES)],
        )
        self.raw.commit()
        self.executed = []
        self.raise_on = {}
        self.commits = self.rollbacks = self.cursors_closed = 0
        self.closed = False

    def cursor(self):
        return SeedCursor(self)

    def commit(self):
        self.raw.commit()
        self.commits += 1

    def rollback(self):
        self.raw.rollback()
        self.rollbacks += 1

    def close(self):
        # Keep the in-memory state inspectable after the CLI closes its connection.
        self.closed = True

    def snapshot(self):
        return {
            table: self.raw.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
            for table in ("users", "posts", "tags", "posts_tags")
        }
