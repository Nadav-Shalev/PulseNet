"""AI assistance API tests (Flask test client, mocked DB seam, scripted LLM).

POST /api/ai/correct          correct a draft: plain text, or the editor's HTML
POST /api/ai/suggest-post     draft a post body from its title and tags
POST /api/ai/suggest-comment  propose a comment on a post, or a reply to a comment

Every endpoint needs a session, is limited per user per day (AI_USER_DAILY_LIMIT,
counting only the AI purposes), turns each LLM failure into a friendly 429 or 503,
and sanitizes any HTML the model returns. Nothing is stored.
"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import app  # noqa: E402
from llm import (LLMError, LLMRateLimited, LLMTimeout, MemoryUsageStore,  # noqa: E402
                 UsageRecord)
from support import FakeConn, client, patch_db, patch_llm  # noqa: E402

ROUTES = ("/api/ai/correct", "/api/ai/suggest-post", "/api/ai/suggest-comment")
POST_ROW = {"title": "Async tips", "body": "plain body", "body_html": "<p>Use <b>await</b> with care</p>"}


def _session_user(**over):
    row = {
        "id": 42, "name": "Ada", "username": "ada", "email": "ada@example.com",
        "bio": "hi", "avatar": "a.svg", "profile_image": "p.svg", "role": "user",
    }
    row.update(over)
    return row


def _call(route, body, fetchone=(), conn=None):
    """POST ``body`` to ``route`` as the session user 42; returns (response, conn).

    require_session reads the user on a connection of its own, so ``conn`` (the
    request's, seeded with ``fetchone``) is closed only if the endpoint closes it."""
    session = FakeConn(fetchone=[_session_user()])
    conn = conn or FakeConn(fetchone=list(fetchone))
    with patch_db(conn), patch.object(app, "get_db_connection", side_effect=[session, conn]):
        c = client()
        c.set_cookie("session_id", "valid-sid")
        resp = c.post(route, json=body)
    return resp, conn


def _used(*purposes, user_id=42, status="ok"):
    """A usage store holding one call today per purpose, for ``user_id``."""
    store = MemoryUsageStore()
    today = datetime.now(timezone.utc).date()
    for purpose in purposes:
        store.record(UsageRecord(today, "scripted", "m", purpose, user_id, status, 5, 5, 5))
    return store


class AuthAndOffTests(unittest.TestCase):
    def test_every_route_needs_a_session(self):
        for route in ROUTES:
            with self.subTest(route=route), patch_llm("never sent") as llm:
                conn = FakeConn()
                with patch_db(conn):
                    resp = client().post(route, json={"text": "x", "title": "x", "post_id": 7})
                self.assertEqual(resp.status_code, 401)
                self.assertEqual(llm.provider.calls, [])

    def test_with_the_llm_off_every_route_says_so(self):
        bodies = {
            "/api/ai/correct": ({"text": "teh"}, ()),
            "/api/ai/suggest-post": ({"title": "Hi"}, ()),
            "/api/ai/suggest-comment": ({"post_id": 7}, (POST_ROW,)),
        }
        for route, (body, fetchone) in bodies.items():
            with self.subTest(route=route):
                resp, _conn = _call(route, body, fetchone)
                self.assertEqual(resp.status_code, 503)
                self.assertEqual(resp.get_json(), {"error": "AI assistance is turned off on this server."})


class CorrectTests(unittest.TestCase):
    def test_plain_text_is_corrected_for_the_session_user(self):
        with patch_llm("The text is fine.") as llm:
            resp, _conn = _call("/api/ai/correct", {"text": "teh text is fien", "user_id": 99})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"text": "The text is fine."})
        prompt, system = llm.provider.calls[0]
        self.assertEqual(prompt, "<draft>\nteh text is fien\n</draft>")
        self.assertIn("Reply with only the corrected text", system)
        self.assertEqual([(r.purpose, r.user_id) for r in llm.store.records], [("ai_correct", 42)])

    def test_html_is_sanitized_on_the_way_to_the_model_and_back(self):
        reply = '```html\n<p>The <strong>bold</strong> text</p><img src=x onerror="alert(1)"><script>x()</script>\n```'
        with patch_llm(reply) as llm:
            resp, _conn = _call("/api/ai/correct", {"text": '<p>teh <strong>bold</strong> text</p>'
                                                            '<script>steal()</script>', "format": "html"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"text": "<p>The <strong>bold</strong> text</p>x()"})
        prompt = llm.provider.calls[0][0]
        self.assertEqual(prompt, "<draft>\n<p>teh <strong>bold</strong> text</p>steal()\n</draft>")

    def test_an_echoed_draft_block_is_removed(self):
        with patch_llm("<draft>\nFixed\n</draft>"):
            resp, _conn = _call("/api/ai/correct", {"text": "fixd"})

        self.assertEqual(resp.get_json(), {"text": "Fixed"})

    def test_bad_input_is_a_400_without_an_llm_call(self):
        cases = {
            "text not a string": {"text": 123},
            "unknown format": {"text": "x", "format": "markdown"},
            "format not a string": {"text": "x", "format": ["html"]},
            "blank text": {"text": "   "},
            "html with no text": {"text": "<p> </p><script></script>", "format": "html"},
            "too long": {"text": "a" * (app.ai_assist.MAX_INPUT_CHARS + 1)},
            "not an object": ["text"],
        }
        for name, body in cases.items():
            with self.subTest(case=name), patch_llm("never sent") as llm:
                resp, _conn = _call("/api/ai/correct", body)
                self.assertEqual(resp.status_code, 400, resp.get_json())
                self.assertEqual(llm.provider.calls, [])

    def test_the_longest_draft_passes(self):
        with patch_llm("ok") as llm:
            resp, _conn = _call("/api/ai/correct", {"text": "a" * app.ai_assist.MAX_INPUT_CHARS})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(llm.provider.calls), 1)

    def test_a_reply_with_nothing_left_is_a_503(self):
        for reply, fmt in (("```\n```", "text"), ("<script></script>", "html")):
            with self.subTest(reply=reply), patch_llm(reply):
                resp, _conn = _call("/api/ai/correct", {"text": "<p>teh</p>", "format": fmt})
                self.assertEqual(resp.status_code, 503)
                self.assertIn("unavailable right now", resp.get_json()["error"])


