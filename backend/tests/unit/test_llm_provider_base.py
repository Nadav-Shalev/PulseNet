"""llm/providers/base.py: the Provider interface and the shared HTTP plumbing.

post_json turns every HTTP failure into a typed LLMError, and the API key never
appears in any message. No network: ``FakeHttp`` stands in for requests.
"""

import sys
import unittest
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
for _p in (TESTS_DIR.parent, TESTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from llm import (CourseProvider, FakeProvider, LLMError, LLMRateLimited,  # noqa: E402
                 LLMTimeout, OpenAICompatProvider, Provider)
from llm.providers import base  # noqa: E402
from llm_support import FakeHttp, FakeResponse  # noqa: E402

KEY = "key-under-test-42"
URL = "https://llm.example.test/v1/chat/completions"


def call(*results, timeout=15):
    """post_json against a FakeHttp answering ``results``; returns (http, outcome)."""
    http = FakeHttp(*results)
    outcome = base.post_json(http, URL, headers={"Authorization": f"Bearer {KEY}"},
                             body={"q": 1}, timeout=timeout, secret=KEY, provider="demo")
    return http, outcome


class PostJsonTests(unittest.TestCase):
    def test_returns_the_decoded_json(self):
        http, data = call(FakeResponse(200, {"answer": 42}))

        self.assertEqual(data, {"answer": 42})
        sent = http.calls[0]
        self.assertEqual(sent["url"], URL)
        self.assertEqual(sent["json"], {"q": 1})
        self.assertEqual(sent["headers"], {"Authorization": f"Bearer {KEY}"})

    def test_connect_timeout_is_capped_and_read_timeout_is_the_setting(self):
        http, _ = call(FakeResponse(200, {}), timeout=30)
        self.assertEqual(http.calls[0]["timeout"], (5, 30))

        http, _ = call(FakeResponse(200, {}), timeout=2)
        self.assertEqual(http.calls[0]["timeout"], (2, 2))

    def test_timeouts_become_llm_timeout(self):
        for exc in (requests.ReadTimeout("read timed out"), requests.ConnectTimeout("slow")):
            with self.subTest(exc=type(exc).__name__):
                with self.assertRaisesRegex(LLMTimeout, f"demo: timed out \\({type(exc).__name__}\\)"):
                    call(exc)

    def test_connection_failure_names_the_type_but_not_the_url(self):
        with self.assertRaises(LLMError) as caught:
            call(requests.ConnectionError(f"Max retries exceeded with url: {URL}"))

        self.assertNotIsInstance(caught.exception, LLMTimeout)
        self.assertEqual(str(caught.exception), "demo: cannot reach the server (ConnectionError)")
        self.assertIsNone(caught.exception.__cause__)

    def test_429_is_rate_limited_with_retry_after(self):
        with self.assertRaises(LLMRateLimited) as caught:
            call(FakeResponse(429, {"error": {"message": "Quota exceeded"}}, headers={"Retry-After": "37"}))

        self.assertEqual(caught.exception.retry_after, 37)
        self.assertEqual(str(caught.exception), "demo: rate limited (HTTP 429): Quota exceeded")

    def test_retry_after_that_is_not_a_number_is_ignored(self):
        for header in ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, {"Retry-After": "-5"}, {}):
            with self.subTest(header=header):
                with self.assertRaises(LLMRateLimited) as caught:
                    call(FakeResponse(429, text="slow down", headers=header))
                self.assertIsNone(caught.exception.retry_after)

    def test_rejected_key(self):
        for status in (401, 403):
            with self.subTest(status=status):
                with self.assertRaisesRegex(LLMError, f"demo: the server rejected the API key \\(HTTP {status}\\)"):
                    call(FakeResponse(status, {"message": "Forbidden"}))

    def test_not_found_and_other_errors(self):
        cases = [
            (404, "demo: model or URL not found (HTTP 404): models/nope is not found"),
            (400, "demo: HTTP 400: models/nope is not found"),
            (500, "demo: HTTP 500: models/nope is not found"),
        ]
        for status, message in cases:
            with self.subTest(status=status):
                with self.assertRaises(LLMError) as caught:
                    call(FakeResponse(status, {"error": {"message": "models/nope is not found"}}))
                self.assertNotIsInstance(caught.exception, LLMRateLimited)
                self.assertEqual(str(caught.exception), message)

    def test_success_that_is_not_json(self):
        with self.assertRaisesRegex(LLMError, r"demo: the reply is not JSON \(HTTP 200\)"):
            call(FakeResponse(200, text="<html>gateway</html>"))


