# Ultimate Agent Factory (UAF)

**A local-first, durable, policy-enforced agent runtime — not a larger system prompt.**

UAF turns goals into persisted task contracts, immutable agent-team DAGs, bounded ReAct tool loops, governed effects, review evidence, and resumable SQLite timelines. Reproducible evaluation compares real behavior against fixed baselines. The core uses only the Python standard library. It works offline without API keys, never pretends that deterministic work was cloud AI, and has no paid fallback. Optional slices add one-Gemini-key OS-vault onboarding, a loopback company dashboard with voice/text commands, a dedicated visible browser, and approval-gated Windows mouse/keyboard batches.

> **Status: 0.1.0 alpha.** The CLI and loopback dashboard are supported interfaces. Linux execution evidence is recorded in [Verification](docs/VERIFICATION.md); user-reported Windows onboarding is partial evidence, not completed Windows/dashboard/microphone acceptance. See the truthful [capability matrix](docs/CAPABILITIES.md) before relying on a feature.

## Why this architecture

| Instead of… | UAF implements… |
|---|---|
| One long prompt claiming many agents | Immutable declarative teams plus typed Manager → Supervisor → Worker → Reviewer checkpoints |
| In-memory conversation state | Versioned SQLite schema, durable DAGs, WAL, legal transitions, checkpoints, and explicit recovery |
| “The model decided to use a tool” | Typed ReAct decisions plus task allowlists, schemas, risk policy, and payload-bound human approval |
| A throughput number called “improvement” | Labelled task suites, deterministic scorers, resource evidence, and same-suite regression gates |
| Retrying an external request until it looks successful | Payload-bound idempotency records, replay protection, and `uncertain_side_effect` reconciliation |
| Unverified “free AI” | Disabled providers by default, dated official-source evidence, OS vault/environment credentials, quotas, cooldowns, and `Retry-After` handling |
| Memory as an opaque vector dump | Provenance, sensitivity, approval, revision history, FTS5/LIKE search, export, privacy deletion, and reviewed consolidation |
| Plugin hot reload as a security boundary | Checksummed declarative workflows, disabled by default; no automatic third-party imports |
| Automatic self-modification | Read-only update checks, isolated worktree candidates, mandatory gates, human promotion, and incumbent snapshots |

The “factory” is a reusable execution and governance kernel. It does **not** claim AGI, human-level autonomy, exactly-once arbitrary external effects, or feature parity with every referenced project.

## Quick start

Requires **Python 3.11+**. No Docker, database server, Redis, vector database, GPU, or paid account is required.

### Windows one-click company dashboard

From a reviewed source checkout/ZIP, double-click **`Start-UAF.cmd`**. The launcher prepares a local `.venv`, optional computer-use dependencies/Chromium, and real `init`/`doctor` checks before opening the private loopback dashboard. First-run dependency downloads require internet; no admin shell or global package installation is used.

In the local page, paste one Gemini API key and explicitly confirm the linked current free-tier terms. UAF then performs official discovery, reviewed-model selection, OS-vault storage, one bounded live readiness request, and an idempotent three-step company startup DAG with one orchestration worker and one reviewer call. Voice is optional push-to-talk with text fallback; it never accepts/echoes credential-like commands or approves R2/R3 actions—still never speak a key into a microphone. See [Dashboard and voice](docs/DASHBOARD.md) for security, audio-processing disclosure, commands, and recovery.

### Windows PowerShell (manual alternative)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\uaf.exe init
.\.venv\Scripts\uaf.exe doctor --json
```

### Linux / macOS

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools
.venv/bin/python -m pip install -e .
.venv/bin/uaf init
.venv/bin/uaf doctor --json
```

By default, state lives in the platform data directory. For a portable demo, choose a directory yourself:

```bash
uaf --home ./uaf-home init --workspace ./demo-workspace
```

Keep the database/config home on stable local storage. A workspace on removable storage is supported, but writes fail closed when that workspace is disconnected.

For complete first-time laptop installation, optional extras, Gemini onboarding, and real Windows acceptance steps, follow [Windows installation](docs/WINDOWS.md) or the [Roman Urdu laptop guide](docs/INSTALL_ROMAN_URDU.md). For browser/desktop actions and recovery, follow [Computer use](docs/COMPUTER_USE.md).

## Open the company dashboard

```bash
uaf dashboard
# or: uaf dashboard --no-open --port 8766
```

The dashboard shows real doctor/provider/factory evidence, supports one-key setup and explicit start/retry, and uses a random per-launch capability with strict Host/Origin checks. Credential writes require literal loopback. Startup executes reliability inventory, an orchestration worker/reviewer brief with no workspace filenames or contents, and a quality acceptance record. Department cards default to actual execution evidence; an opt-in toggle reveals other governed capabilities without presenting them as active staff. The separate live diagnostic and two startup model calls are honestly labelled and bounded.

## Run real offline work

```bash
TASK_ID=$(uaf task add "Verify the durable offline path" --kind smoke --json | python -c 'import json,sys; print(json.load(sys.stdin)["task_id"])')
uaf task run "$TASK_ID" --json
uaf task timeline "$TASK_ID" --json
uaf status --json
uaf benchmark --iterations 5 --json
```

