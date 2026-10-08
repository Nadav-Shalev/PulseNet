"""llm/service.py: the rules around every LLM call.

Daily limit, usage rows, statuses, the UTC day, fail-closed counting, argument
checks and log lines, with a ScriptedProvider and a MemoryUsageStore (no network,
no DB).
"""

import logging
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
for _p in (TESTS_DIR.parent, TESTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from llm import (MAX_PROMPT_CHARS, LLMError, LLMLimitReached, LLMRateLimited,  # noqa: E402
                 LLMService, LLMTimeout, MemoryUsageStore, UsageRecord)
from llm_support import ScriptedProvider  # noqa: E402

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 8)


def service(*results, limit=5, now=NOW, clock=None, store=None):
    """An LLMService over a ScriptedProvider answering ``results``. The clock
    advances 0.25 s per reading, so every call takes 250 ms."""
    provider = ScriptedProvider(*results)
    ticks = iter(range(10_000))
    return LLMService(
        provider, store if store is not None else MemoryUsageStore(), daily_limit=limit,
        now=lambda: now, clock=clock or (lambda: next(ticks) * 0.25),
    )


def past_calls(n, day=TODAY, status="ok"):
    store = MemoryUsageStore()
    for _ in range(n):
        store.record(UsageRecord(day, "scripted", "scripted-1", "check", None, status, 10, 5, 5))
    return store


class BrokenStore:
    """A usage store whose DB is down (``fail`` says which operation fails)."""

    class Down(Exception):
        errno = 2003

    def __init__(self, fail=("count", "record"), used=0):
        self.fail, self.used, self.records = fail, used, []

    def count(self, usage_day):
        if "count" in self.fail:
            raise self.Down("Can't connect to MySQL server on 'db.internal' as dbuser")
        return self.used

    def count_for_user(self, usage_day, user_id, purposes):
        return self.count(usage_day)

    def record(self, entry):
        if "record" in self.fail:
            raise self.Down("Can't connect to MySQL server on 'db.internal' as dbuser")
        self.records.append(entry)


class SuccessTests(unittest.TestCase):
    def test_returns_the_stripped_reply_and_logs_one_ok_row(self):
        svc = service("  Hello!\n")

        reply = svc.complete("Say hi", system="Be brief.", purpose="check", user_id=42)

        self.assertEqual(reply, "Hello!")
        self.assertEqual(svc.provider.calls, [("Say hi", "Be brief.")])
        self.assertEqual(svc.store.records, [UsageRecord(
            usage_day=TODAY, provider="scripted", model="scripted-1", purpose="check", user_id=42,
            status="ok", latency_ms=250, prompt_chars=len("Say hi") + len("Be brief."),
            reply_chars=len("Hello!"),
        )])

    def test_system_is_optional(self):
        svc = service("ok")

        svc.complete("prompt only", purpose="check")

        self.assertEqual(svc.provider.calls, [("prompt only", None)])
        self.assertEqual(svc.store.records[0].prompt_chars, len("prompt only"))
        self.assertIsNone(svc.store.records[0].user_id)

    def test_describe_is_the_providers(self):
        self.assertEqual(service().describe(), "scripted (test double)")


