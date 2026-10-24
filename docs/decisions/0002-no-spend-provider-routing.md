# ADR 0002: Fail-closed free/local provider routing

Date: 2026-10-24
Status: accepted

## Context

Free model availability and quotas change by provider, model, project/organization, tier, and time. Hard-coded model lists or third-party quota tables can become false and potentially costly. Credentials and provider error bodies may leak into logs.

## Decision

Ship no enabled cloud model. Require an explicit model, operator free confirmation, official provider HTTPS evidence host, verification date, environment credential, network permission, and budgets. Reject stale/future/ambiguous evidence. Restrict OpenRouter further to `:free` IDs and Ollama to loopback local inference.

Adapters only implement protocol parsing. The central router enforces eligibility, local daily attempts, capabilities, bounded retries, `Retry-After`, and persistent scoped cooldowns. Never store raw credentials or enable paid fallback/key rotation.

## Consequences

- A fresh install cannot make a cloud request accidentally.
- Configuration can become ineligible when evidence expires; this is intentional.
- UAF cannot guarantee that a provider remains free; operator/provider-side limits are still required.
- Live terms and quality need separate dated acceptance evidence.

## Verification

`tests/test_providers.py` covers disabled defaults, stale/unofficial evidence, credentials, OpenRouter suffixes, response parsing, output limits, quotas, retries, and persisted cooldowns using fake transports.
