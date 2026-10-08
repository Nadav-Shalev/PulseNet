"""llm_replay.py: the recorded cases, the recorder, and the replay of the recorded
moderation replies (the AI-assist replies are replayed through the endpoints, in
tests/integration/test_llm_replay_api.py).

No call reaches a real model here: the recorder is driven by ScriptedProvider, and
the replay feeds the saved replies to a ScriptedProvider.
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
for _p in (TESTS_DIR.parent, TESTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ai_assist  # noqa: E402
import llm_replay  # noqa: E402
import moderation  # noqa: E402
from llm import LLMService, LLMTimeout, MemoryUsageStore  # noqa: E402
from llm_support import ScriptedProvider  # noqa: E402

# Providers whose recording is kept in the repo: each must hold every case.
RECORDED_PROVIDERS = ("course",)
# Cases a model answered against the case's expectation, as recorded. The code
# reading them is right; the model is not. Each stays listed only while its
# recording still misses: a re-recording that gets it right fails the test until the
# entry goes.
#   course / moderation_quote (S12, 2026-10-08): the course model blocks a comment
#   that quotes "kill yourself" in order to condemn it (category "threat"). Gemini let
#   it through in S10. In production this is what the word list would decide anyway,
#   so the LLM just does not improve on it here.
KNOWN_MODEL_MISSES = {("course", "moderation_quote")}
RERECORD = "the prompt changed since it was recorded: re-record with " \
           "python backend/manage.py llm-record --case {name} (a real call: ask first)"


def _service(*replies):
    return LLMService(ScriptedProvider(*replies), MemoryUsageStore(), daily_limit=100)


def _moderate(case, service):
    checker = moderation.Moderator(service)
    if case.kind == "comment":
        return checker.check_comment(case.inputs["text"])
    return checker.check_post(case.inputs["title"], case.inputs["body_text"], case.inputs["tags"])


class CasesTests(unittest.TestCase):
    def test_eight_cases_with_unique_names_and_real_purposes(self):
        names = [case.name for case in llm_replay.CASES]

        self.assertEqual(len(names), 8)
        self.assertEqual(len(set(names)), 8)
        purposes = {"moderation", *ai_assist.PURPOSES}
        for case in llm_replay.CASES:
            with self.subTest(case=case.name):
                self.assertIn(case.purpose, purposes)
                self.assertTrue(case.prompt.strip())
                self.assertTrue(case.system.strip())

    def test_moderation_cases_carry_the_prompt_production_sends(self):
        for case in llm_replay.CASES:
            if case.purpose != "moderation":
                continue
            with self.subTest(case=case.name):
                service = _service('{"toxic": false, "category": "none"}')
                _moderate(case, service)
                self.assertEqual(service.provider.calls, [(case.prompt, case.system)])

    def test_the_word_list_alone_would_get_these_cases_wrong_or_right_as_designed(self):
        # toxic and injection pass the word list (only the LLM can block them);
        # quote trips it (only the LLM can let it through).
        for case in llm_replay.CASES:
            if case.purpose != "moderation":
                continue
            with self.subTest(case=case.name):
                fields = case.inputs.get("text") or "\n".join(
                    [case.inputs["title"], ", ".join(case.inputs["tags"]), case.inputs["body_text"]])
                self.assertEqual(moderation.wordlist_verdict(fields).blocked,
                                 case.expect["wordlist_blocks"])

    def test_the_injection_cannot_close_its_block(self):
        case = llm_replay.CASES_BY_NAME["moderation_injection"]

        self.assertEqual(case.prompt.count("</post_body>"), 1)     # only the real end tag
        self.assertIn("&lt;/post_body>", case.prompt)

    def test_the_digest_covers_prompt_and_system(self):
        digest = llm_replay.digest("p", "s")

        self.assertEqual(len(digest), 64)
        self.assertNotEqual(digest, llm_replay.digest("p", "s2"))
        self.assertNotEqual(digest, llm_replay.digest("p2", "s"))


class RecordTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.out = Path(self._dir.name)

    def tearDown(self):
        self._dir.cleanup()

    def test_each_case_is_one_call_and_one_fixture(self):
        cases = llm_replay.CASES[:2]
        service = _service("  first reply ", "second reply")
        clock = iter([0.0, 0.25, 1.0, 1.5]).__next__
        lines = []

        paths = llm_replay.record(service, cases, self.out, clock=clock, log=lines.append)

        self.assertEqual(service.provider.calls, [(c.prompt, c.system) for c in cases])
        self.assertEqual(paths, [self.out / "scripted" / f"{c.name}.json" for c in cases])
        first = json.loads(paths[0].read_text(encoding="utf-8"))
        self.assertEqual(tuple(first), llm_replay.FIELDS)    # nothing else: no URL, no key
        self.assertEqual(first["case"], cases[0].name)
        self.assertEqual(first["purpose"], "moderation")
        self.assertEqual((first["provider"], first["model"]), ("scripted", "scripted-1"))
        self.assertEqual(first["reply"], "first reply")       # as callers get it: stripped
        self.assertEqual(first["latency_ms"], 250)
        self.assertEqual(first["prompt_sha256"], llm_replay.digest(cases[0].prompt, cases[0].system))
        self.assertEqual(first["recorded_on"], datetime.now(timezone.utc).date().isoformat())
        self.assertNotIn(b"\r\n", paths[0].read_bytes())
        self.assertEqual(lines[1], f"{cases[1].name}: 500 ms, 12 characters")
        # Logged like any call, under the purpose production uses.
        self.assertEqual([r.purpose for r in service.store.records], ["moderation", "moderation"])

    def test_the_first_failure_stops_the_run_without_a_retry(self):
        cases = llm_replay.CASES[:3]
        service = _service("first reply", LLMTimeout("too slow"), "never asked")

        with self.assertRaises(LLMTimeout):
            llm_replay.record(service, cases, self.out, log=lambda _line: None)

        self.assertEqual(len(service.provider.calls), 2)
        self.assertEqual([p.name for p in (self.out / "scripted").iterdir()], [f"{cases[0].name}.json"])

    def test_recorded_reads_every_fixture_by_provider_and_case(self):
        llm_replay.record(_service("a reply"), llm_replay.CASES[:1], self.out, log=lambda _line: None)

        found = llm_replay.recorded(self.out)

        self.assertEqual(list(found), [("scripted", llm_replay.CASES[0].name)])
        self.assertEqual(found[("scripted", llm_replay.CASES[0].name)]["reply"], "a reply")


class RecordedFixturesTests(unittest.TestCase):
    """The replies saved in tests/fixtures/llm_replies, from real calls."""

    @classmethod
    def setUpClass(cls):
        cls.fixtures = llm_replay.recorded()

    def test_each_kept_recording_has_every_case(self):
        for provider in RECORDED_PROVIDERS:
            with self.subTest(provider=provider):
                names = sorted(name for (prov, name) in self.fixtures if prov == provider)
                self.assertEqual(names, sorted(llm_replay.CASES_BY_NAME))

    def test_fixtures_hold_only_the_known_fields(self):
        for (provider, name), entry in self.fixtures.items():
            with self.subTest(provider=provider, case=name):
                self.assertEqual(tuple(entry), llm_replay.FIELDS)
                self.assertEqual((entry["provider"], entry["case"]), (provider, name))
                self.assertTrue(entry["reply"].strip())

    def test_every_fixture_answers_the_current_prompt(self):
        for (provider, name), entry in self.fixtures.items():
            with self.subTest(provider=provider, case=name):
                case = llm_replay.CASES_BY_NAME.get(name)
                self.assertIsNotNone(case, f"{name} is no longer a case: delete its fixture")
                self.assertEqual(entry["prompt_sha256"], llm_replay.digest(case.prompt, case.system),
                                 RERECORD.format(name=name))
                self.assertEqual(entry["purpose"], case.purpose)

    def test_moderation_replies_are_verdicts_and_the_expected_ones(self):
        for (provider, name), entry in self.fixtures.items():
            case = llm_replay.CASES_BY_NAME.get(name)
            if case is None or case.purpose != "moderation":
                continue
            with self.subTest(provider=provider, case=name):
                parsed = moderation.parse_verdict(entry["reply"])        # no LLMBadReply
                verdict = _moderate(case, _service(entry["reply"]))
                self.assertEqual(verdict.source, "llm")                  # the reply decided
                expected = case.expect["blocked"]
                if (provider, name) in KNOWN_MODEL_MISSES:
                    expected = not expected
                self.assertEqual(verdict.blocked, expected)
                self.assertEqual(verdict, parsed)
                if verdict.blocked:
                    self.assertIn(verdict.category, moderation.CATEGORIES)

    def test_ai_replies_survive_clean_reply(self):
        for (provider, name), entry in self.fixtures.items():
            case = llm_replay.CASES_BY_NAME.get(name)
            if case is None or case.purpose == "moderation":
                continue
            with self.subTest(provider=provider, case=name):
                cleaned = ai_assist.clean_reply(entry["reply"], "draft", unquote=True)
                self.assertTrue(cleaned.strip())
                self.assertNotIn("<draft>", cleaned)
                self.assertFalse(cleaned.startswith("```"))


if __name__ == "__main__":
    unittest.main()
