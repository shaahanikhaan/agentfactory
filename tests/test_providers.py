from __future__ import annotations

import unittest
from datetime import date, timedelta

from tests.support import FactoryCase, FakeAdapter
from uaf.errors import ProviderError, UnavailableError
from uaf.providers import GenerateRequest
from uaf.providers.gemini import GeminiAdapter
from uaf.providers.http import parse_retry_after
from uaf.providers.openai_compat import OpenAICompatibleAdapter


class ProviderTests(FactoryCase):
    def request(self, **kwargs):
        return GenerateRequest(
            task_id="task", role="worker", system="system", prompt="prompt", **kwargs
        )

    def test_default_has_no_eligible_cloud_model(self):
        with self.assertRaises(UnavailableError):
            self.app.providers.generate(self.request())

    def test_cloud_requires_explicit_network(self):
        self.install_fake()
        self.app.settings.network_allowed = False
        with self.assertRaises(UnavailableError) as caught:
            self.app.providers.generate(self.request())
        self.assertIn("offline", str(caught.exception))

    def test_stale_or_unverified_free_terms_fail_closed(self):
        self.install_fake(verified_at=(date.today() - timedelta(days=60)).isoformat())
        with self.assertRaises(UnavailableError):
            self.app.providers.generate(self.request())
        self.app.settings.providers["gemini"]["models"]["fake-free"]["verified_at"] = (
            date.today().isoformat()
        )
        self.app.settings.providers["gemini"]["models"]["fake-free"]["free_tier_status"] = "paid"
        with self.assertRaises(UnavailableError):
            self.app.providers.generate(self.request())

    def test_unofficial_free_source_fails_closed(self):
        self.install_fake(free_tier_source="https://attacker.example/free")
        with self.assertRaises(UnavailableError):
            self.app.providers.generate(self.request())

    def test_openrouter_requires_explicit_free_suffix(self):
        adapter = FakeAdapter()
        adapter.name = "openrouter"
        from uaf.providers import ProviderService

        self.app.settings.network_allowed = True
        self.app.settings.providers["openrouter"].update(
            {
                "enabled": True,
                "models": {
                    "paid-model": {
                        "free_tier_status": "free",
                        "verified_at": date.today().isoformat(),
                        "free_tier_source": "https://openrouter.ai/docs/api_reference/limits",
                    }
                },
            }
        )
        service = ProviderService(
            self.app.settings,
            self.db,
            environ={"OPENROUTER_API_KEY": "secret"},
            adapters={"openrouter": adapter},
        )
        with self.assertRaises(UnavailableError):
            service.generate(self.request(provider="openrouter"))

    def test_success_records_usage_without_storing_secret(self):
        self.install_fake()
        response = self.app.providers.generate(self.request())
        self.assertEqual(response.text, "worker answer")
        self.assertEqual(self.db.one("SELECT COUNT(*) c FROM quota_observations")["c"], 1)
        rows = self.db.query("SELECT * FROM provider_configs")
        self.assertNotIn("test-secret", str(rows))

    def test_rate_limit_honors_retry_after_and_persists_cooldown(self):
        adapter = self.install_fake(
            [
                ProviderError(
                    "limited", kind="rate_limit", retryable=True, retry_after=120, status=429
                )
            ]
        )
        with self.assertRaises(UnavailableError):
            self.app.providers.generate(self.request())
        cooldowns = self.app.providers.cooldowns()
        self.assertEqual(len(cooldowns), 1)
        self.assertEqual(len(adapter.calls), 1)
        with self.assertRaises(UnavailableError):
            self.app.providers.generate(self.request())
        self.assertEqual(len(adapter.calls), 1)

    def test_transient_error_has_bounded_retry(self):
        adapter = self.install_fake(
            [ProviderError("down", kind="provider_unavailable", retryable=True), "recovered"]
        )
        response = self.app.providers.generate(self.request())
        self.assertEqual(response.text, "recovered")
        self.assertEqual(len(adapter.calls), 2)

    def test_permanent_error_is_not_retried(self):
        adapter = self.install_fake([ProviderError("bad key", kind="invalid_credentials")])
        with self.assertRaises(UnavailableError):
            self.app.providers.generate(self.request())
        self.assertEqual(len(adapter.calls), 1)

    def test_output_budget_is_not_silently_truncated(self):
        self.install_fake(["x" * 100])
        with self.assertRaises(UnavailableError):
            self.app.providers.generate(self.request(max_output_chars=10))

    def test_daily_call_budget(self):
        self.install_fake()
        self.app.settings.budgets.max_daily_calls = 1
        self.app.providers.generate(self.request())
        with self.assertRaises(UnavailableError):
            self.app.providers.generate(self.request())

    def test_retry_after_date_and_seconds(self):
        self.assertEqual(parse_retry_after("2"), 2)
        self.assertIsNone(parse_retry_after("not-a-date"))

    def test_gemini_and_openai_response_parsing(self):
        class HTTP:
            def __init__(self, value):
                self.value = value
                self.bodies = []

            def post_json(self, *args, **kwargs):
                self.bodies.append(kwargs)
                return self.value

        gemini_http = HTTP({"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})
        spec = self.app.providers._spec(
            "gemini", "fake-free", {"free_tier_status": "free", "capabilities": ["text"]}
        )
        gemini = GeminiAdapter(gemini_http)
        self.assertEqual(gemini.generate(spec, self.request(), "secret").text, "ok")
        self.assertNotIn("secret", str(gemini_http.bodies[0]["body"]))
        openai_http = HTTP({"choices": [{"message": {"content": "ok"}}]})
        openai = OpenAICompatibleAdapter(
            "groq", "https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY", openai_http
        )
        self.assertEqual(openai.generate(spec, self.request(), "secret").text, "ok")


if __name__ == "__main__":
    unittest.main()
