# Architecture

## 1. System boundary

UAF is a **deterministic control plane around probabilistic model calls**. A model may propose text inside a bounded worker/reviewer step or one typed ReAct decision; it cannot mutate task/factory state, add DAG nodes, choose arbitrary Python, grant itself a tool, approve an action, or promote a release.

```text
CLI / loopback dashboard / optional MCP stdio
          |
          v
   typed task contract
          |
          v
+-------------------------------+
| Durable runner / state machine|
| Manager -> Supervisor         |
| Worker -> Reviewer            |
+---------------+---------------+
                |
     +----------+-----------+-------------+
     v          v           v             v
 provider     tool        memory       checkpoints
 router      registry     curator      + audit timeline
     |          |
 free/local   policy + approval + idempotency + workspace
 adapters
                |
             SQLite
```

All major services share the composition root in `src/uaf/app.py`. The CLI, loopback dashboard, and MCP adapter do not maintain separate parallel state. The dashboard is a thin stdlib HTTP/browser client over onboarding, provider diagnostics, doctor, and factory services; it has no independent agent runtime or approval path. Browser voice recognition translates a small command set into those same explicit requests and never becomes an authorization principal.

## 2. Task contract and state machine

A task includes a stable ID, goal, kind, requester, department, priority, risk tier, deadline, dependencies, input, constraints, tool allowlist, expected output schema, budget, idempotency key, and correlation ID.

Persisted states are:

```text
queued -> planning -> running -> verifying -> succeeded
                    |          |       |
                    |          |       +-> running (bounded revision)
                    |          +-> awaiting_approval
                    |          +-> retry_wait
                    |          +-> paused_offline
                    |          +-> uncertain_side_effect
                    +-> failed / cancelled
```

`ALLOWED_TRANSITIONS` is code, not documentation. Invalid transitions raise an error. Terminal success cannot be reopened. Failed/cancelled/paused tasks require explicit resume; interrupted in-flight states are not silently executed again.

### Durable steps

Every logical role step has a deterministic step ID and a checksummed result. `_step()` first looks for a completed checkpoint. A resumed task can therefore reuse committed manager/supervisor/worker evidence instead of repeating model calls.

A crash between an external effect and its checkpoint is exactly why the idempotency ledger is separate from task checkpoints. Arbitrary external systems still require destination-specific reconciliation.

## 3. Roles and budgets

- **Manager:** normalizes the contract and records acceptance intent.
- **Supervisor:** creates one bounded work order and checks tool/policy scope.
- **Worker:** performs deterministic smoke work, one governed tool, or one bounded model call.
- **Reviewer:** validates deterministic evidence or returns a structured pass/revise/fail verdict.

Additional role charters (recovery, provider, memory, extension security, security, release) are explicit logical profiles. They are not claims that separate model processes are always running.

Defaults are serial execution, one LLM call at a time, at most four model calls per agent task, two worker revisions, bounded prompt/output sizes, a wall deadline, and finite queue/tool/step budgets. Task budgets may narrow but not exceed global ceilings.

## 4. Provider router

Each adapter is narrow and independent:

- Gemini uses its native `generateContent` response shape.
- Groq and OpenRouter use bounded OpenAI-compatible chat requests with different fixed endpoints.
- Ollama uses a loopback-only local endpoint and never requires a cloud credential.

The router, not an adapter, decides eligibility. It checks configuration, capability, freshness, official evidence host, credential presence, network permission, daily local budget, and persisted cooldown. Provider configuration is redacted before persistence; raw OS-vault/environment credentials are never inserted into SQLite. Guided Gemini onboarding uses the official model-list API and an approved OS-vault backend, but requires a separate free-tier attestation.

Retries are bounded. Rate limits persist cooldown and honor `Retry-After`; scoped health/quota observations survive process restart. No provider key rotation, paid fallback, or hidden network call exists.

## 5. Tools, policy, and effects

Every tool has metadata, version, JSON-schema subset, risk tier, allowed roles, timeout budget, idempotency declaration, and output bounds. Invocation order is:

1. Resolve registered tool.
2. Validate exact input shape.
3. Check task allowlist and role.
4. For R2/R3, require approval bound to canonical payload and destination.
5. For effects, reserve/replay through the idempotency ledger.
6. Execute the built-in operation.
7. Validate output and enforce size limits.
8. Persist receipt, status, elapsed time, and redacted audit metadata.

The built-in workspace adapter uses confined paths, rejects traversal/absolute/sensitive paths, checks symlinks, writes atomically, verifies postconditions, and backs up overwritten/deleted files. It pauses if the workspace is disconnected rather than redirecting to another drive. The R0 `workspace.python_map` adapter walks only confined, non-sensitive Python sources and parses them with the standard-library AST; it returns bounded hashes/imports/symbols and never imports or executes source.

Optional browser/desktop adapters use the same registry, approval, and ledger rather than a separate action path. The browser launches a visible dedicated Playwright profile, restricts public allowlisted HTTPS destinations, and produces bounded redacted element snapshots. Its deterministic snapshot digest and expected label are revalidated before every action, including after approval/process restart. Desktop batches resolve the exact Win32 process/window, enforce focus and bounded declarative actions, and force PyAutoGUI fail-safe on. Neither adapter is an OS sandbox or a direct chat connector.

### Exactly-once boundary

