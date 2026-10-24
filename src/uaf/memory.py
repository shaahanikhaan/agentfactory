"""Dual-horizon memory with provenance, revisions, FTS fallback, and safe maintenance."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from uaf.backup import BackupManager
from uaf.db import Database
from uaf.errors import PolicyDenied, StateTransitionError, UnavailableError, ValidationError
from uaf.util import (
    atomic_write_text,
    bounded,
    canonical_json,
    json_data,
    new_id,
    now_dt,
    parse_time,
    redact_data,
    redact_text,
    sha256_text,
    utc_now,
)

_MEMORY_TYPES = {"event", "task", "preference", "fact", "procedure", "repository", "telemetry"}
_SENSITIVITIES = {"public", "internal", "private"}


def normalize_content(content: str) -> str:
    return " ".join(content.casefold().split())


class MemoryStore:
    def __init__(self, db: Database, backups: BackupManager | None = None) -> None:
        self.db = db
        self.backups = backups

    def add(
        self,
        content: str,
        *,
        memory_type: str = "fact",
        source: str = "local-user",
        confidence: float = 1.0,
        sensitivity: str = "internal",
        expires_at: str | None = None,
        approved: bool = False,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        bounded(content.strip(), 20_000, label="memory content")
        if not content.strip():
            raise ValidationError("Memory content cannot be empty")
        if memory_type not in _MEMORY_TYPES or sensitivity not in _SENSITIVITIES:
            raise ValidationError("Invalid memory type or sensitivity")
        if sensitivity == "secret" or redact_text(content) != content:
            raise PolicyDenied(
                "Secrets must not be stored in agent memory; use OS credential storage"
            )
        if not 0 <= confidence <= 1:
            raise ValidationError("Memory confidence must be between 0 and 1")
        if expires_at:
            parse_time(expires_at)
        bounded(source, 500, label="memory source")
        memory_id = new_id("mem")
        now = utc_now()
        status = "approved" if approved else "pending"
        safe_provenance = redact_data(
            {
                **(provenance or {}),
                "source": source,
                "untrusted_instructions_ignored": True,
            }
        )
        normalized_hash = sha256_text(normalize_content(content))
        with self.db.transaction():
            self.db._conn.execute(
                "INSERT INTO memory_items(memory_id,type,content,normalized_hash,source,provenance_json,"
                "created_at,updated_at,confidence,sensitivity,expires_at,approval_status,revision) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)",
                (
                    memory_id,
                    memory_type,
                    content.strip(),
                    normalized_hash,
                    source,
                    canonical_json(safe_provenance),
                    now,
                    now,
                    confidence,
                    sensitivity,
                    expires_at,
                    status,
                ),
            )
            self.db._conn.execute(
                "INSERT INTO memory_revisions(revision_id,memory_id,revision,content,source,"
                "provenance_json,created_at,reason) VALUES(?,?,1,?,?,?,?,?)",
                (
                    new_id("rev"),
                    memory_id,
                    content.strip(),
                    source,
                    canonical_json(safe_provenance),
                    now,
                    "created",
                ),
            )
            self._fts_insert(memory_id, content.strip(), source)
            self.db.audit(
                "memory.add",
                actor=source,
                object_type="memory",
                object_id=memory_id,
                decision=status,
                metadata={"type": memory_type, "sensitivity": sensitivity},
            )
        return self.get(memory_id) or {}

    def _decode(self, row: dict[str, Any]) -> dict[str, Any]:
        row["provenance"] = json_data(row.get("provenance_json"), {})
        return row

    def get(self, memory_id: str, *, include_deleted: bool = False) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM memory_items WHERE memory_id=?", (memory_id,))
        if row and (include_deleted or not row["deleted_at"]):
            return self._decode(row)
        return None

    def require(self, memory_id: str) -> dict[str, Any]:
        row = self.get(memory_id)
        if not row:
            raise ValidationError(f"Unknown active memory: {memory_id}")
        return row

    def list(
        self,
        *,
        memory_type: str | None = None,
        include_pending: bool = True,
        include_deleted: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValidationError("Memory list limit must be between 1 and 500")
        clauses, params = [], []
        if memory_type:
            if memory_type not in _MEMORY_TYPES:
                raise ValidationError("Invalid memory type")
            clauses.append("type=?")
            params.append(memory_type)
        if not include_pending:
            clauses.append("approval_status='approved'")
        if not include_deleted:
            clauses.append("deleted_at IS NULL")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.db.query(
            # Only the static clauses above are interpolated; all values are bound.
            f"SELECT * FROM memory_items{where} ORDER BY updated_at DESC LIMIT ?",  # noqa: S608
            (*params, limit),
        )
        return [self._decode(row) for row in rows]

    def search(
        self, query: str, *, limit: int = 20, approved_only: bool = True
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValidationError("Search limit must be between 1 and 100")
        tokens = re.findall(r"[\w]+", query, flags=re.UNICODE)[:12]
        if not tokens:
            raise ValidationError("Memory search requires a word or number")
        if self.db.fts_enabled:
            fts_query = " AND ".join('"' + token.replace('"', '""') + '"' for token in tokens)
            base = (
                "SELECT m.* FROM memory_items m JOIN ("
                "SELECT memory_id FROM memory_fts WHERE memory_fts MATCH ?"
                ") f ON m.memory_id=f.memory_id WHERE m.deleted_at IS NULL"
            )
            if approved_only:
                rows = self.db.query(
                    base + " AND m.approval_status='approved' ORDER BY m.updated_at DESC LIMIT ?",
                    (fts_query, limit),
                )
            else:
                rows = self.db.query(
                    base + " ORDER BY m.updated_at DESC LIMIT ?", (fts_query, limit)
                )
            return [self._decode(row) for row in rows]
        pattern = "%" + "%".join(tokens) + "%"
        if approved_only:
            rows = self.db.query(
                "SELECT * FROM memory_items WHERE deleted_at IS NULL AND content LIKE ? "
                "AND approval_status='approved' ORDER BY updated_at DESC LIMIT ?",
                (pattern, limit),
            )
        else:
            rows = self.db.query(
                "SELECT * FROM memory_items WHERE deleted_at IS NULL AND content LIKE ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (pattern, limit),
            )
        return [self._decode(row) for row in rows]

    def approve(self, memory_id: str, *, actor: str = "local-user") -> dict[str, Any]:
        if actor.lower() in {"worker", "manager", "reviewer", "supervisor", "runtime"}:
            raise PolicyDenied("An agent cannot approve its own durable memory promotion")
        self.require(memory_id)
        self.db.execute(
            "UPDATE memory_items SET approval_status='approved',updated_at=? WHERE memory_id=?",
            (utc_now(), memory_id),
        )
        self.db.audit(
            "memory.approve",
            actor=actor,
            role="human",
            object_type="memory",
            object_id=memory_id,
            decision="approved",
        )
        return self.require(memory_id)

    def correct(
        self,
        memory_id: str,
        content: str,
        *,
        source: str = "local-user",
        reason: str = "correction",
    ) -> dict[str, Any]:
        current = self.require(memory_id)
        bounded(content.strip(), 20_000, label="memory content")
        if not content.strip() or redact_text(content) != content:
            raise PolicyDenied("Corrected memory is empty or appears to contain a secret")
        revision = current["revision"] + 1
        now = utc_now()
        with self.db.transaction():
            self.db._conn.execute(
                "UPDATE memory_items SET content=?,normalized_hash=?,source=?,revision=?,updated_at=? "
                "WHERE memory_id=?",
                (
                    content.strip(),
                    sha256_text(normalize_content(content)),
                    source,
                    revision,
                    now,
                    memory_id,
                ),
            )
            self.db._conn.execute(
                "INSERT INTO memory_revisions(revision_id,memory_id,revision,content,source,"
                "provenance_json,created_at,reason) VALUES(?,?,?,?,?,?,?,?)",
                (
                    new_id("rev"),
                    memory_id,
                    revision,
                    content.strip(),
                    source,
                    canonical_json({"corrected_from": current["source"]}),
                    now,
                    reason[:500],
                ),
            )
            self._fts_delete(memory_id)
            self._fts_insert(memory_id, content.strip(), source)
            self.db.audit(
                "memory.correct",
                actor=source,
                object_type="memory",
                object_id=memory_id,
                decision="revision_created",
                metadata={"revision": revision},
            )
        return self.require(memory_id)

    def revisions(self, memory_id: str) -> list[dict[str, Any]]:
        self.get(memory_id, include_deleted=True) or self.require(memory_id)
        rows = self.db.query(
            "SELECT * FROM memory_revisions WHERE memory_id=? ORDER BY revision", (memory_id,)
        )
        for row in rows:
            row["provenance"] = json_data(row["provenance_json"], {})
        return rows

    def delete(self, memory_id: str, *, actor: str = "local-user", confirmed: bool = False) -> None:
        if not confirmed:
            raise ValidationError("Memory deletion requires confirmation")
        current = self.require(memory_id)
        with self.db.transaction():
            # Privacy deletion scrubs historical content too; an audit tombstone remains without it.
            self.db._conn.execute(
                "UPDATE memory_items SET content='[deleted by user]',normalized_hash=?,source='tombstone',"
                "provenance_json='{}',deleted_at=?,updated_at=?,revision=revision+1 WHERE memory_id=?",
                (sha256_text(new_id("deleted")), utc_now(), utc_now(), memory_id),
            )
            self.db._conn.execute(
                "UPDATE memory_revisions SET content='[deleted by user]',source='tombstone',"
                "provenance_json='{}' WHERE memory_id=?",
                (memory_id,),
            )
            self._fts_delete(memory_id)
            self.db.audit(
                "memory.delete",
                actor=actor,
                role="human",
                object_type="memory",
                object_id=memory_id,
                decision="content_scrubbed",
                metadata={"previous_sensitivity": current["sensitivity"]},
            )

    def export(self, destination: Path) -> dict[str, Any]:
        rows = self.list(include_pending=True, include_deleted=False, limit=500)
        payload = {
            "format": "uaf-memory-export-v1",
            "exported_at": utc_now(),
            "count": len(rows),
            "items": rows,
        }
        serialized = canonical_json(redact_data(payload)) + "\n"
        atomic_write_text(destination, serialized, private=True)
        return {"path": str(destination), "count": len(rows), "sha256": sha256_text(serialized)}

    def dry_run(self, *, record_limit: int = 500) -> dict[str, Any]:
        if not 1 <= record_limit <= 500:
            raise ValidationError("Consolidation record limit must be between 1 and 500")
        rows = self.list(include_pending=True, include_deleted=False, limit=record_limit)
        groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
        counts = {
            "examined": len(rows),
            "merged": 0,
            "kept": 0,
            "expired": 0,
            "proposed": 0,
            "skipped_for_privacy": 0,
            "failed": 0,
        }
        actions = []
        now = now_dt()
        for row in rows:
            if row["expires_at"] and parse_time(row["expires_at"]) <= now:
                actions.append(
                    {
                        "action": "expire",
                        "memory_id": row["memory_id"],
                        "before": {"expires_at": row["expires_at"]},
                        "after": {"deleted_at": "job-time"},
                    }
                )
                counts["expired"] += 1
                continue
            if row["sensitivity"] == "private":
                counts["skipped_for_privacy"] += 1
            key = (row["normalized_hash"], row["type"], row["sensitivity"], row["approval_status"])
            groups[key].append(row)
        for group in groups.values():
            if len(group) < 2:
                continue
            group.sort(key=lambda item: (item["approval_status"] != "approved", item["created_at"]))
            keeper = group[0]
            for duplicate in group[1:]:
                actions.append(
                    {
                        "action": "deduplicate",
                        "memory_id": duplicate["memory_id"],
                        "before": {"content_preview": duplicate["content"][:200]},
                        "after": {"duplicate_of": keeper["memory_id"], "index_removed": True},
                        "keeper_id": keeper["memory_id"],
                        "normalized_hash": duplicate["normalized_hash"],
                    }
                )
                counts["merged"] += 1
            if (
                keeper["type"] in {"event", "task"}
                and keeper["sensitivity"] == "public"
                and keeper["confidence"] >= 0.8
                and keeper["approval_status"] == "approved"
            ):
                counts["proposed"] += 1
                actions.append(
                    {
                        "action": "propose_long_term",
                        "memory_id": keeper["memory_id"],
                        "before": {"type": keeper["type"]},
                        "after": {"type": "fact", "approval_status": "human_review_required"},
                    }
                )
        counts["kept"] = len(rows) - counts["merged"] - counts["expired"]
        job_id = new_id("consolidation")
        plan = {"record_limit": record_limit, "actions": actions, "idempotent": True}
        self.db.execute(
            "INSERT INTO consolidation_jobs(job_id,state,plan_json,counts_json,created_at) "
            "VALUES(?,'dry_run',?,?,?)",
            (job_id, canonical_json(plan), canonical_json(counts), utc_now()),
        )
        return {"job_id": job_id, "state": "dry_run", "plan": plan, "counts": counts}

    def apply(self, job_id: str) -> dict[str, Any]:
        job = self.db.one("SELECT * FROM consolidation_jobs WHERE job_id=?", (job_id,))
        if not job:
            raise ValidationError("Unknown consolidation job")
        if job["state"] == "applied":
            return self._job_result(job)
        if job["state"] != "dry_run":
            raise StateTransitionError(f"Cannot apply consolidation job in {job['state']}")
        if not self.backups:
            raise UnavailableError("A backup manager is required before memory consolidation")
        snapshot = self.backups.create("memory-consolidation-lifeline")
        plan = json_data(job["plan_json"], {})
        counts = json_data(job["counts_json"], {})
        try:
            with self.db.transaction():
                for action in plan["actions"]:
                    if action["action"] == "propose_long_term":
                        continue  # Promotion requires a separate explicit human approval flow.
                    memory_id = action["memory_id"]
                    row = self.db._conn.execute(
                        "SELECT * FROM memory_items WHERE memory_id=?", (memory_id,)
                    ).fetchone()
                    if not row or row["deleted_at"]:
                        continue
                    if action["action"] == "deduplicate":
                        if row["normalized_hash"] != action["normalized_hash"]:
                            raise StateTransitionError("Memory changed after consolidation dry-run")
                        self.db._conn.execute(
                            "INSERT INTO memory_links(link_id,from_memory_id,to_memory_id,relation,"
                            "provenance_json,created_at) VALUES(?,?,?,'duplicate_of',?,?)",
                            (
                                new_id("link"),
                                memory_id,
                                action["keeper_id"],
                                canonical_json({"source": row["source"], "job_id": job_id}),
                                utc_now(),
                            ),
                        )
                    self.db._conn.execute(
                        "UPDATE memory_items SET deleted_at=?,updated_at=? WHERE memory_id=? AND deleted_at IS NULL",
                        (utc_now(), utc_now(), memory_id),
                    )
                    self._fts_delete(memory_id)
                self.db._conn.execute(
                    "UPDATE consolidation_jobs SET state='applied',snapshot_id=?,applied_at=? WHERE job_id=?",
                    (snapshot["snapshot_id"], utc_now(), job_id),
                )
                self.db.audit(
                    "memory.consolidate",
                    object_type="consolidation",
                    object_id=job_id,
                    decision="applied",
                    metadata={"counts": counts, "snapshot": snapshot["snapshot_id"]},
                )
        except Exception:
            self.db.execute(
                "UPDATE consolidation_jobs SET state='failed' WHERE job_id=?", (job_id,)
            )
            counts["failed"] += 1
            raise
        return self._job_result(
            self.db.one("SELECT * FROM consolidation_jobs WHERE job_id=?", (job_id,))
        )

    @staticmethod
    def _job_result(job: dict[str, Any]) -> dict[str, Any]:
        return {
            "job_id": job["job_id"],
            "state": job["state"],
            "plan": json_data(job["plan_json"], {}),
            "counts": json_data(job["counts_json"], {}),
            "snapshot_id": job["snapshot_id"],
            "applied_at": job["applied_at"],
        }

    def _fts_insert(self, memory_id: str, content: str, source: str) -> None:
        if self.db.fts_enabled:
            self.db._conn.execute(
                "INSERT INTO memory_fts(memory_id,content,source) VALUES(?,?,?)",
                (memory_id, content, source),
            )

    def _fts_delete(self, memory_id: str) -> None:
        if self.db.fts_enabled:
            self.db._conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (memory_id,))
