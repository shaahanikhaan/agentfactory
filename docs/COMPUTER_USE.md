# One-key onboarding and governed computer use

## Status and evidence boundary

| Slice | State | What is actually provided |
|---|---|---|
| One Gemini key | `implemented_optional` | Official `models.list` discovery, explicit free-tier confirmation, OS-vault storage, environment fallback |
| Visible browser | `implemented_optional` | Dedicated Playwright Chromium profile, allowlisted HTTPS navigation, redacted snapshots, digest-bound click/type approvals |
| Windows mouse/keyboard | `implemented_optional` | Bounded PyAutoGUI batches, executable/window/focus binding, mandatory fail-safe, R3 approval and uncertain-effect recovery |
| Browser/native-app chat actions | `implemented_optional` | User login plus exact approved typing/clicks in an allowed destination; no delivery guarantee |
| Direct Slack/WhatsApp/Teams API connectors | `planned` | No native service connector or direct API token flow is included |
| Desktop screenshots/vision, Unicode desktop input, voice and avatar UI | `planned` | Not claimed by this release |
| Windows physical-host acceptance | `planned` | Automated tests in this checkout use Linux and fake drivers, not real mouse/keyboard or a real browser account |

Optional slices never change the offline core into a simulated cloud agent. A missing model, browser binary, OS vault, visible session, or adapter produces an explicit blocker.

## 1. One Gemini key

Run the guided wizard from an installed repository checkout:

```powershell
& $uaf setup
```

The wizard:

1. Reads the key with a hidden prompt. There is deliberately no `--api-key` argument that would expose it in command history/process listings.
2. Asks before one HTTPS request to Google's fixed official `models.list` endpoint.
3. Lists models returned for that key which support `generateContent` and have bounded metadata.
4. Requires a separate explicit confirmation that the selected key/model is currently free under the official pricing/terms. **Model discovery alone does not prove free eligibility.**
5. Stores the credential in an approved OS vault backend and stores only non-secret model configuration in `config.json`.
6. Enables network and Gemini only. Groq/OpenRouter/Ollama do not need keys or setup for Gemini operation.

On Windows the supported vault is Windows Credential Locker through `keyring`. Other approved backends are macOS Keychain and platform Secret Service/KWallet implementations. Plaintext/fail backends are rejected. Environment variables remain a fallback and take precedence when both sources exist.

Useful checks:

```powershell
& $uaf auth status --json
& $uaf provider list --json
& $uaf provider test gemini --json          # configuration/health only
& $uaf provider test gemini --live --json   # one explicit real generation request
```

To delete the vault entry (this does not unset an environment variable):

```powershell
& $uaf auth delete gemini --yes --json
Remove-Item Env:GEMINI_API_KEY -ErrorAction SilentlyContinue
```

For noninteractive setup, provide `GEMINI_API_KEY`, `--model`, `--online`, `--confirm-free`, and the current official `--source`/`--verified-at`. Protect and clear that environment variable afterward. Interactive setup is recommended on a personal laptop.

## 2. Dedicated visible browser

Install the optional packages and browser binary, then configure explicit domains:

```powershell
& $python -m pip install -e '.[browser]'
& $python -m playwright install chromium
& $uaf config set network_allowed true
& $uaf config set browser_enabled true
& $uaf config set browser_allowed_domains '["example.com"]'
& $uaf browser inspect https://example.com --wait-seconds 1 --json
```

Domain entries are exact DNS names. An entry such as `*.example.com` permits subdomains, not the bare root. Real sites may require separately reviewed CDN/identity domains; UAF does not provide an “allow the whole web” shortcut.

### Manual login

```powershell
& $uaf browser login https://YOUR-ALLOWLISTED-SERVICE/ --wait-seconds 120 --json
```

The browser is visible. Log in yourself while the command waits. The dedicated profile preserves normal browser session state for later explicit sessions. UAF does not read the password, cookies, local storage, or browser credential database. Do not replace the dedicated profile with a personal Chrome/Edge profile.

`browser inspect` prints bounded redacted text and numbered visible elements. `browser login` prints only a summary. The profile persists; an open page is not promised to persist after the CLI process exits.

### Exact browser action

Use the `url`, `snapshot_id`, `ref`, and visible label from `browser inspect`. For `expected_label`, UAF uses the element's non-empty ARIA label, then visible text, then placeholder.

```powershell
& $uaf task add "One reviewed browser click" --kind tool --tool browser.click `
  --arguments '{"url":"https://example.com/","snapshot_id":"snapshot_REPLACE","ref":1,"expected_label":"More information..."}' --json
```

The example values are placeholders: use one actual inspected snapshot, do not copy this payload blindly. Run the returned task, inspect its pending approval, then approve/resume:

```powershell
$run = & $uaf task run $task.task_id --json | ConvertFrom-Json
& $uaf approval approve $run.approval_id --actor local-human --reason "Reviewed exact URL, label, and snapshot"
& $uaf task resume $run.task_id --json
& $uaf task run $run.task_id --json
```

`browser.type` is R2 and additionally requires `text`; `browser.click` is R3 because a click may send, publish, delete, accept, or purchase. Neither tool supports arbitrary JavaScript. After typing, take a fresh snapshot before a send click.

### Resume invariant

A snapshot ID is a truncated SHA-256 digest of the bounded extracted page, elements, title, and URL. Before every click/type, UAF takes another read-only snapshot. After a process restart it may restore the approved URL, but the digest and expected label must still match. Changed content requires a fresh snapshot and approval. A redirect to a different URL is not silently accepted.

### Agent-driven browsing

A single governed ReAct task can navigate and read in one run:

```powershell
$task = & $uaf task add "Open https://example.com and summarize its visible text. Do not click or type." `
  --kind react --allowed-tool browser.navigate --allowed-tool browser.snapshot --json | ConvertFrom-Json
& $uaf task run $task.task_id --json
```

