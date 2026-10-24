# Capability matrix

Generated conceptually from `uaf capabilities --json`; the CLI is authoritative for the running version. Evidence paths refer to automated tests, not a guarantee that every environment was exercised.

| Capability | State | Actual scope / evidence |
|---|---|---|
| Core config | `implemented` | Validated portable config, secret rejection, no-spend defaults — `tests/test_config.py` |
| SQLite durability | `implemented` | Schema v1/v2/v3/v4, WAL, FTS5/fallback, integrity/FK checks — `tests/test_db.py` |
| Backup/restore | `implemented` | Online backup, hash/integrity verification, lifeline, restore — `tests/test_backup.py` |
| Task orchestration | `implemented` | Contracts, dependencies, legal transitions, checkpoints, cancel/resume, bounded revisions — `tests/test_tasks.py`, `tests/test_runner.py` |
| Offline agent factory | `implemented` | Real deterministic four-role smoke workflow; zero model calls — `tests/test_runner.py` |
| Cloud agent factory | `implemented_optional` | Worker/reviewer through a configured eligible provider; mocked transport tests — `tests/test_runner.py` |
| Declarative agent blueprints | `implemented` | Immutable bounded team specs, validated tools/DAG/templates, disabled custom registration — `tests/test_factory.py` |
| Durable factory DAG | `implemented` | Atomic task graph, upstream data flow, digest-bound materialization, idempotent start, explicit recovery — `tests/test_factory.py` |
| Governed ReAct | `implemented_optional` | Typed decision/observation checkpoints, tool/schema/budget enforcement, approval resume; eligible model required — `tests/test_react.py` |
| Reproducible evaluation | `implemented` | Eight-case offline suite, custom model/task suites, deterministic scorers, resource metrics, same-suite regression gates — `tests/test_evaluations.py` |
| One Gemini key onboarding | `implemented_optional` | Official discovery, explicit free confirmation, OS vault and rollback — `tests/test_onboarding.py`, `tests/test_credentials.py`; no live account tested here |
| Brain pool | `implemented_optional` | Gemini/Groq/OpenRouter/Ollama adapters, free/local eligibility, quotas/cooldowns — `tests/test_providers.py`; live terms unverified here |
| Workspace tools | `implemented` | Read/list/Python AST map/write/delete, confinement, schemas, approvals, atomic/reversible operations — `tests/test_tools.py`, `tests/test_repository.py` |
| Governed task experience | `implemented` | Idempotent pending outcomes, sensitive-capture skip, privacy-delete-safe ledger, human-approved non-private untrusted recall — `tests/test_experience.py` |
| Idempotency | `implemented` | Replay, digest conflicts, uncertain recovery, `effect` reconciliation and resume gating — `tests/test_idempotency.py`, `tests/test_desktop.py` |
| Durable memory | `implemented` | Provenance, revisions, privacy deletion, FTS/LIKE, export, dry-run/apply consolidation — `tests/test_memory.py` |
| Skills | `implemented` | Checksummed progressive disclosure — `tests/test_extensions.py` |
| Declarative plugins | `implemented` | Disabled by default, manifest integrity, governed workflow rendering — `tests/test_extensions.py` |
| Python plugins | `planned` | No safe OS sandbox claimed; discovery never imports code |
| MCP stdio | `implemented_optional` | Official SDK integration with three narrow tools — `tests/test_mcp.py`; SDK/client acceptance is environment-specific |
| MCP HTTP | `planned` | No HTTP listener |
| Research fetch | `prototype` | Bounded HTTPS, SSRF checks, provenance/untrusted wrapper — `tests/test_research.py`; DNS rebinding residual risk |
| Self-update | `prototype` | Trusted-origin check, isolated candidate, gate enforcement — `tests/test_self_update.py`; no automatic rollout |
| Windows 10/11 acceptance | `prototype` | Windows-compatible code/runbook plus user-reported Python 3.11.9, doctor, Credential Locker, and Gemini configuration evidence; full dashboard/mic/desktop/4 GB acceptance remains pending |
| Local company dashboard | `implemented` | Stdlib serial loopback UI/API, one-key onboarding, live readiness, real idempotent three-step startup DAG with two bounded model calls, per-department execution evidence, opt-in unused capabilities, and loopback-only experience review — `tests/test_dashboard.py`; Windows/browser acceptance pending |
| One-click Windows launcher | `implemented_optional` | Local venv, pinned bootstrap, optional Chromium, init/doctor gate, dashboard launch — `Start-UAF.cmd`, `scripts/start_factory.py`, `tests/test_bootstrap.py`; target-OS execution pending |
| Browser voice commands | `implemented_optional` | Permission-based one-utterance Web Speech, on-device preference, explicit vendor-processing consent, text fallback, two-step start — dashboard assets/tests; physical microphone acceptance pending |
| Browser automation | `implemented_optional` | Visible dedicated profile, domain/SSRF checks, bounded snapshots, digest-bound R2/R3 actions and restart revalidation — `tests/test_browser.py`; real browser/account acceptance pending |
| Desktop mouse/keyboard | `implemented_optional` | Bounded Windows batches, exact process/window/focus binding, fail-safe, R3 and reconciliation — `tests/test_desktop.py`; physical Windows input untested here |
| Native chat connectors | `planned` | No direct Slack/WhatsApp/Teams API connector; approved browser/native-app actions only |
| Native desktop voice/vision/Unicode input | `planned` | Dashboard voice is not a native desktop adapter; desktop typing is printable ASCII only |
| Arbitrary shell | `planned` / denied | No arbitrary shell tool; do not represent this as a safe shell sandbox |

## Meaning of states

- `implemented`: core code exists and the cited local tests exercise its main success/failure paths.
- `implemented_optional`: code exists behind an optional dependency/service and explicit configuration; external acceptance is still required.
- `prototype`: narrow code exists with documented residual risks or incomplete production hardening.
- `planned`: no working implementation is claimed.

## What “more powerful” means here

No unsupported multiplier is used. Improvements are measured by concrete controls: durable replay, bounded retries/revisions, exact approval binding, denied traversal/permission expansion, quota persistence, reproducible tests, audit evidence, and explicit failure states. `uaf eval` now adds fixed suites, per-case scores, resource usage, and same-digest baseline regressions. A broader performance or model-quality claim still needs a representative frozen benchmark, baseline, machine/provider configuration, and reproducible result.