class DailyLimitTests(unittest.TestCase):
    def test_under_the_limit_calls_the_provider(self):
        svc = service("ok", limit=3, store=past_calls(2))

        self.assertEqual(svc.complete("hi", purpose="check"), "ok")
        self.assertEqual(svc.usage_today(), (3, 3))

    def test_at_the_limit_refuses_without_calling_the_provider(self):
        svc = service("never sent", limit=3, store=past_calls(3))

        with self.assertRaisesRegex(LLMLimitReached, r"daily LLM limit reached \(3/3\)"):
            svc.complete("hi", purpose="check", user_id=7)

        self.assertEqual(svc.provider.calls, [])
        refused = svc.store.records[-1]
        self.assertEqual((refused.status, refused.latency_ms, refused.reply_chars, refused.user_id),
                         ("over_limit", None, 0, 7))
        self.assertEqual(refused.prompt_chars, 2)

    def test_refused_calls_do_not_count(self):
        store = past_calls(2)
        for _ in range(5):
            store.record(UsageRecord(TODAY, "scripted", None, "check", None, "over_limit", None, 1, 0))
        svc = service("ok", limit=3, store=store)

        self.assertEqual(svc.complete("hi", purpose="check"), "ok")

    def test_failed_calls_count(self):
        # A failed call still reached the provider (and may have cost quota).
        store = past_calls(1)
        for status in ("error", "timeout", "rate_limited"):
            store.record(UsageRecord(TODAY, "scripted", None, "check", None, status, 5, 1, 0))
        svc = service("never sent", limit=4, store=store)

        with self.assertRaises(LLMLimitReached):
            svc.complete("hi", purpose="check")

    def test_zero_limit_turns_the_llm_off(self):
        svc = service("never sent", limit=0)

        with self.assertRaisesRegex(LLMLimitReached, r"\(0/0\)"):
            svc.complete("hi", purpose="check")
        self.assertEqual(svc.provider.calls, [])

    def test_the_day_is_the_utc_day(self):
        # 23:59 UTC on the 8th is still the 8th, though it is already the 9th in Israel.
        late = datetime(2026, 10, 8, 23, 59, 59, tzinfo=timezone.utc)
        svc = service("ok", limit=3, now=late, store=past_calls(3, day=TODAY - timedelta(days=1)))
        self.assertEqual(svc.complete("hi", purpose="check"), "ok")
        self.assertEqual(svc.store.records[-1].usage_day, TODAY)

        # From midnight UTC the 8th's calls no longer count.
        midnight = datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc)
        svc = service("ok", limit=3, now=midnight, store=past_calls(3, day=TODAY))
        self.assertEqual(svc.complete("hi", purpose="check"), "ok")
        self.assertEqual(svc.store.records[-1].usage_day, date(2026, 10, 9))

    def test_the_real_clock_is_used_by_default(self):
        svc = LLMService(ScriptedProvider("ok"), MemoryUsageStore(), daily_limit=1)

        svc.complete("hi", purpose="check")

        record = svc.store.records[0]
        self.assertEqual(record.usage_day, datetime.now(timezone.utc).date())
        self.assertGreaterEqual(record.latency_ms, 0)


class FailureTests(unittest.TestCase):
    def test_each_provider_failure_is_logged_with_its_status_and_reraised(self):
        cases = [
            (LLMRateLimited("scripted: rate limited (HTTP 429)", retry_after=30), "rate_limited"),
            (LLMTimeout("scripted: timed out (ReadTimeout)"), "timeout"),
            (LLMError("scripted: HTTP 500"), "error"),
        ]
        for error, status in cases:
            with self.subTest(status=status):
                svc = service(error)
                with self.assertRaises(type(error)) as caught:
                    svc.complete("hi", purpose="check", user_id=3)
                self.assertIs(caught.exception, error)
                record = svc.store.records[0]
                self.assertEqual((record.status, record.latency_ms, record.reply_chars, record.user_id),
                                 (status, 250, 0, 3))

    def test_a_provider_bug_becomes_an_llm_error(self):
        svc = service(KeyError("choices"))

        with self.assertRaises(LLMError) as caught:
            svc.complete("hi", purpose="check")

        self.assertEqual(str(caught.exception), "scripted failed (KeyError)")
        self.assertIsNone(caught.exception.__cause__)
        self.assertEqual(svc.store.records[0].status, "error")

    def test_an_empty_or_non_text_reply_is_an_error(self):
        for reply in ("", "  \n ", None, 42):
            with self.subTest(reply=reply):
                svc = service(reply)
                with self.assertRaisesRegex(LLMError, "scripted: empty reply"):
                    svc.complete("hi", purpose="check")
                self.assertEqual(svc.store.records[0].status, "error")

    def test_no_retries(self):
        svc = service(LLMRateLimited("scripted: rate limited"), "would be the retry")

        with self.assertRaises(LLMRateLimited):
            svc.complete("hi", purpose="check")
        self.assertEqual(len(svc.provider.calls), 1)


