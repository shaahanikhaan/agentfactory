# UAF ko Windows laptop par download aur install karein

Yeh guide Windows 10/11, 64-bit Python 3.11+, CPU-only aur 4 GB RAM ke liye hai. Docker, Redis, Postgres, GPU ya paid API zaroori nahi. Source ZIP se install ke liye Git bhi zaroori nahi.

> **Evidence boundary:** is source par Linux automated tests aur clean-wheel acceptance pass hain. Real Windows Credential Locker, Chromium login aur physical mouse/keyboard acceptance aapke laptop par neeche diye steps se alag verify karni hai. UAF 0.1.0 alpha hai.

## 1. Source ZIP download aur extract karein

1. Provided `UAF-0.1.0-alpha-windows-source.zip` ya reviewed GitHub branch ZIP download karein.
2. ZIP par right-click karke **Extract All** select karein aur ise `Documents` mein extract karein.
3. Provided ZIP mein `UAF-0.1.0-alpha` folder kholein. GitHub branch ZIP ka folder naam `agentfactory-arena-9a06efb0-agentfactory` ho sakta hai. Woh directory choose karein jahan `pyproject.toml` aur `src` majood hon.
4. Us folder mein address bar mein `powershell` type karke Enter dabayein, ya PowerShell mein us path par `cd` karein.

Check:

```powershell
Test-Path .\pyproject.toml
```

Output `True` hona chahiye. ZIP ke saath `.venv`, database, logs, browser profile ya API key include nahi hoti.

## 2. Python install aur check karein

Agar Python 3.11+ installed nahi hai to official page se 64-bit Python install karein:

`https://www.python.org/downloads/`

Installer mein Python launcher/PATH option enable karein. Phir **new PowerShell** window mein:

```powershell
py -3.11 --version
```

Agar sirf newer supported version hai, masalan 3.12, to neeche tamam `py -3.11` commands ki jagah `py -3.12` use karein.

## 3. Source folder mein PowerShell kholein

Misal, agar ZIP `Documents` mein is naam se extract hua hai:

```powershell
# Provided ZIP:
cd "$env:USERPROFILE\Documents\UAF-0.1.0-alpha"
# GitHub branch ZIP ho to usually yeh path use karein:
# cd "$env:USERPROFILE\Documents\agentfactory-arena-9a06efb0-agentfactory"
Test-Path .\pyproject.toml
```

Commands ko administrator PowerShell mein chalane ki zaroorat nahi. UAC/elevated apps ko bypass karne ki koshish na karein.

## 4. Isolated virtual environment banayein

```powershell
py -3.11 -m venv .venv
$python = Join-Path $PWD ".venv\Scripts\python.exe"
& $python -m pip install --upgrade pip setuptools
```

Hum `python.exe` ko directly call kar rahe hain, is liye PowerShell execution policy change karni zaroori nahi.

## 5. UAF aur browser/desktop extras install karein

One-key onboarding + visible browser + Windows mouse/keyboard ke liye:

```powershell
& $python -m pip install -e '.[computer-use]'
$uaf = Join-Path $PWD ".venv\Scripts\uaf.exe"
& $uaf --version
```

Expected version: `uaf 0.1.0`.

**Optional desktop license note:** PyAutoGUI ke dependency tree mein current PyPI metadata `mouseinfo` ko GPLv3+ batata hai. Redistribution/bundling se pehle complete license/NOTICE review zaroori hai. Agar desktop extra nahi chahiye to sirf onboarding + browser install karein:

```powershell
& $python -m pip install -e '.[setup,browser]'
```

Core offline install ke liye optional packages ke baghair `& $python -m pip install -e .` bhi supported hai.

## 6. UAF ka dedicated Chromium install karein

Browser use karna ho to yeh separate download chalayein:

```powershell
& $python -m playwright install chromium
```

Yeh aapke personal Chrome/Edge profile ko use nahi karta; UAF ka dedicated visible profile banta hai.

## 7. Local data aur workspace initialize karein

```powershell
$workspace = Join-Path $env:USERPROFILE "Documents\UAFWorkspace"
& $uaf init --workspace $workspace --json
& $uaf doctor --json
& $uaf capabilities --json
```

Config, SQLite DB, backups aur browser profile default taur par stable local `%LOCALAPPDATA%\UltimateAgentFactory` mein rehte hain. Active DB/profile ko disconnect hone wale USB drive par na rakhein.

## 8. API key ke baghair offline test karein

```powershell
$task = & $uaf task add "Windows offline acceptance" --kind smoke --json | ConvertFrom-Json
& $uaf task run $task.task_id --json
& $uaf eval run --json
```

Offline task `succeeded` aur evaluation mein `passed_cases: 8`, `total_cases: 8`, `total_model_calls: 0` expected hain. Yeh real deterministic local work hai, offline LLM ya fake cloud response nahi.

