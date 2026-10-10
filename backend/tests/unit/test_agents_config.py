"""agents.config: AGENTS_ENABLED and AGENTS_MAX_ACTIONS_PER_DAY from the environment."""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agents.config import AgentsConfig, AgentsConfigError, from_env  # noqa: E402


class EnabledTests(unittest.TestCase):
    def test_off_unless_switched_on(self):
        self.assertEqual(from_env({}), AgentsConfig(enabled=False, max_actions_per_day=20))

    def test_on(self):
        for raw in ("1", "true", "TRUE", "yes", "on", " On "):
            with self.subTest(raw=raw):
                self.assertTrue(from_env({"AGENTS_ENABLED": raw}).enabled)

    def test_off(self):
        for raw in ("", "  ", "0", "false", "False", "no", "off"):
            with self.subTest(raw=raw):
                self.assertFalse(from_env({"AGENTS_ENABLED": raw}).enabled)

    def test_anything_else_is_an_error_that_names_the_variable(self):
        for raw in ("2", "enabled", "y", "tru"):
            with self.subTest(raw=raw):
                with self.assertRaises(AgentsConfigError) as caught:
                    from_env({"AGENTS_ENABLED": raw})
                # The same words whatever the value: it is named, never echoed.
                self.assertEqual(str(caught.exception), "AGENTS_ENABLED must be one of: "
                                 "1, true, yes, on, 0, false, no, off (or empty)")


class MaxActionsTests(unittest.TestCase):
    def test_default_and_set(self):
        self.assertEqual(from_env({"AGENTS_MAX_ACTIONS_PER_DAY": ""}).max_actions_per_day, 20)
        self.assertEqual(from_env({"AGENTS_MAX_ACTIONS_PER_DAY": " 5 "}).max_actions_per_day, 5)

    def test_the_range_ends_are_allowed(self):
        self.assertEqual(from_env({"AGENTS_MAX_ACTIONS_PER_DAY": "1"}).max_actions_per_day, 1)
        self.assertEqual(from_env({"AGENTS_MAX_ACTIONS_PER_DAY": "500"}).max_actions_per_day, 500)

    def test_out_of_range_or_not_a_whole_number_is_an_error(self):
        for raw in ("0", "-3", "501", "2.5", "twenty", "1e2"):
            with self.subTest(raw=raw):
                with self.assertRaises(AgentsConfigError) as caught:
                    from_env({"AGENTS_MAX_ACTIONS_PER_DAY": raw})
                self.assertIn("AGENTS_MAX_ACTIONS_PER_DAY must be a whole number from 1 to 500",
                              str(caught.exception))

    def test_the_error_is_a_value_error(self):
        # Like AI_USER_DAILY_LIMIT: a caller that only knows ValueError still stops.
        self.assertTrue(issubclass(AgentsConfigError, ValueError))


if __name__ == "__main__":
    unittest.main()
