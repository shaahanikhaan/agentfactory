from __future__ import annotations

import unittest

from tests.support import FactoryCase
from uaf.errors import PolicyDenied
from uaf.util import sha256_text


class MemoryTests(FactoryCase):
    def test_approved_search_and_pending_isolation(self):
        item = self.app.memory.add("User likes concise answers", memory_type="preference")
        self.assertEqual(self.app.memory.search("concise"), [])
        self.app.memory.approve(item["memory_id"], actor="human")
        self.assertEqual(len(self.app.memory.search("concise")), 1)

    def test_like_fallback(self):
        self.app.memory.add("Fallback search works", approved=True)
        self.db.fts_enabled = False
        self.assertEqual(len(self.app.memory.search("fallback")), 1)

    def test_correction_preserves_revision_history(self):
        item = self.app.memory.add("Original fact", approved=True)
        self.app.memory.correct(item["memory_id"], "Corrected fact", reason="new evidence")
        revisions = self.app.memory.revisions(item["memory_id"])
        self.assertEqual(len(revisions), 2)
        self.assertEqual(revisions[0]["content"], "Original fact")
        self.assertEqual(revisions[1]["content"], "Corrected fact")

    def test_secret_memory_is_rejected(self):
        with self.assertRaises(PolicyDenied):
            self.app.memory.add("api_key=super-secret-value")
        self.assertEqual(self.db.one("SELECT COUNT(*) c FROM memory_items")["c"], 0)

    def test_privacy_delete_scrubs_history_and_index(self):
        item = self.app.memory.add(
            "Private unforgettable phrase", approved=True, sensitivity="private"
        )
        self.app.memory.correct(item["memory_id"], "Private corrected phrase")
        self.app.memory.delete(item["memory_id"], confirmed=True)
        tombstone = self.app.memory.get(item["memory_id"], include_deleted=True)
        self.assertIsNotNone(tombstone["deleted_at"])
        self.assertNotIn("Private", tombstone["content"])
        for revision in self.app.memory.revisions(item["memory_id"]):
            self.assertNotIn("Private", revision["content"])
        self.assertEqual(self.app.memory.search("unforgettable", approved_only=False), [])

    def test_consolidation_dry_run_apply_and_idempotency(self):
        first = self.app.memory.add("Same supported fact", approved=True, sensitivity="public")
        duplicate = self.app.memory.add(
            "Same   supported fact", approved=True, sensitivity="public"
        )
        dry = self.app.memory.dry_run()
        self.assertEqual(dry["counts"]["merged"], 1)
        self.assertIsNotNone(self.app.memory.get(duplicate["memory_id"]))
        applied = self.app.memory.apply(dry["job_id"])
        self.assertEqual(applied["state"], "applied")
        self.assertIsNotNone(applied["snapshot_id"])
        self.assertIsNone(self.app.memory.get(duplicate["memory_id"]))
        self.assertIsNotNone(self.app.memory.get(first["memory_id"]))
        snapshots = len(self.app.backups.list())
        again = self.app.memory.apply(dry["job_id"])
        self.assertEqual(again["state"], "applied")
        self.assertEqual(len(self.app.backups.list()), snapshots)

    def test_expiry_is_reviewable(self):
        self.app.memory.add("Expired fact", approved=True, expires_at="2000-01-01T00:00:00Z")
        dry = self.app.memory.dry_run()
        self.assertEqual(dry["counts"]["expired"], 1)
        self.app.memory.apply(dry["job_id"])
        self.assertEqual(self.app.memory.list(), [])

    def test_export_digest_matches_actual_file(self):
        self.app.memory.add("Exported fact", approved=True)
        destination = self.root / "export.json"
        result = self.app.memory.export(destination)
        self.assertEqual(sha256_text(destination.read_text()), result["sha256"])


if __name__ == "__main__":
    unittest.main()
