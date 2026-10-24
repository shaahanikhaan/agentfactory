# External repository research and integration decisions

Accessed **2026-10-24**. This register distinguishes metadata screening from actual documentation/source inspection. A README claim, star count, or model listing is not acceptance evidence. Reference checkouts and downloaded artifacts stayed outside this repository and are not shipped in the ZIP.

## Integration rules

- Keep UAF's Python 3.11+, standard-library core, serial resource profile, SQLite durability, and one-key optional Gemini path.
- Do not import a repository merely because it is popular. Review license, provenance, resource cost, security model, and fit with existing services first.
- No quota-evading failover, paid fallback, autonomous approvals, arbitrary shell, auto-installed git hooks/watchers, unreviewed cyber capabilities, or third-party code auto-import.
- No source files were copied from the projects below. The implemented slices are independent, bounded adaptations of architectural ideas using UAF's existing contracts. Any future copied permissively licensed code requires its copyright/license notice and a separate review.

## Requested repositories

| Project and inspected revision | Evidence inspected | Decision |
|---|---|---|
| [Friday](https://github.com/subhansh-dev/Friday-Autonomous-Cognitive-AI-Operating-System) — `6e090cf8784966b16995e80867d6eff15de602fc` | README, complete tree, license: 289 files/39.3 MB; large MediaPipe binaries; cognitive/memory/orchestration/cyber modules | **No code integration.** Its BUSL-1.1 grant is non-commercial with a four-year change to MIT, incompatible with simply absorbing code into this MIT distribution. Large binaries and cyber modules are outside the 4 GB/minimal-ZIP and safety scope. Existing UAF memory, approvals, and role DAGs already cover the useful high-level direction without copying it. |
| [open-cowork](https://github.com/coasty-ai/open-cowork) — `fbbc6713912f28db593b2954cdf270c601f3dd5e` | MIT license, README, `ARCHITECTURE.md`, `SECURITY.md`, core agent-loop/types, backend run routes; 343 files/3.1 MB | **Patterns adapted, no runtime imported.** Useful ideas are one executor-neutral run contract, structured durable activity, explicit approval, bounded stalls/retries, and idempotent event replay. UAF keeps its Python stdlib server and existing task/checkpoint records instead of adding Node 22/pnpm/Electron/cloud-machine dependencies. Dashboard activity is read from real factory state, not a fabricated event stream. |
| [DevMind / apcodingagentjarvis](https://github.com/lion-guru/apscodingagentjarvis) — `c0b5f30584870e0cfcc53f60291b5b2ac3120899` | README, MIT top-level license, complete tree: 9,498 files/202.1 MB | **Rejected for integration.** The tree includes bundled runtimes, large tree-output artifacts, many third-party/vendor directories, and a `clude code/claude-code-leak-main` directory. A top-level MIT file cannot establish provenance or relicense all bundled content. Nothing was copied or executed. Specialist/reviewer concepts already exist in UAF's governed runtime. |
| Supplied `http://stonic.ai` | Direct page fetch failed; no ownership/provenance assumption was made | **No integration.** The failed domain was not treated as proof of relation to another Stonic website or repository. |
| [Stonic-AI](https://github.com/alfaazkhanofficial/Stonic-AI) — `b6a271705c0c7721e4ece499cde546fd4f88affd` | README and repository metadata/tree; GitHub reported no license; README labels task/search/voice areas as developing | **No code or installer integration.** Missing license and developing features do not meet the reuse/acceptance bar. UAF's real browser/desktop adapters and browser speech preflight remain honestly optional instead of claiming Stonic feature parity. |

## Additional projects screened

| Project and revision | Review result |
|---|---|
| [projectmem](https://github.com/riponcm/projectmem) — `e49dd0c5eabaf5962a54ffc7f7480d60a2f63133` | MIT; README, security guidance, complete tree (92 files/3.9 MB). Its typed issue/attempt/fix events and warning before repeating a failed approach are useful. Its own security guide warns that agent-read memory can be prompt injection and may contain sensitive typed data. UAF independently implemented pending, redacted task outcomes with explicit human approval, privacy-delete-safe idempotency, and untrusted bounded recall. No background watcher, global memory, or git hook was added. |
| [agent-memory](https://github.com/tigerless-labs/agent-memory) — `489eb9df3c694ef1cb4669afa0a5ba4d5ad27728` | MIT; README, tree (207 files/1.6 MB), and recall implementation inspected. Local eligibility/ranking/provenance ideas are useful, but UAF already has SQLite FTS5/LIKE, revisions, approval, and privacy deletion. No second memory runtime or host hooks were introduced. |
| [Aider](https://github.com/Aider-AI/aider) — `5dc9490bb35f9729ef2c95d00a19ccd30c26339c` | Apache-2.0; README/tree (691 files/77.7 MB) and repository-map documentation located. The useful lightweight idea is compact repository evidence before model work. UAF independently implemented a narrower stdlib-Python AST map rather than importing Aider, tree-sitter, a terminal AI, or model backends. JavaScript/TS mapping is not claimed. |
| [Cognee](https://github.com/topoteretes/cognee) — `37f788bd287750e10d7610173e5332b3843f6ebd` | Apache-2.0 metadata/README screened. Graph/embedding infrastructure and optional model pipelines do not justify a second heavy memory stack for the current 4 GB core. Not integrated. |
| [ERA](https://github.com/BinSquare/ERA) — `04193bd4f25d06c0bfd0b3ad01461f57cce2857f` | Apache-2.0 metadata screened; repository is archived. No sandbox claim or runtime was imported. UAF still has no arbitrary shell tool. |
| [AutoGen](https://github.com/microsoft/autogen) — `004749e6b7102c8fd317b9b1499ce5807223c278` | Metadata/README screened only. A second orchestration framework would overlap UAF's durable manager/supervisor/worker/reviewer contracts; GitHub's license metadata alone is not enough for selective file reuse. Not integrated. |
| [CrewAI](https://github.com/crewAIInc/crewAI) — `38db11e3324fa0e23beb5eecd0d87e8e31ca2bb0` | MIT metadata/README screened only. Role-playing crews do not replace UAF's typed task state, policy, checkpoint, approval, and recovery boundaries. Not integrated. |

## Follow-up screening: lightweight setup and honest readiness

| Project and revision | Evidence inspected | Decision |
|---|---|---|
| [keyring](https://github.com/jaraco/keyring) — `566a2c61c8d13961185333370d7ee3a13494246f` | `pyproject.toml` declares MIT and Windows-only `pywin32-ctypes`; `keyring/backends/Windows.py` inspected for the real Credential Manager backend | **Retain the existing reviewed dependency, not a custom secret store.** The default launcher now installs only UAF's `setup` extra instead of Playwright/PyAutoGUI/Chromium. No keyring source was copied. |
| [uv](https://github.com/astral-sh/uv) — `6fe4f0f5cfa8322e97af4479cbfb3d53a3ce9596` | Apache-2.0 metadata and README sections for standalone installers, Windows, tools, and Python-version management | **Useful installation precedent, no binary/runtime integration.** Adding a second native package manager and another update channel would enlarge the trust/resource surface. The launcher keeps bounded `pip` commands in a repository-local venv. |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) — `b206650681ecc827b6870c29d3196dfd1a1d0a08` | Repository metadata and `COPYING.txt`, including GPLv2-or-later terms and the bootloader exception | **No executable bundle in this round.** A native Windows bundle needs Windows build/acceptance, dependency/license review, and a larger artifact; it is not required for the reviewed source ZIP launcher. No claim of a prebuilt offline executable is made. |

The corresponding independent quality review did not import an orchestration framework. UAF's new acceptance gate checks durable upstream evidence directly, and its default startup path removes optional downloads rather than hiding their failures.

## Implemented from this research round

### 1. Governed real task experience

- `src/uaf/experience.py` captures only real terminal `succeeded`/`failed` task outcomes.
- Migration 4 adds a content-free capture ledger. Replaying a task cannot duplicate experience or resurrect a privacy-deleted record.
- Credential-like goals/content are skipped; model output is never captured. Records start **pending**.
- Only human-approved, non-private UAF task outcomes are recalled, bounded and wrapped as untrusted historical data. Agents cannot approve their own experience.
- Dashboard review is loopback-only, explicitly confirmed, idempotent, and unavailable to voice commands. Non-loopback responses omit experience content.
- `company-startup@2` explicitly disables memory recall so its privacy-safe startup prompt remains free of memory, workspace names, and workspace contents.
- Evidence: `tests/test_experience.py`, dashboard HTTP tests, migration/privacy/replay tests.

### 2. Real Python repository map

- `src/uaf/repository.py` parses bounded UTF-8 Python files with `ast`; it never imports or executes them.
- Output contains hashes, imports, top-level classes/functions, methods, line numbers, and syntax-error evidence—not source/docstring dumps.
- File count, source bytes, skipped directories, symlinks/reparse escapes, errors, and output size are bounded. Truncation is explicit.
- `workspace.python_map` is a governed R0 tool with task allowlists, schemas, invocation evidence, and SQLite audit records.
- Evidence: `tests/test_repository.py`, including a top-level `raise` proving that successful mapping does not execute source.

### 3. Evidence-first dashboard

- Default department view hides unused capabilities and shows only actual execution evidence. The complete capability map remains opt-in.
- Run activity comes from durable factory steps with real task IDs/states/error codes.
- No fake progress, autonomous staff claims, remote memory approval, or additional runtime dependency was added.

### 4. Lightweight one-click startup

- Default `Start-UAF.cmd` bootstraps only the dashboard and approved OS-vault dependency; Chromium, Playwright, and PyAutoGUI require an explicit `--with-computer-use` flag.
- Port `0` lets the OS select an available loopback port, avoiding a fixed-port conflict while retaining the exact per-launch private URL.
- Required init/doctor gates still fail closed. Optional full computer-use installation does not change voice, provider, approval, or readiness authority.

### 5. Real startup quality acceptance

- `factory.accept_startup` is an eleventh governed R0 tool, not a generic smoke success or another model persona.
- It checks upstream succeeded states, inventory shape, at most 200 entries, a non-empty bounded brief, and the actual independent reviewer verdict. Output contains counts/checks/hash evidence, not copied filenames or a semantic-quality guarantee.
- `company-startup@2` uses this tool through the ordinary schema/policy/checkpoint path. A blank brief fails startup even if a test reviewer claims `pass`.
- Version 2 and a new dashboard idempotency key preserve existing version-1 registrations and run history instead of causing an immutable-checksum upgrade failure.
- Evidence: `tests/test_acceptance.py`, dashboard startup tests, and clean-wheel company DAG checks.

## Deliberately not implemented

Semantic/vector memory, JS/TS symbol parsing, autonomous code execution/test runners, remote mobile approval, cloud VMs, screen streaming, repository watchers, git hooks, arbitrary shell, and sandboxed execution are **not** implied by this round. Each needs its own threat model, resource budget, acceptance tests, and where applicable human approval. UAF does not call a worktree, AST parser, browser profile, or desktop adapter an OS sandbox.