class LimitAndFailureTests(unittest.TestCase):
    def test_a_user_at_the_daily_limit_gets_a_429_and_no_call(self):
        with patch.object(app, "AI_USER_DAILY_LIMIT", 2), \
             patch_llm("never sent", store=_used("ai_correct", "ai_suggest_comment")) as llm:
            resp, _conn = _call("/api/ai/correct", {"text": "teh"})

        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.get_json(), {"error": "You have used today's 2 AI requests. They renew at midnight UTC."})
        self.assertEqual(llm.provider.calls, [])

    def test_only_this_users_ai_calls_count(self):
        store = _used("moderation", "moderation")                     # moderating their posts
        store.record(_used("ai_correct", user_id=7).records[0])         # someone else's AI call
        store.record(_used("ai_correct", status="over_limit").records[0])  # refused, never sent
        with patch.object(app, "AI_USER_DAILY_LIMIT", 1), patch_llm("Fixed", store=store) as llm:
            resp, _conn = _call("/api/ai/correct", {"text": "teh"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(llm.provider.calls), 1)

    def test_a_limit_of_zero_refuses_everyone(self):
        with patch.object(app, "AI_USER_DAILY_LIMIT", 0), patch_llm("never sent") as llm:
            resp, _conn = _call("/api/ai/suggest-post", {"title": "Hi"})

        self.assertEqual(resp.status_code, 429)
        self.assertEqual(llm.provider.calls, [])

    def test_the_sites_daily_limit_is_a_429(self):
        with patch_llm("never sent", daily_limit=0) as llm:
            resp, _conn = _call("/api/ai/correct", {"text": "teh"})

        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.get_json(), {"error": "PulseNet has used up today's AI quota. Try again tomorrow."})
        self.assertEqual(llm.provider.calls, [])

    def test_a_rate_limited_provider_is_a_429_with_its_retry_after(self):
        with patch_llm(LLMRateLimited("429", retry_after=30), LLMRateLimited("429")):
            with_header, _conn = _call("/api/ai/correct", {"text": "teh"})
            without, _conn = _call("/api/ai/correct", {"text": "teh"})

        self.assertEqual(with_header.status_code, 429)
        self.assertEqual(with_header.headers.get("Retry-After"), "30")
        self.assertIn("busy right now", with_header.get_json()["error"])
        self.assertEqual(without.status_code, 429)
        self.assertNotIn("Retry-After", without.headers)

    def test_a_timeout_or_any_other_failure_is_a_503(self):
        for failure, words in ((LLMTimeout("slow"), "took too long"), (LLMError("boom"), "unavailable right now"),
                               (RuntimeError("provider bug"), "unavailable right now")):
            with self.subTest(failure=type(failure).__name__), patch_llm(failure):
                resp, _conn = _call("/api/ai/correct", {"text": "teh"})
                self.assertEqual(resp.status_code, 503)
                self.assertIn(words, resp.get_json()["error"])
                self.assertNotIn("boom", str(resp.get_json()))

    def test_an_unreadable_usage_log_refuses(self):
        class DownStore(MemoryUsageStore):
            def count_for_user(self, usage_day, user_id, purposes):
                raise RuntimeError("2003: Can't connect")

        with patch_llm("never sent", store=DownStore()) as llm:
            resp, _conn = _call("/api/ai/correct", {"text": "teh"})

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(llm.provider.calls, [])


