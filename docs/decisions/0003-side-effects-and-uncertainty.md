# ADR 0003: Model side effects as uncertain, not magically exactly-once

Date: 2026-10-24
Status: accepted

## Context

A process can fail after an external service applies an effect but before UAF records its receipt. Retrying may duplicate the effect; not retrying may omit it. A generic local checkpoint cannot determine the remote outcome.

## Decision

Bind each effect to a task/step key, canonical payload digest, destination, and idempotency record. Idempotent operations may replay a stored result. Interrupted non-idempotent reservations persist `uncertain`; the task enters `uncertain_side_effect` and cannot blind-rerun. Reconciliation requires destination-specific evidence or a human decision.

R2/R3 execution additionally requires an approval bound to the exact canonical payload and destination. R3 delete creates a file backup before execution.

## Consequences

- UAF can honestly claim replay/conflict/uncertainty controls, not universal exactly-once delivery.
- New external adapters must declare idempotency and implement reconciliation where possible.
- Some crashes require manual intervention; this is safer than hiding ambiguity.

## Verification

`tests/test_idempotency.py` includes the interrupted-reservation regression, replay, digest conflict, and reconciliation. `tests/test_tools.py` covers approval and R3 recovery.