This requires an eligible configured model. Offline mode does not invent browser decisions. Add `browser.type`/`browser.click` only when their exact approval interruptions are acceptable.

### Browser controls and residuals

- Visible `headless=False` Chromium only; dedicated user-data directory.
- HTTPS port 443, allowlisted domains, public DNS answers, no URL userinfo or credential-like query keys.
- All routed requests and final redirects checked; service workers blocked, downloads disabled, browser permissions empty.
- Credential/security-looking paths and password/file/hidden/payment fields denied.
- Bounded/redacted page text and at most 80 candidate elements, further truncated to the registry output budget.
- No cookie/storage/session export, screenshot, arbitrary script, file download, or personal-profile import.
- DNS validation is not a pinned enterprise egress proxy; hostile pages can still mislead a model or user. Review the visible page and exact approval.
- A click/type exception after an attempted effect is `uncertain`, not automatically retried.

## 3. Chat on the user's behalf

There is no direct Slack/WhatsApp/Teams connector in this slice. Two governed routes exist:

1. **Browser:** manually log into the dedicated profile, allow the service and required static/identity domains, then use approved type/click actions.
2. **Native Windows app:** explicitly allow its exact executable and use an approved desktop batch.

Rules:

- The user must own/authorize the account and handle its terms, login, MFA, and billing. UAF does not automate account creation or acceptance.
- Drafting/typing and sending are separate actions. A send/submit click requires its own exact R3 approval.
- Approval means permission for that exact payload/action, not proof of delivery, moderation compliance, or recipient consent.
- UAF does not harvest existing browser credentials, rotate accounts, evade quotas/blocks, or send unapproved messages.
- Dynamic pages may legitimately require repeated fresh snapshots/approvals.

## 4. Windows desktop mouse/keyboard

Review optional dependency licenses first: current PyPI metadata marks PyAutoGUI's transitive `mouseinfo` package as GPLv3+. It is not vendored/relicensed by UAF; skip this extra if your distribution policy does not allow it.

Install and enable only a reviewed native application:

```powershell
& $python -m pip install -e '.[desktop]'
& $uaf config set desktop_enabled true
& $uaf config set desktop_allowed_applications '["notepad.exe"]'
```

Open exactly one matching Notepad window and confirm its exact title/process. The example assumes `Untitled - Notepad`; edit the JSON if the actual title differs.

```powershell
Copy-Item .\examples\desktop\notepad-batch.json (Join-Path $workspace "notepad-batch.json")
$run = & $uaf desktop run notepad-batch.json --json | ConvertFrom-Json
& $uaf approval approve $run.approval_id --actor local-human --reason "Reviewed exact Notepad text"
& $uaf task resume $run.task_id --json
& $uaf task run $run.task_id --json
```

The batch executor:

- Resolves the executable from the Win32 window process, requires exactly one exact title match, activates it, and checks focus before every action.
- Stops if focus/process changes. Multiple matching windows are ambiguous and denied.
- Forces `FAILSAFE=True` and a bounded pause. PyAutoGUI's upper-left-corner fail-safe remains available.
- Allows `move`, `click`, `type`, `press`, `hotkey`, `scroll`, and bounded `wait` actions only.
- Defaults to 12 actions per batch (hard maximum 20), at most 1,000 printable-ASCII typed characters and 5,000 ms explicit waits per batch.
- Denies off-screen coordinates, unknown keys, clipboard/system/focus hotkeys, secret-like text, NUL/non-ASCII desktop typing, and excessive batches.
- Denies known shells, interpreters, browsers, file/system administration tools, and remote-control executables in configuration. Use browser/workspace tools for those domains instead.
- Is not an OS sandbox. It controls the real visible desktop and can cause real effects. Run UAF and the target at the same integrity level, never as an unnecessary administrator.

No screenshot/vision, clipboard read, Unicode clipboard injection, background locked-session control, or hard real-time driver timeout is claimed. A locked screen, RDP session, secure desktop/UAC prompt, elevated target, or changing UI can block or invalidate an action.

## 5. Uncertain-effect recovery

Never blindly rerun a task in `uncertain_side_effect`. Inspect the visible destination first:

```powershell
& $uaf effect list $run.task_id --json
```

If human inspection proves that the desired complete effect occurred, reconcile `executed` with a tool-shaped result. For the one-action Notepad example:

```powershell
& $uaf effect reconcile $run.task_id 'EXACT_KEY_FROM_EFFECT_LIST' --observed executed `
  --evidence '{"note":"Human verified the complete approved text in Notepad"}' `
  --result '{"output":{"application":"notepad.exe","window_title":"Untitled - Notepad","executed_actions":1,"postcondition":true},"evidence":{"reconciled":true}}' `
  --actor local-human --yes --json
```

A completed ledger entry replays the recorded result without another mouse/keyboard action. If inspection proves no effect occurred, use `--observed not-executed` with evidence and **without** `--result`; explicit resume may then retry. If a partial effect occurred and neither statement is true, leave it uncertain and manually remediate first. Reconciliation evidence is audited and must not contain credentials.

After all task effects are reconciled:

```powershell
& $uaf task resume $run.task_id --json
& $uaf task run $run.task_id --json
```
