"""Consistent SQLite snapshots with verification and reversible restore."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from uaf.db import Database
from uaf.errors import IntegrityError, ValidationError
from uaf.util import canonical_json, file_digest, new_id, utc_now


class BackupManager:
    def __init__(self, db: Database, backup_dir: Path) -> None:
        self.db = db
        self.backup_dir = backup_dir
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create(self, purpose: str = "manual") -> dict[str, Any]:
        snapshot_id = new_id("snap")
        destination = self.backup_dir / f"{snapshot_id}.db"
        with self.db._lock:
            target = sqlite3.connect(destination)
            try:
                self.db._conn.backup(target)
                target.commit()
            finally:
                target.close()
        try:
            report = self.verify_path(destination)
            self.db.execute(
                "INSERT INTO snapshots(snapshot_id,purpose,schema_version,path,created_at,size,"
                "sha256,verification_status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    snapshot_id,
                    purpose,
                    report["schema_version"],
                    str(destination),
                    utc_now(),
                    destination.stat().st_size,
                    file_digest(destination),
                    "verified",
                    canonical_json({"method": "python_sqlite_backup"}),
                ),
            )
            self.db.audit(
                "backup.create",
                object_type="snapshot",
                object_id=snapshot_id,
                decision="verified",
                metadata={"purpose": purpose, "sha256": report["sha256"]},
            )
            return self.get(snapshot_id) or {}
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    def get(self, snapshot_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM snapshots WHERE snapshot_id=?", (snapshot_id,))

    def list(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM snapshots ORDER BY created_at DESC")

    def _path_for(self, snapshot_id: str) -> Path:
        row = self.get(snapshot_id)
        if not row:
            raise ValidationError(f"Unknown snapshot: {snapshot_id}")
        path = Path(row["path"]).resolve()
        if not path.is_relative_to(self.backup_dir.resolve()):
            raise IntegrityError("Snapshot path escapes the configured backup directory")
        return path

    def verify_path(self, path: Path) -> dict[str, Any]:
        path = Path(path)
        if not path.is_file() or path.stat().st_size < 100:
            raise IntegrityError("Snapshot is missing or too small to be a SQLite database")
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA query_only=ON")
            integrity = [r[0] for r in connection.execute("PRAGMA integrity_check").fetchall()]
            if integrity != ["ok"]:
                raise IntegrityError(f"Snapshot integrity check failed: {integrity}")
            try:
                version = connection.execute(
                    "SELECT COALESCE(MAX(version),0) FROM schema_migrations"
                ).fetchone()[0]
            except sqlite3.Error as exc:
                raise IntegrityError("Snapshot has no readable UAF migration table") from exc
            return {
                "ok": True,
                "path": str(path),
                "schema_version": version,
                "size": path.stat().st_size,
                "sha256": file_digest(path),
            }
        except sqlite3.DatabaseError as exc:
            raise IntegrityError(f"Snapshot is not a valid SQLite database: {exc}") from exc
        finally:
            connection.close()

    def verify(self, snapshot_id: str) -> dict[str, Any]:
        path = self._path_for(snapshot_id)
        report = self.verify_path(path)
        expected = self.get(snapshot_id)
        if expected and report["sha256"] != expected["sha256"]:
            self.db.execute(
                "UPDATE snapshots SET verification_status='hash_mismatch' WHERE snapshot_id=?",
                (snapshot_id,),
            )
            raise IntegrityError("Snapshot content hash does not match its registry entry")
        self.db.execute(
            "UPDATE snapshots SET verification_status='verified' WHERE snapshot_id=?",
            (snapshot_id,),
        )
        report["snapshot_id"] = snapshot_id
        return report

    def restore(self, snapshot_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        if not confirmed:
            raise ValidationError("Restore requires explicit confirmation")
        source_path = self._path_for(snapshot_id)
        self.verify(snapshot_id)
        lifeline = self.create("pre-restore-lifeline")
        # Restore through SQLite's backup API into the existing destination. This avoids
        # replacing an open database file (which fails on Windows) and preserves one DB object.
        self.db._conn.commit()
        source = sqlite3.connect(source_path)
        try:
            source.backup(self.db._conn)
        finally:
            source.close()
        restored_integrity = self.db.integrity_check()
        if not restored_integrity["ok"] or restored_integrity["foreign_key_violations"]:
            raise IntegrityError(
                "Restored database failed integrity checks; recover from the pre-restore lifeline"
            )
        self.db.audit(
            "backup.restore",
            object_type="snapshot",
            object_id=snapshot_id,
            decision="restored",
            metadata={"lifeline_snapshot": lifeline["snapshot_id"]},
        )
        self.db.execute(
            "INSERT INTO rollback_events(rollback_id,target,snapshot_id,reason,evidence_json,created_at)"
            " VALUES(?,?,?,?,?,?)",
            (
                new_id("rollback"),
                "database",
                lifeline["snapshot_id"],
                f"Restore from {snapshot_id}",
                canonical_json({"verified": True}),
                utc_now(),
            ),
        )
        self.db.execute(
            "UPDATE snapshots SET restore_tested_at=? WHERE snapshot_id=?", (utc_now(), snapshot_id)
        )
        return {
            "restored": snapshot_id,
            "lifeline_snapshot": lifeline["snapshot_id"],
            "integrity": self.db.integrity_check(),
        }
