# Windows 10/11 laptop installation and removable storage

## Target and current evidence

UAF targets Windows 10/11, Python 3.11+, CPU-only operation, and 4 GB RAM with serial defaults. Core SQLite/config work needs no GPU, Docker, database server, or paid account.

**The automated checkout gates ran on Linux.** Browser/desktop tests use fake drivers. Separately, the user reported Windows Python 3.11.9 initialization, doctor checks, approved Credential Locker storage, and eligible `gemini-3.8-flash` configuration; real generation attempts then failed with provider-unavailable/timeout results. This is partial user-reported evidence, not successful live inference or completed dashboard/microphone/physical-desktop/4 GB acceptance.

## Easiest one-click dashboard path

From the reviewed source directory, double-click **`Start-UAF.cmd`**. It automates the local environment, optional dependencies/Chromium, `init`, and `doctor`, then opens the private loopback company dashboard. Paste the Gemini key only into that local page and explicitly confirm current official free-tier terms. Setup includes one bounded live diagnostic, then a durable three-step startup DAG with local inventory, one privacy-safe worker/reviewer brief (two additional model calls), and deterministic quality acceptance before it can be reported ready.

The launcher does not need an administrator shell, global pip install, PowerShell execution-policy change, or a second AI key. A required failure stops with recovery text; optional Chromium failure does not block the normal-browser dashboard. For URL/capability, voice/audio privacy, provider failures, and run recovery, use [Dashboard and voice](DASHBOARD.md). Windows execution of this new launcher/dashboard is still an acceptance step, not a passed result.

## Complete first-time installation (manual alternative)

### 1. Install prerequisites

1. Install 64-bit **Python 3.11 or newer** from `https://www.python.org/downloads/`. Enable the Python launcher/PATH option offered by the installer.
2. Git is optional if you already have the source ZIP. Otherwise install Git from `https://git-scm.com/download/win`.
3. Use a normal user account. Do not run UAF as administrator merely to make desktop automation work; elevated targets and UAC secure desktops are intentionally not bypassed.

Open a new PowerShell window and check:

```powershell
py -3.11 --version
git --version   # only if Git is installed
```

If only another supported Python 3.x is installed, use `py -3.12` (or the installed 3.11+ version) consistently instead.

### 2. Open the reviewed source directory

The working directory must contain `pyproject.toml`, `src`, `examples`, and `scripts`. For a Git checkout, clone the repository and select the reviewed revision containing this update; do not assume an older release already has computer-use features.

```powershell
cd $env:USERPROFILE\Documents
# Either extract the reviewed source here, or:
git clone https://github.com/shaahanikhaan/agentfactory.git
cd agentfactory
# If a specific reviewed revision/branch was supplied, select it before continuing.
```

### 3. Create an isolated virtual environment

```powershell
py -3.11 -m venv .venv
$python = Join-Path $PWD ".venv\Scripts\python.exe"
& $python -m pip install --upgrade pip setuptools
```

Calling `python.exe` directly avoids changing PowerShell execution policy. Do not disable execution policy globally.

### 4. Install UAF and selected extras

For one-key onboarding + browser + desktop:

```powershell
& $python -m pip install -e '.[computer-use]'
$uaf = Join-Path $PWD ".venv\Scripts\uaf.exe"
```

Other supported choices:

```powershell
# Core only (offline/deterministic; no optional packages):
& $python -m pip install -e .

# Development verification plus computer use:
& $python -m pip install -e '.[dev,computer-use]'

# Individual slices:
& $python -m pip install -e '.[setup]'
& $python -m pip install -e '.[browser]'
& $python -m pip install -e '.[desktop]'
```

The combined `computer-use` extra currently installs `keyring`, `playwright`, and `PyAutoGUI` within the constraints in `pyproject.toml`. The core dependency set remains empty.

**License review:** UAF does not relicense optional packages. Current PyPI metadata marks PyAutoGUI's transitive `mouseinfo` dependency as GPLv3+, and some transitive metadata is inconsistent. Review the complete installed licenses/NOTICEs before accepting the desktop extra or bundling it. If that is unsuitable, skip `desktop`/`computer-use` and install `setup` + `browser` instead.

### 5. Install the dedicated Chromium binary

This is a separate explicit download; pip does not install the browser binary:

```powershell
& $python -m playwright install chromium
```

Skip this only if browser automation is not needed. UAF launches visible Chromium with its own profile, not the user's existing Chrome/Edge profile.

### 6. Initialize stable local state and workspace

```powershell
$workspace = Join-Path $env:USERPROFILE "Documents\UAFWorkspace"
& $uaf init --workspace $workspace --json
& $uaf doctor --json
& $uaf capabilities --json
```

Default core home is `%LOCALAPPDATA%\UltimateAgentFactory`. To use another stable local directory for every command in the current PowerShell session:

