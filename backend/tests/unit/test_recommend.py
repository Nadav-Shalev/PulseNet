"""recommend.py: the trending tags and the who-to-follow merge, on a FakeConn
cursor (the SQL is asserted here; tests/integration covers the endpoints)."""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import recommend  # noqa: E402
from support import FakeConn  # noqa: E402

EXCLUDES = ("u.id <> %s AND NOT EXISTS (SELECT 1 FROM follows mine "
            "WHERE mine.follower_id = %s AND mine.following_id = u.id)")


def _user(uid, **extra):
    row = {"id": uid, "name": f"User {uid}", "username": f"user{uid}", "avatar": None,
           "profile_image": f"{uid}.svg", "is_agent": 0}
    row.update(extra)
    return row


def _flat(sql):
    return " ".join(sql.split())


class TrendingTagsTests(unittest.TestCase):
    def test_the_tags_on_the_most_posts_of_the_window(self):
        rows = [{"name": "python", "post_count": 3}, {"name": "rust", "post_count": 1}]
        conn = FakeConn(fetchall=[rows])

        self.assertEqual(recommend.trending_tags(conn.cursor(dictionary=True), 24, 10), rows)
        sql, params = conn.find("from posts_tags pt")[0]
        self.assertIn("WHERE p.created_at >= NOW() - INTERVAL %s HOUR", _flat(sql))
        self.assertIn("COUNT(*) AS post_count", sql)
        self.assertIn("ORDER BY post_count DESC, t.name LIMIT %s", _flat(sql))
        self.assertEqual(params, (24, 10))


class SuggestedUsersTests(unittest.TestCase):
    def suggest(self, fetchall, viewer_id=42, limit=5):
        self.conn = FakeConn(fetchall=fetchall)
        return recommend.suggested_users(self.conn.cursor(dictionary=True), viewer_id, limit)

    def test_friends_of_friends_first_then_shared_tags_then_popular(self):
        users = self.suggest([
            [_user(7, mutuals=2)],
            [_user(8, shared=2, tag_names="python\trust")],
            [_user(9, followers=5, is_agent=1)],
        ])

        self.assertEqual([u["id"] for u in users], [7, 8, 9])
        self.assertEqual([u["reason"] for u in users], [
            {"kind": "friends", "count": 2},
            {"kind": "tags", "tags": ["python", "rust"]},
            {"kind": "popular", "count": 5},
        ])
        self.assertEqual(users[2]["is_agent"], True)
        self.assertEqual(users[0]["is_agent"], False)
        self.assertEqual(set(users[0]), {"id", "name", "username", "avatar", "profile_image", "is_agent", "reason"})

    def test_someone_found_twice_is_listed_once_with_the_first_reason(self):
        users = self.suggest([
            [_user(7, mutuals=1)],
            [_user(7, shared=1, tag_names="go"), _user(8, shared=1, tag_names="go")],
            [_user(8, followers=4), _user(9, followers=2)],
        ])

        self.assertEqual([(u["id"], u["reason"]["kind"]) for u in users],
                         [(7, "friends"), (8, "tags"), (9, "popular")])
        # Each later read asks for enough rows to make up for the repeats.
        self.assertEqual(self.conn.params_for("from posts_tags theirs")[-1], 6)
        self.assertEqual(self.conn.params_for("from users u join follows f")[-1], 7)

    def test_a_full_list_skips_the_later_reads(self):
        users = self.suggest([[_user(7, mutuals=1), _user(8, mutuals=1)]], limit=2)

        self.assertEqual(len(users), 2)
        self.assertEqual(len(self.conn.executed), 1)

    def test_the_limit_cuts_a_longer_read(self):
        users = self.suggest([[_user(i, mutuals=1) for i in range(1, 9)]], limit=3)

        self.assertEqual([u["id"] for u in users], [1, 2, 3])

    def test_a_guest_gets_the_popular_ones_only(self):
        users = self.suggest([[_user(9, followers=2)]], viewer_id=None)

        self.assertEqual([u["reason"] for u in users], [{"kind": "popular", "count": 2}])
        self.assertEqual(len(self.conn.executed), 1)
        sql, params = self.conn.executed[0]
        self.assertNotIn("mine.follower_id", sql)
        self.assertEqual(params, (5,))

    def test_friends_of_friends_sql(self):
        self.suggest([[], [], []])

        sql, params = self.conn.find("from follows f1")[0]
        flat = _flat(sql)
        self.assertIn("COUNT(DISTINCT f1.following_id) AS mutuals", flat)
        self.assertIn("JOIN follows f2 ON f2.follower_id = f1.following_id JOIN users u ON u.id = f2.following_id",
                      flat)
        self.assertIn("WHERE f1.follower_id = %s AND NOT u.is_banned AND " + EXCLUDES, flat)
        self.assertIn("ORDER BY mutuals DESC, u.id LIMIT %s", flat)
        self.assertEqual(params, (42, 42, 42, 5))
        self.assertNotIn("email", sql.lower())

    def test_shared_tags_sql_takes_the_tags_the_viewer_wrote_or_liked(self):
        self.suggest([[], [], []])

        sql, params = self.conn.find("from posts_tags theirs")[0]
        flat = _flat(sql)
        self.assertIn("WHERE mp.author_id = %s UNION SELECT pt.tag_id FROM posts_tags pt "
                      "JOIN likes l ON l.post_id = pt.post_id WHERE l.user_id = %s", flat)
        self.assertIn("COUNT(DISTINCT theirs.tag_id) AS shared", flat)
        self.assertIn("GROUP_CONCAT(DISTINCT t.name ORDER BY t.name SEPARATOR '\t') AS tag_names", sql)
        self.assertIn("AND NOT u.is_banned AND " + EXCLUDES, flat)
        self.assertEqual(params, (42, 42, 42, 42, 5))
        self.assertNotIn("email", sql.lower())

    def test_popular_means_followed_by_someone(self):
        self.suggest([[], [], []])

        sql, params = self.conn.find("from users u join follows f")[0]
        flat = _flat(sql)
        # An inner join: a user nobody follows is never "popular".
        self.assertIn("FROM users u JOIN follows f ON f.following_id = u.id", flat)
        self.assertIn("WHERE NOT u.is_banned AND " + EXCLUDES, flat)
        self.assertIn("ORDER BY followers DESC, u.id LIMIT %s", flat)
        self.assertEqual(params, (42, 42, 5))

    def test_the_reason_names_at_most_three_tags(self):
        users = self.suggest([[], [_user(8, shared=5, tag_names="a\tb\tc\td\te")], []])

        self.assertEqual(users[0]["reason"]["tags"], ["a", "b", "c"])

    def test_no_tag_names_is_an_empty_list(self):
        users = self.suggest([[], [_user(8, shared=0, tag_names=None)], []])

        self.assertEqual(users[0]["reason"]["tags"], [])

    def test_nobody_to_suggest(self):
        self.assertEqual(self.suggest([[], [], []]), [])
        self.assertEqual(len(self.conn.executed), 3)


if __name__ == "__main__":
    unittest.main()
