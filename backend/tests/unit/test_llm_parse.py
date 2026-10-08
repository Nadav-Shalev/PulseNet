"""llm/parse.py: the first JSON object in an LLM reply, however it is wrapped."""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
for _p in (TESTS_DIR.parent, TESTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from llm import LLMBadReply, LLMError, parse_json_object  # noqa: E402


class ParseJsonObjectTests(unittest.TestCase):
    def test_a_bare_object(self):
        self.assertEqual(parse_json_object('{"toxic": false, "category": "none"}'),
                         {"toxic": False, "category": "none"})

    def test_a_json_fence_and_a_bare_fence(self):
        for reply in ('```json\n{"toxic": true}\n```',
                      '```\n{"toxic": true}\n```',
                      'Here you go:\n```JSON\n{"toxic": true}\n```\nHope this helps.'):
            with self.subTest(reply=reply):
                self.assertEqual(parse_json_object(reply), {"toxic": True})

    def test_text_before_and_after_the_object(self):
        reply = 'Sure! The verdict is {"toxic": false, "category": "none"} as asked.'
        self.assertEqual(parse_json_object(reply), {"toxic": False, "category": "none"})

    def test_nested_objects_and_braces_inside_strings(self):
        reply = '{"why": "a } and a { in text", "inner": {"a": 1}}'
        self.assertEqual(parse_json_object(reply), {"why": "a } and a { in text", "inner": {"a": 1}})

    def test_the_first_object_wins(self):
        self.assertEqual(parse_json_object('{"a": 1} {"b": 2}'), {"a": 1})

    def test_a_broken_object_is_skipped_for_the_next_one(self):
        self.assertEqual(parse_json_object('{not json} then {"a": 1}'), {"a": 1})

    def test_a_fence_without_an_object_falls_back_to_the_whole_reply(self):
        reply = '```text\nno object here\n``` but {"a": 1} after it'
        self.assertEqual(parse_json_object(reply), {"a": 1})

    def test_no_object_is_a_bad_reply(self):
        for reply in ("", "(fake reply) Hello there", "[1, 2, 3]", '"just a string"',
                      "{'single': 'quotes'}", "{", "```json\n```"):
            with self.subTest(reply=reply):
                with self.assertRaisesRegex(LLMBadReply, "no JSON object"):
                    parse_json_object(reply)

    def test_a_list_holding_an_object_yields_the_object(self):
        # The first '{' starts a valid object; the list around it is not the answer.
        self.assertEqual(parse_json_object('[{"a": 1}]'), {"a": 1})

    def test_not_text_is_a_bad_reply(self):
        with self.assertRaisesRegex(LLMBadReply, "not text"):
            parse_json_object(None)

    def test_a_bad_reply_is_an_llm_error(self):
        # Callers catch LLMError to fall back, so an unusable reply falls back too.
        self.assertTrue(issubclass(LLMBadReply, LLMError))


if __name__ == "__main__":
    unittest.main()
