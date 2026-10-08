"""llm/providers/fake.py: offline, deterministic replies (tests and the E2E run)."""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
for _p in (TESTS_DIR.parent, TESTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from llm import FakeProvider  # noqa: E402


class FakeProviderTests(unittest.TestCase):
    def test_echoes_the_prompt_the_same_way_every_time(self):
        fake = FakeProvider()

        first = fake.complete("Hello\n   there  world", system="ignored")

        self.assertEqual(first, "(fake reply) Hello there world")
        self.assertEqual(fake.complete("Hello\n   there  world"), first)

    def test_echo_is_cut_to_80_characters(self):
        self.assertEqual(FakeProvider().complete("a" * 200), "(fake reply) " + "a" * 80)

    def test_a_given_reply_is_returned_for_every_prompt(self):
        fake = FakeProvider(reply='{"toxic": false}')

        self.assertEqual(fake.complete("one"), '{"toxic": false}')
        self.assertEqual(fake.complete("two"), '{"toxic": false}')

    def test_identity(self):
        fake = FakeProvider(reply="x")

        self.assertEqual(fake.name, "fake")
        self.assertIsNone(fake.model)
        self.assertEqual(fake.describe(), "fake (canned replies, no network)")
        self.assertEqual(repr(fake), "FakeProvider(reply='x')")


if __name__ == "__main__":
    unittest.main()