For a known idempotent local operation, replay can return the recorded result. For a non-idempotent external effect, an interrupted reservation becomes `uncertain`; UAF does not blindly retry. Only a destination-specific reconciler or audited human evidence through `effect reconcile` can complete that record. Task resume remains blocked until every uncertain/reserved effect is resolved. UAF therefore claims **idempotent orchestration where supported**, not universal exactly-once delivery.

## 6. Memory and checkpoints are different

- **Task checkpoints:** operational replay state for one task.
- **Durable memory:** user-visible facts/preferences/procedures with provenance, sensitivity, confidence, expiry, approval status, and revisions.
- **Audit events:** append-oriented operational evidence, redacted before persistence.
- **Logs:** rotating local diagnostics, not the source of truth.

Memory supports exact normalized-hash consolidation proposals, dry-run evidence, pre-apply snapshot, idempotent apply, FTS5 search, LIKE fallback, export digest, and privacy deletion that also scrubs revisions and search indexes. Secret-looking content is rejected rather than promoted.

Task experience is a narrower governed layer over that store. Terminal task outcomes are captured idempotently without model output and remain pending. A schema-v4 content-free capture ledger prevents replay duplication and privacy-delete resurrection. Only explicitly human-approved non-private outcomes can be recalled into worker/ReAct prompts, where they are bounded untrusted evidence rather than instructions. Privacy-sensitive blueprints can disable recall with `memory_recall: false`; the built-in company startup does so.

## 7. Extensions

Skills register metadata first and load a checksummed Markdown body only when requested. Declarative plugins contain a typed input schema and a governed tool workflow; they are disabled until explicitly enabled. Discovery of Python entry points is metadata-only.

There is intentionally no “safe Python hot reload.” Importing third-party Python is code execution and would require a separate OS sandbox, dependency review, and license review.

## 8. Research, MCP, and self-update

Research fetch permits bounded HTTPS text/HTML/JSON/Markdown, blocks credentials/nonstandard ports/private or special DNS answers, revalidates redirects, strips script/style content, stores source hashes, and wraps model context as untrusted data. It is a prototype because validation-time DNS and the actual egress connection are not bound to the same address.

Optional MCP uses the official SDK over stdio and exposes only task list/add and bounded approved non-private memory search. There is no network listener or bearer-auth claim for stdio.

Self-update performs a trusted-origin read-only commit comparison or creates an isolated detached worktree candidate from a reviewed patch. Protected policy/test/release paths are rejected. Tests, security review, dependency/license review, incumbent comparison, and human approval remain explicit gates. The current release never merges, pushes, or deploys automatically.

## 9. Data locations and recovery

Config, the primary database, and the logged-in dedicated browser profile belong on stable local storage with user-only access where supported. Snapshots use SQLite's online backup API, are hashed and integrity-checked, and a pre-restore lifeline is created automatically. Restore uses the same backup API into the existing destination, avoiding replacement of an open database file on Windows.

See [Operations](OPERATIONS.md) for recovery commands and [Security](SECURITY.md) for trust boundaries.

## 10. Declarative factory graph and materialization

Schema v3 adds immutable agent blueprints, factory runs, and run/task mappings. A blueprint is validated data—not executable Python—and defines at most eight agent profiles and twelve DAG steps. Custom registrations are disabled until explicitly enabled. A name/version cannot be overwritten with different content.

Factory start writes the run, all tasks, dependencies, and mappings in one transaction. Every task uses the factory run as its correlation ID and has a stable per-run idempotency key. The serial driver executes topological order through the same `TaskRunner`; there is no parallel hidden executor.

Templates can read the factory goal, validated inputs, and declared upstream output/result/state. Since upstream evidence is not available at graph creation, a ready task is materialized just before execution. Goal, input, constraints, and agent profile are stored atomically with a materialization digest. Resume verifies the digest before using the task. Static tool names, schema checks, task allowlists, and the normal policy engine remain mandatory.

The factory run has explicit approval, quota-retry, offline, interruption, failure, cancellation, success, and uncertain-effect states. `factory resume` is the operator boundary for recovery; it does not auto-approve, reconcile unknown effects, or bypass attempt/quota limits. See [Factory and ReAct](FACTORY.md).

## 11. Governed ReAct decision/observation journal

A `react` task adds a bounded protocol to the existing worker/reviewer runtime. Each model call returns either a final answer or one tool name plus a JSON argument object. The decision is checkpointed before any effect. A separate observation checkpoint contains the actual governed tool result. Subsequent prompts receive only bounded history and untrusted-content wrappers.

The runner limits decisions to three turns, reserves a reviewer call, and independently enforces the tool-call budget. A tool budget of one still permits the sequence decision → observation → final decision → review; a second tool request is denied. Approval resume reuses the committed decision and deterministic observation step ID, preserving payload and idempotency identity.

## 12. Evaluation evidence plane

Evaluation runs execute real task contracts and store per-case results separately from the summary run. A canonical suite digest binds baseline comparisons to identical cases/scorers. Metrics distinguish expected safe behavior (`accuracy`) from raw task success, and include development/held-out splits, durations, model calls, tool calls, and checkpoints.

The regression gate is evidence for a human, not an automatic learner or promotion mechanism. The built-in eight-case suite is deterministic and offline; optional model suites use the same no-spend provider gates. See [Evaluation](EVALUATION.md) and ADR 0006.
