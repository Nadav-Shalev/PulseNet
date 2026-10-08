"""llm/providers/openai_compat.py: the request it sends and how it reads the reply.

No network: ``FakeHttp`` stands in for requests.
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
for _p in (TESTS_DIR.parent, TESTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from llm import LLMError, OpenAICompatProvider  # noqa: E402
from llm_support import FakeHttp, FakeResponse  # noqa: E402

KEY = "compat-key-7"


def provider(*results, base_url="https://generativelanguage.example.test/v1beta/openai", timeout=15):
    http = FakeHttp(*results)
    return OpenAICompatProvider(base_url, "flash-model", KEY, timeout, http=http), http


def reply(content, finish_reason="stop"):
    return FakeResponse(200, {"choices": [{"index": 0, "finish_reason": finish_reason,
                                           "message": {"role": "assistant", "content": content}}]})


class RequestTests(unittest.TestCase):
    def test_posts_chat_completions_with_system_then_user(self):
        llm, http = provider(reply("Hello!"))

        self.assertEqual(llm.complete("Say hi", system="Be brief."), "Hello!")

        sent = http.calls[0]
        self.assertEqual(sent["url"], "https://generativelanguage.example.test/v1beta/openai/chat/completions")
        self.assertEqual(sent["headers"], {"Authorization": f"Bearer {KEY}"})
        self.assertEqual(sent["json"], {
            "model": "flash-model",
            "messages": [{"role": "system", "content": "Be brief."},
                         {"role": "user", "content": "Say hi"}],
        })
        self.assertEqual(sent["timeout"], (5, 15))

    def test_without_system_only_the_user_message_is_sent(self):
        llm, http = provider(reply("ok"))

        llm.complete("Say hi")

        self.assertEqual(http.calls[0]["json"]["messages"], [{"role": "user", "content": "Say hi"}])

    def test_trailing_slash_in_base_url_is_ignored(self):
        llm, http = provider(reply("ok"), base_url="http://localhost:11434/v1/")

        llm.complete("hi")

        self.assertEqual(http.calls[0]["url"], "http://localhost:11434/v1/chat/completions")

    def test_no_max_tokens_is_sent(self):
        llm, http = provider(reply("ok"))
        llm.complete("hi")
        self.assertNotIn("max_tokens", http.calls[0]["json"])


class ReplyTests(unittest.TestCase):
    def test_unexpected_shapes(self):
        cases = [
            {"id": "x"},                                  # no choices
            {"choices": []},                              # empty choices
            {"choices": ["not an object"]},               # a choice that is not an object
            {"choices": [{"message": None}]},             # no message
            {"choices": [{"message": {"role": "assistant"}}]},  # no content
            ["a", "list"],                                # not an object at all
        ]
        for body in cases:
            with self.subTest(body=body):
                llm, _ = provider(FakeResponse(200, body))
                with self.assertRaisesRegex(LLMError, r"openai_compat: unexpected reply"):
                    llm.complete("hi")

    def test_empty_content_reports_the_finish_reason(self):
        cases = [(None, "length"), ("", "stop"), ("   \n", "content_filter"), (42, "stop")]
        for content, finish in cases:
            with self.subTest(content=content):
                llm, _ = provider(reply(content, finish_reason=finish))
                with self.assertRaises(LLMError) as caught:
                    llm.complete("hi")
                self.assertEqual(str(caught.exception), f"openai_compat: empty reply (finish_reason {finish!r})")

    def test_http_errors_come_from_the_shared_helper(self):
        llm, _ = provider(FakeResponse(404, {"error": {"message": "models/flash-model is not found"}}))
        with self.assertRaisesRegex(LLMError, r"openai_compat: model or URL not found \(HTTP 404\)"):
            llm.complete("hi")


class DescribeTests(unittest.TestCase):
    def test_describe_and_repr_never_show_the_key(self):
        llm, _ = provider()

        self.assertEqual(llm.describe(), "openai_compat, model flash-model at generativelanguage.example.test")
        self.assertNotIn(KEY, llm.describe())
        self.assertNotIn(KEY, repr(llm))
        self.assertIn("flash-model", repr(llm))


if __name__ == "__main__":
    unittest.main()