```powershell
$env:UAF_HOME = "C:\UAFData"
& $uaf init --workspace $workspace --json
```

Keep `UAF_HOME`, the active DB, approvals, backups, and browser profile on stable local storage. Do not put the active SQLite DB or logged-in browser profile on a USB drive that may disconnect.

### 7. Prove offline operation before adding a key

```powershell
$task = & $uaf task add "Windows offline acceptance" --kind smoke --json | ConvertFrom-Json
& $uaf task run $task.task_id --json
& $uaf task timeline $task.task_id --json
& $uaf factory start offline-workspace-inventory@1 "Windows inventory" `
  --input '{"path":".","limit":100}' --idempotency-key windows-inventory --json
& $uaf eval run --json
```

Expected results are deterministic `succeeded`, eight passing evaluation cases, and zero model calls. This is real local control-plane work, not an offline LLM.

If development extras were installed, also run:

```powershell
& $python scripts\verify.py
```

### 8. Add one Gemini API key

Create/authorize a Gemini key in the provider's official account flow yourself. Review current pricing, rate limits, and terms. UAF does not scrape the key from a browser or enable billing.

```powershell
& $uaf setup --workspace $workspace
```

Follow the hidden key prompt, explicit `ONLINE` confirmation, model selection, and separate `FREE` confirmation. The default evidence source is `https://ai.google.dev/gemini-api/docs/pricing`; use `--source` and `--verified-at` when a different current official source/date applies.

Then check without generating content:

```powershell
& $uaf auth status --json
& $uaf provider list --json
& $uaf provider test gemini --json
```

`setup_complete: true` means configuration, vault credential, network policy, and dated free eligibility all passed locally. It is not a live generation result. To make one explicit real request:

```powershell
& $uaf provider test gemini --live --json
```

No Groq, OpenRouter, or other AI-provider key is required for Gemini-backed built-in roles. Do not enable paid fallback or add extra keys to work around quotas.

### 9. Optional visible browser acceptance

Start with a harmless public page before using an authenticated service:

```powershell
& $uaf config set network_allowed true
& $uaf config set browser_enabled true
& $uaf config set browser_allowed_domains '["example.com"]'
& $uaf browser inspect https://example.com --wait-seconds 1 --json
```

Confirm that Chromium is visible, the output has a digest-based `snapshot_id`, and the profile path reported by `uaf doctor` is the dedicated UAF path.

For a real account, first review the service's current official domain requirements and allow only required service/identity/CDN domains. Then run `browser login` and log in manually. Passwords, cookies, local storage, and existing personal browser profiles are not imported into model context.

A model-driven read-only acceptance task:

```powershell
$task = & $uaf task add "Open https://example.com and summarize visible text. Do not click or type." `
  --kind react --allowed-tool browser.navigate --allowed-tool browser.snapshot --json | ConvertFrom-Json
