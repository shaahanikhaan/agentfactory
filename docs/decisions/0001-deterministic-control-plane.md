# ADR 0001: Deterministic control plane, optional models

Date: 2026-10-24
Status: accepted

## Context

The requested system must be local-first, resumable, testable without keys, and safe under prompt injection. A model-only router or a larger prompt cannot enforce persistence, permissions, budgets, or recovery. Combining multiple agent frameworks would add services and dependencies without proving those properties.

## Decision

Use a standard-library deterministic runner and SQLite state machine as the core. Models are optional worker/reviewer steps behind narrow adapters. The runner owns state transitions, checkpoints, tool dispatch, and final success. Offline smoke tasks execute deterministic code and explicitly report `ai_generated=false`.

Task checkpoints, long-term memory, audit events, and logs are separate stores. Role profiles describe logical responsibilities; they do not imply independent processes or formal reviewer independence.

## Consequences

- Core installation and offline tests have no third-party runtime dependency.
- Model outages become explicit paused/retry/failure states rather than fabricated responses.
- Every new capability needs a typed contract and evidence.
- Advanced graph/durable-framework features are not inherited automatically; implement only when a concrete requirement justifies them.

## Verification

`tests/test_runner.py`, `tests/test_tasks.py`, and the offline CLI/benchmark scenario verify durable role checkpoints and zero-call offline execution.
