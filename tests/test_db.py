from __future__ import annotations

import sqlite3
import unittest

from tests.support import FactoryCase
from uaf.db import Database
from uaf.errors import IntegrityError
from uaf.migrations import MIGRATION_1
from uaf.util import sha256_text, utc_now


class DatabaseTests(FactoryCase):
    def test_fresh_migrations_and_integrity(self):
        report = self.db.integrity_check()
        self.assertTrue(report["ok"])
        self.assertEqual(report["schema_version"], 3)
        for table in ("agent_blueprints", "factory_runs", "evaluation_case_results"):
            self.assertTrue(self.db.one("SELECT name FROM sqlite_master WHERE name=?", (table,)))
        self.assertTrue(report["foreign_key_violations"] == [])
        self.assertEqual(self.db.one("PRAGMA foreign_keys")["foreign_keys"], 1)

    def test_transaction_rolls_back_and_audit_redacts(self):
        with self.assertRaises(RuntimeError), self.db.transaction():
            self.db.execute(
                "INSERT INTO evaluation_cases VALUES(?,?,?,?,?)",
                ("case", "name", "{}", "{}", "[]"),
            )
            raise RuntimeError("crash")
        self.assertIsNone(self.db.one("SELECT * FROM evaluation_cases WHERE case_id='case'"))
        self.db.audit("test.secret", object_type="test", metadata={"api_key": "super-secret-value"})
        event = self.db.one("SELECT * FROM audit_events WHERE action='test.secret'")
        self.assertNotIn("super-secret-value", event["metadata_json"])
        self.assertIn("REDACTED", event["metadata_json"])

    def test_upgrade_from_v1_creates_lifeline(self):
        path = self.root / "old.db"
        conn = sqlite3.connect(path)
        conn.executescript(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,checksum TEXT NOT NULL,applied_at TEXT NOT NULL);"
            + MIGRATION_1
            + f"INSERT INTO schema_migrations VALUES(1,'{sha256_text(MIGRATION_1)}','{utc_now()}');"
        )
        conn.close()
        with Database(path, backup_dir=self.root / "upgrade-backups") as upgraded:
            self.assertEqual(upgraded.migrate(), [2, 3])
            for table in ("research_sources", "agent_blueprints", "factory_run_tasks"):
                self.assertTrue(
                    upgraded.one("SELECT name FROM sqlite_master WHERE name=?", (table,))
                )
        backups = list((self.root / "upgrade-backups").glob("pre-migration-*.db"))
        self.assertEqual(len(backups), 1)

    def test_migration_checksum_tamper_fails(self):
        self.db.execute("UPDATE schema_migrations SET checksum='tampered' WHERE version=1")
        with self.assertRaises(IntegrityError):
            self.db.migrate()


if __name__ == "__main__":
    unittest.main()