& $uaf task run $task.task_id --json
```

For exact click/type and chat examples, follow [Computer Use](COMPUTER_USE.md). Sending is never implied by typing; the send click requires separate R3 approval.

### 10. Optional desktop acceptance

Use a disposable Notepad window before any native chat/productivity app:

```powershell
& $uaf config set desktop_enabled true
& $uaf config set desktop_allowed_applications '["notepad.exe"]'
Copy-Item .\examples\desktop\notepad-batch.json (Join-Path $workspace "notepad-batch.json")
```

Open exactly one Notepad window with the title in the JSON (`Untitled - Notepad` in the example). Edit the JSON title if necessary, then:

```powershell
$run = & $uaf desktop run notepad-batch.json --json | ConvertFrom-Json
& $uaf approval list --state pending --json
& $uaf approval approve $run.approval_id --actor local-human --reason "Reviewed disposable Notepad acceptance"
& $uaf task resume $run.task_id --json
& $uaf task run $run.task_id --json
```

Verify exactly one approved ASCII text entry and zero unexpected effects. Keep the mouse available for PyAutoGUI's upper-left fail-safe. If anything is unclear or partially executed, inspect first and follow the uncertain-effect procedure instead of rerunning.

## Troubleshooting

### `py` or Python is not found

Reinstall Python with the launcher/PATH option, open a new PowerShell, and retry `py -3.11 --version`. Do not install packages into a random system Python.

### Secure OS vault is unavailable

Install the `setup`/`computer-use` extra in the same virtual environment. On Windows, ensure the normal Credential Locker service is available and the session is not an unsupported headless/service account. UAF rejects plaintext/fallback keyrings instead of writing the key to config. `GEMINI_API_KEY` remains an explicit alternative; protect and clear it after use.

### `No eligible free/local model`

Run `uaf provider list --json` and read `reason`. Check network enablement, vault/env presence, exact model configuration, official HTTPS source, verification date, and cooldown/daily budget. A model being listed by Google does not prove it is free. Do not clear cooldowns merely to evade `Retry-After`.

### Chromium does not start

Run `& $python -m playwright install chromium` in the same environment. Check `uaf doctor` for `playwright`, browser enablement, domains, and profile path. Real browser acceptance was not performed in the Linux development checkout.

### A page or subresource is blocked

Review the exact blocked domain and add only required HTTPS domains. Redirects, non-public IPs, credential-like query parameters, credential pages, downloads, and service workers are denied deliberately. There is no allow-all domain setting.

### Desktop target is missing or ambiguous

Check the exact lowercase executable basename and full window title. Close duplicate matching windows, keep the desktop unlocked and visible, and run UAF/target at the same integrity level. Shells, browsers, system tools, and remote-control programs cannot be enabled through the desktop allowlist.

### Desktop text is rejected

This slice accepts printable ASCII only, at most 1,000 characters per batch. Urdu/Arabic and other Unicode desktop input is not implemented; do not work around it by reading/overwriting the clipboard. Browser `type` has a separate bounded text path, subject to its own policy.

### Focus changed or fail-safe triggered

The batch stops and may become `uncertain_side_effect`. Inspect the real window. Use `uaf effect list`, then reconcile only with actual human evidence. Never use repeated resume attempts as a way to discover whether input occurred.

## Storage layout and removable workspaces

Recommended:

- `%LOCALAPPDATA%\UltimateAgentFactory` or `C:\UAFData`: config, SQLite DB, snapshots, audit state, logs, and dedicated browser profile on stable local storage.
- `E:\UAFWorkspace`: optional user artifacts on removable storage.

```powershell
$env:UAF_HOME = "C:\UAFData"
& $uaf init --workspace E:\UAFWorkspace
```

Do not put the active SQLite database on USB/network storage that may disappear. WAL is single-host and not for concurrent network-share writers. Only one UAF writer should use a given database.

If the workspace disconnects, UAF raises unavailable and pauses instead of redirecting writes to a similarly named drive. Reconnect the same workspace, inspect the task, and resume explicitly.

## Controlled shutdown and recovery

1. Stop starting new tasks.
2. Let the current bounded step finish or use Ctrl-C once.
3. Confirm no `uaf` process is writing the DB or controlling the desktop.
4. Run `uaf doctor --json` and `uaf backup create --purpose controlled-shutdown --json`.
5. After restart, inspect `uaf status --json`, task timelines, and uncertain effects.
6. Explicitly resume interrupted tasks; never blindly repeat uncertain effects.

This release is a CLI, not a Windows service. Windows Service Recovery, `Ctrl+Break` service semantics, and service control manager integration are not implemented. Browser/desktop automation requires an interactive visible session, not a locked background service.

## Small-machine settings

Defaults use one worker and one LLM request at a time. For 4 GB RAM:

- Close unrelated browser/desktop apps during acceptance; Chromium has its own memory cost.
- Leave desktop vision/voice and local large models disabled.
- Keep prompt/output, action, text, and queue budgets bounded.
- Do not run multiple UAF instances against one home or two desktop controllers simultaneously.
- Treat Ollama model fit as a separate measurement; `--confirm-local-resources` is not a resource guarantee.
- Use `uaf doctor --json` for available RAM and warnings.

## Manual Windows acceptance checklist

- [ ] Clean install and `uaf --version` on Python 3.11+.
- [ ] Full test/verification script.
- [ ] Paths with spaces and non-ASCII characters.
- [ ] Offline smoke, built-in DAG, eight-case evaluation, and same-suite baseline.
- [ ] Gemini key in Credential Locker, no secret in config/log/output, no other provider key.
- [ ] One explicit live Gemini connectivity test recorded separately with current terms/quota.
- [ ] Real visible Chromium navigation/snapshot on a harmless page.
- [ ] Dedicated-profile manual login without agent access to passwords/cookies/storage.
- [ ] Browser type/click approval, process restart, unchanged-digest resume, and changed-page denial.
- [ ] Disposable Notepad R3 batch with exact executable/title and fail-safe available.
- [ ] Focus-change stop and human evidence reconciliation without duplicate input.
- [ ] Workspace read/write/delete approval and file-backup restore.
- [ ] Controlled Ctrl-C during a task and explicit resume.
- [ ] USB workspace disconnect/reconnect without DB relocation.
- [ ] Backup, verify, restore, and integrity check through the normal CLI.
- [ ] No unexpected outbound connection in default offline mode.
- [ ] Optional MCP stdio with the intended client.

Record OS build, Python/dependency versions, hardware/RAM, commands, and actual results before changing `windows_10_11_acceptance` from `planned`.
