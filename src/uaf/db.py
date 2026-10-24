"""Central SQLite owner: connections, migrations, transactions, and audit events."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from uaf.errors import IntegrityError, UAFError
from uaf.migrations import MIGRATIONS
from uaf.util import canonical_json, new_id, redact_data, sha256_text, utc_now


class Database:
    def __init__(self, path: str | Path, *, backup_dir: str | Path | None = None) -> None:
        self.path = Path(path)
        self.backup_dir = Path(backup_dir) if backup_dir else self.path.parent / "backups"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._savepoint = 0
        self._conn = self._connect()
        self.fts_enabled = False

    def _connect(self) -> sqlite3.Connection:
        # MCP's SDK executes synchronous tools in worker threads. Every connection
        # operation is guarded by this Database's RLock, so cross-thread use is explicit.
        conn = sqlite3.connect(
            self.path, timeout=5.0, isolation_level=None, check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def reopen(self) -> None:
        with self._lock:
            if not self._conn:
                self._conn = self._connect()
                self._ensure_fts()

    def close(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None  # type: ignore[assignment]

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def migrate(self) -> list[int]:
        """Apply pending migrations; back up an existing DB before an upgrade."""
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            rows = self._conn.execute(
                "SELECT version, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
            applied = {int(row["version"]): row["checksum"] for row in rows}
            for version, sql in MIGRATIONS:
                if version in applied and applied[version] != sha256_text(sql):
                    raise IntegrityError(
                        f"Migration {version} checksum differs from applied schema"
                    )
            pending = [(v, sql) for v, sql in MIGRATIONS if v not in applied]
            if applied and pending:
                self._pre_migration_backup(max(applied))
            completed: list[int] = []
            for version, sql in pending:
                checksum = sha256_text(sql)
                script = (
                    "BEGIN IMMEDIATE;\n"
                    + sql
                    + "\nINSERT INTO schema_migrations(version,checksum,applied_at) VALUES ("
                    + f"{version},'{checksum}','{utc_now()}');\nCOMMIT;"
                )
                try:
                    self._conn.executescript(script)
                except sqlite3.Error as exc:
                    if self._conn.in_transaction:
                        self._conn.rollback()
                    raise IntegrityError(f"Migration {version} failed: {exc}") from exc
                completed.append(version)
            self._ensure_fts()
            return completed

    def _pre_migration_backup(self, version: int) -> Path:
        destination = self.backup_dir / f"pre-migration-v{version}-{utc_now().replace(':', '-')}.db"
        target = sqlite3.connect(destination)
        try:
            self._conn.backup(target)
            target.commit()
        finally:
            target.close()
        check = sqlite3.connect(destination)
        try:
            result = check.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise IntegrityError("Pre-migration backup failed integrity verification")
        finally:
            check.close()
        return destination

    def _ensure_fts(self) -> None:
        try:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5("
                "memory_id UNINDEXED, content, source UNINDEXED)"
            )
            self._conn.execute("SELECT memory_id FROM memory_fts LIMIT 1").fetchone()
            self.fts_enabled = True
        except sqlite3.Error:
            self.fts_enabled = False

    @contextmanager
    def transaction(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        with self._lock:
            nested = self._conn.in_transaction
            savepoint = f"uaf_sp_{self._savepoint}"
            try:
                if nested:
                    self._savepoint += 1
                    savepoint = f"uaf_sp_{self._savepoint}"
                    self._conn.execute(f"SAVEPOINT {savepoint}")
                else:
                    self._conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                yield self._conn
                if nested:
                    self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                else:
                    self._conn.commit()
            except Exception:
                if nested:
                    self._conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                elif self._conn.in_transaction:
                    self._conn.rollback()
                raise

    def execute(self, sql: str, parameters: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, parameters)

    def executemany(self, sql: str, parameters: list[tuple]) -> None:
        with self._lock, self.transaction():
            self._conn.executemany(sql, parameters)

    def query(self, sql: str, parameters: tuple | dict = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, parameters).fetchall()]

    def one(self, sql: str, parameters: tuple | dict = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, parameters).fetchone()
            return dict(row) if row else None

    def audit(
        self,
        action: str,
        *,
        actor: str = "local-user",
        role: str = "user",
        object_type: str,
        object_id: str | None = None,
        decision: str = "recorded",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        event_id = new_id("audit")
        safe_metadata = redact_data(metadata or {})
        with self.transaction():
            self._conn.execute(
                "INSERT INTO audit_events(event_id,timestamp,actor,role,action,object_type,"
                "object_id,decision,metadata_json) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    utc_now(),
                    actor,
                    role,
                    action,
                    object_type,
                    object_id,
                    decision,
                    canonical_json(safe_metadata),
                ),
            )
        return event_id

    def integrity_check(self) -> dict[str, Any]:
        with self._lock:
            integrity = [row[0] for row in self._conn.execute("PRAGMA integrity_check").fetchall()]
            foreign = [
                tuple(row) for row in self._conn.execute("PRAGMA foreign_key_check").fetchall()
            ]
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            migrations = (
                self._conn.execute(
                    "SELECT COALESCE(MAX(version),0) FROM schema_migrations"
                ).fetchone()[0]
                if self._table_exists("schema_migrations")
                else 0
            )
            ok = integrity == ["ok"] and not foreign
            return {
                "ok": ok,
                "integrity": integrity,
                "foreign_key_violations": foreign,
                "schema_version": migrations,
                "user_version": version,
                "fts5": self.fts_enabled,
            }

    def _table_exists(self, name: str) -> bool:
        return bool(
            self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()
        )

    def assert_healthy(self) -> None:
        report = self.integrity_check()
        if not report["ok"]:
            raise UAFError("Database integrity check failed", details=report)