class ErrorDetailTests(unittest.TestCase):
    def detail(self, response):
        with self.assertRaises(LLMError) as caught:
            call(response)
        return str(caught.exception).split("demo: HTTP 500", 1)[1]

    def test_message_shapes(self):
        cases = [
            ({"error": {"message": "openai style"}}, ": openai style"),
            ([{"error": {"message": "gemini list style"}}], ": gemini list style"),
            ({"error": "plain error string"}, ": plain error string"),
            ({"message": "api gateway style"}, ": api gateway style"),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(self.detail(FakeResponse(500, body)), expected)

    def test_unknown_json_falls_back_to_the_raw_body(self):
        cases = [
            {"error": {"code": 13}},       # error object without a message
            {"status": "broken"},          # no error at all
            [],                            # an empty list
            "just a string",               # JSON, but not an object
        ]
        for body in cases:
            with self.subTest(body=body):
                response = FakeResponse(500, body, text="raw   body\n text")
                self.assertEqual(self.detail(response), ": raw body text")

    def test_non_json_body_is_used_as_text_and_empty_adds_nothing(self):
        self.assertEqual(self.detail(FakeResponse(500, text="Internal  Server\nError")),
                         ": Internal Server Error")
        self.assertEqual(self.detail(FakeResponse(500, text="  ")), "")

    def test_the_key_is_scrubbed_before_the_message_is_cut(self):
        # The key straddles the 200-character cut: cutting first would leave half of it.
        message = "x" * (base.MAX_ERROR_CHARS - 5) + KEY + " tail"
        detail = self.detail(FakeResponse(500, {"error": {"message": message}}))

        self.assertNotIn(KEY, detail)
        self.assertNotIn(KEY[:5], detail)
        self.assertEqual(len(detail), len(": ") + base.MAX_ERROR_CHARS)

    def test_the_key_never_reaches_any_error_message(self):
        echoed = {"error": {"message": f"API key {KEY} not valid"}}
        for response in (FakeResponse(400, echoed), FakeResponse(401, echoed),
                         FakeResponse(404, echoed), FakeResponse(429, echoed),
                         FakeResponse(503, text=f"bad key {KEY}")):
            with self.subTest(status=response.status_code):
                with self.assertRaises(LLMError) as caught:
                    call(response)
                self.assertNotIn(KEY, str(caught.exception))
                self.assertIn("***", str(caught.exception))


class HelperTests(unittest.TestCase):
    def test_scrub(self):
        self.assertEqual(base.scrub(f"a {KEY} b {KEY}", KEY), "a *** b ***")
        self.assertEqual(base.scrub("nothing to hide", ""), "nothing to hide")
        self.assertEqual(base.scrub("nothing to hide", None), "nothing to hide")

    def test_host_of_keeps_only_host_and_port(self):
        self.assertEqual(base.host_of("https://user:pw@api.example.test/v1/x?key=1"), "api.example.test")
        self.assertEqual(base.host_of("http://localhost:11434/v1"), "localhost:11434")
        self.assertEqual(base.host_of("no scheme at all"), "?")


class ProviderInterfaceTests(unittest.TestCase):
    def test_every_provider_meets_the_interface(self):
        providers = [
            FakeProvider(),
            OpenAICompatProvider("https://llm.example.test/v1", "m", KEY, 15),
            CourseProvider("https://course.example.test/llm", KEY, 15),
        ]
        for provider in providers:
            with self.subTest(provider=type(provider).__name__):
                self.assertIsInstance(provider, Provider)

    def test_something_without_complete_does_not(self):
        class Incomplete:
            name, model = "half", None

            def describe(self):
                return "half a provider"

        self.assertNotIsInstance(Incomplete(), Provider)


if __name__ == "__main__":
    unittest.main()
