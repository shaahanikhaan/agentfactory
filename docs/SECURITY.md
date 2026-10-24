# Security and threat model

## Security objective

A malicious prompt, fetched page, memory item, plugin manifest, agent blueprint, evaluation definition, model response, or candidate patch must not be able to expand authority merely by emitting instructions. Authorization is re-evaluated in ordinary Python at each governed boundary.

This is defense in depth, not a claim of complete sandboxing or invulnerability.

## Assets

- Workspace files and pre-action backups.
- SQLite task, memory, approval, quota, and audit state.
- Provider credentials in approved OS vaults or process environment variables.
- Dedicated browser profile cookies/session state and desktop account identity.
- Local network and cloud quota.
- Incumbent source tree and release configuration.
- Private memory and fetched content.

## Trust boundaries

| Boundary | Rule |
|---|---|
| Model → runner | Text/structured output or one typed ReAct decision; bounded calls; no direct state/graph mutation |
| Model/user → tool | Task allowlist + role + schema + risk policy on every invocation, including every ReAct observation |
| Blueprint → factory | Immutable version, disabled custom default, static tool names, bounded DAG/templates, digest-bound materialization |
| Suite → evaluation | Declarative checks only; no scorer imports; bounded fixtures/cases; no implicit provider/network/approval |
| External content → model | Explicit untrusted wrapper; chat-role tokens removed; source and hash retained |
| Plugin → runtime | Declarative manifest only; disabled by default; checksum verified; no auto-import |
| Candidate → incumbent | Isolated worktree, protected paths, tests/reviews, human-only promotion |
| Environment → persistence/logs | Credentials looked up only for a request; redaction before storage/output |
| Workspace → filesystem | Confined normalized paths, symlink checks, atomic write, output limits |
| Model/user → browser | Dedicated visible profile, public allowlisted HTTPS, bounded redacted snapshots, digest/label revalidation, R2/R3 exact approval |
| Model/user → desktop | Explicit executable allowlist, exact Win32 process/title, focus checks, bounded actions/text, mandatory fail-safe, R3 approval |
| OS vault → provider | Backend allowlist, hidden onboarding prompt, header-only credential use, no config/SQLite secret storage |
| Browser → local dashboard | Exact Host allowlist, per-launch header capability, Origin/Fetch-Site checks, 16 KiB JSON, CSP/no-store, no CORS, serial requests |
| Voice → dashboard commands | Permission-based one utterance, on-device preference/explicit vendor-processing consent, text fallback, separate start confirmation, no R2/R3 authority |
| Dashboard → onboarding/factory | Same governed services as CLI; literal-loopback credential writes and factory start; live readiness before success; fixed R0 idempotent startup DAG |

## Risk tiers in this build

- **R0:** bounded local reads/listing, non-executing Python AST maps, deterministic checks, and allowlisted browser navigation/snapshots.
- **R1:** reversible local writes. These still pass schema, allowlist, role, and idempotency controls.
- **R2:** externally consequential or sensitive operations such as browser text entry; exact payload/destination approval required.
- **R3:** destructive/irreversible-capable operations such as workspace delete, browser click, and desktop input; exact approval required. Workspace delete also creates a pre-action backup.

Ten narrow tools are registered in the current composition: five workspace (including read-only Python AST mapping), four browser, and one desktop batch tool. Browser/desktop execution remains disabled until explicitly configured and their optional dependencies are available. There is no direct messaging/publishing API connector; governed browser/native-app actions can still have external effects and require approval.

## Prompt-injection controls

- External bytes are labelled `EXTERNAL_UNTRUSTED_CONTENT` and described as data only.
- Common chat-template role tokens are removed from fetched/model-bound content.
- Script/style/template content is not included by the research text extractor.
- Tool permissions do not come from prompts, memory, skill text, blueprint instructions, upstream context, observations, or fetched content.
- Task experience captures no model output and starts pending. Only human-approved non-private records can be recalled, always bounded and wrapped as untrusted historical data; company startup explicitly disables recall.
- ReAct decisions cannot add tools or DAG nodes; malformed decisions, disallowed tools, and decision/tool budgets fail closed.
- Reviewer output must match a small verdict contract; it cannot mark arbitrary tool effects successful.
- Plugins and candidates cannot introduce arbitrary model-generated execution.

