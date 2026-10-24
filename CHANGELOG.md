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
- Serial loopback company dashboard with per-launch capabilities, strict Host/Origin/JSON boundaries, API-key-first setup, reviewed automatic model selection, live readiness, honest department states, and an idempotent real startup DAG.
- `Start-UAF.cmd` plus bounded local bootstrap for Windows venv/dependencies/optional Chromium/init/doctor/dashboard launch.
- Optional permission-based browser voice commands with on-device availability/install preflight, explicit vendor-processing consent, text fallback, and separate start confirmation; no voice credential or R2/R3 authority.
- Optional visible dedicated-profile browser navigation/snapshots and digest-bound approved click/type actions, including restart revalidation.
- Optional bounded Windows mouse/keyboard batches with exact process/window/focus checks and mandatory fail-safe.
- Human `effect list/reconcile` recovery with structured result replay and unresolved-effect resume blocking.
- Typed workspace tools with confinement, schemas, risk policy, payload-bound approvals, idempotency, uncertainty handling, atomic writes, and file backups.
- Provenance-aware memory with revisions, approval, search, export, privacy deletion, and snapshot-backed consolidation.
- Schema-v4 governed task experience with idempotent pending outcomes, sensitive-capture skips, deletion-safe replay, and human-approved non-private untrusted recall.
- Governed R0 `workspace.python_map` with bounded stdlib AST imports/symbols, syntax evidence, symlink defenses, and no source execution.
- Evidence-first dashboard activity, opt-in unused capability cards, and loopback-only confirmed experience review; non-loopback responses omit experience content.
- Three-step company startup with local reliability inventory, privacy-safe memory-free orchestration worker/reviewer brief, and deterministic quality acceptance.
- Checksummed skills and disabled-by-default declarative plugins with a note-writer example.
- Bounded research prototype, optional MCP stdio adapter, and isolated human-gated self-update prototype.
- Verified SQLite snapshots/restores, diagnostics, capability reporting, and reproducible offline benchmark.
- Automated success/failure/security tests, research/architecture/operations/provider/Windows documentation, and release checklist.

### Fixed

- Gemini 3.8 live connectivity probes now use explicit low thinking and a 256-token combined thinking/output budget instead of an 8-token default-thinking probe; invalid or unsupported thinking levels fail closed.
- Provider diagnostics can target an explicit configured model so dashboard readiness tests the selected eligible model rather than assuming the first entry.
- Daily provider request budgets are rechecked before every transient retry instead of only during initial candidate selection.
- `uaf doctor` now exits nonzero when required checks fail, so the Windows launcher's doctor gate cannot report a false success.
- Optional Chromium timeout/OS-install failures no longer abort the normal-browser dashboard setup.
- Onboarding restores the previous vault credential even when configuration rollback also fails; the runner failure-state guard now checks the actual current state.
- Workspace listings report `truncated` only when visible entries actually remain after the requested limit.
- Non-loopback dashboards deny factory start as well as credential/experience writes; stale live readiness is labelled `stale`, failed doctor checks are named, busy credential fields are disabled, and hidden remote experience counts no longer produce a misleading empty message.

### Known limits

- Windows 10/11 dashboard/launcher, real browser/account/microphone, physical desktop-input, successful live external-provider, and third-party MCP-client acceptance are not established by the Linux/fake-driver test run; user-reported Windows onboarding is partial evidence only.
- Direct chat connectors, native desktop vision/voice, and Unicode desktop input are not implemented; browser/native-app actions have no delivery guarantee. Browser dashboard voice is optional and support/audio-path dependent.
- Research and browser DNS rebinding/pinning remain documented residual risks; optional GUI control is not an OS sandbox.
- Candidate worktrees are not OS sandboxes; no automatic merge/deploy/rollout exists.
- No arbitrary shell or Python plugin sandbox is implemented.
- The optional desktop dependency tree includes GPLv3+ `mouseinfo`; bundled-distribution license review is required.

No claim of AGI, universal exactly-once effects, permanent free cloud capacity, or unmeasured performance multiplier is made.
