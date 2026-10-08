"""llm/config.py: building the service from LLM_* environment variables.

Every error names the variable and never echoes its value: a key must never reach
a log. Also guards the package boundary: llm/ imports neither Flask nor the app.
"""

import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from llm import (CourseProvider, DbUsageStore, FakeProvider, LLMConfigError,  # noqa: E402
                 LLMService, OpenAICompatProvider, from_env)

KEY = "config-key-3"
GEMINI = {
    "LLM_PROVIDER": "openai_compat",
    "LLM_BASE_URL": "https://generativelanguage.example.test/v1beta/openai",
    "LLM_MODEL": "flash-model",
    "LLM_API_KEY": KEY,
}
COURSE = {
    "LLM_PROVIDER": "course",
    "LLM_API_URL": "https://course.example.test/prod/generate",
    "LLM_API_KEY": KEY,
}


def connect():
    raise AssertionError("from_env must not connect: the store connects per operation")


class ProviderChoiceTests(unittest.TestCase):
    def test_fake(self):
        service = from_env({"LLM_PROVIDER": "fake"}, connect=connect)

        self.assertIsInstance(service, LLMService)
        self.assertIsInstance(service.provider, FakeProvider)
        self.assertIsInstance(service.store, DbUsageStore)
        self.assertIs(service.store._connect, connect)

    def test_openai_compat(self):
        service = from_env(GEMINI, connect=connect)

        provider = service.provider
        self.assertIsInstance(provider, OpenAICompatProvider)
        self.assertEqual(provider.url, "https://generativelanguage.example.test/v1beta/openai/chat/completions")
        self.assertEqual(provider.model, "flash-model")
        self.assertEqual(provider._api_key, KEY)

    def test_course(self):
        service = from_env(COURSE, connect=connect)

        self.assertIsInstance(service.provider, CourseProvider)
        self.assertEqual(service.provider._url, COURSE["LLM_API_URL"])
        self.assertEqual(service.provider._api_key, KEY)

    def test_values_are_trimmed(self):
        # A stray space or a Windows \r at the end of a .env line must not break the key.
        env = {name: f"  {value}\r\n" for name, value in GEMINI.items()}
        provider = from_env(env, connect=connect).provider
        self.assertEqual((provider._api_key, provider.model), (KEY, "flash-model"))

    def test_unset_provider_means_the_llm_is_off(self):
        for env in ({}, {"LLM_PROVIDER": ""}, {"LLM_PROVIDER": "   "}, {"LLM_PROVIDER": None}):
            with self.subTest(env=env):
                with self.assertRaisesRegex(LLMConfigError, "LLM_PROVIDER is not set, so the LLM is off"):
                    from_env(env, connect=connect)

    def test_unknown_provider_lists_the_choices_but_not_the_value(self):
        with self.assertRaises(LLMConfigError) as caught:
            from_env({"LLM_PROVIDER": "gemini-typo"}, connect=connect)

        self.assertEqual(str(caught.exception), "LLM_PROVIDER must be one of: fake, openai_compat, course")


class RequiredSettingTests(unittest.TestCase):
    def test_each_missing_setting_is_named(self):
        cases = [
            (GEMINI, "LLM_BASE_URL", "openai_compat"),
            (GEMINI, "LLM_MODEL", "openai_compat"),
            (GEMINI, "LLM_API_KEY", "openai_compat"),
            (COURSE, "LLM_API_URL", "course"),
            (COURSE, "LLM_API_KEY", "course"),
        ]
        for base_env, missing, provider in cases:
            with self.subTest(missing=missing, provider=provider):
                env = {k: v for k, v in base_env.items() if k != missing}
                with self.assertRaises(LLMConfigError) as caught:
                    from_env(env, connect=connect)
                self.assertEqual(str(caught.exception), f"{missing} is not set (LLM_PROVIDER={provider} needs it)")
                self.assertNotIn(KEY, str(caught.exception))

    def test_urls_must_be_http_or_https_with_a_host(self):
        bad = ["ftp://files.example.test/llm", "generativelanguage.example.test/v1",
               "https://", "https://host:notaport/v1", "javascript:alert(1)"]
        for name, base_env in (("LLM_BASE_URL", GEMINI), ("LLM_API_URL", COURSE)):
            for value in bad:
                with self.subTest(name=name, value=value):
                    with self.assertRaises(LLMConfigError) as caught:
                        from_env({**base_env, name: value}, connect=connect)
                    self.assertEqual(str(caught.exception), f"{name} must be an http:// or https:// URL")

    def test_plain_http_is_allowed_for_a_local_server(self):
        env = {**GEMINI, "LLM_BASE_URL": "http://localhost:11434/v1"}
        self.assertEqual(from_env(env, connect=connect).provider.url, "http://localhost:11434/v1/chat/completions")


class TimeoutTests(unittest.TestCase):
    def timeout(self, value):
        return from_env({**GEMINI, "LLM_TIMEOUT_SECONDS": value}, connect=connect).provider._timeout

    def test_default_is_15_seconds(self):
        self.assertEqual(from_env(GEMINI, connect=connect).provider._timeout, 15)
        self.assertEqual(self.timeout(""), 15)

    def test_range_is_1_to_120_seconds(self):
        self.assertEqual(self.timeout("1"), 1)
        self.assertEqual(self.timeout("120"), 120)
        self.assertEqual(self.timeout("7.5"), 7.5)

    def test_zero_negative_too_long_and_not_a_number_are_rejected(self):
        for value in ("0", "0.5", "-1", "121", "abc", "nan", "inf", "15s"):
            with self.subTest(value=value):
                with self.assertRaises(LLMConfigError) as caught:
                    self.timeout(value)
                self.assertEqual(str(caught.exception),
                                 "LLM_TIMEOUT_SECONDS must be a number of seconds from 1 to 120")

    def test_the_timeout_reaches_the_course_provider_too(self):
        service = from_env({**COURSE, "LLM_TIMEOUT_SECONDS": "40"}, connect=connect)
        self.assertEqual(service.provider._timeout, 40)


class DailyLimitTests(unittest.TestCase):
    def limit(self, value):
        return from_env({"LLM_PROVIDER": "fake", "LLM_DAILY_LIMIT": value}, connect=connect).daily_limit

    def test_default_is_100(self):
        self.assertEqual(from_env({"LLM_PROVIDER": "fake"}, connect=connect).daily_limit, 100)
        self.assertEqual(self.limit(" "), 100)

    def test_whole_numbers_from_zero(self):
        self.assertEqual(self.limit("0"), 0)
        self.assertEqual(self.limit("250"), 250)

    def test_negative_and_fractions_are_rejected(self):
        for value in ("-1", "2.5", "lots"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(LLMConfigError, "LLM_DAILY_LIMIT must be a whole number, 0 or more"):
                    self.limit(value)


class PackageBoundaryTests(unittest.TestCase):
    def test_llm_imports_neither_flask_nor_the_app_nor_a_db_driver(self):
        # In a fresh interpreter: this test process has long since imported Flask.
        code = (
            "import sys, llm, llm.config, llm.service, llm.usage, llm.providers, llm.parse, llm.prompt;"
            "print(','.join(sorted(m for m in ('flask', 'app', 'manage', 'mysql', 'mysql.connector')"
            " if m in sys.modules)))"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=str(BACKEND_DIR),
                                capture_output=True, text=True, timeout=60)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
