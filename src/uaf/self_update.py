"""Read-only update checks and isolated, human-gated candidate worktrees."""

from __future__ import annotations

import os
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any

from uaf import __version__
from uaf.backup import BackupManager
from uaf.db import Database
from uaf.errors import PolicyDenied, UnavailableError, ValidationError
from uaf.policy import validate_candidate_paths
from uaf.util import atomic_write_bytes, canonical_json, file_digest, json_data, new_id, utc_now


class SelfUpdateManager:
    def __init__(
        self, db: Database, backups: BackupManager, repo_root: Path, candidates_dir: Path
    ) -> None:
        self.db = db
        self.backups = backups
        self.repo_root = Path(repo_root).resolve()
        self.candidates_dir = Path(candidates_dir)

    def _git(self, args: list[str], *, timeout: int = 30, cwd: Path | None = None) -> str:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C.UTF-8",
        }
        if os.name == "nt":
            for key in ("SYSTEMROOT", "WINDIR", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
                if key in os.environ:
                    env[key] = os.environ[key]
        try:
            # Only fixed git subcommands/flags reach this boundary; paths are confined above.
            result = subprocess.run(  # noqa: S603
                ["git", *args],  # noqa: S607 - resolved through the trusted process PATH
                cwd=cwd or self.repo_root,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UnavailableError(
                f"Git operation failed or timed out: {type(exc).__name__}"
            ) from exc
        if result.returncode:
            # Git stderr can contain a URL with userinfo; never return it verbatim.
            raise UnavailableError(f"Git {args[0]} failed with exit code {result.returncode}")
        return result.stdout.strip()

    def check(self) -> dict[str, Any]:
        self._git(["rev-parse", "--is-inside-work-tree"])
        remote = self._git(["remote", "get-url", "origin"])
        parsed = urllib.parse.urlparse(remote)
        if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username:
            raise PolicyDenied("Only an explicitly trusted HTTPS GitHub origin is supported")
        local = self._git(["rev-parse", "HEAD"])
        output = self._git(["ls-remote", "origin", "HEAD"], timeout=30)
        remote_hash = output.split()[0] if output else ""
        if len(remote_hash) != 40 or any(ch not in "0123456789abcdefABCDEF" for ch in remote_hash):
            raise UnavailableError("Trusted remote did not return a valid HEAD hash")
        result = {
            "source": f"https://github.com{parsed.path}",
            "local_commit": local,
            "remote_commit": remote_hash,
            "update_available": local != remote_hash,
            "current_version": __version__,
            "read_only": True,
            "notes": "Commit comparison only; release notes/signature review remains a separate human gate",
        }
        self.db.audit(
            "self_update.check",
            object_type="release",
            object_id=local,
            decision="update_available" if result["update_available"] else "current",
            metadata={"source": result["source"], "remote_commit": remote_hash},
        )
        return result

    def plan(
        self, patch_path: Path, *, run_tests: bool = False, allow_untrusted_code: bool = False
    ) -> dict[str, Any]:
        patch_path = Path(patch_path).resolve()
        if not patch_path.is_file() or patch_path.stat().st_size > 5_000_000:
            raise ValidationError("Candidate patch is missing or exceeds 5 MB")
        patch = patch_path.read_bytes()
        if b"\x00" in patch:
            raise ValidationError("Binary patch input is not accepted by this planner")
        self._git(["rev-parse", "--is-inside-work-tree"])
        self._git(["apply", "--check", "--whitespace=error-all", str(patch_path)])
        numstat = self._git(["apply", "--numstat", str(patch_path)])
        paths = []
        for line in numstat.splitlines():
            fields = line.split("\t", 2)
            if len(fields) == 3:
                paths.append(fields[2])
        if not paths:
            raise ValidationError("Patch has no reviewable changed paths")
        if any(any(ch.isspace() for ch in path) for path in paths):
            raise PolicyDenied("Candidate paths with whitespace need manual review")
        validate_candidate_paths(paths)
        if run_tests and not allow_untrusted_code:
            raise PolicyDenied(
                "Running candidate code requires --allow-untrusted-code; no host sandbox is claimed"
            )
        candidate_id = new_id("candidate")
        candidate_dir = self.candidates_dir / candidate_id
        worktree = candidate_dir / "repo"
        candidate_dir.mkdir(parents=True, exist_ok=False)
        submitted_patch = candidate_dir / "submitted.patch"
        atomic_write_bytes(submitted_patch, patch, private=True)
        snapshot = self.backups.create("self-update-lifeline")
        base = self._git(["rev-parse", "HEAD"])
        gates: dict[str, Any] = {
            "patch_check": "passed",
            "protected_paths": "passed",
            "tests": "not_run",
            "security_review": "human_required",
            "dependency_license_review": "human_required",
            "incumbent_comparison": "not_run",
            "snapshot_id": snapshot["snapshot_id"],
        }
        state = "awaiting_tests"
        try:
            self._git(["worktree", "add", "--detach", str(worktree), base], timeout=60)
            self._git(
                ["-C", str(worktree), "apply", "--whitespace=error-all", str(submitted_patch)]
            )
            exact_diff = self._git(["-C", str(worktree), "diff", "--binary"], timeout=30)
            diff_path = candidate_dir / "candidate.diff"
            atomic_write_bytes(diff_path, exact_diff.encode("utf-8"), private=True)
            if run_tests:
                test_env = {
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONPATH": str(worktree / "src"),
                    "UAF_HOME": str(candidate_dir / "test-home"),
                    "LC_ALL": "C.UTF-8",
                }
                if os.name == "nt":
                    for key in ("SYSTEMROOT", "WINDIR", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
                        if key in os.environ:
                            test_env[key] = os.environ[key]
                try:
                    completed = subprocess.run(
                        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                        cwd=worktree,
                        env=test_env,
                        capture_output=True,
                        text=True,
                        timeout=300,
                        check=False,
                    )
                    evidence = (completed.stdout + completed.stderr)[-100_000:]
                    (candidate_dir / "test-output.txt").write_text(evidence, encoding="utf-8")
                    gates["tests"] = "passed" if completed.returncode == 0 else "failed"
                    state = "awaiting_human_approval" if completed.returncode == 0 else "rejected"
                except subprocess.TimeoutExpired:
                    gates["tests"] = "timeout"
                    state = "rejected"
        except Exception:
            gates["candidate_application"] = "failed"
            state = "rejected"
            self._record(candidate_id, patch_path, base, candidate_dir, None, state, gates)
            raise
        self._record(candidate_id, patch_path, base, candidate_dir, diff_path, state, gates)
        self.db.audit(
            "self_update.plan",
            object_type="candidate",
            object_id=candidate_id,
            decision=state,
            metadata={"paths": paths, "gates": gates, "patch_sha256": file_digest(patch_path)},
        )
        return self.get(candidate_id) or {}

    def _record(
        self,
        candidate_id: str,
        source: Path,
        base: str,
        candidate_dir: Path,
        diff_path: Path | None,
        state: str,
        gates: dict[str, Any],
    ) -> None:
        self.db.execute(
            "INSERT INTO candidate_releases(candidate_id,source,base_version,candidate_version,path,"
            "diff_path,state,gates_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                candidate_id,
                str(source),
                base,
                "uncommitted-candidate",
                str(candidate_dir),
                str(diff_path) if diff_path else None,
                state,
                canonical_json(gates),
                utc_now(),
                utc_now(),
            ),
        )

    def get(self, candidate_id: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM candidate_releases WHERE candidate_id=?", (candidate_id,))
        if row:
            row["gates"] = json_data(row["gates_json"], {})
        return row

    def evaluate_promotion(self, candidate_id: str, *, actor: str) -> dict[str, Any]:
        candidate = self.get(candidate_id)
        if not candidate:
            raise ValidationError("Unknown candidate")
        gates = candidate["gates"]
        required = {"patch_check", "protected_paths", "tests"}
        if any(gates.get(gate) != "passed" for gate in required):
            raise PolicyDenied("Candidate cannot promote with missing/failed mandatory gates")
        if actor.lower() in {"worker", "manager", "reviewer", "runtime", "system"}:
            raise PolicyDenied("Agent-driven promotion is forbidden")
        # This release deliberately records review state only; it never merges/pushes/deploys.
        return {
            "candidate_id": candidate_id,
            "state": "awaiting_human_approval",
            "promotion_executed": False,
            "remaining": [
                "security/dependency review",
                "incumbent evaluation",
                "explicit human merge",
            ],
        }