The smoke task executes and reviews a deterministic contract, writes four role checkpoints, and makes **zero model calls**. Its output is deliberately labelled `offline_deterministic` and `ai_generated: false`.

PowerShell users can capture the ID without `jq`:

```powershell
$task = uaf task add "Verify the durable offline path" --kind smoke --json | ConvertFrom-Json
uaf task run $task.task_id --json
uaf task timeline $task.task_id --json
```

## Compose a durable agent factory

Run the built-in two-step offline DAG (one workspace inventory, one deterministic record):

```bash
uaf factory start offline-workspace-inventory@1 "Inventory demo" \
  --input '{"path":".","limit":100}' --idempotency-key demo-inventory --json
uaf factory show <factory-run-id> --json
```

Custom JSON blueprints support up to eight bounded agent profiles and twelve dependency steps, with validated upstream data-flow templates. Registration is disabled-by-default; review and enable before starting:

```bash
uaf blueprint register examples/blueprints/evidence-team.json --json
uaf blueprint enable evidence-team@1 --json
# This optional ReAct -> analyst team requires a configured eligible free/local model.
uaf factory start evidence-team@1 "Analyze a note" --input '{"path":"notes/hello.txt"}' --json
```

See [Factory blueprints, recovery, and ReAct](docs/FACTORY.md) for the schema, template, approval, and interruption contract.

## Measure behavior and regressions

```bash
uaf eval run --json
uaf eval show <evaluation-run-id> --json
uaf eval run --baseline <baseline-run-id> --candidate local-change --json
```

The built-in eight-case suite performs real offline control-plane/safety checks with zero model calls. It distinguishes expected safe failures from raw task success and records per-case evidence, durations, model/tool calls, and checkpoints. Baseline comparison requires the identical suite digest. Custom `agent`/`react` suites are optional and use the same provider/no-spend gates. See [Evaluation](docs/EVALUATION.md).

## Governed filesystem example

```bash
uaf task add "Write a note" --kind tool --tool workspace.write \
  --arguments '{"path":"notes/hello.txt","content":"Hello from UAF"}' --json
uaf task run <task-id> --json

uaf task add "Read the note" --kind tool --tool workspace.read \
  --arguments '{"path":"notes/hello.txt"}' --json
uaf task run <task-id> --json
```

`workspace.delete` is R3: the first run pauses for approval, `uaf approval list` shows the exact destination and payload digest, and only the matching approval permits resume. A pre-action backup is retained for reversible recovery.

## Real repository evidence and governed experience

```bash
uaf task add "Map the Python repository" --kind tool --tool workspace.python_map \
  --arguments '{"path":".","limit":40}' --json
uaf task run <task-id> --json
uaf memory list --type task --json
uaf memory approve <experience-memory-id> --json
```

`workspace.python_map` uses the Python standard-library AST to return bounded imports, classes, functions, hashes, and syntax-error evidence. It never executes source code and is not a JavaScript/parser or sandbox claim. Succeeded/failed tasks also create idempotent local experience records without model output. They remain pending until human approval; only approved non-private records enter future worker/ReAct context as untrusted historical evidence. Privacy deletion is not undone by task replay. The dashboard exposes the same review flow on loopback and hides unused department capabilities by default.

## One Gemini key and governed computer use

Install the optional slices and run the guided wizard:

```powershell
# Windows PowerShell; $python/$uaf point into the virtual environment.
& $python -m pip install -e '.[computer-use]'
& $python -m playwright install chromium
& $uaf setup
& $uaf auth status --json
& $uaf provider test gemini --json
```

The wizard uses official model discovery, a hidden key prompt, an approved OS credential vault, and explicit current free-tier/network confirmations. One Gemini key is sufficient for built-in Gemini cloud roles; no other AI-provider setup is required. `provider test --live` is a separate explicit generation request. The dashboard combines those steps after its own explicit free-tier/start confirmation and requires live readiness before reporting factory readiness.

Browser/desktop features are disabled until explicitly configured. The browser uses a visible dedicated UAF profile, exact domain allowlists, bounded redacted snapshots, and digest-bound R2/R3 actions. Desktop batches are Windows-only, exact-window/focus bound, ASCII-limited, fail-safe enabled, and R3 approved. Neither is an OS sandbox. Dashboard voice is optional browser push-to-talk with on-device preference and explicit vendor-processing consent; direct chat API connectors, native desktop voice/vision, and Unicode desktop input are not claimed.

See the [complete computer-use guide](docs/COMPUTER_USE.md) for manual login, chat-on-behalf rules, exact action payloads, approval resume, and uncertain-effect reconciliation.

## Optional free/local models

Cloud providers start with **no configured models**. UAF does not assume that a named model is currently free. A cloud call requires explicit model configuration, current official free evidence, a credential in the OS vault or environment, explicit network enablement, and all capability/resource budgets.

The recommended Gemini path is `uaf setup`. Advanced manual configuration remains available:

```bash
# Example shape only: replace the model/evidence with currently verified information.
export GEMINI_API_KEY='your-key'
uaf provider configure gemini <currently-verified-model> \
  --confirm-free --source https://ai.google.dev/gemini-api/docs/rate-limits \
  --verified-at 2026-10-24
uaf config set network_allowed true
uaf provider test gemini --live --json
```

OpenRouter is further restricted to explicit `:free` model IDs. Ollama is loopback-only and requires `--confirm-local-resources`. Free eligibility, quotas, and terms can change; UAF can fail closed on stale/missing evidence but cannot guarantee a provider will remain free. See [Providers](docs/PROVIDERS.md).

## Extensions, research, and MCP

```bash
uaf skill list --json
uaf plugin discover --json
uaf plugin register examples/plugins/note-writer/plugin.json --json
uaf plugin enable note-writer --json
uaf plugin run note-writer --input '{"name":"demo","content":"Governed note"}' --json

# Explicit network must be enabled first. Fetched text remains untrusted data.
uaf research fetch https://example.com --json

# Optional protocol support; not a mandatory core dependency.
python -m pip install -e '.[mcp]'
uaf config set mcp_enabled true
uaf mcp serve
```

The MCP server exposes only narrow task/memory operations over stdio. There is no MCP HTTP listener. Third-party Python entry points are reported as metadata, never imported during discovery.

## Verification

```bash
python -m pip install -e '.[dev]'
python scripts/verify.py
# Or run individual gates:
python -m pytest -q
python -m ruff check src tests scripts
python -m pip_audit --progress-spinner off
```

Current checkout evidence: **177 tests and 57 subtests passed** with optional MCP and computer-use Python packages installed, including real loopback dashboard HTTP tests, a real MCP stdio initialize/discover/call/shutdown scenario, and fake-driver browser/desktop/vault/provider coverage. Compile and Ruff are clean, and the audited environment reported no known vulnerabilities. A clean no-dependency wheel passed three packaged dashboard assets, two blueprints, ten-tool registration, the two-step offline DAG, three-step company DAG with memory/privacy exclusion, real AST mapping, governed experience, and eight-case evaluation/baseline acceptance. These are reproducible checks, not a proof against unknown vulnerabilities. The automated Linux gates made no real cloud request, browser account/microphone session, OS-vault secret write, physical desktop input, or external message; core-only environments explicitly skip the MCP protocol integration test. User-reported Windows onboarding and failed live Gemini attempts are recorded separately in [Verification](docs/VERIFICATION.md), not presented as successful live/Windows acceptance.

## Documentation

- [Architecture and durable execution](docs/ARCHITECTURE.md)
- [Agent blueprints, durable DAGs, and governed ReAct](docs/FACTORY.md)
- [Reproducible evaluation and regression gates](docs/EVALUATION.md)
- [CLI and operations runbook](docs/OPERATIONS.md)
- [Company dashboard, one-key setup, and voice](docs/DASHBOARD.md)
- [Security and threat model](docs/SECURITY.md)
- [Provider setup and quota policy](docs/PROVIDERS.md)
- [Capability matrix](docs/CAPABILITIES.md)
- [Verification evidence](docs/VERIFICATION.md)
- [One-key onboarding and governed computer use](docs/COMPUTER_USE.md)
- [Complete Windows installation and removable-storage notes](docs/WINDOWS.md)
- [Research register and project comparisons](docs/RESEARCH.md)
- [External repository evidence and integration decisions](docs/EXTERNAL_RESEARCH.md)
- [Release checklist](docs/RELEASE_CHECKLIST.md)
- [Security disclosure policy](SECURITY.md)

## Important limits

- Roles are logical execution stages. Reviewer independence is a separate prompt/step, not a guarantee of a different model or formal verification.
- The offline smoke path and built-in inventory DAG are deterministic systems work, not an offline LLM.
- Factory execution is currently serial and bounded to twelve steps; it does not generate dynamic graphs or claim parallel/agent-town visualization.
- The packaged evaluation held-out split is public and the default suite measures control-plane behavior, not general model intelligence.
- Research fetch is a prototype. DNS rebinding and hostile content remain residual risks; do not point it at sensitive network environments without an egress-controlled resolver/proxy.
- Candidate self-update tests execute code on the host only after an explicit untrusted-code flag. A Git worktree is not an OS sandbox. Automatic merge, push, deployment, and permission expansion are not implemented.
- No arbitrary shell tool is registered. Optional browser/desktop adapters are bounded and approval-gated, but host GUI control is not sandboxed or risk-free. Direct chat connectors, automatic account/terms acceptance, native desktop voice/vision, Unicode desktop input, and unattended publishing/deployment are not included. Dashboard voice is optional and browser-dependent; external browser/native-app actions require explicit approval and have no delivery guarantee.
- A benchmark measures the stated local scenario on the stated machine; it is not a universal “1000×” claim.

## License

MIT for this repository's original code and first-party examples. See [LICENSE](LICENSE). Research references and optional dependencies remain under their own licenses; no unlicensed Stonic AI code or assets are vendored. The optional desktop dependency tree currently includes GPLv3+ `mouseinfo`, so review all installed licenses/NOTICEs before accepting it or creating a bundled distribution. Core installation does not install that package.
