"""User read/profile API tests (Flask test client + mocked DB seam).

Covers PATCH /api/me, user search, the user list, profiles with their viewer flags
(``is_self`` / ``is_following``), follower/following lists, tag autocomplete and
the /api/test-db probe. Of these, only user search falls back to mock_data when
MySQL is unreachable; the others answer 503 (or 500 for the probe).
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from support import FakeConn, client, db_down, patch_db  # noqa: E402


def _session_user(**over):
    """Row shape returned by require_session's JOIN (no password_hash)."""
    row = {
        "id": 42, "name": "Ada", "username": "ada", "email": "ada@example.com",
        "bio": "hi", "avatar": "a.svg", "profile_image": "p.svg",
    }
    row.update(over)
    return row


def _profile_row(**over):
    """Row shape returned by the GET /api/users/<username> SELECT."""
    row = {
        "id": 7, "name": "Bob", "username": "bob",
        "bio": "backend", "avatar": None, "profile_image": "b.svg",
        "is_agent": 0, "personality": None,
        "post_count": 3, "followers_count": 2, "following_count": 1,
    }
    row.update(over)
    return row


def _authed_client(sid="valid-sid"):
    c = client()
    c.set_cookie("session_id", sid)
    return c


class UpdateMeTests(unittest.TestCase):
    def _patch(self, body, db_available=True):
        conn = FakeConn(fetchone=[_session_user()])
        with patch_db(conn, db_available=db_available):
            resp = _authed_client().patch("/api/me", json=body)
        return resp, conn

    def test_requires_session(self):
        resp = client().patch("/api/me", json={"name": "Eve"})

        self.assertEqual(resp.status_code, 401)

    def test_db_unavailable_returns_503(self):
        resp, conn = self._patch({"name": "Ada L."}, db_available=False)

        self.assertEqual(resp.status_code, 503)
        self.assertFalse(conn.ran("update users"))

    def test_updates_editable_fields_and_returns_merged_user(self):
        resp, conn = self._patch({"name": " Ada L. ", "bio": " math ", "profile_image": "new.png"})

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["name"], "Ada L.")
        self.assertEqual(body["bio"], "math")
        self.assertEqual(body["profile_image"], "new.png")
        self.assertEqual(body["username"], "ada")          # untouched fields come from the session
        self.assertNotIn("password_hash", body)
        self.assertEqual(
            conn.params_for("update users set name = %s, bio = %s, profile_image = %s where id = %s"),
            ["Ada L.", "math", "new.png", 42],
        )
        self.assertEqual(conn.commits, 2)                  # session purge + the update

    def test_only_sent_fields_are_updated(self):
        _, conn = self._patch({"bio": "new bio"})

        self.assertEqual(conn.params_for("update users set bio = %s where id = %s"), ["new bio", 42])

    def test_target_user_comes_from_session_not_body(self):
        _, conn = self._patch({"id": 99, "bio": "x"})

        self.assertEqual(conn.params_for("update users")[-1], 42)

    def test_non_editable_fields_alone_are_rejected(self):
        resp, conn = self._patch({"username": "root", "email": "root@example.com", "password_hash": "x"})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "No updatable fields provided")
        self.assertFalse(conn.ran("update users"))

    def test_blank_name_is_rejected(self):
        resp, conn = self._patch({"name": "   "})

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(conn.ran("update users"))

    def test_name_over_100_chars_is_rejected(self):
        resp, _ = self._patch({"name": "a" * 101})

        self.assertEqual(resp.status_code, 400)
        self.assertIn("100 characters", resp.get_json()["error"])

    def test_image_url_over_500_chars_is_rejected(self):
        resp, conn = self._patch({"profile_image": "https://x/" + "a" * 500})

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(conn.ran("update users"))

    def test_empty_image_clears_it_to_null(self):
        resp, conn = self._patch({"profile_image": "  "})

        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.get_json()["profile_image"])
        self.assertEqual(conn.params_for("update users set profile_image"), [None, 42])

    def test_null_bio_is_stored_as_empty_string(self):
        _, conn = self._patch({"bio": None})

        self.assertEqual(conn.params_for("update users set bio"), ["", 42])


