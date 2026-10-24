from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.support import FactoryCase
from uaf.errors import IntegrityError, PolicyDenied, UnavailableError, ValidationError


class ExtensionTests(FactoryCase):
    def manifest(self):
        source = (
            Path(__file__).parent.parent / "examples" / "plugins" / "note-writer" / "plugin.json"
        )
        target = self.paths.plugins / "note-writer" / "plugin.json"
        target.parent.mkdir(parents=True)
        target.write_bytes(source.read_bytes())
        return target

    def test_skills_progressive_disclosure_and_tamper_detection(self):
        rows = self.app.skills.list()
        self.assertGreaterEqual(len(rows), 2)
        self.assertTrue(all(not row["body_loaded"] for row in rows))
        loaded = self.app.skills.load("verified-research")
        self.assertIn("primary", loaded["body"])
        body = Path(
            self.db.one("SELECT body_path FROM skill_registry WHERE skill_id='verified-research'")[
                "body_path"
            ]
        )
        original = body.read_bytes()
        try:
            body.write_text("tampered")
            with self.assertRaises(IntegrityError):
                self.app.skills.load("verified-research")
        finally:
            body.write_bytes(original)

    def test_plugin_disabled_until_explicit_enable(self):
        self.app.plugins.register(self.manifest())
        with self.assertRaises(UnavailableError):
            self.app.plugins.render("note-writer", {"name": "x", "content": "y"})
        self.app.plugins.enable("note-writer", confirmed=True)
        rendered = self.app.plugins.render("note-writer", {"name": "x", "content": "y"})
        self.assertEqual(rendered["arguments"]["path"], "notes/x.md")
        self.app.plugins.disable("note-writer")
        with self.assertRaises(UnavailableError):
            self.app.plugins.render("note-writer", {"name": "x", "content": "y"})

    def test_plugin_manifest_tampering_fails_closed(self):
        path = self.manifest()
        self.app.plugins.register(path)
        self.app.plugins.enable("note-writer", confirmed=True)
        value = json.loads(path.read_text())
        value["workflow"]["arguments"]["path"] = "../{{name}}.md"
        path.write_text(json.dumps(value))
        with self.assertRaises(IntegrityError):
            self.app.plugins.render("note-writer", {"name": "x", "content": "y"})
        self.assertFalse(self.app.plugins.list()[0]["enabled"])

    def test_python_plugin_is_not_auto_imported(self):
        path = self.manifest()
        value = json.loads(path.read_text())
        value["kind"] = "python"
        path.write_text(json.dumps(value))
        with self.assertRaises(PolicyDenied):
            self.app.plugins.register(path)

    def test_plugin_input_schema_is_validated(self):
        self.app.plugins.register(self.manifest())
        self.app.plugins.enable("note-writer", confirmed=True)
        with self.assertRaises(ValidationError):
            self.app.plugins.render("note-writer", {"name": "x", "unexpected": "y"})


if __name__ == "__main__":
    unittest.main()
