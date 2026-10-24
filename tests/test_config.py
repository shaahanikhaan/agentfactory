from __future__ import annotations

import json
import unittest

from tests.support import FactoryCase
from uaf.config import AppPaths, Budgets, Settings
from uaf.errors import ValidationError


class ConfigTests(FactoryCase):
    def test_safe_defaults(self):
        self.assertFalse(self.app.settings.network_allowed)
        self.assertFalse(self.app.settings.allow_paid)
        self.assertEqual(self.app.settings.budgets.max_workers, 1)
        self.assertEqual(self.app.settings.budgets.max_llm_concurrency, 1)

    def test_secret_values_cannot_be_written_to_config(self):
        with self.assertRaises(ValidationError):
            self.app.config._reject_secrets({"providers": {"x": {"api_key": "do-not-store"}}})
        raw = json.loads(self.paths.config.read_text())
        # Variable NAMES are allowed; raw credential VALUES are not.
        self.assertEqual(raw["providers"]["gemini"]["credential_env"], "GEMINI_API_KEY")
        self.assertNotIn("test-secret", json.dumps(raw))

    def test_paid_mode_fails_closed(self):
        with self.assertRaises(ValidationError):
            Settings.from_dict({"workspace": "/tmp/x", "allow_paid": True})
        with self.assertRaises(ValidationError):
            self.app.config.set("allow_paid", True)

    def test_budget_validation(self):
        with self.assertRaises(ValidationError):
            Budgets(max_workers=0).validate()
        with self.assertRaises(ValidationError):
            Budgets(max_workers=100).validate()
        with self.assertRaises(ValidationError):
            self.app.config.set("budgets.max_steps", "not-an-int")

    def test_workspace_change_does_not_assume_drive_letter(self):
        changed = self.app.config.set("workspace", str(self.root / "removable" / "project"))
        self.assertTrue(changed.workspace.endswith("project"))
        self.assertFalse(changed.workspace_path.exists())

    def test_explicit_home_is_used(self):
        paths = AppPaths.discover(self.root / "elsewhere")
        self.assertEqual(paths.home, (self.root / "elsewhere").absolute())

    def test_computer_use_defaults_and_round_trip(self):
        self.assertFalse(self.app.settings.browser_enabled)
        self.assertFalse(self.app.settings.desktop_enabled)
        settings = self.app.config.set("browser_allowed_domains", ["example.com", "*.example.org"])
        self.assertEqual(settings.browser_allowed_domains, ["example.com", "*.example.org"])
        settings = self.app.config.set("desktop_allowed_applications", ["notepad.exe"])
        self.assertEqual(settings.desktop_allowed_applications, ["notepad.exe"])
        restored = Settings.from_dict(json.loads(self.paths.config.read_text()))
        self.assertEqual(restored.desktop_max_actions_per_batch, 12)

    def test_computer_use_configuration_rejects_ambiguous_values(self):
        for key, value in (
            ("browser_enabled", "true"),
            ("desktop_enabled", 1),
            ("browser_allowed_domains", ["https://example.com"]),
            ("browser_allowed_domains", ["EXAMPLE.COM"]),
            ("desktop_max_actions_per_batch", 21),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(ValidationError):
                self.app.config.set(key, value)
        with self.assertRaises(ValidationError):
            Settings.from_dict({"workspace": "/tmp/x", "desktop_max_actions_per_batch": True})
        with self.assertRaises(ValidationError):
            Settings(workspace="/tmp/x", browser_enabled="true").validate()


if __name__ == "__main__":
    unittest.main()
