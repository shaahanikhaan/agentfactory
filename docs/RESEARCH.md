# Research register and design decisions

Access date for this register: **2026-10-24**. Sources were used to make architecture and licensing decisions, not to copy a stack indiscriminately. Vendor documentation describes vendor claims and current behavior; it is not independent proof of quality or permanent free availability. For exact external Git revisions, license/provenance rejection decisions, and the implemented experience/repository-map slices, see [External repository research](EXTERNAL_RESEARCH.md).

## Primary documentation reviewed

| Source | Evidence used | UAF decision |
|---|---|---|
| [SQLite WAL](https://www.sqlite.org/wal.html) | WAL supports readers/one writer on a single host and has shared-memory/network-filesystem constraints | Local single-writer DB, bounded concurrency, no network-share multi-writer claim |
| [SQLite Backup API](https://www.sqlite.org/backup.html) | Online backup produces a consistent snapshot while the source is active | `Connection.backup()` for snapshots and restore, plus hash/integrity/lifeline checks |
| [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | Distinguishes thread checkpoints from cross-thread long-term memory | Separate task checkpoints, durable memory, and audit events |
| [Pydantic AI durable execution](https://pydantic.dev/docs/ai/capabilities/durable_execution/overview/) | Durable execution journals/replays operations; snapshots alone are not sufficient | Persist role results and side-effect records independently; no “checkpoint equals exactly-once” claim |
| [Microsoft Agent Framework overview](https://learn.microsoft.com/en-us/agent-framework/overview/) and [workflows](https://learn.microsoft.com/en-us/agent-framework/workflows/) | Explicit graph workflows and sequential/concurrent/handoff/group/manager patterns; deterministic workflows remain appropriate | Immutable declarative DAGs outside the model; serial first; no framework dependency in core |
| [Stonic desktop](https://stonicai.com/features/desktop-automation/) and [multi-agent](https://stonicai.com/features/multi-agent/) | Vendor describes Windows voice/desktop automation, local agents, MCP delegation, and visual Agent Town | Product inspiration only; no copied code/assets, visual parity, or independent superiority claim |
| [OpenJarvis architecture](https://open-jarvis.github.io/OpenJarvis/architecture/overview/) and [agents](https://open-jarvis.github.io/OpenJarvis/architecture/agents/) | Composable reasoning loops, tools/memory, traces, evaluation, and opt-in learning/non-regression concepts | Adopt bounded composable loops and regression evidence; reject automatic self-optimization/promotion |
| [OpenHands SDK architecture](https://docs.openhands.dev/sdk/arch/overview) | Typed reasoning/action loops, event-sourced state, workspace boundaries, and evaluation discipline | Separate typed tool decisions/observations and durable task evidence; no host-is-sandbox claim |
| [Inspect AI tutorial](https://inspect.aisi.org.uk/tutorial.html) and [scorers](https://inspect.aisi.org.uk/scorers.html) | Evaluations combine datasets, solvers/agents, deterministic/model scorers, metrics, epochs, and logs | Real task cases, deterministic scorers, per-case evidence, split metrics, and baseline comparisons |
| [OpenAI Agents SDK agents](https://openai.github.io/openai-agents-python/agents/) and [guardrails](https://openai.github.io/openai-agents-python/guardrails/) | Bounded agent loops and input/output/tool guardrails; side-effect approval must remain resumable | Typed ReAct decisions plus code-enforced policy; approval pauses before effects and reuses decision checkpoints |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) and SDK run/tool docs | Official Python SDK, stdio local server boundary, typed tools, Streamable HTTP for network deployment | Optional MCP stdio only; three narrow tools; no HTTP listener or bearer-auth confusion |
| [Gemini models API](https://ai.google.dev/api/models) and [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) | `models.list` returns available models/metadata; limits vary by model/tier and apply per project | Fixed header-authenticated discovery, bounded metadata, no inference that availability equals free eligibility; dated evidence and project-scoped observations |
| [Gemini thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking), [troubleshooting](https://ai.google.dev/gemini-api/docs/troubleshooting), and [Interactions overview](https://ai.google.dev/gemini-api/docs/interactions-overview) | Thinking raises latency; output ceilings include thought tokens; low thinking reduces latency; metadata discovery does not prove inference enablement; generateContent remains supported though Interactions is recommended for new projects | Low-thinking 256-token 3.8 connectivity probe, unchanged normal agent reasoning, bounded retries/cooldowns, no unnecessary API migration during transient failures |
| [Current Gemini models](https://ai.google.dev/gemini-api/docs/models), [3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite), [3.1 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite), and [pricing](https://ai.google.dev/gemini-api/docs/pricing) | Stable reviewed model IDs; current standard free tiers for 3.8/3.5 Lite/3.1 Lite; 2.5 access is restricted for new projects; Gemini 4 Argon has no free tier; free-tier content may be used to improve products | Reviewed 3.8 → 3.5 Lite → 3.1 Lite dashboard allowlist only; no paid/new-model auto-upgrade, explicit attestation/live check, fixed no-workspace-data readiness prompt |
| [MDN Web Speech usage](https://developer.mozilla.org/en-US/docs/Web/API/Web_Speech_API/Using_the_Web_Speech_API), [Edge SpeechRecognition](https://learn.microsoft.com/en-us/microsoft-edge/web-platform/speech-recognition-api), and [Edge speech policy/privacy](https://learn.microsoft.com/en-us/legal/microsoft-edge/privacy) | Browser recognition may use a vendor service; `processLocally`, availability/install, and language models require feature detection; Edge local recognition is limited to specific Insider versions/flags | Optional one-utterance voice, local-first preflight, disclosed browser-managed language download, no silent remote fallback, text fallback, no voice approval authority |
| [OWASP CSRF prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html) and [GitHub DNS-rebinding guidance](https://github.blog/security/application-security/dns-rebinding-attacks-explained-the-lookup-is-coming-from-inside-the-house/) | Loopback alone is not an authorization boundary; browser-origin and Host validation are needed in addition to capabilities | Exact Host allowlists, random per-launch header capability, Origin/Fetch-Site checks, bounded JSON, no CORS relaxation, literal-loopback credential writes |
| [Playwright persistent contexts](https://playwright.dev/python/docs/api/class-browsertype), [context routing](https://playwright.dev/python/docs/api/class-browsercontext), and [authentication](https://playwright.dev/python/docs/auth) | Dedicated persistent profiles retain sensitive session state; context routing does not intercept service-worker requests, so blocking them is recommended | Visible dedicated UAF profile, `service_workers="block"`, no cookie/storage export, domain/route checks, no personal-profile import |
| [PyAutoGUI documentation](https://pyautogui.readthedocs.io/en/latest/index.html) and [quickstart](https://pyautogui.readthedocs.io/en/latest/quickstart.html) | Real mouse/keyboard automation with a default corner fail-safe and configurable pause; host GUI control is not an OS sandbox | Fail-safe forced on, bounded pause/actions/text, exact window/focus binding, R3 approval, no risk-free/background-control claim |
| [keyring documentation](https://keyring.readthedocs.io/) | Standard password APIs support Windows Credential Locker, macOS Keychain, Secret Service and KWallet; backend viability varies | Approved OS-backend allowlist, hidden prompt, non-secret status, no plaintext fallback |
| [Groq rate limits](https://console.groq.com/docs/rate-limits) | Organization-level, model-dependent multidimensional limits; 429 may include `retry-after` | Persistent scoped cooldown and `Retry-After` parsing |
| [OpenRouter limits](https://openrouter.ai/docs/api_reference/limits) and [API overview](https://openrouter.ai/docs/api_reference/overview) | OpenAI-like API and credit/rate-limit behavior; additional keys do not create governed capacity | Fixed adapter, explicit `:free` guard, no key/account rotation |
| [Python entry points](https://packaging.python.org/en/latest/specifications/entry-points/) | Standard discovery mechanism, not an isolation mechanism | Metadata-only discovery; imports treated as code execution |
| [OWASP GenAI Top 10](https://genai.owasp.org/initiatives/top-10-for-llm-and-genai/) | Prompt injection, sensitive disclosure, excessive agency, supply chain, unbounded consumption, etc. | Threat checklist mapped to policy, budgets, provenance, and release gates |
| [OpenClaw prompt-injection guidance](https://docs.openclaw.ai/gateway/security/prompt-injection) | Fetched pages/files/email remain hostile input; model resistance is not a security boundary | Untrusted-content wrappers plus code-enforced tool policy and approvals |

A Microsoft Learn request also returned an authorization warning alongside accessible overview content. No claim is made that restricted Microsoft sections were reviewed.

## Open-source landscape and licenses

Canonical repository metadata/documentation was checked for architecture references. Licenses apply to the referenced repositories, not automatically to every model, dataset, or asset.

| Project | Reported license | Relevance | Adopted? |
|---|---|---|---|
| LangGraph | MIT | Checkpoint/store separation and graph thinking | Concepts only; no dependency |
| Pydantic AI | MIT | Typed agents and durable execution concepts | Concepts only; no dependency |
| Microsoft Agent Framework | MIT | Workflow/agent boundary and successor direction | Concepts only |
| OpenHands | MIT | Agent/tool workspace and evaluation discipline | Concepts only |
| OpenCoworkAI/open-cowork and AIDotNet/OpenCowork | MIT (reviewed repositories) | Local GUI/computer-use, skills/MCP, approval and workflow references | Concepts only; similarly named projects are not conflated and no parity claim |
| Google ADK | Apache-2.0 | Typed agent/tool ecosystem | Not combined into core |
| UI-TARS | Apache-2.0 | Computer-use/vision reference | Planned optional domain only |
| OpenJarvis | Apache-2.0 | JARVIS-like orchestration reference | Concepts only; no autonomy claim |
| Open Duet | Apache-2.0 | Multi-agent interaction reference | Concepts only |
| Official MCP Python SDK | MIT | Interoperability boundary | Optional `mcp>=2.3,<3` dependency |
| Playwright | Apache-2.0 | Reviewed browser automation API | Optional `playwright>=1.64,<2`; no source vendored |
| keyring | MIT | OS credential-vault abstraction | Optional `keyring>=25.7,<26`; approved backends only |
| PyAutoGUI | BSD-3-Clause (repository) | Mouse/keyboard adapter | Optional `pyautogui>=0.9.54,<0.10`; its current PyPI dependency `mouseinfo 0.1.3` reports GPLv3+, so distribution/copyleft review is required |
| AutoGen | Repository archived | Historical multi-agent patterns | Not adopted for new core |

`alfaazkhanofficial/Stonic-AI` metadata did not provide a reliable detected license and its README licensing language was inconsistent during review. **No Stonic code or assets were copied.** “OpenAI Dots” and JARVIS-like descriptions were treated as product inspiration, not evidence of an implementable open license or reproducible architecture.

Optional packages are installed from their own distributions, not vendored or relicensed by UAF. Current PyPI metadata reports `mouseinfo 0.1.3` as GPLv3+, and some other transitive package metadata/classifiers are inconsistent. `pip-audit` checks vulnerabilities, not license compliance. Review the complete installed dependency/NOTICE/license set before accepting the desktop extra or creating a bundled distribution.

## Why not combine all frameworks?

Combining several large agent frameworks would multiply dependencies, background services, credential paths, resource use, and failure modes without proving reliability. UAF instead keeps a standard-library deterministic kernel and borrows narrow, verifiable ideas:

1. Durable journal/checkpoints rather than chat history as execution state.
2. Deterministic workflows where a model is unnecessary.
3. Typed tools and contracts rather than arbitrary code generation.
4. Cross-task memory separate from task replay.
5. Optional protocol interoperability rather than mandatory framework lock-in.
6. Explicit no-spend and offline behavior rather than hidden cloud fallback.

## Research-to-test traceability

| Risk/question | Implemented check |
|---|---|
| Can a crash cause blind effect retry? | Payload ledger, interrupted-reservation regression, `uncertain_side_effect` |
| Can stale free-tier assumptions cause a call? | Dated official-source eligibility tests and no default cloud models |
| Can a fetched/page/model instruction grant tools? | Untrusted wrapper + task allowlist/role/policy tests |
| Can a model turn a tool request into an unauthorized effect? | Typed ReAct decision tests, disallowed-tool denial, schema/turn/tool budgets, separate observation checkpoints |
| Can approval resume change the requested payload? | ReAct R3 decision-checkpoint reuse, exact payload approval, and browser digest/label revalidation after service restart |
| Can onboarding leak a key or infer free access from discovery? | Approved vault backend tests, config/DB secret absence, rollback, official discovery and explicit free-attestation tests |
| Can a hostile website call the local dashboard or write a key remotely? | Exact Host/capability/Origin/Fetch-Site/JSON tests, no CORS, literal-loopback credential tests, non-loopback write denial |
| Can dashboard readiness hide a live-provider failure or duplicate startup? | Live-failure status tests, 24-hour health bound, selected-model probe, fixed idempotency key and three-step DAG evidence with two bounded model calls and private-filename prompt exclusion |
| Can voice silently submit/echo a key, use remote audio, or approve risky work? | Credential-like command discard without echo, no credential path/storage, local availability/install preflight, explicit vendor-processing choice, separate start confirmation, unchanged R2/R3 services |
| Can browser/desktop state change between approval and effect? | Browser content-change denial and desktop exact process/title/focus/partial-effect tests |
| Can a user resume an unresolved external effect? | Uncertain/reserved resume gate plus executed-result replay without a second desktop input |
| Can a custom graph hide cycles or downstream data dependencies? | Blueprint cycle/unknown-reference/static-tool validation and immutable version tests |
| Can interrupted DAG execution duplicate tasks or materialize different input? | Atomic graph creation, task identity/checkpoint recovery, materialization digest tamper test |
| Can an easier dataset create a misleading improvement claim? | Same-suite-digest baseline enforcement, per-case regressions, negative safety cases |
| Can workspace paths escape? | Absolute/traversal/sensitive/symlink/disconnect tests |
| Can plugins silently import or change after review? | Disabled default, no auto-import, manifest checksum/tamper tests |
| Can a candidate weaken its own gates? | Protected paths and human-only promotion tests |
| Can memory corrections erase provenance? | Revision, export, consolidation, and privacy-deletion tests |
| Can backups be trusted without checks? | Hash, corruption, integrity, restore, and lifeline tests |

## Unverified and future research

- Current live free-tier terms and real provider latency/quality on the operator's account.
- Windows 10/11 dashboard/one-click launcher, physical 4 GB hardware, real Chromium/microphone/mouse/keyboard, and controlled USB removal; only partial user-reported Windows onboarding/vault evidence exists.
- Real authenticated browser/account acceptance, browser speech recognition/audio-path verification, dynamic-chat reliability, and destination-specific delivery verification.
- OS-sandboxed third-party Python plugins.
- Production-grade SSRF egress proxy with address pinning.
- Authenticated research fetching, PDF/OCR, source-specific adapters, native desktop vision/voice, and Unicode desktop input.
- Formal multi-model evaluation of review quality and calibrated task success.
- Signed releases/provenance and a human-approved rollout pipeline.

These remain explicit work items rather than implied features.
