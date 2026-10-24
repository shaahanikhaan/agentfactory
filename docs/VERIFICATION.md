# Verification evidence

## Reproducible gates

From a clean Python 3.11+ environment:

```bash
python -m pip install --upgrade pip setuptools
python -m pip install -e '.[dev]'
python scripts/verify.py

# Reproduce the optional MCP + computer-use evidence as well:
python -m pip install -e '.[dev,mcp,computer-use]'
python scripts/verify.py --pytest
```

Individual commands:

```bash
python -m compileall -q src tests scripts
python -m unittest discover -s tests -v
python -m pytest -q
python -m ruff check src tests scripts
python -m pip_audit --progress-spinner off
uaf doctor --json
uaf capabilities --json
uaf benchmark --iterations 5 --json
```

## Evidence from this checkout

Date: **2026-10-25**. Environment: Linux sandbox, Python 3.11.2, SQLite 3.40.1 with FTS5, 2 logical CPUs, approximately 3.8 GiB RAM. No real cloud credentials or cloud requests were used.

| Gate | Result |
|---|---|
| Editable package install / `uaf` entry point | Passed; core and combined computer-use extras |
| Compile all source/tests | Passed |
| Formal tests with optional MCP + computer-use packages installed | **183 passed, 70 subtests passed** |
| Release gate `scripts/verify.py --pytest` | Passed; compile, 183 unittest tests, pytest/subtests, Ruff, audit, and MCP integration |
| Ruff `src tests scripts` | Passed |
| `pip-audit` with optional dependencies installed | **No known vulnerabilities found** in that environment |
| CLI init/doctor/status | Passed; optional dependency detection and non-secret credential status |
| Offline add/run/timeline | Passed; deterministic success, 4 checkpoints, 0 model calls |
| Built-in offline factory DAG (CLI and clean wheel) | Passed; 2/2 steps, 8 checkpoints, 1 tool call, 0 model calls |
| Governed task experience | Passed; pending/idempotent terminal outcomes, sensitive-capture skip, human-only approval, bounded untrusted recall, private exclusion, and no privacy-delete resurrection |
| Python repository map | Passed; real AST imports/symbols/syntax evidence, top-level raise not executed, governed tool task, traversal/symlink defenses, and bounded/truncated output |
| Deterministic startup acceptance | Passed; five real contract checks, two startup tool calls, version-1/version-2 coexistence, and failed readiness for a whitespace brief despite a fake reviewer `pass` |
| Custom blueprint/ReAct/approval/recovery tests | Passed; immutable specs, nested data flow, decision reuse, tamper and interruption coverage |
| One-key onboarding and credential routing | Passed with fake official HTTP/vault drivers; rollback, previous-credential restoration even when config rollback also fails, backend allowlist, env precedence, and no config/DB secret |
| Company dashboard HTTP + one-key startup | Passed with real loopback HTTP and fake official/provider/vault drivers; Host/capability/Origin/JSON boundaries, selected-model low-thinking probe, no response/config/audit secret, live failure without readiness, non-loopback credential/start/write denial, stale-readiness and failed-doctor-check reporting, and idempotent 3/3 company DAG success/replay with two model calls, per-department evidence, private-filename/content exclusion, explicit/idempotent loopback-only experience approval, and non-loopback experience-content omission |
| Clean-wheel dashboard process/HTTP contract | Passed on a real OS-assigned loopback port; CSP static response, authenticated status, 11 named doctor checks, hostile-Host 403, fake-live setup and 3/3 company readiness with five acceptance checks, idempotent replay, private-filename/content exclusion, and non-loopback setup/factory-start/experience-approval writes each returning 403; no physical browser or live provider claim |
| One-click bootstrap | Passed command-plan/marker/doctor-gate tests plus an actual isolated Linux `prepare()` run: patched pinned pip/setuptools, lightweight `setup` extra, keyring present, Playwright/PyAutoGUI absent, Chromium marker false, and 11/11 doctor checks. Also covers automatic free-port launch, explicit full computer-use plan, fixed argv/no shell, bounded timeouts, optional Chromium failure tolerance, and doctor-failure launch blocking; no Windows execution claimed |
| Browser voice command slice | Passed JavaScript syntax and static/privacy/command markers; one utterance, `available/install` + `processLocally` preflight, no silent remote fallback, text fallback, no browser credential storage or voice approval; no physical microphone test |
| Governed browser tools | Passed with fake/real-adapter launch-contract drivers; visible dedicated profile, redaction, digest/restart revalidation, denied credential fields, and uncertainty |
| Governed desktop tools | Passed with fake Windows driver; approval-before-input, exact process/title/focus, bounded batches, reconciliation, resume, and replay without repeated input |
| Offline evaluation and same-suite baseline (CLI and clean wheel) | Passed; 8/8 cases, development/held-out accuracy 1.0, 0 model calls; regression gate passed |
| Optional ReAct blueprint without a provider | Correctly paused offline; 0 completed model calls, 1 routing attempt |
| Memory add/search | Passed |
| Backup create/verify/restore | Passed, including lifeline and corruption rejection |
| Plugin register/enable/run | Passed; governed note written in the confined workspace |
| Mocked provider worker/reviewer | Passed; bounded calls and durable evidence; malformed candidates/content/usage/token counts fail as bounded `invalid_response` errors |
| Official MCP 2.3.0 stdio integration | Passed; initialize, discover 3 tools, durable task add, memory search, clean shutdown |
| Wheel build and clean no-dependency install | Passed; 3 packaged dashboard assets, 2 blueprints, 11 governed tools, offline DAG 2/2, company DAG 3/3 with two fake-transport calls, two real startup tool calls and memory/privacy exclusion, real AST map, pending/approved experience, 8/8 evaluation, baseline gate, and truthful capability states |
| Benchmark | 5/5 succeeded, 0 failed, 0 model calls; 315.086 tasks/s and 29,810,688-byte process peak RSS on this host |
| Read-only self-update check | Passed against the trusted repository origin; no source mutation |

