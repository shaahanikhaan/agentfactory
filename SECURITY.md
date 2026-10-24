# Security policy

## Supported version

UAF 0.1.x is alpha software. Apply fixes to the current default branch and keep dependencies patched. There is no long-term-support branch yet.

## Reporting

Use the repository owner's private GitHub vulnerability-reporting channel if available. Otherwise contact the maintainer through the repository's listed private contact method. Do not open a public issue containing an unpatched exploit, credential, private memory, or sensitive task payload.

Include:

- Affected version/commit and OS/Python version.
- Minimal reproduction with synthetic data.
- Expected versus actual authorization or integrity behavior.
- Impact and any suggested mitigation.

Never include real API keys. Rotate exposed credentials through the provider immediately.

## Scope and expectations

Security reports involving tool allowlist bypass, path escape, approval substitution, credential disclosure, paid fallback, plugin auto-execution, unsafe self-promotion, or idempotency replay are high priority. Issues requiring an already-compromised OS account should still be documented, but UAF does not claim to protect data from an administrator/kernel attacker.

The research fetcher and self-update candidate runner have explicit prototype limitations in `docs/SECURITY.md`; read them before processing hostile input or code.

## Response

An acknowledgement or fix timeline is not guaranteed by this alpha repository. Maintainers should reproduce safely, add a regression test, prepare a fix without weakening existing gates, and document any required credential rotation or data recovery.