These controls reduce injection impact; they do not prove that a model will never follow hostile text. Keep sensitive credentials and network egress unavailable when processing hostile sources.

## Deny-by-default and least privilege

- Network, MCP, telemetry, providers, plugins, browser automation, and desktop control start disabled.
- `allow_paid=true` is rejected by configuration validation.
- Unknown providers, tools, models, task kinds, schema types, and config keys fail closed.
- Agents cannot approve their own high-risk action or durable memory promotion.
- Candidate paths cannot modify policy, approval, idempotency, configuration, tests, or CI release workflows.
- No arbitrary shell tool is registered.

## Approval integrity

Approval records bind action type, destination, risk, canonical payload digest, requester, and state. Approving a different payload does not authorize the pending invocation. Decisions and execution are audited with stable IDs. The approval CLI is intended for a human; agent role names are rejected by the service.

## Side-effect safety

The idempotency ledger stores payload digest, destination, attempt count, state, and receipt. Payload reuse with a different digest conflicts. A failed non-idempotent reservation is persisted as `uncertain` after transaction rollback, forcing reconciliation rather than silent retry. The `effect` CLI records bounded human evidence. An `executed` reconciliation requires a tool-shaped result for replay; `not-executed` permits only explicit subsequent resume. A task remains blocked while any of its effects is uncertain/reserved. This is not a universal exactly-once guarantee.

## Computer-use boundary

- The browser is visible and uses a dedicated persistent profile. That profile is sensitive logged-in identity, not a safe artifact to export or place on removable storage.
- Only allowlisted public HTTPS port-443 destinations are permitted. Routed requests and final URLs are checked, service workers/downloads are blocked, and credential-like paths/queries and credential/payment fields are denied.
- Snapshots are bounded/redacted and contain no cookie, local-storage, password-field, or arbitrary-script interface. Snapshot IDs bind a bounded page extraction, URL, title, element ref, and expected label. Every action revalidates the digest; changed content needs fresh approval.
- DNS checks do not pin the connection to the validated address. Hostile pages, dynamic DOM changes, lookalike labels, and user deception remain residual risks. Keep the browser visible and review the exact action.
- Desktop control resolves the real Win32 process and exact window title, requires one unambiguous target, and checks focus before every action. It is real host input, **not an OS sandbox**.
- Known shells, interpreters, browsers, system/file administration tools, and remote-control executables are rejected from the desktop allowlist. Clipboard/system/focus hotkeys and non-ASCII/secret-like desktop text are denied.
- Desktop action counts, coordinates, ASCII text, and waits are bounded; PyAutoGUI fail-safe is forced on. Driver calls are not claimed to have a hard real-time kill timeout. Locked/secure/elevated desktops are not bypassed.
- Browser clicks and all desktop batches are non-idempotent R3 effects. Browser typing is R2. Post-effect inspection failures are uncertain and must be reconciled from human evidence, not blindly repeated.

## Dashboard and voice boundary

- The dashboard binds to literal `127.0.0.1` by default. Credential writes are accepted only for literal loopback binds (`127.0.0.1` or `::1`), not merely a hostname that claims to resolve locally.
- A random per-launch capability appears in the URL fragment and is copied by first-party JavaScript to `X-UAF-Token`. Fragments are not sent in HTTP requests. Query-string capabilities, cookies, localStorage, and sessionStorage are not accepted/used.
- Static assets contain no status or credential data. API requests require the capability and an exact allowed `Host`; write requests require bounded JSON. Origin/Fetch-Site checks and no CORS headers reduce cross-site request risk. CSP, no-store, frame denial, no-referrer, and nosniff are applied to responses.
- Request handling is serial and responses close connections, bounding local resource use. A long provider diagnostic can delay other dashboard requests; it does not create an unbounded worker pool.
- Explicit non-loopback exposure requires an exact Host allowlist and disables credential writes, experience approval, and factory start. It is a narrow read-only preview/status mode, not a production remote-access/authentication design. Loopback is the recommended setup mode.
- The key is submitted directly to the local onboarding route and then to the approved OS vault. It is not accepted through voice and is not persisted by browser storage. Unexpected credential-route exception tracebacks are suppressed because third-party exception text may not be redaction-safe.
- Browser speech recognition is optional and starts only after a user action. On-device processing is preferred where feature-detected; unavailable local recognition never silently falls back to a vendor service. The user must explicitly clear that preference to permit browser/vendor processing.
- Voice commands can refresh or create/confirm the same bounded start request as the buttons. They cannot approve R2/R3 actions, alter policy, enable paid mode, or submit credentials. A separate start confirmation limits accidental speech activation.
- Dashboard department cards expose actual step evidence plus capability state, not fabricated agent activity. Startup uses the existing fixed R0 company DAG: local reliability inventory, an orchestration worker/reviewer brief whose model context excludes inventory entries and workspace filenames/contents, and deterministic quality acceptance that verifies upstream states, inventory bounds, a non-empty bounded brief, and the independent reviewer verdict without claiming additional execution. Planning text grants no tools or execution authority; higher-risk effects retain ordinary approval/recovery boundaries.

