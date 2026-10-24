from __future__ import annotations

import unittest

from tests.support import FactoryCase
from uaf.errors import IdempotencyConflict, SideEffectError, UnavailableError
from uaf.util import payload_digest


class IdempotencyTests(FactoryCase):
    def test_completed_effect_replays_without_duplicate(self):
        calls = []
        result = self.app.ledger.execute(
            scope="test",
            key="one",
            payload={"x": 1},
            destination="service",
            operation=lambda key: calls.append(key) or {"ok": True},
            supports_idempotency=True,
        )
        replay = self.app.ledger.execute(
            scope="test",
            key="one",
            payload={"x": 1},
            destination="service",
            operation=lambda key: self.fail("must not execute"),
            supports_idempotency=True,
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(replay["status"], "replayed")
        self.assertEqual(len(calls), 1)

    def test_same_key_different_payload_fails_closed(self):
        with self.assertRaises(IdempotencyConflict):
            self.app.ledger.execute(
                scope="test",
                key="one",
                payload={"x": 1},
                destination="service",
                operation=lambda key: {"ok": True},
                supports_idempotency=True,
            )
            self.app.ledger.execute(
                scope="test",
                key="one",
                payload={"x": 2},
                destination="service",
                operation=lambda key: {"ok": True},
                supports_idempotency=True,
            )

    def test_interrupted_non_idempotent_effect_becomes_uncertain(self):
        payload = {"x": 1}
        self.app.ledger._reserve("test", "crash", payload_digest(payload), "service", False)
        with self.assertRaises(UnavailableError):
            self.app.ledger.execute(
                scope="test",
                key="crash",
                payload=payload,
                destination="service",
                operation=lambda key: self.fail("blind retry"),
                supports_idempotency=False,
            )
        entry = self.app.ledger.get("test", "crash")
        self.assertEqual(entry["state"], "uncertain")

    def test_reserved_native_idempotency_can_resume_same_identity(self):
        payload = {"x": 1}
        self.app.ledger._reserve("test", "reserved", payload_digest(payload), "service", True)
        calls = []
        result = self.app.ledger.execute(
            scope="test",
            key="reserved",
            payload=payload,
            destination="service",
            operation=lambda key: calls.append(key) or {"ok": True},
            supports_idempotency=True,
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(calls, ["reserved"])

    def test_timeout_marks_uncertain_and_reconciles(self):
        with self.assertRaises(SideEffectError):
            self.app.ledger.execute(
                scope="test",
                key="timeout",
                payload={"x": 1},
                destination="service",
                operation=lambda key: (_ for _ in ()).throw(TimeoutError("after submit")),
                supports_idempotency=False,
            )
        self.assertEqual(self.app.ledger.get("test", "timeout")["state"], "uncertain")
        result = self.app.ledger.reconcile(
            scope="test",
            key="timeout",
            observed=True,
            evidence={"receipt": "remote-1"},
            result={"remote_id": "remote-1"},
        )
        self.assertEqual(result["state"], "completed")

    def test_reserved_native_idempotency_retries_same_identity(self):
        seen = []
        with self.assertRaises(SideEffectError):
            self.app.ledger.execute(
                scope="test",
                key="native",
                payload={"x": 1},
                destination="service",
                operation=lambda key: (_ for _ in ()).throw(
                    SideEffectError("crash", uncertain=True)
                ),
                supports_idempotency=True,
            )
        # Uncertain still requires reconciliation even when the destination supports keys.
        with self.assertRaises(UnavailableError):
            self.app.ledger.execute(
                scope="test",
                key="native",
                payload={"x": 1},
                destination="service",
                operation=lambda key: seen.append(key) or {"ok": True},
                supports_idempotency=True,
            )
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
