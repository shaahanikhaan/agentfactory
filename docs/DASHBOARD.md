# Company dashboard, one-key setup, and voice commands

## Status

- **Local dashboard:** `implemented`. It uses the same onboarding, provider, diagnostics, credential, and factory services as the CLI.
- **One-click Windows launcher:** `implemented` for a reviewed source checkout/ZIP. Windows dashboard acceptance is still pending.
- **Browser voice commands:** `implemented_optional`. Browser recognition, microphone permission, and language support are feature-detected; text commands always remain available.
- **Real live provider success:** not established in the automated checkout. Fake transport tests prove the request/config/run contract, not provider availability.

The dashboard does not promise error-free cloud operation, continuous listening, autonomous R2/R3 approval, or a simulated company of parallel agents.

## Easiest Windows path

1. Extract the reviewed UAF source ZIP or open the reviewed checkout. The directory must contain `Start-UAF.cmd`, `pyproject.toml`, `src`, and `scripts`.
2. Double-click **`Start-UAF.cmd`**.
3. The launcher uses Python 3.11+, creates a repository-local `.venv`, installs bounded/pinned bootstrap packages and the `computer-use` extra, prepares optional Chromium, and runs the real `init` and `doctor` gates. First-run downloads require internet. No administrator shell, global package install, or PowerShell execution-policy change is used.
4. A required bootstrap/doctor failure stops startup with a recovery message. Optional Chromium failure leaves the normal-browser dashboard available and retries Chromium on a later launch.
5. The exact private dashboard URL opens in the normal browser. Keep its `#token=...` fragment private. If browser opening fails, copy the exact URL printed in the launcher window.
6. On the literal loopback page (`127.0.0.1` or `::1`), paste one Gemini API key. Review the visible official free-tier confirmation and select **Confirm free tier, save key & start**.

The API key is never a launcher argument, voice command, config value, browser-storage value, or setup-file value.

For an existing installation, the equivalent command is:

```powershell
& $uaf dashboard
# Alternative port / do not auto-open:
& $uaf dashboard --port 8766
& $uaf dashboard --no-open
```

The CLI remains fully supported. The one-click file is a source-checkout convenience; installed wheels include the dashboard assets and `uaf dashboard` entry point, not the root `.cmd` file.

## What one-key setup actually does

After the explicit button action, one bounded setup operation performs:

1. Fixed official Gemini `models.list` discovery using the supplied key.
2. Automatic selection from the reviewed stable allowlist, in order:
   - `gemini-3.8-flash`
   - `gemini-3.5-flash-lite`
   - `gemini-3.1-flash-lite`
3. Explicit user free-tier attestation against the linked official pricing page, with the current date. Discovery alone is never treated as free-tier proof. Newly discovered or paid-only models are not silently added.
4. Existing approved OS-vault onboarding with rollback on config-write failure. Other AI provider keys are not required.
5. One explicit bounded live diagnostic. Gemini 3.8 uses `thinkingLevel=low` and a 256-token combined thinking/output ceiling; normal agent reasoning is unchanged.
6. The existing durable `company-startup@1` factory DAG with idempotency key `dashboard-company-start-v2`:
   - **Reliability:** real bounded local workspace inventory; zero model calls.
   - **Orchestration:** one bounded model worker plus one independent model reviewer for a startup brief; two model calls. Their context contains fixed privacy instructions and the goal, never inventory entries, workspace filenames/contents, credentials, or memory.
   - **Quality:** a real deterministic durable acceptance record; zero model calls.

The first complete startup therefore has a hard bound of one diagnostic plus two DAG model calls, executed serially. Department cards show `last_execution` only for actual live-readiness/inventory/operations-brief/acceptance-record evidence. The default UI hides departments without execution evidence; an opt-in toggle reveals other capability/readiness states without claiming autonomous parallel staff.

A successful setup response has an eligible model, a completed live diagnostic, and a succeeded three-step DAG. If live generation fails, the key/config may already be saved, but `ready` stays false and no successful factory start is claimed. Refresh status before retrying. Provider cooldowns and `Retry-After` remain authoritative. A completed DAG replay does not repeat its worker/reviewer calls.

The official free-tier terms currently state that free-tier content may be used to improve provider products. The readiness probe and startup planning/review prompts are fixed and contain no workspace filenames or contents. Review current provider terms before other model-backed work on sensitive content.

## Voice and text commands

Select **Enable microphone / Push to talk** to request one utterance. There is no continuous background listener and leaving the page stops recognition.

| Command | Result |
|---|---|
| `status`, `refresh`, `factory status`, `status batao` | Refresh actual local state |
| `start factory`, `start departments`, `factory shuru karo` | Create a pending start request; does not start immediately |
| `confirm start factory`, `confirm karo` | Confirm the pending start and permit one bounded live probe plus the local DAG |
| `open setup` | Focus the key form; voice never accepts/submits the key and credential-like commands are discarded without echo |
| `cancel`, `cancel start`, `stop` | Cancel the pending start without a provider request |

English and Urdu recognition languages can be selected; recognition quality and language-pack availability are browser-dependent. Text accepts the documented command aliases even when speech recognition is unavailable.

### Audio processing boundary

