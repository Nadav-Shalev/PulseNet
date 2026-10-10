"""The agents' fixed data: personas.py against migration 007, the turn outcomes
against migration 008 and schema.sql, and the agents' limits and llm_usage purposes
against the rest of the backend."""

import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ai_assist  # noqa: E402
import app  # noqa: E402
import migrate  # noqa: E402
from agents import OUTCOMES, PURPOSES, RECORDED, SKILLS, personas, skills  # noqa: E402

DATABASE_DIR = BACKEND_DIR.parent / "database"
MIGRATION = DATABASE_DIR / "migrations" / "007_agents.sql"
# One row of the INSERT: ('Name', 'username', 'email', 'bio', 'avatar', 'image', '', TRUE, 'persona')
_ROW = re.compile(
    r"\(\s*'([^']+)',\s*'([^']+)',\s*'([^']+)',\s*'[^']*',\s*'([^']+)',\s*'([^']+)',\s*'',\s*TRUE,\s*'([^']+)'\)"
)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.sql = MIGRATION.read_text(encoding="utf-8")
        self.rows = _ROW.findall(self.sql)

    def test_it_is_one_insert_of_ten_agents(self):
        statements = migrate.split_sql(self.sql)
        self.assertEqual(len(statements), 1)
        self.assertTrue(statements[0].startswith("INSERT INTO users ("))
        self.assertNotIn("IGNORE", statements[0].upper())   # a taken username must fail loudly
        self.assertEqual(len(self.rows), 10)

    def test_the_usernames_are_the_personas(self):
        self.assertEqual({row[1] for row in self.rows}, set(personas.INTERESTS))

    def test_every_agent_is_marked_unreachable_and_has_a_persona(self):
        for name, username, email, avatar, image, persona in self.rows:
            with self.subTest(username=username):
                self.assertTrue(username.endswith("_ai"))
                self.assertEqual(email, f"{username}@agents.pulsenet.invalid")
                self.assertEqual(avatar, f"https://api.dicebear.com/7.x/bottts/svg?seed={username}")
                self.assertEqual(image, avatar)
                self.assertIn(name.split()[0], persona)
                self.assertGreater(len(persona), 150)

    def test_the_columns_are_the_ones_the_row_pattern_reads(self):
        self.assertIn("INSERT INTO users (name, username, email, bio, avatar, profile_image, "
                      "password_hash, is_agent, personality) VALUES", self.sql)


class PersonaTests(unittest.TestCase):
    def test_every_agent_has_lower_case_topics(self):
        for username, tags in personas.INTERESTS.items():
            with self.subTest(username=username):
                self.assertTrue(tags)
                for tag in tags:
                    self.assertRegex(tag, r"^[a-z0-9]{1,30}$")

    def test_an_unknown_agent_has_no_topics(self):
        self.assertEqual(personas.interests_of("someone_else"), ())
        self.assertEqual(personas.interests_of("ingrid_ai"), ("rust", "performance", "systems"))


class TurnOutcomeTests(unittest.TestCase):
    """agent_actions.outcome is an ENUM: an outcome tick.py records that it does not
    list would make MySQL refuse the INSERT (strict mode), after the write."""

    def enum_values(self, path):
        sql = path.read_text(encoding="utf-8")
        table = re.search(r"CREATE TABLE (?:IF NOT EXISTS )?agent_actions \((.*?)\n\);", sql, re.S).group(1)
        values = re.search(r"outcome\s+ENUM\(([^)]*)\)", table).group(1)
        return tuple(re.findall(r"'([a-z_]+)'", values))

    def test_the_enum_is_what_a_tick_records(self):
        for path in (DATABASE_DIR / "migrations" / "008_agent_actions.sql", DATABASE_DIR / "schema.sql"):
            with self.subTest(path=path.name):
                self.assertEqual(self.enum_values(path), RECORDED)

    def test_a_tick_that_tried_nothing_is_not_a_turn(self):
        self.assertEqual(set(OUTCOMES) - set(RECORDED), {"idle", "no_agent", "dry_run", "capped"})


class LimitTests(unittest.TestCase):
    def test_an_agent_writes_within_what_the_api_allows_a_person(self):
        self.assertLessEqual(skills.MAX_COMMENT_CHARS, app.MAX_COMMENT_CHARS)
        # The worst case of text_to_html is 5 characters per character ("&" -> "&amp;").
        self.assertLessEqual(5 * skills.MAX_COMMENT_CHARS, app.MAX_COMMENT_HTML)
        self.assertLessEqual(skills.MAX_TITLE_CHARS, app.MAX_TITLE_CHARS)
        self.assertLessEqual(skills.MAX_TAGS, app.MAX_TAGS)

    def test_purposes_are_valid_and_never_count_against_a_users_ai_help(self):
        self.assertEqual(len(PURPOSES), len(set(PURPOSES)))
        self.assertEqual(len(PURPOSES), sum(1 for skill in SKILLS if skill.needs_llm))
        for purpose in PURPOSES:
            with self.subTest(purpose=purpose):
                self.assertRegex(purpose, r"^agent_[a-z_]{1,26}$")
                self.assertNotIn(purpose, ai_assist.PURPOSES)
                self.assertNotEqual(purpose, "moderation")


if __name__ == "__main__":
    unittest.main()
