# Evidence-Led Coding Procedure

Use this as a procedure, not as permission.

1. Inspect the existing implementation, tests, version-control state, and conventions before editing.
2. Preserve user work and choose the smallest coherent vertical slice.
3. Define observable acceptance behavior and failure paths before implementation.
4. Keep authorization, approvals, and secret handling in deterministic runtime code, never only in prompts.
5. Use workspace-confined writes and dependency review. Do not execute generated code on the host by default.
6. Run relevant unit, integration, security, migration, and recovery tests. Report actual results and unrun checks.
7. Review the diff for data loss, permission expansion, secret leakage, and dependency/license changes.
8. Leave a known-good rollback path. Promotion requires the configured release gate and human approval.

Output: changed files, behavior, test evidence, security impact, resource impact, and remaining limitations.
