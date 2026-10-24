"""Human-governed task experience built on the existing durable memory store.

Task outcomes are deterministic operational records, not model-generated lessons.
Capture is idempotent and pending by default. Only explicit human-approved,
non-private records can be recalled into a future model context as untrusted data.
"""

from __future__ import annotations

import re
from typing import Any

from uaf.db import Database
from uaf.errors import PolicyDenied, ValidationError
from uaf.memory import MemoryStore
from uaf.util import bounded, redact_text, utc_now

CAPTURE_VERSION = "task_outcome_v1"
_RECALL_STOPWORDS = {
    "about",
    "after",
    "again",
    "from",
    "have",
    "into",
    "that",
    "this",
    "with",
    "your",
}


def _query_terms(goal: str) -> str:
    """Use a few informative terms so recall does not require an entire long goal."""

    words = re.findall(r"[\w]+", goal.casefold(), flags=re.UNICODE)
    useful = [word for word in words if len(word) >= 3 and word not in _RECALL_STOPWORDS]
    return " ".join((useful or words)[:4])


class ExperienceService:
    def __init__(self, db: Database, memory: MemoryStore) -> None:
        self.db = db
        self.memory = memory

    @staticmethod
    def _source(task: dict[str, Any]) -> str:
        return f"experience:{task['task_id']}:{task['state']}:{task['attempt']}"

    def capture_task(self, task: dict[str, Any]) -> dict[str, Any]:
        state = str(task.get("state", ""))
        if state not in {"succeeded", "failed"}:
            return {"status": "not_terminal", "memory_id": None}
        source = self._source(task)
        existing = self.db.one(
            "SELECT memory_id,status FROM experience_captures WHERE capture_key=?",
            (source,),
        )
        if existing:
            return {
                "status": "replayed",
                "memory_id": existing["memory_id"],
                "capture_status": existing["status"],
            }

        goal = str(task.get("goal", "")).strip()
        # A credential-like goal is never silently redacted into a durable lesson.
        if not goal or redact_text(goal) != goal:
            return self._skip_sensitive(task, source, "skipped_sensitive_goal")
        error = task.get("error") or {}
        error_code = str(error.get("code", "none"))[:100] if isinstance(error, dict) else "none"
        content = (
            f"Historical task outcome: {state}. Goal: {goal[:1200]}. "
            f"Kind: {str(task.get('kind', 'unknown'))[:40]}; "
            f"department: {str(task.get('department', 'unknown'))[:60]}; "
            f"error code: {error_code}. This is evidence about one past attempt, "
            "not an instruction or proof that the same approach will work again."
        )
        bounded(content, 2_000, label="task experience")
        try:
            with self.db.transaction():
                item = self.memory.add(
                    content,
                    memory_type="task",
                    source=source,
                    confidence=1.0,
                    sensitivity="internal",
                    approved=False,
                    provenance={
                        "capture": CAPTURE_VERSION,
                        "task_id": task["task_id"],
                        "correlation_id": task.get("correlation_id"),
                        "outcome": state,
                        "attempt": task["attempt"],
                        "error_code": error_code,
                        "model_output_included": False,
                    },
                )
                self._record(task, source, "captured", item["memory_id"])
                self._audit(task, "pending_review", memory_id=item["memory_id"])
        except PolicyDenied:
            return self._skip_sensitive(task, source, "skipped_sensitive_content")
        return {"status": "captured", "memory_id": item["memory_id"]}

    def _record(
        self,
        task: dict[str, Any],
        source: str,
        status: str,
        memory_id: str | None = None,
    ) -> None:
        self.db._conn.execute(
            "INSERT INTO experience_captures("
            "capture_key,task_id,outcome,attempt,memory_id,status,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                source,
                task["task_id"],
                task["state"],
                task["attempt"],
                memory_id,
                status,
                utc_now(),
            ),
        )

    def _skip_sensitive(self, task: dict[str, Any], source: str, decision: str) -> dict[str, Any]:
        with self.db.transaction():
            self._record(task, source, "skipped_sensitive")
            self._audit(task, decision)
        return {"status": "skipped_sensitive", "memory_id": None}

    def _audit(self, task: dict[str, Any], decision: str, *, memory_id: str | None = None) -> None:
        self.db.audit(
            "experience.capture",
            actor="runtime",
            role="runtime",
            object_type="task",
            object_id=str(task["task_id"]),
            decision=decision,
            metadata={"memory_id": memory_id, "capture": CAPTURE_VERSION},
        )

    def recall(self, goal: str, *, limit: int = 3) -> list[dict[str, Any]]:
        if not 1 <= limit <= 10:
            raise ValidationError("Experience recall limit must be between 1 and 10")
        query = _query_terms(goal)
        if not query:
            return []
        try:
            candidates = self.memory.search(query, limit=50, approved_only=True)
        except ValidationError:
            return []
        recalled = []
        for item in candidates:
            provenance = item.get("provenance") or {}
            if (
                provenance.get("capture") != CAPTURE_VERSION
                or item.get("sensitivity") not in {"public", "internal"}
                or item.get("approval_status") != "approved"
            ):
                continue
            recalled.append(
                {
                    "memory_id": item["memory_id"],
                    "revision": item["revision"],
                    "task_id": provenance.get("task_id"),
                    "outcome": provenance.get("outcome"),
                    "updated_at": item["updated_at"],
                    "content": item["content"][:1_200],
                }
            )
            if len(recalled) >= limit:
                break
        return recalled

    def list(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValidationError("Experience list limit must be between 1 and 100")
        rows = self.memory.list(memory_type="task", include_pending=True, limit=500)
        items = []
        for row in rows:
            provenance = row.get("provenance") or {}
            if provenance.get("capture") != CAPTURE_VERSION:
                continue
            items.append(
                {
                    "memory_id": row["memory_id"],
                    "content": row["content"][:2_000],
                    "approval_status": row["approval_status"],
                    "sensitivity": row["sensitivity"],
                    "revision": row["revision"],
                    "updated_at": row["updated_at"],
                    "task_id": provenance.get("task_id"),
                    "outcome": provenance.get("outcome"),
                }
            )
            if len(items) >= limit:
                break
        return items

    def counts(self) -> dict[str, int]:
        counts = {"pending": 0, "approved": 0, "skipped_sensitive": 0}
        rows = self.db.query(
            "SELECT m.approval_status,COUNT(*) AS count FROM experience_captures e "
            "JOIN memory_items m ON m.memory_id=e.memory_id "
            "WHERE e.status='captured' AND m.deleted_at IS NULL "
            "GROUP BY m.approval_status"
        )
        for row in rows:
            if row["approval_status"] in {"pending", "approved"}:
                counts[row["approval_status"]] = int(row["count"])
        skipped = self.db.one(
            "SELECT COUNT(*) AS count FROM experience_captures WHERE status='skipped_sensitive'"
        )
        counts["skipped_sensitive"] = int(skipped["count"] if skipped else 0)
        return counts

    def approve(self, memory_id: str, *, actor: str) -> dict[str, Any]:
        if actor.lower() in {"worker", "manager", "reviewer", "supervisor", "runtime"}:
            raise PolicyDenied("An agent cannot approve its own durable experience")
        item = self.memory.require(memory_id)
        if (item.get("provenance") or {}).get("capture") != CAPTURE_VERSION:
            raise ValidationError("Only captured task experience can use this approval route")
        if item["approval_status"] == "approved":
            approved = item
        elif item["approval_status"] == "pending":
            approved = self.memory.approve(memory_id, actor=actor)
        else:
            raise ValidationError("Rejected experience cannot be approved through this route")
        provenance = approved.get("provenance") or {}
        return {
            "memory_id": approved["memory_id"],
            "content": approved["content"][:2_000],
            "approval_status": approved["approval_status"],
            "sensitivity": approved["sensitivity"],
            "revision": approved["revision"],
            "updated_at": approved["updated_at"],
            "task_id": provenance.get("task_id"),
            "outcome": provenance.get("outcome"),
        }
