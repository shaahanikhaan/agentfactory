# Release checklist

Do not release from an unreviewed working tree or treat a candidate worktree as a sandbox. Keep the incumbent recoverable throughout.

## 1. Source and supply chain

- [ ] Confirm intended branch/commit and review the complete diff.
- [ ] Confirm no credentials, DBs, backups, memory exports, logs, candidates, or large artifacts are tracked.
- [ ] Review direct/optional dependency changes and license obligations.
- [ ] Run `pip-audit` in the actual clean release environment; investigate skipped packages.
- [ ] Record exact Python, OS, SQLite, dependency, and UAF versions.

## 2. Automated gates

- [ ] `python scripts/verify.py` from a clean virtual environment.
- [ ] Build a wheel and install it into a second clean environment.
- [ ] Verify packaged skills, built-in blueprint, evaluation suite, and the `uaf` console script from the wheel.
- [ ] Run offline CLI smoke, durable DAG, evaluation/baseline, backup/restore, plugin, and benchmark scenarios.
- [ ] Confirm no cloud request occurs in default offline tests.

## 3. Platform acceptance

- [ ] Windows 10 or 11, Python 3.11: full suite and CLI.
- [ ] Paths containing spaces and Unicode.
- [ ] Controlled interruption and explicit resume.
- [ ] Removable workspace disconnect/reconnect while DB remains on stable storage.
- [ ] 4 GB RAM or documented constrained equivalent; serial defaults.
- [ ] Linux/macOS results labelled separately, never substituted for Windows evidence.

## 4. Optional integrations

- [ ] Official MCP SDK installed and intended local client handshake exercised.
- [ ] Any live provider tested only after current official free/terms review.
- [ ] Provider-side quota/account scope and credential restrictions reviewed.
- [ ] Live results recorded by provider/model/date; no generalized free claim.
- [ ] Research tested only against approved sources with an egress-controlled environment if required.

## 5. Safety and recovery

- [ ] Approval payload mismatch/rejection and R3 file-backup recovery tests pass.
- [ ] Idempotency conflict and interrupted non-idempotent uncertainty tests pass.
- [ ] Prompt-injection fixtures cannot expand tool permissions.
- [ ] ReAct disallowed-tool/budget denial and R3 decision-checkpoint replay pass.
- [ ] Blueprint immutability, DAG data-flow validation, materialization tamper, and interrupted recovery tests pass.
- [ ] Evaluation baseline rejects different suite digests and reports deliberate regressions.
- [ ] Candidate cannot modify protected policy/test/release paths.
- [ ] Verified pre-release snapshot and independent offline backup exist.
- [ ] Restore and rollback procedure has actually been exercised.

## 6. Documentation and release decision

- [ ] `uaf capabilities --json` matches docs and actual evidence.
- [ ] README quick start works from clean install.
- [ ] Known limitations/residual risks are prominent.
- [ ] Changelog and migration notes match schema/config changes.
- [ ] No AGI, universal exactly-once, unmeasured multiplier, or unverified parity claim.
- [ ] Human release owner approves the exact reviewed artifact.
- [ ] Tag/sign/publish only through the repository owner's explicit release process; UAF never does this autonomously.

A failed or missing mandatory gate blocks promotion. Do not relabel a failed gate as optional to make a release pass.
