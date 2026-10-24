from __future__ import annotations

import unittest

from tests.support import FactoryCase, FakeAdapter, FakeKeyring
from uaf.credentials import CredentialStore
from uaf.errors import UnavailableError, ValidationError
from uaf.providers import ProviderService


class CredentialStoreTests(unittest.TestCase):
    def test_os_vault_round_trip_has_non_secret_status(self):
        keyring = FakeKeyring()
        store = CredentialStore(keyring_module=keyring)
        secret = "AIza" + "a" * 32
        store.set("gemini", secret)
        self.assertEqual(store.get("gemini"), secret)
        status = store.status()
        self.assertTrue(status["available"])
        self.assertTrue(status["gemini_present"])
        self.assertNotIn(secret, str(status))
        self.assertTrue(store.delete("gemini"))
        self.assertFalse(store.delete("gemini"))
        self.assertIsNone(store.get("gemini"))

    def test_insecure_or_unavailable_backends_fail_closed(self):
        class PlaintextBackend:
            pass

        class Keyring:
            def get_keyring(self):
                return PlaintextBackend()

        store = CredentialStore(keyring_module=Keyring())
        with self.assertRaises(UnavailableError):
            store.set("gemini", "AIza" + "a" * 32)
        self.assertIsNone(store.get("gemini"))
        self.assertFalse(store.status()["available"])

    def test_secret_shape_and_provider_are_validated(self):
        store = CredentialStore(keyring_module=FakeKeyring())
        for value in ("short", "has whitespace " + "x" * 20, "x" * 513):
            with self.subTest(value=len(value)), self.assertRaises(ValidationError):
                store.set("gemini", value)
        with self.assertRaises(ValidationError):
            store.set("ollama", "x" * 20)


class CredentialRoutingTests(FactoryCase):
    def test_environment_precedes_vault_and_vault_is_fallback(self):
        adapter = FakeAdapter()
        self.install_fake(adapter)
        vault = CredentialStore(keyring_module=FakeKeyring())
        vault.set("gemini", "AIza" + "v" * 32)
        common = {
            "settings": self.app.settings,
            "db": self.db,
            "adapters": {"gemini": adapter},
            "credential_store": vault,
        }
        environment = ProviderService(
            **common, environ={"GEMINI_API_KEY": "AIza" + "e" * 32}
        )
        self.assertEqual(environment._api_key("gemini"), "AIza" + "e" * 32)
        fallback = ProviderService(**common, environ={})
        self.assertEqual(fallback._api_key("gemini"), "AIza" + "v" * 32)
        self.assertEqual(vault.get("gemini"), "AIza" + "v" * 32)


if __name__ == "__main__":
    unittest.main()