## 9. Sirf ek Gemini API key add karein

Gemini key official Google account flow mein khud create/authorize karein. Current pricing, quota aur terms review karein; UAF billing enable nahi karta.

```powershell
& $uaf setup --workspace $workspace
```

Wizard mein:

1. API key hidden prompt par paste karein; typing screen par nazar nahi aayegi.
2. Official model discovery ke liye poocha gaya `ONLINE` confirmation dein.
3. Available model select karein.
4. Official current pricing/terms check karke alag `FREE` confirmation dein. Model list mein aana free eligibility ka proof nahi.

Phir:

```powershell
& $uaf auth status --json
& $uaf provider list --json
& $uaf provider test gemini --json
```

`provider test` ke is form mein real generation nahi hoti. Ek deliberate real request ke liye hi:

```powershell
& $uaf provider test gemini --live --json
```

Groq, OpenRouter ya doosre AI provider keys configure karne ki zaroorat nahi. Key approved OS vault/Windows Credential Locker mein jati hai; config/SQLite mein raw key save nahi hoti.

## 10. Harmless browser test karein

Pehle public example page par test karein:

```powershell
& $uaf config set network_allowed true
& $uaf config set browser_enabled true
& $uaf config set browser_allowed_domains '["example.com"]'
& $uaf browser inspect https://example.com --wait-seconds 1 --json
```

Visible Chromium aur bounded page snapshot milna chahiye. Kisi chat/account service ke liye pehle required official domains review karke hi allow karein, phir:

```powershell
& $uaf browser login https://YOUR-ALLOWLISTED-SERVICE/ --wait-seconds 120 --json
```

Login/MFA khud karein. UAF password, cookies, local storage ya personal browser credential database read/export nahi karta. Message type karna aur send click karna alag approvals hain; send/publish/delete/purchase click R3 approval ke baghair execute nahi hota.

Exact click/type aur chat workflow ke liye `docs\COMPUTER_USE.md` dekhein.

## 11. Disposable Notepad desktop test karein

Real chat/app se pehle sirf Notepad par test karein:

```powershell
& $uaf config set desktop_enabled true
& $uaf config set desktop_allowed_applications '["notepad.exe"]'
Copy-Item .\examples\desktop\notepad-batch.json (Join-Path $workspace "notepad-batch.json")
```

Exactly one Notepad window kholein. Example title `Untitled - Notepad` hai; apne actual exact title ke mutabiq workspace wali JSON edit karein. Phir:

```powershell
$run = & $uaf desktop run notepad-batch.json --json | ConvertFrom-Json
& $uaf approval list --state pending --json
& $uaf approval approve $run.approval_id --actor local-human --reason "Reviewed disposable Notepad test"
& $uaf task resume $run.task_id --json
& $uaf task run $run.task_id --json
```

Sirf approved ASCII text type hona chahiye. Mouse ko upper-left corner par le jane se PyAutoGUI fail-safe available rehta hai. Focus change ya unclear/partial effect ho to blind retry na karein; `uaf effect list` aur `docs\COMPUTER_USE.md` ka reconciliation procedure follow karein.

## 12. Roz use ke liye

Har new PowerShell session mein extracted source folder par jayein aur paths dobara set karein:

```powershell
cd "$env:USERPROFILE\Documents\UAF-0.1.0-alpha"
# GitHub ZIP ho to upar wala GitHub extracted-folder path use karein.
$uaf = Join-Path $PWD ".venv\Scripts\uaf.exe"
$workspace = Join-Path $env:USERPROFILE "Documents\UAFWorkspace"
& $uaf doctor --json
```

Dobara install ya `init` karna normally zaroori nahi. Agar `UAF_HOME` custom set kiya tha to use bhi har new shell mein same value par set karein.

## Common problems

- **`py` not found:** Python launcher/PATH ke saath reinstall karein aur new PowerShell kholein.
- **`No eligible free/local model`:** `provider list` ka `reason` dekhein; model discovery ko free proof na samjhein. Cooldown/`Retry-After` bypass na karein.
- **Secure vault unavailable:** `setup`/`computer-use` same venv mein installed ho aur normal Windows Credential Locker available ho. Plaintext keyring reject hota hai.
- **Chromium not found:** step 6 same venv mein repeat karein.
- **Desktop Unicode/Urdu typing:** current desktop slice printable ASCII only hai; Urdu/Arabic Unicode desktop input abhi implemented nahi.
- **Direct Slack/WhatsApp/Teams connector:** included nahi; governed browser ya approved native app route use hota hai, delivery guarantee nahi.

Detailed English installation/troubleshooting `docs\WINDOWS.md` mein aur security limits `docs\SECURITY.md` mein hain.
