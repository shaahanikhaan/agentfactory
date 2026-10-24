# ADR 0004: Discovery is not execution; a worktree is not a sandbox

Date: 2026-10-24
Status: accepted

## Context

Python entry-point discovery normally leads to imports, which execute third-party code. “Hot reload” does not provide isolation. Likewise, a Git worktree isolates file paths but candidate tests still execute with host OS permissions.

## Decision

Support checksummed declarative workflows and progressive Markdown skills. Disable plugins by default and never auto-import Python entry points. Any future Python plugin support requires a separate OS-sandbox design.

Self-update can compare trusted-origin commits or create a detached worktree candidate from a bounded patch. Reject protected policy/test/release paths. Running candidate tests requires two explicit operator flags and a reduced environment/timeout; missing/failed tests and agent actors cannot pass promotion evaluation. This version never merges, pushes, deploys, or expands its own permissions.

## Consequences

- Declarative extensions are useful without pretending to isolate arbitrary Python.
- Self-update remains a review/recovery workflow rather than autonomous self-modification.
- Truly untrusted candidate tests still need a disposable VM/container supplied by the operator; Docker is not a core requirement.

## Verification

`tests/test_extensions.py` covers tamper/no-import behavior. `tests/test_self_update.py` covers trusted origins, protected paths, worktree isolation, mandatory tests, and human-only evaluation.
