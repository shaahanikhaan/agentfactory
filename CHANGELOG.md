# Changelog

All notable changes are recorded here. This project uses semantic versioning for the package; 0.x releases may still change interfaces after migration notes and review.

## 0.1.0 — 2026-10-24 (alpha)

### Added

- Standard-library Python 3.11+ package and `uaf` CLI.
- Portable no-spend configuration and versioned SQLite schema with WAL, FTS5/fallback, integrity checks, and redacted audit events.
- Durable task contracts, legal transitions, dependencies, cancellation/resume, checkpoints, bounded Manager/Supervisor/Worker/Reviewer execution, and deterministic offline smoke work.
- Immutable declarative agent blueprints, atomic durable DAG factory runs, upstream-only data templates, digest-bound materialization, and explicit interruption recovery.
- Governed ReAct typed decisions, separate observation checkpoints, independent decision/tool budgets, and approval-safe replay.
- Reproducible development/held-out task suites, deterministic scorers, resource evidence, and same-suite regression gates.
- Gemini, Groq, OpenRouter, and loopback Ollama adapters behind explicit free/local eligibility, credentials, network, quota, retry, and cooldown controls.
- Guided one-Gemini-key onboarding with official model discovery, explicit free attestation, approved OS-vault backends, and rollback.
- Optional visible dedicated-profile browser navigation/snapshots and digest-bound approved click/type actions, including restart revalidation.
- Optional bounded Windows mouse/keyboard batches with exact process/window/focus checks and mandatory fail-safe.
- Human `effect list/reconcile` recovery with structured result replay and unresolved-effect resume blocking.
- Typed workspace tools with confinement, schemas, risk policy, payload-bound approvals, idempotency, uncertainty handling, atomic writes, and file backups.
- Provenance-aware memory with revisions, approval, search, export, privacy deletion, and snapshot-backed consolidation.
- Checksummed skills and disabled-by-default declarative plugins with a note-writer example.
- Bounded research prototype, optional MCP stdio adapter, and isolated human-gated self-update prototype.
- Verified SQLite snapshots/restores, diagnostics, capability reporting, and reproducible offline benchmark.
- Automated success/failure/security tests, research/architecture/operations/provider/Windows documentation, and release checklist.

### Known limits

- Windows 10/11, real browser/account, physical desktop-input, live external-provider, and third-party MCP-client acceptance are not established by the Linux/fake-driver test run.
- Direct chat connectors, desktop vision/voice, Unicode desktop input, and dashboard are not implemented; browser/native-app actions have no delivery guarantee.
- Research and browser DNS rebinding/pinning remain documented residual risks; optional GUI control is not an OS sandbox.
- Candidate worktrees are not OS sandboxes; no automatic merge/deploy/rollout exists.
- No arbitrary shell or Python plugin sandbox is implemented.
- The optional desktop dependency tree includes GPLv3+ `mouseinfo`; bundled-distribution license review is required.

No claim of AGI, universal exactly-once effects, permanent free cloud capacity, or unmeasured performance multiplier is made.