class SuggestPostTests(unittest.TestCase):
    def test_a_markdown_draft_comes_back_as_sanitized_html(self):
        reply = "```markdown\nAwait **carefully**.\n\n- one\n- two\n\n<script>alert(1)</script>\n```"
        with patch_llm(reply) as llm:
            resp, _conn = _call("/api/ai/suggest-post", {"title": "Async tips", "tags": [" python ", ""]})

        self.assertEqual(resp.status_code, 200)
        body_html = resp.get_json()["body_html"]
        self.assertIn("<p>Await <strong>carefully</strong>.</p>", body_html)
        self.assertIn("<li>one</li>", body_html)
        self.assertNotIn("<script", body_html)
        self.assertEqual(llm.provider.calls[0][0],
                         "<post_title>\nAsync tips\n</post_title>\n<post_tags>\npython\n</post_tags>")
        self.assertEqual([(r.purpose, r.user_id) for r in llm.store.records], [("ai_suggest_post", 42)])

    def test_bad_input_is_a_400_without_an_llm_call(self):
        cases = {
            "no title": {"tags": ["x"]},
            "blank title": {"title": "  "},
            "title too long": {"title": "t" * 151},
            "title not a string": {"title": 5},
            "tags not a list": {"title": "Hi", "tags": "python"},
            "a tag not a string": {"title": "Hi", "tags": [1]},
            "too many tags": {"title": "Hi", "tags": [f"t{i}" for i in range(11)]},
        }
        for name, body in cases.items():
            with self.subTest(case=name), patch_llm("never sent") as llm:
                resp, _conn = _call("/api/ai/suggest-post", body)
                self.assertEqual(resp.status_code, 400, resp.get_json())
                self.assertEqual(llm.provider.calls, [])

    def test_an_empty_draft_is_a_503(self):
        with patch_llm("<script></script>"):
            resp, _conn = _call("/api/ai/suggest-post", {"title": "Hi"})

        self.assertEqual(resp.status_code, 503)


