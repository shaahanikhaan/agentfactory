# Reproducible evaluation and regression gates

UAF evaluation executes real task contracts through the same runner, tools, checkpoints, and policy used by the CLI. It does not assign a score by asking the same model whether it did well.

## Built-in offline suite

```bash
uaf eval run --json
uaf eval list --json
uaf eval show <evaluation-run-id> --json
```

The packaged `uaf-core-offline` v1 suite has eight cases: four development and four held-out. It covers deterministic output, checkpoint replay, workspace write/list evidence, schema rejection, missing files, traversal denial, and R3 approval pause. It uses zero model calls and no network.

The suite is a **control-plane/safety regression suite**, not a model reasoning or quality benchmark. Its held-out partition is visible in the source package; “held-out” describes evaluation reporting and is not a claim of a secret generalization test.

## Metrics and expected safe behavior

Each case declares an expected task state plus deterministic checks over actual output/error/resource evidence. The run records:

- `accuracy`: fraction of cases whose expected state and all checks passed.
- `development_accuracy` and `held_out_accuracy`: the same score by split.
- `task_success_rate`: fraction whose actual task state is `succeeded`.
- `passed_cases` / `total_cases`.
- Mean and p95 case wall duration in milliseconds.
- Total completed model calls, all model routing attempts, tool invocations, and checkpoints. A no-eligible-model pause can have one attempt but zero completed model calls.

These metrics answer different questions. A traversal case that fails with the expected validation error scores **1 for accuracy** but is not a successful task. Therefore the built-in suite's expected task success rate is lower than its accuracy. Reporting only successful answers would hide whether unsafe behavior was correctly rejected.

Every case result persists its expected value, redacted actual value, score, failure explanations, task ID, tags, repeat count, and resource usage. A malformed suite is rejected before execution; an ordinary case failure becomes scored evidence rather than crashing the whole suite.

## Custom declarative suites

```json
{
  "suite_id": "my-regression-suite",
  "version": "1",
  "description": "Local task regression checks",
  "cases": [
    {
      "case_id": "exact-smoke",
      "name": "Offline output and resource contract",
      "split": "held_out",
      "tags": ["offline"],
      "task": {"goal": "Evaluate", "kind": "smoke"},
      "repeat": 1,
      "expect": {
        "state": "succeeded",
        "checks": [
          {"path": "result.mode", "operator": "eq", "value": "offline_deterministic"},
          {"path": "metrics.model_calls", "operator": "eq", "value": 0}
        ]
      }
    }
  ]
}
```

Run it with:

```bash
uaf eval run --suite ./my-suite.json --candidate local-working-tree --json
```

Task cases may be `smoke`, `tool`, `agent`, or `react`. Model cases use the configured eligible provider and record actual model usage; UAF never enables a provider or network for evaluation implicitly. Optional `fixtures` create bounded workspace files through the confined workspace implementation. `repeat` is limited to 1–3 and is useful for checkpoint replay checks.

Supported deterministic operators are `eq`, `contains`, `not_contains`, `exists`, `lte`, and `gte`. Paths traverse bounded actual JSON such as `result.output.answer`, `error.code`, or `metrics.checkpoints`. Custom Python scorers/imports, unknown fields/operators, oversized suites, duplicate case IDs, and secret-like persisted definitions are rejected.

Evaluation tool cases perform real governed operations in the configured workspace. Use a disposable workspace. The service never auto-approves or auto-rejects R2/R3 actions; an approval pause can itself be the expected outcome. The packaged approval-pause case intentionally leaves its pending approval as inspectable evidence; review and reject it during cleanup if you do not want to execute that action.

## Baseline comparison and release gate

```bash
BASELINE=$(uaf eval run --suite ./my-suite.json --json | python -c 'import json,sys; print(json.load(sys.stdin)["run_id"])')
uaf eval run --suite ./my-suite.json --baseline "$BASELINE" --candidate candidate-1 --json
uaf eval compare <candidate-run-id> "$BASELINE" --json
```

Comparison is allowed only when the canonical suite digest is identical. This prevents two different datasets from being presented as a causal improvement. The report includes accuracy delta, regressions, improvements, missing cases, and new cases.

`regression_gate_passed` requires:

1. No previously passing case regressed.
2. No baseline case is missing.
3. Every current case passes, including newly added cases.

A baseline is evidence, not an automatic promotion. Self-update still requires its separate tests, security review, protected-path checks, incumbent preservation, and human decision.

## Interpretation limits

- One suite does not prove universal reliability, model superiority, or a “1000×” improvement.
- Mocked/fake providers in tests verify orchestration, not real model quality.
- Real model evaluation needs a frozen dataset, provider/model/configuration record, current eligibility, and explicit cost/network approval under the no-spend policy.
- The current service runs cases serially. Duration percentiles on a small suite are diagnostic, not statistically strong latency claims.
- Current scorers are deterministic JSON/state checks. Model-based rubric grading, calibrated human review, multi-model comparison, and hidden external benchmarks remain future work.
