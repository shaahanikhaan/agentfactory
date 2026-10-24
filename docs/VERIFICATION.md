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

Date: **2026-10-24**. Environment: Linux sandbox, Python 3.11.2, SQLite 3.40.1 with FTS5, 2 logical CPUs, approximately 3.8 GiB RAM. No real cloud credentials or cloud requests were used.

| Gate | Result |
|---|---|
| Editable package install / `uaf` entry point | Passed; core and combined computer-use extras |
| Compile all source/tests | Passed |
| Formal tests with optional MCP + computer-use packages installed | **145 passed, 48 subtests passed** |
| Release gate `scripts/verify.py --pytest` | Passed; compile, 145 unittest tests, pytest/subtests, Ruff, audit, and MCP integration |
| Ruff `src tests scripts` | Passed |
| `pip-audit` with optional dependencies installed | **No known vulnerabilities found** in that environment |
| CLI init/doctor/status | Passed; optional dependency detection and non-secret credential status |
| Offline add/run/timeline | Passed; deterministic success, 4 checkpoints, 0 model calls |
| Built-in offline factory DAG (CLI and clean wheel) | Passed; 2/2 steps, 8 checkpoints, 1 tool call, 0 model calls |
| Custom blueprint/ReAct/approval/recovery tests | Passed; immutable specs, nested data flow, decision reuse, tamper and interruption coverage |
| One-key onboarding and credential routing | Passed with fake official HTTP/vault drivers; rollback, backend allowlist, env precedence, and no config/DB secret |
| Governed browser tools | Passed with fake/real-adapter launch-contract drivers; visible dedicated profile, redaction, digest/restart revalidation, denied credential fields, and uncertainty |
| Governed desktop tools | Passed with fake Windows driver; approval-before-input, exact process/title/focus, bounded batches, reconciliation, resume, and replay without repeated input |
| Offline evaluation and same-suite baseline (CLI and clean wheel) | Passed; 8/8 cases, development/held-out accuracy 1.0, 0 model calls; regression gate passed |
| Optional ReAct blueprint without a provider | Correctly paused offline; 0 completed model calls, 1 routing attempt |
| Memory add/search | Passed |
| Backup create/verify/restore | Passed, including lifeline and corruption rejection |
| Plugin register/enable/run | Passed; governed note written in the confined workspace |
| Mocked provider worker/reviewer | Passed; bounded calls and durable evidence |
| Official MCP 2.3.0 stdio integration | Passed; initialize, discover 3 tools, durable task add, memory search, clean shutdown |
| Wheel build and clean no-dependency install | Passed; 9 governed tools, non-secret vault status, disabled browser/desktop fail-closed, packaged offline DAG, 8/8 evaluation, and baseline gate |
| Benchmark | 10/10 succeeded, 0 failed, 0 model calls; 493.198 tasks/s and 29,253,632-byte process peak RSS on this host |
| Read-only self-update check | Passed against the trusted repository origin; no source mutation |

`pip-audit` skips the local `ultimate-agent-factory` project because it is not a PyPI dependency; its direct core dependency set is empty. The final audit environment also contained keyring 25.7.0, Playwright 1.64.1, PyAutoGUI 0.9.54, and their resolved transitive packages. Audit results cover installed third-party packages at the time of execution and are not a permanent vulnerability guarantee. Separate metadata review confirmed MIT keyring, Apache-2.0 Playwright, BSD PyAutoGUI, and GPLv3+ `mouseinfo`; this is not a complete redistribution legal review.

## Scenario coverage

The tests exercise:

- Config round-trip, secret rejection, paid-mode rejection, and resource ceilings.
- Migration idempotence, WAL/FTS5, integrity, foreign keys, and persistent audit.
- Snapshot hash/corruption checks, confirmed restore, and pre-restore lifeline.
- Task deduplication/conflicts, dependencies, transitions, cancellation, checkpoints, and timeline.
- Offline orchestration, bounded cloud worker/reviewer flows, one revision, schema enforcement, offline resume, and model budgets.
- Immutable blueprints, disabled registration, DAG cycles/data-flow validation, atomic creation, nested templates, idempotent start, materialization tamper checks, failure blocking, approval pause, and interruption recovery.
- Governed ReAct typed/final decisions, separate observations, disallowed tools, independent decision/tool budgets, structured output, hostile observations, and R3 decision replay.
- Offline/model evaluation cases, expected safe failures, development/held-out metrics, resource evidence, malformed/secret definitions, identical-digest baselines, and deliberate regression detection.
- Workspace confinement, schema rejection, role/allowlist denial, approvals, reversible R3 deletion, and disconnected storage.
- Idempotency replay, payload conflicts, interrupted non-idempotent uncertainty, human reconciliation, ledger-aware resume, and completed-result replay without repeated effects.
- OS-vault backend allowlisting, environment precedence, non-secret status, one-Gemini-key setup, rollback, bounded official discovery, and no free-tier inference.
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

- No Windows 10/11 execution, real Credential Locker secret write, physical mouse/keyboard input, or 4 GB Windows acceptance in this checkout.
- No real Chromium page/account session, chat delivery, or external message; browser/desktop tests use fake drivers and adapter launch contracts.
- No real Gemini/Groq/OpenRouter request and no live Ollama model benchmark; onboarding HTTP discovery is mocked.
- No third-party GUI MCP client evidence; the automated protocol test uses the official Python SDK client over real stdio.
- No production egress proxy or hostile-network test.
- No formal reasoning-quality benchmark or proof of reviewer independence.
- No automatic release rollout, external deployment, public publishing, or external messaging.

Run the corresponding acceptance gate and record its environment before changing these statements.