class UsageLogDownTests(unittest.TestCase):
    def test_no_count_means_no_call(self):
        # Without the count the limit cannot hold: refuse rather than spend blind.
        svc = service("never sent", store=BrokenStore(fail=("count",)))

        with self.assertLogs("pulsenet.llm", "WARNING") as logs:
            with self.assertRaisesRegex(LLMError, "the LLM usage log is unavailable") as caught:
                svc.complete("hi", purpose="check")

        self.assertNotIsInstance(caught.exception, LLMLimitReached)
        self.assertEqual(svc.provider.calls, [])
        self.assertEqual(logs.output, ["WARNING:pulsenet.llm:llm usage count failed (Down 2003)"])

    def test_usage_today_fails_the_same_way(self):
        svc = service(store=BrokenStore(fail=("count",)))
        with self.assertLogs("pulsenet.llm", "WARNING"):
            with self.assertRaisesRegex(LLMError, "the LLM usage log is unavailable"):
                svc.usage_today()

    def test_user_usage_today_fails_the_same_way(self):
        svc = service(store=BrokenStore(fail=("count",)))
        with self.assertLogs("pulsenet.llm", "WARNING") as logs:
            with self.assertRaisesRegex(LLMError, "the LLM usage log is unavailable"):
                svc.user_usage_today(42, ["ai_correct"])
        self.assertEqual(logs.output, ["WARNING:pulsenet.llm:llm usage count failed (Down 2003)"])


class UserUsageTests(unittest.TestCase):
    def record(self, store, user_id, purpose, status="ok", day=TODAY):
        store.record(UsageRecord(day, "scripted", "scripted-1", purpose, user_id, status, 10, 5, 5))

    def test_counts_one_users_calls_today_for_the_given_purposes(self):
        store = MemoryUsageStore()
        self.record(store, 42, "ai_correct")
        self.record(store, 42, "ai_suggest_post", status="timeout")       # failed calls count
        self.record(store, 42, "ai_correct", status="over_limit")         # refused ones do not
        self.record(store, 42, "moderation")                              # another purpose
        self.record(store, 7, "ai_correct")                               # another user
        self.record(store, 42, "ai_correct", day=TODAY - timedelta(days=1))
        svc = service(store=store)

        self.assertEqual(svc.user_usage_today(42, ("ai_correct", "ai_suggest_post")), 2)
        self.assertEqual(svc.user_usage_today(42, ["moderation"]), 1)
        self.assertEqual(svc.user_usage_today(99, ["ai_correct"]), 0)

    def test_the_day_is_the_services_utc_day(self):
        store = MemoryUsageStore()
        self.record(store, 42, "ai_correct", day=date(2026, 10, 9))
        late = service(store=store, now=datetime(2026, 10, 8, 23, 59, tzinfo=timezone.utc))
        next_day = service(store=store, now=datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc))

        self.assertEqual(late.user_usage_today(42, ["ai_correct"]), 0)
        self.assertEqual(next_day.user_usage_today(42, ["ai_correct"]), 1)

    def test_bad_arguments_are_a_bug_in_the_caller(self):
        svc = service()
        for user_id, purposes in ((True, ["ai_correct"]), ("42", ["ai_correct"]), (None, ["ai_correct"]),
                                  (42, []), (42, ())):
            with self.subTest(user_id=user_id, purposes=purposes):
                with self.assertRaises(ValueError):
                    svc.user_usage_today(user_id, purposes)

    def test_a_reply_is_kept_when_its_row_cannot_be_written(self):
        svc = service("worth keeping", store=BrokenStore(fail=("record",)))

        with self.assertLogs("pulsenet.llm", "INFO") as logs:
            reply = svc.complete("hi", purpose="check")

        self.assertEqual(reply, "worth keeping")
        self.assertIn("WARNING:pulsenet.llm:llm usage not recorded (Down 2003)", logs.output)
        # Only the error type and number: not the text, which names the host and user.
        self.assertNotIn("db.internal", "\n".join(logs.output))
        self.assertNotIn("dbuser", "\n".join(logs.output))

    def test_a_failure_whose_row_cannot_be_written_still_raises_the_failure(self):
        error = LLMTimeout("scripted: timed out (ReadTimeout)")
        svc = service(error, store=BrokenStore(fail=("record",)))

        with self.assertLogs("pulsenet.llm", "WARNING"):
            with self.assertRaises(LLMTimeout) as caught:
                svc.complete("hi", purpose="check")
        self.assertIs(caught.exception, error)

    def test_a_store_error_without_a_number_shows_only_its_type(self):
        class Plain:
            def count(self, usage_day):
                raise RuntimeError("secret detail")

        svc = service(store=Plain())
        with self.assertLogs("pulsenet.llm", "WARNING") as logs:
            with self.assertRaises(LLMError):
                svc.complete("hi", purpose="check")
        self.assertEqual(logs.output, ["WARNING:pulsenet.llm:llm usage count failed (RuntimeError)"])


