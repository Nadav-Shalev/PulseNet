"""Moderation on the write endpoints (Flask test client, mocked DB seam, scripted LLM).

POST /api/articles and POST /api/articles/<id>/comments check the visible text with
one moderation call each, after the request is validated and before anything is
stored: blocked content is a 422 with its category. With the LLM off or failing, the
word list decides. Also covers how app.py builds the LLM service from the environment.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import app  # noqa: E402
from llm import LLMService, LLMTimeout  # noqa: E402
from support import FakeConn, client, patch_db, patch_llm  # noqa: E402

CLEAN = '{"toxic": false, "category": "none"}'
HARASSMENT = '{"toxic": true, "category": "harassment"}'
INSERT_POST = "insert into posts"
INSERT_COMMENT = "insert into comments"


def _session_user(**over):
    row = {
        "id": 42, "name": "Ada", "username": "ada", "email": "ada@example.com",
        "bio": "hi", "avatar": "a.svg", "profile_image": "p.svg", "role": "user",
    }
    row.update(over)
    return row


def _authed_client():
    c = client()
    c.set_cookie("session_id", "valid-sid")
    return c


class PostModerationTests(unittest.TestCase):
    def _publish(self, article, fetchone=()):
        conn = FakeConn(fetchone=[_session_user(), *fetchone], lastrowid=7)
        with patch_db(conn):
            resp = _authed_client().post("/api/articles", json={"article": article})
        return resp, conn

    def test_a_post_is_one_check_of_its_visible_title_tags_and_body(self):
        with patch_llm(CLEAN) as llm:
            resp, conn = self._publish({"title": "Async tips", "tags": ["python", "async"],
                                        "body_html": "<p>Use <strong>await</strong> with care</p>"},
                                       fetchone=[(3,), (4,)])

        self.assertEqual(resp.status_code, 201)
        self.assertTrue(conn.ran(INSERT_POST))
        self.assertEqual(len(llm.provider.calls), 1)
        prompt = llm.provider.calls[0][0]
        self.assertEqual(prompt, "<post_title>\nAsync tips\n</post_title>\n"
                                 "<post_tags>\npython, async\n</post_tags>\n"
                                 "<post_body>\nUse await with care\n</post_body>")
        self.assertEqual([(r.purpose, r.user_id) for r in llm.store.records], [("moderation", 42)])

    def test_a_markdown_post_is_checked_on_its_visible_text_too(self):
        with patch_llm(CLEAN) as llm:
            resp, _conn = self._publish({"title": "MD", "body_markdown": "Some **bold** [link](https://x.dev)"})

        self.assertEqual(resp.status_code, 201)
        self.assertIn("<post_body>\nSome bold link\n</post_body>", llm.provider.calls[0][0])

    def test_a_blocked_post_is_a_422_and_nothing_is_stored(self):
        with patch_llm(HARASSMENT):
            resp, conn = self._publish({"title": "Hey", "body_html": "<p>Rude words</p>", "tags": ["x"]})

        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json(), {
            "error": "This post looks insulting or harassing, so it was not published. Please rephrase it.",
            "category": "harassment",
        })
        self.assertFalse(conn.ran(INSERT_POST))
        self.assertFalse(conn.ran("insert ignore into tags"))

    def test_each_category_has_its_own_wording(self):
        for category, words in (("hate", "looks hateful"), ("threat", "looks threatening")):
            with self.subTest(category=category):
                with patch_llm(f'{{"toxic": true, "category": "{category}"}}'):
                    resp, _conn = self._publish({"title": "T", "body_html": "<p>x</p>"})
                self.assertEqual(resp.status_code, 422)
                self.assertIn(words, resp.get_json()["error"])

    def test_with_the_llm_off_the_word_list_blocks(self):
        resp, conn = self._publish({"title": "Advice", "body_html": "<p>Just kill yourself</p>"})

        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["category"], "threat")
        self.assertFalse(conn.ran(INSERT_POST))

    def test_a_title_or_tag_alone_can_block_a_post(self):
        for article in ({"title": "fuck you", "body_html": "<p>fine</p>"},
                        {"title": "fine", "body_html": "<p>fine</p>", "tags": ["you idiot"]}):
            with self.subTest(article=article):
                resp, _conn = self._publish(article)
                self.assertEqual(resp.status_code, 422)

    def test_a_failed_llm_call_falls_back_to_the_word_list(self):
        with patch_llm(LLMTimeout("slow"), LLMTimeout("slow")):
            blocked, _conn = self._publish({"title": "Hi", "body_html": "<p>you moron</p>"})
            published, _conn = self._publish({"title": "Hi", "body_html": "<p>Nice tool</p>"})

        self.assertEqual(blocked.status_code, 422)
        self.assertEqual(published.status_code, 201)

    def test_an_invalid_post_is_a_400_without_an_llm_call(self):
        with patch_llm(CLEAN) as llm:
            resp, _conn = self._publish({"title": "", "body_html": "<p>x</p>"})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(llm.provider.calls, [])


class CommentModerationTests(unittest.TestCase):
    def _comment(self, body, fetchone=(), post_id=7):
        # The session is read on a connection of its own, so ``conn`` (the comment's)
        # is closed only if create_comment closes it.
        session = FakeConn(fetchone=[_session_user()])
        conn = FakeConn(fetchone=list(fetchone), lastrowid=9)
        with patch_db(conn), patch.object(app, "get_db_connection", side_effect=[session, conn]):
            resp = _authed_client().post(f"/api/articles/{post_id}/comments", json=body)
        return resp, conn

    def test_a_comment_is_one_check_of_its_visible_text(self):
        stored = {"id": 9, "post_id": 7, "parent_id": None, "body_html": "<p>x</p>", "created_at": None,
                  "username": "ada", "name": "Ada", "avatar": None, "profile_image": None}
        with patch_llm(CLEAN) as llm:
            resp, conn = self._comment({"body_html": "<p>Nice <em>post</em></p>"},
                                       fetchone=[{"id": 7}, stored, {"comment_count": 1}])

        self.assertEqual(resp.status_code, 201)
        self.assertTrue(conn.ran(INSERT_COMMENT))
        self.assertEqual(llm.provider.calls, [("<comment>\nNice post\n</comment>", app.moderation.SYSTEM)])
        self.assertEqual([(r.purpose, r.user_id) for r in llm.store.records], [("moderation", 42)])

    def test_a_blocked_comment_is_a_422_and_nothing_is_stored(self):
        with patch_llm(HARASSMENT):
            resp, conn = self._comment({"body_html": "<p>rude</p>"}, fetchone=[{"id": 7}])

        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json(), {
            "error": "This comment looks insulting or harassing, so it was not published. Please rephrase it.",
            "category": "harassment",
        })
        self.assertFalse(conn.ran(INSERT_COMMENT))
        self.assertTrue(conn.closed)

    def test_a_reply_is_checked_too(self):
        parent = {"post_id": 7, "parent_id": None}
        resp, conn = self._comment({"body_html": "<p>stfu</p>", "parent_id": 3}, fetchone=[{"id": 7}, parent])

        self.assertEqual(resp.status_code, 422)
        self.assertFalse(conn.ran(INSERT_COMMENT))

    def test_a_missing_post_or_parent_is_answered_before_any_llm_call(self):
        with patch_llm(CLEAN) as llm:
            missing, _conn = self._comment({"body_html": "<p>hi</p>"}, fetchone=[None])
            bad_parent, _conn = self._comment({"body_html": "<p>hi</p>", "parent_id": 3},
                                              fetchone=[{"id": 7}, None])

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(bad_parent.status_code, 400)
        self.assertEqual(llm.provider.calls, [])

    def test_an_empty_comment_is_a_400_without_an_llm_call(self):
        with patch_llm(CLEAN) as llm:
            resp, _conn = self._comment({"body_html": "<p> </p>"})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(llm.provider.calls, [])


class LlmServiceWiringTests(unittest.TestCase):
    def test_unset_provider_means_off_with_an_info_line(self):
        with self.assertLogs(app.app.logger, level="INFO") as logs:
            service = app._build_llm_service({})

        self.assertIsNone(service)
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(logs.records[0].levelname, "INFO")
        self.assertIn("LLM off: LLM_PROVIDER is not set", logs.output[0])

    def test_a_broken_setting_is_off_with_a_warning_that_names_no_value(self):
        env = {"LLM_PROVIDER": "openai_compat", "LLM_BASE_URL": "https://example.test/v1",
               "LLM_MODEL": "m", "LLM_API_KEY": ""}
        with self.assertLogs(app.app.logger, level="INFO") as logs:
            service = app._build_llm_service(env)

        self.assertIsNone(service)
        self.assertEqual(logs.records[0].levelname, "WARNING")
        self.assertIn("LLM_API_KEY is not set", logs.output[0])
        self.assertNotIn("example.test", logs.output[0])

    def test_a_valid_setting_builds_a_service_that_connects_through_get_db_connection(self):
        service = app._build_llm_service({"LLM_PROVIDER": "fake"})

        self.assertIsInstance(service, LLMService)
        self.assertEqual(service.provider.name, "fake")
        # The connection factory is looked up at each call, so a patched one is used.
        sentinel = object()
        with patch.object(app, "get_db_connection", return_value=sentinel):
            self.assertIs(service.store._connect(), sentinel)

    def test_the_suite_runs_with_the_llm_off(self):
        self.assertIsNone(app.llm_service)
        self.assertIsNone(app.moderator.service)


if __name__ == "__main__":
    unittest.main()