class SearchUsersTests(unittest.TestCase):
    def test_missing_query_returns_400(self):
        conn = FakeConn()
        with patch_db(conn):
            resp = client().get("/api/users/search")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(conn.executed, [])

    def test_matches_name_or_username_with_paging(self):
        rows = [{"id": 42, "name": "Ada", "username": "ada", "avatar": None}]
        conn = FakeConn(fetchall=[rows])
        with patch_db(conn):
            resp = client().get("/api/users/search?q=ad&limit=5&offset=10")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), rows)
        self.assertEqual(
            conn.params_for("where name like %s or username like %s"),
            ("%ad%", "%ad%", 5, 10),
        )

    def test_default_page_is_first_ten(self):
        conn = FakeConn()
        with patch_db(conn):
            client().get("/api/users/search?q=ad")

        self.assertEqual(conn.params_for("from users")[-2:], (10, 0))

    def test_db_down_searches_mock_users(self):
        with db_down():
            resp = client().get("/api/users/search?q=LEO")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual([u["username"] for u in resp.get_json()], ["leo_ai"])

    def test_db_down_mock_search_is_paged(self):
        # Every mock agent username includes "_ai".
        with db_down():
            resp = client().get("/api/users/search?q=_ai&limit=1&offset=1")

        self.assertEqual([u["username"] for u in resp.get_json()], ["leo_ai"])


class ListUsersTests(unittest.TestCase):
    def test_lists_users_with_post_counts(self):
        rows = [{"id": 7, "username": "bob", "post_count": 3},
                {"id": 42, "username": "ada", "post_count": 0}]
        conn = FakeConn(fetchall=[rows])
        with patch_db(conn):
            resp = client().get("/api/users")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), rows)
        sql, params = conn.find("count(p.id) as post_count")[0]
        self.assertNotIn("where", " ".join(sql.split()).lower())
        self.assertEqual(params, [10, 0])

    def test_query_filters_on_username_and_name(self):
        conn = FakeConn()
        with patch_db(conn):
            client().get("/api/users?q=%20bo%20&limit=20&offset=40")

        self.assertEqual(
            conn.params_for("where (u.username like %s or u.name like %s)"),
            ["%bo%", "%bo%", 20, 40],                # q is trimmed before the LIKE
        )

    def test_db_down_returns_503(self):
        with db_down():
            resp = client().get("/api/users")

        self.assertEqual(resp.status_code, 503)


class ProfileTests(unittest.TestCase):
    def test_anonymous_viewer_gets_profile_with_counts(self):
        conn = FakeConn(fetchone=[_profile_row()])
        with patch_db(conn):
            resp = client().get("/api/users/bob")

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["username"], "bob")
        self.assertEqual((body["post_count"], body["followers_count"], body["following_count"]),
                         (3, 2, 1))
        self.assertFalse(body["is_self"])
        self.assertFalse(body["is_following"])
        self.assertEqual(conn.params_for("where u.username = %s"), ("bob",))
        self.assertFalse(conn.ran("select 1 from follows"))

    def test_unknown_username_returns_404(self):
        conn = FakeConn(fetchone=[None])
        with patch_db(conn):
            resp = client().get("/api/users/ghost")

        self.assertEqual(resp.status_code, 404)

    def test_own_profile_is_self_and_skips_follow_lookup(self):
        conn = FakeConn(fetchone=[_profile_row(id=42, username="ada"),
                                  {"id": 42, "username": "ada"}])
        with patch_db(conn):
            resp = _authed_client().get("/api/users/ada")

        body = resp.get_json()
        self.assertTrue(body["is_self"])
        self.assertFalse(body["is_following"])
        self.assertFalse(conn.ran("select 1 from follows"))

    def test_viewer_who_follows_sees_is_following(self):
        conn = FakeConn(fetchone=[_profile_row(), {"id": 42, "username": "ada"}, (1,)])
        with patch_db(conn):
            resp = _authed_client().get("/api/users/bob")

        body = resp.get_json()
        self.assertFalse(body["is_self"])
        self.assertTrue(body["is_following"])
        # (follower_id = viewer, following_id = profile owner)
        self.assertEqual(conn.params_for("select 1 from follows"), (42, 7))

    def test_viewer_who_does_not_follow(self):
        conn = FakeConn(fetchone=[_profile_row(), {"id": 42, "username": "ada"}, None])
        with patch_db(conn):
            resp = _authed_client().get("/api/users/bob")

        self.assertFalse(resp.get_json()["is_following"])

    def test_stale_cookie_is_treated_as_anonymous(self):
        conn = FakeConn(fetchone=[_profile_row(), None])     # session lookup finds nothing
        with patch_db(conn):
            resp = _authed_client("stale-sid").get("/api/users/bob")

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.get_json()["is_self"])
        self.assertFalse(conn.ran("select 1 from follows"))

    def test_db_down_returns_503(self):
        with db_down():
            resp = client().get("/api/users/bob")

        self.assertEqual(resp.status_code, 503)

    def test_an_agent_says_so_and_shows_its_persona(self):
        persona = "You are Priya, a senior Python developer who cares most about tests."
        conn = FakeConn(fetchone=[_profile_row(username="priya_ai", is_agent=1, personality=persona)])
        with patch_db(conn):
            body = client().get("/api/users/priya_ai").get_json()

        self.assertIs(body["is_agent"], True)
        self.assertEqual(body["personality"], persona)
        self.assertTrue(conn.ran("u.is_agent, u.personality"))
        self.assertNotIn("email", body)

    def test_a_person_is_not_an_agent_and_never_shows_a_personality(self):
        # Even if the column were filled for a person (by hand, say), it stays hidden.
        conn = FakeConn(fetchone=[_profile_row(is_agent=0, personality="private notes")])
        with patch_db(conn):
            body = client().get("/api/users/bob").get_json()

        self.assertIs(body["is_agent"], False)
        self.assertIsNone(body["personality"])


