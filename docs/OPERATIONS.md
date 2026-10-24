# CLI and operations runbook

All commands support `--json` (before or after the subcommand). `--home PATH` selects an isolated UAF home. Expected failures return exit code 2 with a stable error code; unexpected failures return 1 and write a redacted local log. `uaf doctor` emits its report and returns 2 when any required check fails, allowing launch scripts to stop reliably. Ctrl-C returns 130 and preserves committed checkpoints.

## Initialize and inspect

```bash
uaf --home ./uaf-home init --workspace ./workspace
uaf doctor --json
uaf status --json
uaf capabilities --json
uaf agents --json
uaf tool list --json
uaf config show --json
```

Safe config writes include `workspace`, `network_allowed`, `mcp_enabled`, `telemetry_enabled`, `browser_enabled`, `browser_allowed_domains`, `desktop_enabled`, `desktop_allowed_applications`, `desktop_max_actions_per_batch`, and `budgets.<name>`. `allow_paid` is never writable. Changing a budget/action ceiling cannot exceed code-level limits.

## Tasks and recovery

```bash
uaf task add "Goal" --kind agent --constraint "Cite actual evidence" --json
uaf task add "Offline check" --kind smoke --json
uaf task add "Read a file" --kind tool --tool workspace.read \
  --arguments '{"path":"notes/a.txt"}' --json
uaf task add "Map Python code" --kind tool --tool workspace.python_map \
  --arguments '{"path":".","limit":40}' --json
uaf task list --state queued --json
uaf task run <task-id> --json
uaf task run --all --limit 20 --json
uaf task show <task-id> --json
uaf task timeline <task-id> --json
uaf task cancel <task-id> --json
uaf task resume <task-id> --json
```

Dependencies can be supplied with repeated `--depends-on`. `--idempotency-key` deduplicates compatible submissions; conflicting reuse is rejected. `--schema` accepts a bounded JSON-schema subset for structured worker output.

Recovery procedure:

1. `uaf doctor --json` and `uaf status --json`.
2. Inspect `uaf task timeline <task-id> --json`.
3. For `paused_offline`, restore network/provider/workspace prerequisites.
4. For `awaiting_approval`, review and decide the exact approval first.
5. For `uncertain_side_effect`, inspect the destination and `uaf effect list <task-id> --json`; do not rerun blindly. Reconcile every effect with bounded human evidence before resume.
6. For interrupted `planning/running/verifying` after process restart, explicitly `task resume` before `task run`.
7. Resume only after understanding the last committed checkpoint.

There is no automatic arbitrary side-effect reconciler for unknown destinations. `effect reconcile` records the operator's destination-specific observation; it does not discover the outcome itself.

## Blueprints and factory recovery

```bash
uaf blueprint list --json
uaf blueprint register ./reviewed-blueprint.json --json
uaf blueprint enable name@version --json
uaf factory start name@version "Goal" --input '{"key":"value"}' --json
uaf factory show <factory-run-id> --json
uaf factory list --json
uaf factory resume <factory-run-id> --actor local-human --json
uaf factory cancel <factory-run-id> --actor local-human --json
```

For `awaiting_approval`, inspect the run's step task and decide its exact pending approval before factory resume. For `retry_wait`, wait for the task's persisted retry time; do not clear a provider cooldown to force execution. For `paused_offline`, restore prerequisites. For `interrupted`, inspect step checkpoints and explicitly resume. For `uncertain_side_effect`, reconcile the underlying destination first. A failed dependency intentionally leaves downstream tasks unexecuted.

## Evaluation operations

```bash
uaf eval run --json
uaf eval run --suite ./reviewed-suite.json --candidate local-change --json
uaf eval show <evaluation-run-id> --json
uaf eval compare <candidate-run-id> <baseline-run-id> --json
```

Use a disposable workspace for suites with tool fixtures/effects. Evaluation never auto-approves high-risk actions or enables models/network. Compare only identical suite digests; the CLI enforces this for `--baseline` and explicit comparison.

## Approvals

```bash
uaf approval list --state pending --json
uaf approval approve <approval-id> --actor local-human --reason "Reviewed exact path" --json
uaf approval reject <approval-id> --actor local-human --reason "Not authorized" --json
uaf task resume <task-id> --json
uaf task run <task-id> --json
```

Review action, canonical payload, destination, risk, and requesting task. Approval is not a blanket tool permission.

## Company dashboard and voice

```bash
uaf dashboard
uaf dashboard --no-open --port 8766
# Explicit non-loopback preview only; credential writes remain disabled:
uaf dashboard --host 0.0.0.0 --allowed-host dashboard.example --no-open
```

Open the exact printed URL including its per-launch `#token` fragment. The loopback page combines official discovery, reviewed-model selection, free-tier confirmation, OS-vault setup, one live diagnostic, and the fixed idempotent three-step company-startup DAG (local inventory, privacy-safe worker/reviewer brief, deterministic acceptance). `status`, `start factory`, and `confirm start factory` are available through text and supported browser speech recognition. Voice cannot submit credentials or approve R2/R3 work.