- The default **Prefer on-device speech recognition** option sets `processLocally=true` only when the browser exposes that control. Where supported, `SpeechRecognition.available/install` checks/prepares the selected language model after the user's click; this optional browser-managed download is disclosed before microphone capture.
- If the control or required language model is unavailable, UAF does not silently fall back to remote speech. Follow the error or use text. Current Edge documentation limits its built-in local model to specific Insider versions/flags, so ordinary stable-browser support must not be assumed.
- To permit browser/vendor speech processing, explicitly clear the on-device preference before starting the microphone. Browser recognition may then send audio to the browser vendor's service.
- Voice is not approval authority. It cannot approve R2/R3 actions, change policy, enable paid mode, or submit an API key. Credential-like command text is discarded without echo/submission.

**Never speak a credential into any microphone.** Discarding recognized command text protects the UAF UI/API, but cannot undo audio processing already performed by the browser/vendor. Use the protected text key field only.

No second AI key, speech service, Node server, or heavy web framework is required.

## HTTP and credential security

- A random per-launch capability is placed in the URL fragment, which is not sent in HTTP requests. JavaScript copies it to an `X-UAF-Token` header; query-string tokens, cookies, localStorage, and sessionStorage are not used.
- Exact `Host` allowlisting, optional `Origin`/`Sec-Fetch-Site` checks, bounded 16 KiB JSON, JSON-only writes, and no CORS relaxation protect the local API.
- Responses include CSP, `no-store`, `nosniff`, no-referrer, frame-ancestor denial, and connection close. Request handling is serial for the 4 GB/CPU-only profile.
- Credential writes require a **literal loopback bind**. Hostname resolution alone is not accepted as loopback proof.
- Explicit non-loopback exposure requires an exact `--allowed-host` and disables credential writes, experience approval, and factory start even with a valid capability. It is a read-only status preview; loopback remains the recommended and supported setup path.
- API errors pass redaction helpers. Credential-route unexpected exception tracebacks are not written because third-party exception text is outside UAF's redaction contract.

If the capability URL is exposed, close the dashboard and start a new one to generate a new capability. Non-loopback exposure is not a production authentication system or a recommended remote deployment.

## Real activity and governed experience

The latest-run timeline is derived from durable factory task IDs, states, and error codes; it is not simulated progress. Live-readiness evidence becomes `stale` when its bounded health window expires instead of remaining a current success. Failed doctor check names are shown in Runtime health for recovery. Request handling remains serial, so a long setup/provider request can delay a refresh.

Real succeeded/failed tasks create bounded local experience records containing the goal and operational outcome, never model output. Records begin **pending** and do not enter model context. The **Real task outcomes** panel lets a loopback user inspect and explicitly approve a record for future recall. Approval uses `APPROVE_TASK_EXPERIENCE` inside the first-party button flow, is idempotent, and cannot be issued through the text/voice command parser. Non-loopback status exposes counts only: experience content and approval are disabled, and the UI explains hidden records rather than claiming that none exist.

Approved non-private outcomes are bounded and wrapped as untrusted historical evidence in future worker/ReAct calls. They grant no tools or permissions. Credential-like captures are skipped, and a content-free schema-v4 ledger prevents task replay from duplicating records or recapturing a privacy-deleted outcome. The company-startup planner sets `memory_recall: false`, so even approved experience is absent from its privacy-safe prompt.

## Recovery

### Missing capability / `capability_denied`

Open the exact URL printed by this dashboard process, including `#token=...`. An old URL from a previous launch has the wrong capability.

### `Host`, `Origin`, or cross-site denial

Use the exact local URL rather than an alias, reverse proxy, or public hostname. Do not weaken Host/Origin checks to make an unofficial tunnel work.

### Provider timeout, unavailable model, quota, or cooldown

Read **Runtime health**, **Gemini access**, and the error message. A configured key is not the same as live readiness. Wait for provider recovery/cooldown, then use **Start / retry factory**. No automatic dashboard retry loop or paid fallback exists. Do not add keys to evade quotas.

### Startup DAG is paused/failed/interrupted

The latest run card exposes the actual state and error. An explicit start/retry may resume only this fixed R0 company-startup DAG from `paused_offline`, `interrupted`, `retry_wait`, or `failed`. Completed inventory/worker checkpoints are reused where available; no blind effect replay is allowed. Approval and uncertain-side-effect states are never auto-resumed; use the ordinary approval/effect recovery runbook.

### Optional Chromium failed

The company dashboard uses the normal browser and does not need Playwright Chromium. Only dedicated browser automation remains unavailable. Rerun the launcher after network recovery or run `python -m playwright install chromium` in the local environment.

### Low RAM or disconnected workspace

Keep the default serial behavior, close unnecessary applications/browser tabs, and run `uaf doctor --json`. Restore the configured workspace before retrying; do not point the active database at an unreliable removable drive.

## Verification

`tests/test_dashboard.py` exercises real loopback HTTP requests with fake official/provider/vault drivers: Host/capability/Origin/body boundaries, one-key setup, selected-model low-thinking probes, no secret in responses/config/audit, live failure without readiness, stale health, non-loopback credential/start denial, failed-doctor-check visibility, and idempotent three-step DAG success/replay with two model calls, per-department evidence, proof that a private inventory filename/content stays out of the worker prompt, and explicit/idempotent loopback-only experience approval with no voice authority. `tests/test_experience.py` covers capture, sensitive-skip, privacy deletion, and approved recall. `tests/test_bootstrap.py` checks bounded local command plans, corrupt-marker recovery, optional-installer failure tolerance, and doctor-failure launch blocking; the CLI suite separately proves failed doctor checks return a nonzero process status.

Real Windows dashboard use, physical microphone recognition, and successful Gemini generation require separate acceptance on the target machine.