class FollowListTests(unittest.TestCase):
    def _get(self, url, target=None, rows=()):
        conn = FakeConn(fetchone=[target], fetchall=[list(rows)])
        with patch_db(conn):
            resp = client().get(url)
        return resp, conn

    def test_followers_are_users_whose_follower_id_points_at_target(self):
        rows = [{"id": 42, "username": "ada"}]
        resp, conn = self._get("/api/users/bob/followers", target={"id": 7}, rows=rows)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), rows)
        self.assertEqual(conn.params_for("select id from users where username"), ("bob",))
        self.assertTrue(conn.ran("join users u on u.id = f.follower_id"))
        self.assertEqual(conn.params_for("where f.following_id = %s"), (7, 50, 0))

    def test_following_are_users_whose_following_id_points_away_from_target(self):
        _, conn = self._get("/api/users/bob/following", target={"id": 7})

        self.assertTrue(conn.ran("join users u on u.id = f.following_id"))
        self.assertEqual(conn.params_for("where f.follower_id = %s"), (7, 50, 0))

    def test_newest_follows_first_with_paging(self):
        _, conn = self._get("/api/users/bob/followers?limit=5&offset=15", target={"id": 7})

        self.assertTrue(conn.ran("order by f.created_at desc"))
        self.assertEqual(conn.params_for("from follows f"), (7, 5, 15))

    def test_unknown_user_returns_404_without_listing(self):
        resp, conn = self._get("/api/users/ghost/following", target=None)

        self.assertEqual(resp.status_code, 404)
        self.assertFalse(conn.ran("from follows f"))

    def test_db_down_returns_503(self):
        with db_down():
            resp = client().get("/api/users/bob/followers")

        self.assertEqual(resp.status_code, 503)


class TagSearchTests(unittest.TestCase):
    def test_blank_query_returns_empty_list_without_db(self):
        conn = FakeConn()
        with patch_db(conn):
            resp = client().get("/api/tags/search?q=%20%20")

        self.assertEqual(resp.get_json(), [])
        self.assertEqual(conn.executed, [])

    def test_case_insensitive_prefix_match(self):
        rows = [{"name": "React"}, {"name": "react"}]
        conn = FakeConn(fetchall=[rows])
        with patch_db(conn):
            resp = client().get("/api/tags/search?q=Rea")

        self.assertEqual(resp.get_json(), rows)
        self.assertTrue(conn.ran("where lower(name) like lower(%s)"))
        self.assertEqual(conn.params_for("from tags"), ("Rea%", 20))    # prefix, not substring

    def test_limit_is_passed_through(self):
        conn = FakeConn()
        with patch_db(conn):
            client().get("/api/tags/search?q=py&limit=5")

        self.assertEqual(conn.params_for("from tags"), ("py%", 5))

    def test_db_down_returns_503(self):
        with db_down():
            resp = client().get("/api/tags/search?q=py")

        self.assertEqual(resp.status_code, 503)


class TestDbProbeTests(unittest.TestCase):
    def test_reachable_db_reports_ok(self):
        conn = FakeConn(fetchone=[(1,)])
        with patch_db(conn):
            resp = client().get("/api/test-db")

        self.assertEqual(resp.get_json(), {"status": "ok"})
        self.assertTrue(conn.ran("select 1"))
        self.assertTrue(conn.closed)

    def test_unreachable_db_reports_error(self):
        with db_down():
            resp = client().get("/api/test-db")

        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.get_json()["status"], "error")


if __name__ == "__main__":
    unittest.main()
