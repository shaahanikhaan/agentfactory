from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from tests.support import FakeKeyring
from uaf.cli import main
from uaf.credentials import CredentialStore
from uaf.onboarding import GeminiOnboarding


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = str(Path(self.temporary.name) / "home")

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--home", self.home, *args, "--json"])
        return code, output.getvalue()

    def test_init_task_smoke_status_and_capabilities(self):
        code, raw = self.invoke("init")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(raw)["initialized"])
        code, raw = self.invoke("task", "add", "CLI offline smoke", "--kind", "smoke")
        task = json.loads(raw)
        code, raw = self.invoke("task", "run", task["task_id"])
        result = json.loads(raw)
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(result["result"]["evidence"]["model_calls"], 0)
        code, raw = self.invoke("status")
        self.assertEqual(json.loads(raw)["tasks"]["succeeded"], 1)
        code, raw = self.invoke("capabilities")
        self.assertIn("capabilities", json.loads(raw))

    def test_cloud_configure_requires_explicit_free_confirmation(self):
        self.invoke("init")
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            code = main(
                ["--home", self.home, "provider", "configure", "gemini", "some-model", "--json"]
            )
        self.assertEqual(code, 2)
        self.assertIn("confirm-free", errors.getvalue())

    def test_one_key_setup_uses_vault_and_no_other_provider_keys(self):
        secret = "AIza" + "c" * 32
        store = CredentialStore(keyring_module=FakeKeyring())
        http = Mock()
        http.get_json.return_value = {
            "models": [
                {
                    "name": "models/gemini-test-free",
                    "displayName": "Test Gemini",
                    "supportedGenerationMethods": ["generateContent"],
                    "inputTokenLimit": 128000,
                    "outputTokenLimit": 8192,
                }
            ]
        }

        def onboarding(config, credentials):
            return GeminiOnboarding(config, credentials, http=http)

        with patch("uaf.app.CredentialStore", return_value=store), patch(
            "uaf.cli.GeminiOnboarding", side_effect=onboarding
        ), patch.dict("os.environ", {"GEMINI_API_KEY": secret}):
            code, raw = self.invoke(
                "setup",
                "--model",
                "gemini-test-free",
                "--online",
                "--confirm-free",
                "--verified-at",
                date.today().isoformat(),
            )
            self.assertEqual(code, 0, raw)
            result = json.loads(raw)
            self.assertTrue(result["setup_complete"])
            self.assertTrue(result["eligibility"]["eligible"])
            self.assertEqual(result["other_provider_keys_required"], [])
            self.assertFalse(result["live_generation_tested"])
            self.assertNotIn(secret, raw)
            config = (Path(self.home) / "config.json").read_text()
            self.assertNotIn(secret, config)
            self.assertEqual(store.get("gemini"), secret)

    def test_invalid_command_fails_without_traceback_by_default(self):
        self.invoke("init")
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            code = main(["--home", self.home, "task", "show", "missing", "--json"])
        self.assertEqual(code, 2)
        self.assertIn("Unknown task", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