class SuggestCommentTests(unittest.TestCase):
    def test_a_comment_is_proposed_from_the_post_in_the_db(self):
        with patch_llm('"Great point about await!"') as llm:
            resp, conn = _call("/api/ai/suggest-comment", {"post_id": 7, "title": "not from here"},
                               fetchone=[POST_ROW])

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"text": "Great point about await!"})
        self.assertEqual(conn.params_for("select title, body, body_html from posts"), (7,))
        self.assertEqual(llm.provider.calls[0][0], "<post_title>\nAsync tips\n</post_title>\n"
                                                   "<post_body>\nUse await with care\n</post_body>")
        self.assertEqual([(r.purpose, r.user_id) for r in llm.store.records], [("ai_suggest_comment", 42)])

    def test_a_reply_includes_the_parent_comment_and_its_writer(self):
        parent = {"post_id": 7, "body_html": "<p>I <em>disagree</em></p>", "username": "bob"}
        with patch_llm("Why so?") as llm:
            resp, conn = _call("/api/ai/suggest-comment", {"post_id": 7, "parent_id": 3}, fetchone=[POST_ROW, parent])

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(conn.params_for("from comments c join users u"), (3,))
        self.assertTrue(llm.provider.calls[0][0].endswith("<parent_comment>\n@bob: I disagree\n</parent_comment>"))

    def test_a_post_without_html_uses_its_body(self):
        with patch_llm("Nice") as llm:
            _call("/api/ai/suggest-comment", {"post_id": 7}, fetchone=[{**POST_ROW, "body_html": None}])

        self.assertIn("<post_body>\nplain body\n</post_body>", llm.provider.calls[0][0])

    def test_the_db_connection_is_closed_before_the_llm_is_asked(self):
        conn = FakeConn(fetchone=[POST_ROW])
        seen = []

        class WatchingProvider:
            name, model = "watching", None

            def describe(self):
                return "watching"

            def complete(self, prompt, system=None):
                seen.append(conn.closed)
                return "Nice"

        with patch_llm() as llm:
            llm.provider = WatchingProvider()
            resp, _conn = _call("/api/ai/suggest-comment", {"post_id": 7}, conn=conn)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(seen, [True])

    def test_a_long_suggestion_is_cut_to_a_comment(self):
        with patch_llm("x" * 3000):
            resp, _conn = _call("/api/ai/suggest-comment", {"post_id": 7}, fetchone=[POST_ROW])

        self.assertEqual(len(resp.get_json()["text"]), app.MAX_COMMENT_CHARS)

    def test_missing_post_or_bad_parent_is_answered_without_an_llm_call(self):
        cases = {
            "missing post": ({"post_id": 7}, [None], 404),
            "missing parent": ({"post_id": 7, "parent_id": 3}, [POST_ROW, None], 400),
            "parent on another post": ({"post_id": 7, "parent_id": 3},
                                       [POST_ROW, {"post_id": 8, "body_html": "x", "username": "bob"}], 400),
        }
        for name, (body, fetchone, status) in cases.items():
            with self.subTest(case=name), patch_llm("never sent") as llm:
                resp, conn = _call("/api/ai/suggest-comment", body, fetchone=fetchone)
                self.assertEqual(resp.status_code, status)
                self.assertEqual(llm.provider.calls, [])
                self.assertTrue(conn.closed)

    def test_ids_must_be_whole_numbers(self):
        for body in ({}, {"post_id": "7"}, {"post_id": True}, {"post_id": 7.5}, {"post_id": None},
                     {"post_id": 7, "parent_id": True}, {"post_id": 7, "parent_id": "3"}):
            with self.subTest(body=body), patch_llm("never sent") as llm:
                resp, _conn = _call("/api/ai/suggest-comment", body)
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(llm.provider.calls, [])

    def test_a_db_failure_while_reading_the_post_is_a_503(self):
        class PostsDown(FakeConn):
            def cursor(self, dictionary=False, **_kwargs):
                cursor = super().cursor(dictionary=dictionary)
                execute = cursor.execute

                def failing(sql, params=None):
                    if "FROM posts" in sql:
                        raise RuntimeError("2013: Lost connection")
                    execute(sql, params)

                cursor.execute = failing
                return cursor

        with patch_llm("never sent") as llm:
            resp, conn = _call("/api/ai/suggest-comment", {"post_id": 7}, conn=PostsDown())

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(llm.provider.calls, [])
        self.assertTrue(conn.closed)

    def test_an_empty_suggestion_is_a_503(self):
        with patch_llm('""'):
            resp, _conn = _call("/api/ai/suggest-comment", {"post_id": 7}, fetchone=[POST_ROW])

        self.assertEqual(resp.status_code, 503)


if __name__ == "__main__":
    unittest.main()