## Data protection

- Config rejects credential fields; one-key onboarding writes the secret only to an approved OS vault, with rollback on failed setup. Plaintext/fail keyring backends are denied.
- Environment credentials take precedence over vault credentials; `auth status` exposes presence/backend only, never the secret.
- Blueprint and suite registration rejects secret-like keys/recognizable credential strings before persistence; do not place real credentials in goals, inputs, or fixtures.
- Provider requests use credentials in headers, not URL query strings.
- Provider error bodies are not copied into logs because they may echo sensitive data.
- Logs and persisted structured data pass redaction helpers.
- Private memory is excluded from the narrow MCP search adapter.
- Privacy deletion scrubs active content, revisions, and FTS state; audit and the content-free experience-capture ledger retain tombstones so replay cannot recapture deleted outcomes.
- Non-loopback dashboard responses omit experience content and deny experience approval; loopback approval requires an explicit confirmed action and is not a voice command.

Redaction is heuristic. Do not use logs or memory as a secret store, and rotate a credential immediately if it was exposed.

## Plugin and update caveats

A Git worktree prevents incidental edits to the incumbent tree; it is **not** an OS security sandbox. `--allow-untrusted-code` explicitly permits host execution of candidate tests with a reduced environment and timeout. Use a disposable VM/container with no credentials for genuinely untrusted code. The application itself does not require Docker.

Python plugin discovery does not import code. Any future Python plugin runner must be treated as a new security boundary, not a small feature addition.

## Research residual risks

The research prototype validates DNS answers before connecting, but the HTTP stack performs its own resolution. A hostile DNS rebinding between those operations is not eliminated. Redirects are revalidated, but there is no egress proxy pinning the validated address. Do not use this prototype as a substitute for an enterprise SSRF boundary.

HTML extraction is intentionally simple, not a browser sanitizer. Binary documents, JavaScript-rendered pages, authenticated sources, and automatic crawling are not supported.

## Operational recommendations

1. Keep the OS and Python dependencies patched; run `pip-audit` in the actual environment.
2. Keep UAF home on stable storage with user-only permissions where the OS supports them.
3. Use separate least-privilege provider projects/accounts and low provider-side quotas.
4. Keep network disabled unless a task needs it.
5. Review approval payload and destination, not only the action name.
6. Verify snapshots periodically and keep an additional offline copy for disaster recovery.
7. Treat backups, memory exports, and the dedicated browser profile as sensitive data.
8. Use a visible unlocked desktop for computer use, disposable test accounts/windows first, and manual inspection after uncertain effects.
9. Run candidate code in a real disposable sandbox, then require human release review.

## Security verification

The suite includes traversal/absolute/sensitive-path denial, symlink escape, disconnected workspace behavior, schema rejection, approval mismatch/rejection, R3 recovery, secret redaction/rejection, OS-vault backend allowlisting, one-key rollback/eligibility, dashboard Host/capability/Origin/JSON/non-loopback boundaries, one-key live-failure/readiness and idempotent DAG checks, voice privacy/static persistence checks, prompt-role token removal, ReAct tool/turn/budget denial, immutable blueprint and cycle/data-flow validation, materialization tampering, interrupted DAG recovery, same-suite evaluation regressions, free-tier fail-closed behavior, quota/cooldown persistence, payload conflicts, uncertain side effects and human reconciliation, plugin tampering, SSRF fixtures, browser launch/domain/credential/stale-digest/restart checks, desktop process/window/focus/action/hotkey/partial-effect checks, and self-update gate tests.

Run `python scripts/verify.py`. Report vulnerabilities through the process in the root [SECURITY.md](../SECURITY.md); do not include live credentials or private data in a report.
