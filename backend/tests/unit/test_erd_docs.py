"""The ER diagram in docs/ must match database/schema.sql.

scripts/render_erd.py generates docs/db-diagram.{png,mmd,md} from schema.sql. These
tests load the script without matplotlib (it is imported only to draw), so they also
run in CI, and fail when schema.sql changed but the diagram was not regenerated.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location(
    "render_erd", BACKEND_DIR.parent / "scripts" / "render_erd.py"
)
render_erd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render_erd)

STALE = "docs/ no longer matches database/schema.sql: run python scripts/render_erd.py"


def _read(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


class GeneratedDocsTests(unittest.TestCase):
    """Regenerate in memory and compare with the committed files."""

    def setUp(self):
        self.schema = _read(render_erd.SCHEMA_SQL)
        self.tables = render_erd.parse_schema(self.schema)

    def test_mermaid_file_matches_the_schema(self):
        self.assertEqual(_read(render_erd.MMD_FILE), render_erd.mermaid(self.tables), STALE)

    def test_markdown_diagram_matches_the_schema(self):
        md = _read(render_erd.MD_FILE)
        regenerated = render_erd.update_markdown(md, render_erd.mermaid(self.tables))
        self.assertEqual(md, regenerated, STALE)

    def test_png_was_rendered_from_this_schema(self):
        with Image.open(render_erd.PNG_FILE) as image:
            stamped = image.info.get(render_erd.PNG_DIGEST_KEY)
        self.assertEqual(stamped, render_erd.schema_digest(self.schema), STALE)

    def test_every_table_has_a_place_in_the_picture(self):
        render_erd.check_layout(self.tables)  # raises ErdError naming what is missing


class ParseSchemaTests(unittest.TestCase):
    SQL = """
        CREATE DATABASE IF NOT EXISTS shop; USE shop;
        -- a comment; with a semicolon
        CREATE TABLE IF NOT EXISTS parents (
            id   INT AUTO_INCREMENT PRIMARY KEY,
            code VARCHAR(10) NOT NULL UNIQUE,      -- inline unique
            kind ENUM('a', 'b') NOT NULL DEFAULT 'a',
            note TEXT
        );
        CREATE TABLE links (
            parent_id INT NOT NULL,
            other_id  INT,
            spare_id  INT,
            PRIMARY KEY (parent_id, other_id),
            INDEX idx_other (other_id),
            CONSTRAINT fk_parent FOREIGN KEY (parent_id) REFERENCES parents(id) ON DELETE CASCADE,
            FOREIGN KEY (other_id) REFERENCES parents(id),
            FOREIGN KEY (spare_id) REFERENCES parents(id),
            CHECK (parent_id <> other_id)
        );
        CREATE INDEX idx_spare ON links(spare_id);
    """

    def setUp(self):
        self.tables = render_erd.parse_schema(self.SQL)
        self.by_name = {table.name: table for table in self.tables}

    def test_only_create_table_statements_become_tables(self):
        self.assertEqual([table.name for table in self.tables], ["parents", "links"])

    def test_columns_keep_order_types_and_inline_keys(self):
        columns = [(c.name, c.type, c.keys) for c in self.by_name["parents"].columns]
        self.assertEqual(columns, [
            ("id", "int", ("PK",)),
            ("code", "varchar", ("UK",)),
            ("kind", "enum", ()),        # the comma inside ENUM(...) does not split the column
            ("note", "text", ()),
        ])

    def test_table_level_keys_are_attached_to_their_columns(self):
        columns = {c.name: c.keys for c in self.by_name["links"].columns}
        # INDEX and CHECK are not columns; CONSTRAINT <name> is read like a bare FOREIGN KEY.
        self.assertEqual(columns, {
            "parent_id": ("PK", "FK"), "other_id": ("PK", "FK"), "spare_id": ("FK",),
        })

    def test_primary_key_columns_are_never_nullable(self):
        nullable = {c.name: c.nullable for c in self.by_name["links"].columns}
        self.assertEqual(nullable, {"parent_id": False, "other_id": False, "spare_id": True})

    def test_relationships_and_mermaid_follow_the_foreign_keys(self):
        text = render_erd.mermaid(self.tables)
        # Labels default to the column name; a nullable foreign key is optional (|o).
        self.assertIn('parents ||--o{ links : "parent_id"', text)
        self.assertIn('parents ||--o{ links : "other_id"', text)
        self.assertIn('parents |o--o{ links : "spare_id"', text)
        self.assertIn("        int parent_id PK, FK\n        int other_id  PK, FK\n", text)

    def test_join_tables_are_those_keyed_by_foreign_keys(self):
        self.assertEqual(render_erd.join_tables(self.tables), ["links"])

    def test_a_table_missing_from_the_layout_is_an_error(self):
        with self.assertRaisesRegex(render_erd.ErdError, "parents, links"):
            render_erd.check_layout(self.tables)

    def test_markdown_without_markers_is_an_error(self):
        with self.assertRaisesRegex(render_erd.ErdError, "GENERATED"):
            render_erd.update_markdown("# no markers here\n", "erDiagram\n")

    def test_schema_digest_ignores_line_endings(self):
        self.assertEqual(render_erd.schema_digest("a;\r\nb;\r\n"), render_erd.schema_digest("a;\nb;\n"))


class SelfReferenceTests(unittest.TestCase):
    """comments.parent_id points at comments: a relationship from a table to itself."""

    SQL = """
        CREATE TABLE notes (
            id        INT AUTO_INCREMENT PRIMARY KEY,
            parent_id INT,
            FOREIGN KEY (parent_id) REFERENCES notes(id) ON DELETE CASCADE
        );
    """

    def test_a_nullable_self_reference_is_an_optional_relationship_to_itself(self):
        tables = render_erd.parse_schema(self.SQL)
        self.assertEqual(render_erd.relationships(tables),
                         [render_erd.Relationship("notes", "notes", "parent_id", True)])
        self.assertIn('notes |o--o{ notes : "parent_id"', render_erd.mermaid(tables))

    def test_the_loop_leaves_and_reenters_the_right_side_of_the_box(self):
        # A line from a box to itself would have no length; the loop sits outside it.
        (x1, y1), (x2, y2), (x3, y3), (x4, y4) = render_erd._self_loop_points((100, 50, 200, 300))
        self.assertEqual((x1, x4), (300, 300))                  # on the right edge
        self.assertTrue(50 < y1 < y4 < 350)                     # within the box's height
        self.assertEqual((x2, x3), (300 + render_erd.SELF_LOOP_REACH,) * 2)
        self.assertEqual((y2, y3), (y1, y4))


if __name__ == "__main__":
    unittest.main()