`pip-audit` skips the local `ultimate-agent-factory` project because it is not a PyPI dependency; its direct core dependency set is empty. The final audit environment also contained keyring 25.7.0, Playwright 1.64.1, PyAutoGUI 0.9.54, and their resolved transitive packages. Audit results cover installed third-party packages at the time of execution and are not a permanent vulnerability guarantee. Separate metadata review confirmed MIT keyring, Apache-2.0 Playwright, BSD PyAutoGUI, and GPLv3+ `mouseinfo`; this is not a complete redistribution legal review.

## Scenario coverage

The tests exercise:

- Config round-trip, secret rejection, paid-mode rejection, and resource ceilings.
- Migration idempotence, WAL/FTS5, integrity, foreign keys, and persistent audit.
- Snapshot hash/corruption checks, confirmed restore, and pre-restore lifeline.
- Task deduplication/conflicts, dependencies, transitions, cancellation, checkpoints, and timeline.
- Offline orchestration, bounded cloud worker/reviewer flows, one revision, schema enforcement, offline resume, model budgets, and daily provider budgets enforced across transient retries.
- Company startup v1/v2 coexistence, real five-check acceptance, two startup tool invocations, and blank-brief readiness rejection independent of a false reviewer pass.
- Lightweight/default and full computer-use bootstrap command plans, no default Chromium invocation, automatic free-port selection, and malformed provider-response normalization.
- Immutable blueprints, disabled registration, DAG cycles/data-flow validation, atomic creation, nested templates, idempotent start, materialization tamper checks, failure blocking, approval pause, and interruption recovery.
- Governed ReAct typed/final decisions, separate observations, disallowed tools, independent decision/tool budgets, structured output, hostile observations, and R3 decision replay.
- Offline/model evaluation cases, expected safe failures, development/held-out metrics, resource evidence, malformed/secret definitions, identical-digest baselines, and deliberate regression detection.
- Workspace confinement, exact visible-entry truncation boundaries, schema rejection, role/allowlist denial, approvals, reversible R3 deletion, disconnected storage, and non-executing bounded Python AST maps.
- Terminal experience capture, schema-v4 idempotency ledger, sensitive skips, agent-approval denial, explicit human recall approval, private exclusion, and deletion-safe replay.
- Idempotency replay, payload conflicts, interrupted non-idempotent uncertainty, human reconciliation, ledger-aware resume, and completed-result replay without repeated effects.
- OS-vault backend allowlisting, environment precedence, non-secret status, one-Gemini-key setup, rollback, bounded official discovery, and no free-tier inference.
- Dashboard Host/capability/Origin/Fetch-Site/JSON boundaries, literal-loopback credential writes, non-loopback denial, selected-model diagnostics, bounded health freshness, idempotent startup, live-failure honesty, explicit/idempotent experience approval, non-loopback content omission, and serial connection-close responses.
- Bootstrap fixed-argv command plans, corrupt-marker recovery, doctor-failure launch blocking, and loopback dashboard command construction.
- Voice local availability/install/privacy/static persistence checks and separate confirmation paths; not a physical speech-recognition result.
- Browser launch contract, dedicated profile, URL/DNS controls, redacted bounded snapshots, content-digest approval binding, restart revalidation, credential-field denial, and post-effect uncertainty.
- Desktop disabled/non-Windows fail-closed behavior, exact window/process/focus checks, bounded action schemas, mandatory fail-safe, R3 approval before adapter input, and uncertain recovery.
- Free/local model eligibility, official evidence hosts, stale dates, credentials, response parsing, output limits, quotas, retries, and cooldown persistence.
- Memory approval/search/fallback, revisions, secret rejection, privacy deletion, dry-run/apply consolidation, expiry, and export digest.
- Skill/plugin progressive loading, enablement, schema checks, tamper rejection, and no Python auto-import.
- Research SSRF fixtures, content limits, provenance, and untrusted-role-token handling.
- Narrow MCP tool registration and limits.
- Self-update trusted origin, protected paths, isolated worktree, missing-test rejection, and human-only promotion evaluation.
- CLI success/error behavior and redacted logs.

## Evidence not claimed

- No assistant-executed Windows 10/11 dashboard/launcher, physical microphone, physical mouse/keyboard, or 4 GB Windows acceptance in this checkout. Separately, the user reported Windows Python 3.11.9/doctor/Credential Locker/Gemini configuration success; that is not a completed Windows acceptance run.
- No real Chromium page/account session, browser speech-recognition/audio-path result, chat delivery, or external message; browser/desktop tests use fake drivers and adapter launch contracts.
- No real cloud request was made by the automated assistant test gates and no successful live Gemini/Groq/OpenRouter generation or live Ollama benchmark is claimed; onboarding/provider HTTP is mocked. The user's separate real Gemini attempts ended in provider-unavailable/timeout outcomes.
- No third-party GUI MCP client evidence; the automated protocol test uses the official Python SDK client over real stdio.
- No production egress proxy or hostile-network test.
- No formal reasoning-quality benchmark or proof of reviewer independence.
- No automatic release rollout, external deployment, public publishing, or external messaging.

Run the corresponding acceptance gate and record its environment before changing these statements.
