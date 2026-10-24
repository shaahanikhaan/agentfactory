from __future__ import annotations

import json
import unittest
from datetime import date, timedelta

from tests.support import FactoryCase, FakeAdapter, FakeKeyring
from uaf.credentials import CredentialStore
from uaf.errors import UnavailableError, ValidationError
from uaf.onboarding import GeminiOnboarding
from uaf.providers import GenerateRequest, ProviderService


class FakeDiscoveryHttp:
    def __init__(self):
        self.calls = []

    def get_json(self, url, *, headers, timeout):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        return {
            "models": [
                {
                    "name": "models/gemini-test-free",
                    "displayName": "Test Gemini",
                    "supportedGenerationMethods": ["generateContent"],
                    "inputTokenLimit": 128000,
                    "outputTokenLimit": 8192,
                },
                {
                    "name": "models/embed-only",
                    "supportedGenerationMethods": ["embedContent"],
                    "inputTokenLimit": 1000,
                    "outputTokenLimit": 100,
                },
                {
                    "name": "models/missing-limits",
                    "supportedGenerationMethods": ["generateContent"],
                },
            ]
        }


class OnboardingTests(FactoryCase):
    def setUp(self):
        super().setUp()
        self.keyring = FakeKeyring()
        self.vault = CredentialStore(keyring_module=self.keyring)
        self.http = FakeDiscoveryHttp()
        self.onboarding = GeminiOnboarding(self.app.config, self.vault, http=self.http)
        self.secret = "AIza" + "k" * 32

    def discover(self):
        return self.onboarding.discover(self.secret, network_confirmed=True)

    def test_discovery_is_bounded_and_does_not_infer_free_eligibility(self):
        with self.assertRaises(UnavailableError):
            self.onboarding.discover(self.secret, network_confirmed=False)
        self.assertEqual(self.http.calls, [])
        models = self.discover()
        self.assertEqual([item["model"] for item in models], ["gemini-test-free"])
        self.assertEqual(models[0]["free_tier_status"], "unverified")
        self.assertNotIn(self.secret, self.http.calls[0]["url"])
        self.assertEqual(self.http.calls[0]["headers"]["x-goog-api-key"], self.secret)

    def test_one_key_completion_enables_only_gemini_without_file_secrets(self):
        discovered = self.discover()
        with self.assertRaises(ValidationError):
            self.onboarding.complete(
                self.secret, discovered, model="gemini-test-free", free_confirmed=False
            )
        self.assertIsNone(self.vault.get("gemini"))
        result = self.onboarding.complete(
            self.secret,
            discovered,
            model="gemini-test-free",
            free_confirmed=True,
            verified_at=date.today().isoformat(),
        )
        self.assertEqual(result["other_provider_keys_required"], [])
        self.assertFalse(result["live_generation_tested"])
        settings = self.app.config.load()
        self.assertTrue(settings.network_allowed)
        self.assertTrue(settings.providers["gemini"]["enabled"])
        self.assertFalse(settings.providers["groq"]["enabled"])
        self.assertEqual(list(settings.providers["gemini"]["models"]), ["gemini-test-free"])
        self.assertNotIn(self.secret, self.paths.config.read_text())
        adapter = FakeAdapter()
        providers = ProviderService(
            settings,
            self.db,
            environ={},
            adapters={"gemini": adapter},
            credential_store=self.vault,
        )
        row = next(row for row in providers.list_models() if row["model"] == "gemini-test-free")
        self.assertTrue(row["eligible"], row["reason"])
        response = providers.generate(
            GenerateRequest(
                task_id="setup-test",
                role="worker",
                system="system",
                prompt="prompt",
                provider="gemini",
                model="gemini-test-free",
            )
        )
        self.assertEqual(response.text, "worker answer")
        self.assertEqual(adapter.calls[0][2], self.secret)
        self.assertNotIn(self.secret, json.dumps(self.db.query("SELECT * FROM provider_configs")))

    def test_unofficial_source_stale_date_and_undiscovered_model_are_rejected(self):
        discovered = self.discover()
        cases = [
            {
                "model": "gemini-test-free",
                "free_confirmed": True,
                "source": "https://attacker.example/free",
            },
            {
                "model": "gemini-test-free",
                "free_confirmed": True,
                "source": "https://ai.google.dev/gemini-api/docs/pricing?api_key=do-not-store",
            },
            {
                "model": "gemini-test-free",
                "free_confirmed": True,
                "verified_at": (date.today() - timedelta(days=60)).isoformat(),
            },
            {"model": "not-discovered", "free_confirmed": True},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                self.onboarding.complete(self.secret, discovered, **kwargs)
        malformed = [dict(discovered[0], context_limit=True)]
        with self.assertRaises(ValidationError):
            self.onboarding.complete(
                self.secret,
                malformed,
                model="gemini-test-free",
                free_confirmed=True,
            )
        self.assertIsNone(self.vault.get("gemini"))

    def test_failed_config_save_rolls_back_new_credential_and_settings(self):
        discovered = self.discover()
        original_save = self.app.config.save
        calls = 0

        def flaky_save(settings):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("simulated config write failure")
            original_save(settings)

        self.app.config.save = flaky_save
        with self.assertRaises(OSError):
            self.onboarding.complete(
                self.secret,
                discovered,
                model="gemini-test-free",
                free_confirmed=True,
                verified_at=date.today().isoformat(),
            )
        self.assertIsNone(self.vault.get("gemini"))
        restored = self.app.config.load()
        self.assertFalse(restored.network_allowed)
        self.assertFalse(restored.providers["gemini"]["enabled"])


if __name__ == "__main__":
    unittest.main()
