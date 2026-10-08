"""llm/providers/course.py: the class demo's contract (community_bot/llm.py).

One flat prompt, the key in an x-api-key header, and the reply in the first of
completion / text / response / output. No network: ``FakeHttp`` stands in for requests.
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
for _p in (TESTS_DIR.parent, TESTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from llm import CourseProvider, LLMError, LLMRateLimited  # noqa: E402
from llm_support import FakeHttp, FakeResponse  # noqa: E402

KEY = "course-key-9"
URL = "https://course.example.test/prod/generate"


def provider(*results):
    http = FakeHttp(*results)
    return CourseProvider(URL, KEY, 20, http=http), http


class RequestTests(unittest.TestCase):
    def test_flat_prompt_with_the_system_text_first(self):
        llm, http = provider(FakeResponse(200, {"completion": "Hi there"}))

        self.assertEqual(llm.complete("POST: Good morning", system="You are CommunityBot."), "Hi there")

        sent = http.calls[0]
        self.assertEqual(sent["url"], URL)
        self.assertEqual(sent["json"], {"prompt": "You are CommunityBot.\n\nPOST: Good morning"})
        self.assertEqual(sent["headers"], {"x-api-key": KEY})
        self.assertEqual(sent["timeout"], (5, 20))

    def test_without_system_the_prompt_goes_alone(self):
        llm, http = provider(FakeResponse(200, {"text": "ok"}))

        llm.complete("just this")

        self.assertEqual(http.calls[0]["json"], {"prompt": "just this"})


class ReplyTests(unittest.TestCase):
    def test_each_reply_key(self):
        for key in ("completion", "text", "response", "output"):
            with self.subTest(key=key):
                llm, _ = provider(FakeResponse(200, {key: f"from {key}", "other": 1}))
                self.assertEqual(llm.complete("hi"), f"from {key}")

    def test_keys_are_tried_in_the_demo_order(self):
        llm, _ = provider(FakeResponse(200, {"output": "4th", "response": "3rd", "text": "2nd"}))
        self.assertEqual(llm.complete("hi"), "2nd")

    def test_a_key_that_is_not_text_is_skipped(self):
        llm, _ = provider(FakeResponse(200, {"completion": {"nested": True}, "response": "used"}))
        self.assertEqual(llm.complete("hi"), "used")

    def test_a_json_string_is_the_reply(self):
        llm, _ = provider(FakeResponse(200, "plain reply"))
        self.assertEqual(llm.complete("hi"), "plain reply")

    def test_any_other_shape_is_an_error(self):
        for body in ({"result": "x"}, {"completion": None}, ["x"], 42):
            with self.subTest(body=body):
                llm, _ = provider(FakeResponse(200, body))
                with self.assertRaisesRegex(LLMError, r"course: unexpected reply \(no completion/text/response/output text\)"):
                    llm.complete("hi")

    def test_quota_exhausted_is_rate_limited(self):
        llm, _ = provider(FakeResponse(429, {"message": "Limit Exceeded"}))
        with self.assertRaisesRegex(LLMRateLimited, r"course: rate limited \(HTTP 429\): Limit Exceeded"):
            llm.complete("hi")


class DescribeTests(unittest.TestCase):
    def test_describe_and_repr_show_only_the_host(self):
        llm, _ = provider()

        self.assertEqual(llm.describe(), "course endpoint at course.example.test")
        for text in (llm.describe(), repr(llm)):
            self.assertNotIn(KEY, text)
            self.assertNotIn("/prod/generate", text)
        self.assertIsNone(llm.model)


if __name__ == "__main__":
    unittest.main()
