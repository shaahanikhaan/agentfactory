# Declarative agent blueprints, durable DAGs, and governed ReAct

These features compose the existing task/policy kernel; they do not create a second executor or a larger system prompt.

## Quick start: real offline DAG

The built-in `offline-workspace-inventory@1` blueprint runs a bounded `workspace.list` task and then a deterministic durability-record task. It requires an explicit path and limit, uses no network, and makes no AI claim.

```bash
uaf factory start offline-workspace-inventory@1 "Inventory demo" \
  --input '{"path":".","limit":100}' --idempotency-key demo-inventory --json
uaf factory show <factory-run-id> --json
```

Expected evidence for a successful run is two tasks, eight role checkpoints, one governed tool call, zero model calls, and the inventory as the selected output. Repeating the same start with the same idempotency key and payload returns the existing run. Changing the payload under that key is a conflict.

## Blueprint lifecycle

```bash
uaf blueprint list --json
uaf blueprint show offline-workspace-inventory@1 --json
uaf blueprint register examples/blueprints/evidence-team.json --json
uaf blueprint enable evidence-team@1 --json
uaf factory start evidence-team@1 "Analyze a local file" \
  --input '{"path":"notes/hello.txt"}' --json
```

Custom blueprints are **disabled after registration**. Registration validates the specification but does not execute it. Enable only after reviewing its instructions, dependencies, tools, and budgets. Cloud/ReAct blueprints additionally pause offline unless an eligible free/local provider is explicitly configured.

A `name@version` is immutable. Registering different content under the same ID fails; create a new version. Disabling a blueprint prevents new starts but does not rewrite historical runs.

## Specification contract

A blueprint contains:

| Field | Meaning |
|---|---|
| `name`, `version`, `description` | Stable immutable identity and human-readable scope |
| `input_schema` | Bounded JSON-schema subset applied to factory inputs |
| `defaults` | Shared constraints, department, priority, and budget |
| `agents` | One to eight logical profiles: `agent`, `react`, `smoke`, or `tool` |
| `steps` | One to twelve typed tasks with explicit `depends_on` edges |
| `output.from` | Which successful step supplies the factory's selected output |

Each agent has an `agent_id`, execution `kind`, optional bounded instructions/constraints/budget, and an explicit `allowed_tools` list. Plain `agent` and `smoke` profiles cannot declare tool authority. A `tool` profile must declare its tools, and every deterministic tool step must select one **static** allowed `input.tool`.

Limits are enforced in code: at most eight agents, twelve steps, sixteen allowed tools per agent, 64 KB canonical specifications, 8,000 characters of instructions per agent, and global task/model/tool/output/attempt ceilings. Cycles, duplicate IDs, unknown fields/tools, malformed templates, hidden data dependencies, and secret-like persisted definitions are rejected.

## Safe data-flow templates

Templates are data substitution, not a programming language. There are no functions, loops, imports, filters, or expression evaluation.

```json
{
  "step_id": "analyze",
  "agent_id": "analyst",
  "goal": "Analyze the upstream result",
  "depends_on": ["read"],
  "input": {
    "context": {
      "evidence": "{{ steps.read.output }}"
    }
  }
}
```

Available roots are:

- `{{ goal }}`: the factory goal.
- `{{ inputs.some.path }}`: validated run input.
- `{{ steps.step-id.output }}`: upstream selected task output.
- `{{ steps.step-id.result }}`: complete upstream task result.
- `{{ steps.step-id.state }}`: upstream terminal state (`succeeded` when a dependent runs).

Nested paths such as `{{ steps.write.output.path }}` are supported. A full-string template preserves the referenced JSON type; interpolation inside a larger string serializes non-string values as canonical JSON. A step may reference only its declared transitive upstream dependencies. Missing values, cycles, and side references fail before execution of that step.

All tasks and dependency mappings are created in one SQLite transaction. Because downstream values do not exist yet, tasks initially retain durable templates. Immediately before a ready step runs, UAF renders its goal/input and atomically stores the materialized payload plus a digest. Resume verifies that digest rather than silently replacing a payload with different evidence.

## Factory states and recovery

Factory runs report `queued`, `running`, `awaiting_approval`, `retry_wait`, `paused_offline`, `interrupted`, `failed`, `succeeded`, `cancelled`, or `uncertain_side_effect`. The state is derived from actual task evidence; `retry_wait` is not mislabeled as offline, and an interrupted process is not called a successful checkpoint recovery.

```bash
# High-risk tool action: inspect and decide the underlying task approval first.
uaf factory show <run-id> --json
uaf approval list --state pending --json
uaf approval approve <approval-id> --actor local-human --json
uaf factory resume <run-id> --actor local-human --json

# Explicit recovery after offline pause or process interruption.
uaf factory resume <run-id> --actor local-human --json

# Cancellation is explicit and does not reconcile uncertain external effects.
uaf factory cancel <run-id> --actor local-human --json
```

Resume preserves task IDs and completed checkpoints. It does not bypass pending approvals, uncertain side-effect reconciliation, attempt budgets, or provider `retry_wait`. A failed dependency prevents dependent materialization/execution. The current scheduler is deliberately serial and fail-fast; independent branches are not claimed to run concurrently.

## Governed ReAct tasks

`react` is a bounded action → observation protocol for an eligible model:

1. A worker checkpoint returns exactly one JSON decision: `{"action":"final","answer":...}` or `{"action":"tool","tool":"...","arguments":{...}}`.
2. The runner—not the model—checks the decision and tool catalog.
3. A requested tool passes the existing schema, task allowlist, role, risk, approval, idempotency, workspace, and output controls.
4. A separate observation checkpoint stores the governed result as untrusted evidence.
5. A final answer receives the normal reviewer gate.

Decision and observation have different deterministic checkpoint IDs. If an R2/R3 tool pauses for approval, resume reuses the already committed model decision instead of generating a potentially different tool/payload request.

The loop uses at most three decision turns and reserves one model call for review. It also respects narrower task model/tool/step/wall/output budgets. Exhaustion, malformed JSON, unknown/disallowed tools, schema violations, and reviewer rejection fail closed. Tool output cannot inject chat role markers or grant permissions.

Run directly through the CLI:

```bash
uaf task add "Read notes/hello.txt and report its content" --kind react \
  --allowed-tool workspace.read --json
uaf task run <task-id> --json
```

This still requires a configured eligible model; offline mode never fabricates a ReAct answer.

## Security and scope boundaries

- Blueprint instructions are wrapped as bounded role guidance; they cannot change the system protocol or grant authority.
- Upstream context and tool observations are labelled untrusted data.
- Model output cannot add DAG nodes, change an immutable blueprint, select an arbitrary tool, or expand a task allowlist.
- R2/R3 approval remains payload- and destination-bound. Arbitrary external effects are not exactly-once.
- These are host-local logical agents, not separate processes or an OS sandbox. Third-party Python remains disabled/unimplemented.
- No visual Agent Town, voice, autonomous learning, or unbenchmarked superiority is implied. Browser/desktop adapters are separate optional governed tools; registering a factory blueprint does not enable them or bypass their approvals.
