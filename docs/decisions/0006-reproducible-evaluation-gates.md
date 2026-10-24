# ADR 0006: Reproducible evaluation and same-suite regression gates

- Status: accepted
- Date: 2026-10-24

## Context

The original benchmark measured durable offline throughput but could not establish whether a candidate preserved task behavior or safety expectations. Inspect AI's dataset/solver/scorer/log structure and OpenJarvis' non-regression learning guidance suggest inspectable cases and explicit gates. OpenJarvis-style automatic self-optimization is intentionally not enabled: UAF candidates require human promotion.

## Decision

Add a data-driven evaluation service that executes real tasks and stores per-case evidence:

- Versioned JSON suites contain labelled development/held-out cases, real task contracts, optional bounded fixtures, expected states, and deterministic checks.
- Scorers operate on actual state/output/error/resource JSON; custom executable scorers are forbidden.
- Runs persist case-level expected/actual values, failures, durations, model/tool/checkpoint counts, and suite digest.
- Baseline comparison is valid only for the identical canonical suite digest. A release regression gate requires no regressions, no missing baseline cases, and all current cases passing.
- The default suite is offline and measures control-plane/safety behavior, not model intelligence. Model suites remain optional and use the existing eligible-provider path.

## Consequences

Positive: “better” can be tied to reproducible behavior and resource evidence; negative safety cases count as expected behavior instead of being hidden by a raw success-rate metric; candidates cannot improve a score by switching to an easier baseline dataset.

Costs/limits: deterministic exact/contains/numeric checks cannot judge every open-ended answer. The packaged held-out split is public and not a secret generalization benchmark. Small-suite latency metrics are weak statistics. Human/model rubric evaluation and external hidden benchmarks remain separate future work.

Alternatives rejected: reporting only tasks/sec or raw task success; model-only self-grading; comparing different suite versions as if they were identical; automatically learning/promoting from evaluation results.