class LogLineTests(unittest.TestCase):
    def test_one_info_line_per_call_with_sizes_but_no_text(self):
        svc = service("the secret reply text")

        with self.assertLogs("pulsenet.llm", "INFO") as logs:
            svc.complete("the private prompt text", system="private system text", purpose="moderation")

        self.assertEqual(logs.output, [
            "INFO:pulsenet.llm:llm scripted purpose=moderation status=ok ms=250 in=42 out=21",
        ])
        joined = "\n".join(logs.output)
        for text in ("secret reply", "private prompt", "private system"):
            self.assertNotIn(text, joined)

    def test_a_failure_is_one_warning_with_its_reason(self):
        svc = service(LLMRateLimited("scripted: rate limited (HTTP 429): quota"))

        with self.assertLogs("pulsenet.llm", "INFO") as logs:
            with self.assertRaises(LLMRateLimited):
                svc.complete("hi", purpose="check")

        self.assertEqual(logs.output, [
            "WARNING:pulsenet.llm:llm scripted purpose=check status=rate_limited ms=250 in=2 out=0: "
            "scripted: rate limited (HTTP 429): quota",
        ])

    def test_a_refusal_is_one_warning(self):
        svc = service(limit=0)

        with self.assertLogs("pulsenet.llm", "INFO") as logs:
            with self.assertRaises(LLMLimitReached):
                svc.complete("hi", purpose="check")

        self.assertEqual(logs.output, [
            "WARNING:pulsenet.llm:llm scripted purpose=check status=over_limit ms=None in=2 out=0: "
            "daily LLM limit reached (0/0)",
        ])


class ArgumentTests(unittest.TestCase):
    def test_bad_arguments_are_a_bug_in_the_caller(self):
        cases = [
            ({"prompt": ""}, "prompt must be a non-empty string"),
            ({"prompt": "   "}, "prompt must be a non-empty string"),
            ({"prompt": None}, "prompt must be a non-empty string"),
            ({"prompt": b"bytes"}, "prompt must be a non-empty string"),
            ({"system": 5}, "system must be a string or None"),
            ({"prompt": "x" * (MAX_PROMPT_CHARS + 1)}, "over 20000 characters"),
            ({"prompt": "x" * 10, "system": "y" * (MAX_PROMPT_CHARS - 9)}, "over 20000 characters"),
            ({"purpose": ""}, "purpose must be lower_snake_case"),
            ({"purpose": "Check"}, "purpose must be lower_snake_case"),
            ({"purpose": "9lives"}, "purpose must be lower_snake_case"),
            ({"purpose": "has space"}, "purpose must be lower_snake_case"),
            ({"purpose": "a" * 33}, "purpose must be lower_snake_case"),
            ({"purpose": None}, "purpose must be lower_snake_case"),
            ({"user_id": True}, "user_id must be an int or None"),
            ({"user_id": "42"}, "user_id must be an int or None"),
            ({"user_id": 4.0}, "user_id must be an int or None"),
        ]
        for overrides, message in cases:
            with self.subTest(overrides={k: (v if len(repr(v)) < 40 else "...") for k, v in overrides.items()}):
                svc = service("never sent")
                kwargs = {"prompt": "hi", "purpose": "check", **overrides}
                prompt = kwargs.pop("prompt")
                with self.assertRaisesRegex(ValueError, message):
                    svc.complete(prompt, **kwargs)
                self.assertEqual(svc.provider.calls, [])
                self.assertEqual(svc.store.records, [])

    def test_the_largest_allowed_prompt_and_longest_purpose_pass(self):
        svc = service("ok")
        svc.complete("x" * 10, system="y" * (MAX_PROMPT_CHARS - 10), purpose="a" + "_b" * 15 + "c")
        self.assertEqual(svc.store.records[0].status, "ok")

    def test_purpose_and_user_id_are_keyword_only(self):
        with self.assertRaises(TypeError):
            service("ok").complete("hi", None, "check")  # noqa


if __name__ == "__main__":
    unittest.main()
