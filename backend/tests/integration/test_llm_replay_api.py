"""The recorded AI-assist replies (llm_replay.py), replayed through the endpoints.

Each saved reply, from a real model, goes through what production does with it:
clean_reply, Markdown to HTML, sanitizing, the length cut. The request is built from
the case's inputs, so the test also proves that the endpoint sends exactly the
prompt the reply was recorded for. No call leaves the machine: patch_llm answers
with the saved reply.
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
import llm_replay  # noqa: E402
from support import FakeConn, client, patch_db, patch_llm  # noqa: E402

POST_ID, PARENT_ID = 7, 3


def _session_user():
    return {"id": 42, "name": "Ada", "username": "ada", "email": "ada@example.com",
            "bio": "", "avatar": None, "profile_image": None, "role": "user"}


def _replay(case, reply):
    """Send the case's request as user 42, the LLM answering ``reply``. Returns
    (response, the (prompt, system) pairs the LLM was sent)."""
    if case.kind == "correct":
        route, body, rows = "/api/ai/correct", {"text": case.inputs["text"], "format": case.inputs["format"]}, []
    elif case.kind == "suggest_post":
        route, body, rows = "/api/ai/suggest-post", {"title": case.inputs["title"], "tags": case.inputs["tags"]}, []
    else:
        username, parent_text = case.inputs["parent"]
        rows = [{"title": case.inputs["title"], "body": case.inputs["post_text"], "body_html": None},
                {"post_id": POST_ID, "body_html": f"<p>{parent_text}</p>", "username": username}]
        route, body = "/api/ai/suggest-comment", {"post_id": POST_ID, "parent_id": PARENT_ID}
    session, conn = FakeConn(fetchone=[_session_user()]), FakeConn(fetchone=rows)
    with patch_db(conn), patch.object(app, "get_db_connection", side_effect=[session, conn]), \
         patch_llm(reply) as llm:
        c = client()
        c.set_cookie("session_id", "valid-sid")
        resp = c.post(route, json=body)
    return resp, llm.provider.calls


class RecordedAiRepliesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.replies = [(provider, llm_replay.CASES_BY_NAME[name], entry["reply"])
                       for (provider, name), entry in llm_replay.recorded().items()
                       if name in llm_replay.CASES_BY_NAME
                       and llm_replay.CASES_BY_NAME[name].purpose != "moderation"]

    def test_there_are_ai_replies_to_replay(self):
        self.assertGreaterEqual(len(self.replies), 4)

    def test_each_endpoint_sends_the_recorded_prompt_and_returns_a_usable_suggestion(self):
        for provider, case, reply in self.replies:
            with self.subTest(provider=provider, case=case.name):
                resp, calls = _replay(case, reply)

                self.assertEqual(resp.status_code, 200, resp.get_json())
                self.assertEqual(calls, [(case.prompt, case.system)])
                body = resp.get_json()
                text = body.get("text") or body.get("body_html")
                self.assertTrue(app.html_to_text(text).strip())
                for leftover in ("<draft", "</draft", "```", "<script"):
                    self.assertNotIn(leftover, text)

    def test_html_suggestions_are_sanitized_html(self):
        for provider, case, reply in self.replies:
            fmt = case.inputs.get("format")
            if case.kind != "suggest_post" and fmt != "html":
                continue
            with self.subTest(provider=provider, case=case.name):
                resp, _calls = _replay(case, reply)
                html = resp.get_json().get("body_html") or resp.get_json()["text"]
                self.assertEqual(html, app.sanitize_html(html))   # already clean
                self.assertIn("<p>", html)

    def test_the_html_correction_keeps_the_draft_tags(self):
        for provider, case, reply in self.replies:
            if case.inputs.get("format") != "html":
                continue
            with self.subTest(provider=provider):
                html = _replay(case, reply)[0].get_json()["text"]
                self.assertIn("<strong>", html)

    def test_comment_suggestions_are_plain_unquoted_text(self):
        for provider, case, reply in self.replies:
            if case.kind != "suggest_comment" and case.inputs.get("format") != "text":
                continue
            with self.subTest(provider=provider, case=case.name):
                text = _replay(case, reply)[0].get_json()["text"]
                self.assertLessEqual(len(text), app.MAX_COMMENT_CHARS)
                self.assertFalse(text[:1] in "\"'“" and text[-1:] in "\"'”", text)


if __name__ == "__main__":
    unittest.main()
