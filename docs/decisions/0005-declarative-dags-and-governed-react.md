# ADR 0005: Declarative durable DAGs and governed ReAct

- Status: accepted
- Date: 2026-10-24

## Context

The alpha runner could execute one smoke, model, or deterministic tool task, but custom teams were only logical role profiles. Research into Microsoft Agent Framework workflows, OpenHands' typed action/event architecture, OpenJarvis' composable agents, and OpenAI Agents SDK loops/guardrails supports explicit graphs and bounded action/observation cycles. Copying those frameworks would add substantial dependencies and would not automatically preserve UAF's no-spend, SQLite, approval, and recovery constraints.

## Decision

Implement the graph and tool loop inside UAF's deterministic control plane:

1. Immutable versioned JSON blueprints define bounded agents and DAG steps. Custom blueprints are disabled until reviewed and enabled.
2. The factory creates the complete task/dependency graph atomically and executes it serially through the existing `TaskRunner`.
3. Upstream-only declarative templates pass validated inputs and outputs. Ready steps are atomically materialized and digest-bound before execution.
4. A ReAct worker may return only a typed final/tool decision. The runner alone executes a registered tool; decision and observation checkpoints are separate.
5. Existing policy, approval, idempotency, workspace, output, reviewer, and budget enforcement remains authoritative. Models cannot add nodes or permissions.
6. Factory recovery is explicit and preserves task identity/checkpoints. Pending approval, quota wait, interruption, failure, and uncertain effects remain distinct states.

## Consequences

Positive: useful custom teams and tool-using agents become possible without framework lock-in; offline deterministic DAGs remain real and testable; approval resume reuses the same model decision; every run has inspectable per-step evidence.

Costs/limits: the current graph has at most eight agents and twelve steps, no parallel scheduler, no dynamic model-generated graph, and no nested subfactory. Materialization adds a second durable representation that must remain digest-consistent. ReAct requires an eligible model and is not available as fake offline AI. Host-local profiles are not process or OS isolation.

Alternatives rejected: adopting a large graph framework as a mandatory core dependency; allowing arbitrary Python/expression templates; treating a model's tool request as authorization; claiming that snapshots alone provide exactly-once effects.
