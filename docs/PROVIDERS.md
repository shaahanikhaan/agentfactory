# Free/local provider runbook

## No-spend policy

UAF ships with **zero eligible cloud models**. A provider name appearing in an adapter is not a claim that every model, account, or region is free. The operator must verify current model eligibility, limits, data-use terms, and account state from official sources.

The router fails closed when evidence is missing, stale, future-dated, from an unofficial host, or when a model is disabled/unverified. There is no paid fallback and no account/key rotation to evade quotas.

> UAF validates the configuration and freshness of your attestation. It cannot independently prove that a provider will charge nothing. Set provider-side budgets/alerts where available and use a least-privilege project.

## Recommended one-key Gemini setup

Install the `setup` or `computer-use` extra and run `uaf setup`. The wizard hides the key prompt, calls the fixed official `models.list` endpoint only after network confirmation, and stores the key in an approved OS vault. Model metadata and free-tier attestation are separate: discovery never automatically marks a model free.

```powershell
& $python -m pip install -e '.[setup]'
& $uaf setup
& $uaf auth status --json
& $uaf provider test gemini --json
# Optional separate real request:
& $uaf provider test gemini --live --json
```

One Gemini credential is sufficient for built-in Gemini roles; no other provider credential is required. The environment variable remains an alternative and takes precedence over the vault. `auth delete gemini --yes` removes only the vault entry. See [Computer Use](COMPUTER_USE.md) for rollback and noninteractive details.

## Common manual setup

1. Create/restrict a credential in the provider's official console.
2. Put it in an approved OS vault through guided setup or in the process environment, never `config.json`, task input, memory, or a workspace file.
3. Read the current official rate-limit/pricing/model documentation.
4. Configure one explicit model with `--confirm-free`, `--source`, and the actual review date.
5. Enable network explicitly.
6. Run an offline provider test, then one deliberate `--live` probe.

```bash
export GEMINI_API_KEY='...'
# or GROQ_API_KEY / OPENROUTER_API_KEY

uaf provider configure gemini <model> \
  --confirm-free \
  --source https://ai.google.dev/gemini-api/docs/rate-limits \
  --verified-at YYYY-MM-DD \
  --capabilities text \
  --priority 100 \
  --context-limit 32000 \
  --output-limit 4096

uaf provider test gemini --json       # configuration/adapter health only
uaf config set network_allowed true
uaf provider test gemini --live --json # one real request
uaf provider list --json
```

Use PowerShell `$env:GEMINI_API_KEY='...'` on Windows. Environment variables can still be visible to the same OS user/processes; use the provider console's restrictions and rotate keys when necessary.

## Provider-specific rules

### Gemini

- Adapter: native `v1beta/models/<model>:generateContent`.
- Onboarding discovery: fixed `GET v1beta/models` with a header credential, bounded response/models, and no redirect. It returns availability/metadata, not free-tier proof.
- Credential: approved OS vault or `GEMINI_API_KEY`, sent in `x-goog-api-key`, never the URL.
- Official evidence hosts accepted by the router: `ai.google.dev`, `aistudio.google.com`, `cloud.google.com`.
- Quota scope recorded locally: project.
- Official rate-limit reference: <https://ai.google.dev/gemini-api/docs/rate-limits>.

Provider limits can vary by model and tier and may be shown most accurately in AI Studio. UAF does not hard-code a third-party quota claim.

### Groq

- Adapter: fixed `https://api.groq.com/openai/v1/chat/completions`.
- Credential: `GROQ_API_KEY` as a bearer token.
- Official evidence hosts: `console.groq.com`, `groq.com`.
- Quota scope recorded locally: organization.
- Official reference: <https://console.groq.com/docs/rate-limits>.

A local daily request budget is not a replacement for the provider's multidimensional organization limits.

### OpenRouter

- Adapter: fixed `https://openrouter.ai/api/v1/chat/completions`.
- Credential: `OPENROUTER_API_KEY` as a bearer token.
- Official evidence host: `openrouter.ai`.
- Only explicit model IDs ending in `:free` are eligible in this no-spend build.
- Official references: <https://openrouter.ai/docs/api_reference/limits> and <https://openrouter.ai/docs/api_reference/overview>.

This suffix check is an additional guard, not a guarantee of availability or future terms. Do not add accounts/keys to work around governed capacity.

### Ollama (local optional)

```bash
uaf provider configure ollama <installed-local-model> \
  --confirm-local-resources \
  --endpoint http://127.0.0.1:11434
uaf provider test ollama --live --json
```

Ollama is restricted to a loopback HTTP endpoint and marked `local`, not cloud-free. Cloud `network_allowed` is not required for local inference. Model download, RAM, disk, and inference time are the operator's responsibility; UAF does not assume that a model fits in 4 GB RAM. Keep workers at 1 on small machines.

## Routing and failure behavior

- Models are sorted by explicit priority, then stable provider/model name.
- Required capabilities must be a subset of configured capabilities.
- Local daily request attempts and per-task model-call ceilings are persisted/enforced.
- `Retry-After` seconds and HTTP-date forms are parsed.
- Rate-limit and selected permanent errors create persistent cooldowns.
- Transient retries are bounded with capped exponential delay/jitter.
- Provider response and error bodies are bounded/redacted; credentials are not logged.
- Output over the character budget is an error, not silently truncated success.

Inspect state:

```bash
uaf provider list --json
uaf status --json
uaf provider clear-cooldown gemini --model <model> --json
```

Clearing a local cooldown does not change the provider's real quota. Do it only after reviewing current provider capacity.

## Live verification status

The repository test suite uses fake transports/adapters. It verifies request parsing, eligibility, retries, quota persistence, and secret handling **without real cloud calls**. Live provider availability, current free terms, quality, and latency remain environment-specific acceptance checks. Record a live result separately before claiming it in a release.
