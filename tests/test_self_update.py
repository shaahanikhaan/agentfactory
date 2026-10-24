from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from tests.support import FactoryCase
from uaf.errors import PolicyDenied
from uaf.policy import validate_candidate_paths
from uaf.self_update import SelfUpdateManager
from uaf.util import canonical_json


class SelfUpdateTests(FactoryCase):
    def git(self, repo: Path, *args: str) -> str:
        result = subprocess.run(  # noqa: S603 - fixed test repository and git arguments
            ["git", *args],  # noqa: S607 - test uses the configured executable PATH
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    def repository(self):
        repo = self.root / "repo"
        repo.mkdir()
        self.git(repo, "init", "-q")
        (repo / "README.md").write_text("incumbent\n")
        self.git(repo, "add", "README.md")
        self.git(
            repo,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "initial",
        )
        return repo

    def test_protected_and_traversal_paths_rejected(self):
        for paths in (
            ["src/uaf/policy.py"],
            ["src/uaf/browser.py"],
            ["src/uaf/desktop.py"],
            ["src/uaf/credentials.py"],
            ["tests/test_runner.py"],
            ["../secret"],
            ["/absolute"],
        ):
            with self.subTest(paths=paths), self.assertRaises(PolicyDenied):
                validate_candidate_paths(paths)

    def test_candidate_is_isolated_and_missing_tests_cannot_promote(self):
        repo = self.repository()
        (repo / "README.md").write_text("incumbent\ncandidate\n")
        patch = self.root / "candidate.patch"
        patch.write_text(self.git(repo, "diff", "--binary"))
        self.git(repo, "checkout", "--", "README.md")
        manager = SelfUpdateManager(self.db, self.app.backups, repo, self.paths.candidates)
        candidate = manager.plan(patch)
        self.assertEqual(candidate["state"], "awaiting_tests")
        candidate_repo = Path(candidate["path"]) / "repo"
        self.assertIn("candidate", (candidate_repo / "README.md").read_text())
        self.assertEqual((repo / "README.md").read_text(), "incumbent\n")
        with self.assertRaises(PolicyDenied):
            manager.evaluate_promotion(candidate["candidate_id"], actor="human")
        gates = candidate["gates"]
        gates["tests"] = "passed"
        self.db.execute(
            "UPDATE candidate_releases SET gates_json=? WHERE candidate_id=?",
            (canonical_json(gates), candidate["candidate_id"]),
        )
        with self.assertRaises(PolicyDenied):
            manager.evaluate_promotion(candidate["candidate_id"], actor="worker")
        decision = manager.evaluate_promotion(candidate["candidate_id"], actor="human")
        self.assertFalse(decision["promotion_executed"])

    def test_check_is_read_only_and_compares_hashes(self):
        repo = self.repository()
        local = self.git(repo, "rev-parse", "HEAD").strip()
        manager = SelfUpdateManager(self.db, self.app.backups, repo, self.paths.candidates)
        responses = {
            "rev-parse": local,
            "remote": "https://github.com/example/project.git",
            "ls-remote": local + "\tHEAD",
        }
        manager._git = lambda args, **kwargs: responses.get(args[0], "true")
        result = manager.check()
        self.assertFalse(result["update_available"])
        self.assertTrue(result["read_only"])

    def test_untrusted_update_origin_rejected(self):
        repo = self.repository()
        manager = SelfUpdateManager(self.db, self.app.backups, repo, self.paths.candidates)
        manager._git = lambda args, **kwargs: (
            "file:///tmp/untrusted" if args[0] == "remote" else "x"
        )
        with self.assertRaises(PolicyDenied):
            manager.check()


if __name__ == "__main__":
    unittest.main()
