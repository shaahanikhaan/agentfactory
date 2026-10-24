"""Effectively-once side-effect ledger with conservative recovery semantics."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from uaf.db import Database
from uaf.errors import IdempotencyConflict, SideEffectError, UnavailableError, ValidationError
from uaf.util import (
    canonical_json,
    json_data,
    new_id,
    payload_digest,
    redact_data,
    reject_secret_data,
    utc_now,
)


class IdempotencyLedger:
    def __init__(self, db: Database) -> None:
        self.db = db

    def execute(
        self,
        *,
        scope: str,
        key: str,
        payload: dict[str, Any],
        destination: str,
        operation: Callable[[str], dict[str, Any]],
        supports_idempotency: bool,
        remote_receipt: str | None = None,
    ) -> dict[str, Any]:
        if not scope.strip() or not key.strip() or len(key) > 256:
            raise ValidationError("A bounded, non-empty idempotency scope/key is required")
        digest = payload_digest(payload)
        try:
            replay = self._reserve(scope, key, digest, destination, supports_idempotency)
        except UnavailableError:
            # _reserve runs transactionally; persist the conservative state after its
            # exception has unwound that transaction rather than losing it in rollback.
            self.db.execute(
                "UPDATE idempotency_ledger SET state='uncertain',error_json=?,updated_at=? "
                "WHERE scope=? AND key=? AND state='reserved'",
                (canonical_json({"code": "interrupted_unknown_outcome"}), utc_now(), scope, key),
            )
            raise
        if replay is not None:
            return {"status": "replayed", "result": replay, "payload_digest": digest}
        try:
            result = operation(key)
            if not isinstance(result, dict):
                raise SideEffectError(
                    "Side-effect operation returned a non-object result", uncertain=True
                )
            self.complete(scope, key, result, receipt=remote_receipt)
            return {"status": "completed", "result": result, "payload_digest": digest}
        except SideEffectError as exc:
            self.fail(scope, key, str(exc), uncertain=exc.uncertain)
            raise
        except (TimeoutError, ConnectionError) as exc:
            self.fail(scope, key, type(exc).__name__, uncertain=True)
            raise SideEffectError(
                "The side-effect outcome is uncertain; reconcile before retrying", uncertain=True
            ) from exc
        except Exception as exc:
            # Callers performing network/external actions must translate ambiguous failures
            # to SideEffectError(uncertain=True) or TimeoutError/ConnectionError.
            self.fail(scope, key, type(exc).__name__, uncertain=False)
            raise

    def _reserve(
        self, scope: str, key: str, digest: str, destination: str, supports_idempotency: bool
    ) -> dict[str, Any] | None:
        with self.db.transaction():
            row = self.db._conn.execute(
                "SELECT * FROM idempotency_ledger WHERE scope=? AND key=?", (scope, key)
            ).fetchone()
            now = utc_now()
            if not row:
                receipt = new_id("effect")
                self.db._conn.execute(
                    "INSERT INTO idempotency_ledger(scope,key,payload_digest,destination,state,"
                    "attempt_count,receipt,created_at,updated_at) VALUES(?,?,?,?,'reserved',1,?,?,?)",
                    (scope, key, digest, destination, receipt, now, now),
                )
                return None
            if row["payload_digest"] != digest:
                raise IdempotencyConflict("Idempotency key was reused with a different payload")
            if row["state"] == "completed":
                return json_data(row["result_json"], {})
            if row["state"] == "uncertain":
                raise UnavailableError("Prior side effect is uncertain; reconciliation is required")
            if row["state"] == "reserved" and not supports_idempotency:
                self.db._conn.execute(
                    "UPDATE idempotency_ledger SET state='uncertain',error_json=?,updated_at=? "
                    "WHERE scope=? AND key=?",
                    (
                        canonical_json({"code": "interrupted_unknown_outcome"}),
                        now,
                        scope,
                        key,
                    ),
                )
                raise UnavailableError(
                    "An interrupted non-idempotent action cannot be retried automatically"
                )
            self.db._conn.execute(
                "UPDATE idempotency_ledger SET state='reserved',attempt_count=attempt_count+1,"
                "updated_at=? WHERE scope=? AND key=?",
                (now, scope, key),
            )
            return None

    def complete(
        self, scope: str, key: str, result: dict[str, Any], *, receipt: str | None = None
    ) -> None:
        with self.db.transaction():
            cursor = self.db._conn.execute(
                "UPDATE idempotency_ledger SET state='completed',result_json=?,"
                "receipt=COALESCE(?,receipt),error_json=NULL,updated_at=? WHERE scope=? AND key=?",
                (canonical_json(redact_data(result)), receipt, utc_now(), scope, key),
            )
            if cursor.rowcount != 1:
                raise ValidationError("Cannot complete a missing idempotency reservation")

    def fail(self, scope: str, key: str, error: str, *, uncertain: bool) -> None:
        state = "uncertain" if uncertain else "failed"
        self.db.execute(
            "UPDATE idempotency_ledger SET state=?,error_json=?,updated_at=? WHERE scope=? AND key=?",
            (
                state,
                canonical_json({"message": error[:500], "uncertain": uncertain}),
                utc_now(),
                scope,
                key,
            ),
        )

    def reconcile(
        self,
        *,
        scope: str,
        key: str,
        observed: bool,
        evidence: dict[str, Any],
        result: dict[str, Any] | None = None,
        actor: str = "local-human",
    ) -> dict[str, Any]:
        if not isinstance(observed, bool):
            raise ValidationError("Reconciliation observation must be boolean")
        if (
            not isinstance(actor, str)
            or not actor.strip()
            or len(actor) > 200
            or actor.lower() in {"manager", "planner", "supervisor", "worker", "reviewer", "runtime", "system"}
        ):
            raise ValidationError("Reconciliation requires a bounded human actor identity")
        if not isinstance(evidence, dict) or len(canonical_json(evidence)) > 8_000:
            raise ValidationError("Reconciliation evidence must be a bounded JSON object")
        reject_secret_data(evidence, label="reconciliation evidence")
        if result is not None and not isinstance(result, dict):
            raise ValidationError("Reconciled result must be an object")
        row = self.get(scope, key)
        if not row:
            raise ValidationError("Unknown idempotency entry")
        if row["state"] not in {"uncertain", "reserved"}:
            raise UnavailableError(f"Cannot reconcile an entry in {row['state']}")
        if observed:
            self.complete(scope, key, result or {"observed": True}, receipt=evidence.get("receipt"))
            state = "completed"
        else:
            self.db.execute(
                "UPDATE idempotency_ledger SET state='failed',error_json=?,updated_at=? "
                "WHERE scope=? AND key=?",
                (
                    canonical_json(
                        {"code": "reconciled_not_executed", "evidence": redact_data(evidence)}
                    ),
                    utc_now(),
                    scope,
                    key,
                ),
            )
            state = "failed"
        self.db.audit(
            "idempotency.reconcile",
            actor=actor,
            role="human",
            object_type="idempotency",
            object_id=f"{scope}:{key}",
            decision=state,
            metadata=evidence,
        )
        return self.get(scope, key) or {}

    def get(self, scope: str, key: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM idempotency_ledger WHERE scope=? AND key=?", (scope, key))
        if row:
            row["result"] = json_data(row["result_json"], None)
            row["error"] = json_data(row["error_json"], None)
        return row

    def for_task(self, task_id: str) -> list[dict[str, Any]]:
        if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 200:
            raise ValidationError("A bounded task ID is required")
        rows = self.db.query(
            "SELECT * FROM idempotency_ledger WHERE scope=? ORDER BY created_at,key",
            (f"task:{task_id}",),
        )
        for row in rows:
            row["result"] = json_data(row["result_json"], None)
            row["error"] = json_data(row["error_json"], None)
        return rows