Use `uaf doctor --json`, `uaf provider list --json`, and `uaf factory list --json` for CLI cross-checks. If setup reaches a live-provider failure, configuration may be saved while readiness remains false; do not interpret it as a successful factory start. Refresh before explicit retry. Non-loopback Host exposure is not production remote authentication and is not the recommended credential-setup path. See [Dashboard](DASHBOARD.md).

## One-key onboarding and computer use

```bash
uaf setup
uaf auth status --json
uaf auth delete gemini --yes --json

uaf config set browser_enabled true
uaf config set browser_allowed_domains '["example.com"]'
uaf browser login https://example.com --wait-seconds 10 --json
uaf browser inspect https://example.com --wait-seconds 1 --json

uaf config set desktop_enabled true
uaf config set desktop_allowed_applications '["notepad.exe"]'
uaf desktop run reviewed-batch.json --json
```

Browser/desktop execution also requires their optional extras and explicit configuration. Browser navigation requires `network_allowed=true`; local desktop input does not. The browser profile is dedicated and sensitive. Desktop execution is Windows-only and requires a visible interactive session.

For uncertain effects:

```bash
uaf effect list <task-id> --json
uaf effect reconcile <task-id> <exact-key> --observed not-executed \
  --evidence '{"note":"Human verified no effect"}' --actor local-human --yes --json
# Or use --observed executed with --result containing output/evidence objects.
uaf task resume <task-id> --json
uaf task run <task-id> --json
```

If a partial effect makes neither observation true, leave the task uncertain and remediate manually first. See [Computer Use](COMPUTER_USE.md) for exact action schemas, chat rules, and executed-result examples.

## Memory

```bash
uaf memory add "Prefer concise release notes" --type preference \
  --source local-user --sensitivity internal --json
uaf memory approve <memory-id> --json
uaf memory search "release notes" --json
uaf memory show <memory-id> --json
uaf memory correct <memory-id> "Use concise, evidence-linked notes" --reason "new preference" --json
uaf memory revisions <memory-id> --json
uaf memory consolidate --json
uaf memory consolidate --apply <job-id> --json
uaf memory export ./memory-export.json --json
uaf memory delete <memory-id> --yes --json
```

New memory is pending unless `--approved` is explicitly supplied. Search defaults to approved entries. Consolidation is dry-run first and creates a snapshot before apply. Export files and backups may contain sensitive data.

Terminal tasks also create pending `task` experience without model output. Review it with `memory list --type task` and explicitly `memory approve` before it can be recalled. Only approved non-private outcomes are used, as untrusted context. Sensitive-looking outcomes are skipped; replay does not duplicate or resurrect deleted experience.

## Backups and restore

```bash
uaf backup create --purpose before-maintenance --json
uaf backup list --json
uaf backup verify <snapshot-id> --json
uaf backup restore <snapshot-id> --yes --json
```

Restore verifies the source, creates a pre-restore lifeline, restores through SQLite's backup API, and checks integrity/foreign keys. Keep an independent offline copy for loss of the whole UAF home; an in-home snapshot does not protect against disk loss.

## Skills and plugins

```bash
uaf skill list --json
uaf skill show verified-research --json
uaf plugin discover --json
uaf plugin register examples/plugins/note-writer/plugin.json --json
uaf plugin list --json
uaf plugin enable note-writer --json
uaf plugin run note-writer --input '{"name":"demo","content":"Text"}' --json
uaf plugin disable note-writer --json
```

The enable command itself is the operator's explicit enablement action. Manifest tampering disables use until the plugin is reviewed/registered again. Entry-point discovery is metadata-only and never imports third-party Python.

## Research

```bash
uaf config set network_allowed true
uaf research fetch https://example.com --json
uaf research list --json
uaf research show <source-id> --json
```

Only bounded HTTPS text-like resources on port 443 are supported. The returned `model_context` is untrusted data, not a system instruction. This research fetcher has no crawler, browser rendering, authenticated fetch, PDF parser, or source publishing. The separate optional browser adapter has its own dedicated-profile and approval controls.

## Optional MCP

```bash
python -m pip install -e '.[mcp]'
uaf config set mcp_enabled true
uaf mcp serve
```

This is a stdio server intended to be launched by a local MCP client. It has no HTTP listener. Stop it with the client/process lifecycle. Its tools can list/add tasks and search bounded approved non-private memory; they cannot run arbitrary tools, approve actions, or promote updates.

## Self-update

```bash
uaf self-update check --repo . --json
uaf self-update plan --repo . --patch ./reviewed.patch --json
# Only in a disposable host/sandbox after explicit code review:
uaf self-update plan --repo . --patch ./reviewed.patch \
  --run-tests --allow-untrusted-code --json
```

`check` performs commit comparison against a trusted HTTPS GitHub origin; it is not signature verification. `plan` creates a lifeline and detached worktree, rejects protected paths, and records gates. This version does not merge, push, deploy, or automatically roll out a candidate.

## Benchmark

```bash
uaf benchmark --iterations 5 --json
```

The benchmark executes real queued durable offline tasks and measures throughput/latency/RSS on the current host. It does not call a model and does not measure reasoning quality. Compare results only with the same command, workload, machine, and configuration.
