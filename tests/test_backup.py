from __future__ import annotations

import unittest

from tests.support import FactoryCase
from uaf.errors import IntegrityError, ValidationError


class BackupTests(FactoryCase):
    def test_create_verify_restore_with_lifeline(self):
        task = self.add_smoke("before restore")
        snapshot = self.app.backups.create("test")
        later = self.add_smoke("after snapshot")
        verified = self.app.backups.verify(snapshot["snapshot_id"])
        self.assertTrue(verified["ok"])
        result = self.app.backups.restore(snapshot["snapshot_id"], confirmed=True)
        self.assertTrue(result["integrity"]["ok"])
        self.assertIsNotNone(self.tasks.get(task["task_id"]))
        self.assertIsNone(self.tasks.get(later["task_id"]))
        self.assertTrue((self.paths.backups / f"{result['lifeline_snapshot']}.db").is_file())

    def test_tampered_snapshot_hash_is_rejected(self):
        snapshot = self.app.backups.create("tamper-test")
        path = self.paths.backups / f"{snapshot['snapshot_id']}.db"
        with path.open("ab") as handle:
            handle.write(b"tamper")
        with self.assertRaises(IntegrityError):
            self.app.backups.verify(snapshot["snapshot_id"])

    def test_corrupt_snapshot_is_rejected(self):
        bad = self.paths.backups / "bad.db"
        bad.write_bytes(b"not a sqlite database" * 100)
        with self.assertRaises(IntegrityError):
            self.app.backups.verify_path(bad)

    def test_restore_requires_confirmation(self):
        snapshot = self.app.backups.create("confirm")
        with self.assertRaises(ValidationError):
            self.app.backups.restore(snapshot["snapshot_id"], confirmed=False)


if __name__ == "__main__":
    unittest.main()
