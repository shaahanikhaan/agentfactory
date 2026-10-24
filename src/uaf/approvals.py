"""Human approval requests bound to an exact action payload and expiry."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from uaf.db import Database
from uaf.errors import PolicyDenied, StateTransitionError, UnavailableError, ValidationError
from uaf.models import RiskTier
from uaf.util import (
    bounded,
    canonical_json,
    json_data,
    new_id,
    now_dt,
    parse_time,
    payload_digest,
    redact_data,
    utc_now,
)

_AGENT_ACTORS = {"manager", "planner", "supervisor", "worker", "reviewer", "runtime", "system"}


class ApprovalService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        *,
        task_id: str,
        action_type: str,
        payload: dict[str, Any],
        summary: str,
        destination: str,
        risk_tier: RiskTier | str,
        requester: str,
        expires_minutes: int = 30,
    ) -> dict[str, Any]:
        risk = RiskTier(risk_tier)
        if risk not in {RiskTier.R2, RiskTier.R3}:
            raise ValidationError("Approval requests are only for R2/R3 actions")
        if not 1 <= expires_minutes <= 24 * 60:
            raise ValidationError("Approval expiry must be between 1 minute and 24 hours")
        bounded(summary, 2_000, label="approval summary")
        digest = payload_digest(
            {"action": action_type, "destination": destination, "payload": payload}
        )
        with self.db.transaction():
            existing = self.db._conn.execute(
                "SELECT * FROM approval_requests WHERE task_id=? AND action_digest=? "
                "AND state='pending' ORDER BY created_at DESC LIMIT 1",
                (task_id, digest),
            ).fetchone()
            if existing:
                return self._decode(dict(existing))
            approval_id = new_id("approval")
            created = now_dt()
            self.db._conn.execute(
                "INSERT INTO approval_requests(approval_id,task_id,action_type,action_digest,"
                "action_summary,payload_json,destination,risk_tier,requester,state,created_at,expires_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,'pending',?,?)",
                (
                    approval_id,
                    task_id,
                    action_type,
                    digest,
                    summary,
                    canonical_json(redact_data(payload)),
                    destination,
                    risk.value,
                    requester,
                    utc_now(),
                    (created + timedelta(minutes=expires_minutes))
                    .isoformat(timespec="milliseconds")
                    .replace("+00:00", "Z"),
                ),
            )
            self.db.audit(
                "approval.request",
                actor=requester,
                role="runtime",
                object_type="approval",
                object_id=approval_id,
                decision="pending",
                metadata={"risk": risk.value, "action": action_type, "digest": digest},
            )
        return self.get(approval_id) or {}

    @staticmethod
    def _decode(row: dict[str, Any]) -> dict[str, Any]:
        row["payload"] = json_data(row.get("payload_json"), {})
        return row

    def get(self, approval_id: str) -> dict[str, Any] | None:
        self._expire()
        row = self.db.one("SELECT * FROM approval_requests WHERE approval_id=?", (approval_id,))
        return self._decode(row) if row else None

    def require(self, approval_id: str) -> dict[str, Any]:
        row = self.get(approval_id)
        if not row:
            raise ValidationError(f"Unknown approval: {approval_id}")
        return row

    def list(self, state: str | None = None) -> list[dict[str, Any]]:
        self._expire()
        if state:
            if state not in {"pending", "approved", "rejected", "expired"}:
                raise ValidationError("Invalid approval state")
            rows = self.db.query(
                "SELECT * FROM approval_requests WHERE state=? ORDER BY created_at DESC", (state,)
            )
        else:
            rows = self.db.query("SELECT * FROM approval_requests ORDER BY created_at DESC")
        return [self._decode(row) for row in rows]

    def _expire(self) -> None:
        self.db.execute(
            "UPDATE approval_requests SET state='expired',decided_at=? "
            "WHERE state='pending' AND expires_at<=?",
            (utc_now(), utc_now()),
        )

    def decide(
        self, approval_id: str, *, approve: bool, actor: str, reason: str = ""
    ) -> dict[str, Any]:
        if actor.lower() in _AGENT_ACTORS:
            raise PolicyDenied("An agent or planner cannot approve a high-risk action")
        bounded(reason, 2_000, label="decision reason")
        with self.db.transaction():
            row = self.db._conn.execute(
                "SELECT * FROM approval_requests WHERE approval_id=?", (approval_id,)
            ).fetchone()
            if not row:
                raise ValidationError(f"Unknown approval: {approval_id}")
            if row["state"] != "pending":
                raise StateTransitionError(f"Approval is already {row['state']}")
            if parse_time(row["expires_at"]) <= now_dt():
                self.db._conn.execute(
                    "UPDATE approval_requests SET state='expired',decided_at=? WHERE approval_id=?",
                    (utc_now(), approval_id),
                )
                raise UnavailableError("Approval has expired; request a fresh review")
            state = "approved" if approve else "rejected"
            self.db._conn.execute(
                "UPDATE approval_requests SET state=?,approver=?,reason=?,decided_at=? "
                "WHERE approval_id=? AND state='pending'",
                (state, actor, reason, utc_now(), approval_id),
            )
            self.db.audit(
                "approval.decision",
                actor=actor,
                role="human",
                object_type="approval",
                object_id=approval_id,
                decision=state,
                metadata={"action_digest": row["action_digest"], "reason": reason},
            )
        return self.require(approval_id)

    def is_approved(self, task_id: str, action_type: str, destination: str, payload: dict) -> bool:
        digest = payload_digest(
            {"action": action_type, "destination": destination, "payload": payload}
        )
        row = self.db.one(
            "SELECT state,expires_at FROM approval_requests WHERE task_id=? AND action_digest=? "
            "AND state='approved' ORDER BY decided_at DESC LIMIT 1",
            (task_id, digest),
        )
        return bool(row and parse_time(row["expires_at"]) > now_dt())

    def pending_for_task(self, task_id: str) -> list[dict[str, Any]]:
        return [row for row in self.list("pending") if row["task_id"] == task_id]
