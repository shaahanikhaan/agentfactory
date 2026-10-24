"use strict";

const START_CONFIRMATION = "START_FREE_FACTORY";
const token = new URLSearchParams(window.location.hash.slice(1)).get("token") || "";
const $ = (id) => document.getElementById(id);
const state = {
  status: null,
  busy: false,
  recognition: null,
  listening: false,
  preparingVoice: false,
  pendingStart: false,
  recognitionLocal: null,
};

function showMessage(text, tone = "") {
  const banner = $("message-banner");
  banner.textContent = text;
  banner.className = `banner ${tone}`.trim();
  banner.classList.toggle("hidden", !text);
}

function setPill(element, text, kind = "neutral") {
  element.textContent = text;
  element.className = `pill ${kind}`;
}

function setStep(name, stepState) {
  const item = document.querySelector(`[data-step="${name}"]`);
  if (!item) return;
  item.classList.remove("done", "active", "failed");
  if (stepState !== "neutral") item.classList.add(stepState);
}

function clearStepActivity() {
  document.querySelectorAll("#readiness-steps li").forEach((item) => {
    item.classList.remove("active", "failed");
  });
}

async function api(path, options = {}) {
  if (!token) throw new Error("Open the exact dashboard URL printed by the launcher, including its private #token fragment.");
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 240000);
  try {
    const response = await fetch(path, {
      method: options.method || "GET",
      headers: {
        "X-UAF-Token": token,
        ...(options.body ? { "Content-Type": "application/json" } : {}),
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
      credentials: "same-origin",
      cache: "no-store",
    });
    const payload = await response.json();
    if (!response.ok) {
      const error = new Error(payload.error?.message || `Request failed (${response.status}).`);
      error.code = payload.error?.code || "request_failed";
      error.details = payload.error?.details || {};
      throw error;
    }
    return payload;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("The local request timed out. Refresh status before retrying; no automatic retry was attempted.");
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

function setBusy(busy) {
  state.busy = busy;
  const remoteReadOnly = Boolean(state.status && !state.status.security.credential_write);
  $("setup-button").disabled = busy || remoteReadOnly;
  $("start-button").disabled = busy || remoteReadOnly || Boolean(state.status?.ready && state.status?.factory?.state === "succeeded");
  $("refresh-button").disabled = busy;
  $("voice-confirm-button").disabled = busy || remoteReadOnly;
  $("api-key").disabled = busy || remoteReadOnly;
  $("reveal-key").disabled = busy || remoteReadOnly;
  document.querySelectorAll("button[data-experience-approval]").forEach((button) => {
    button.disabled = busy || remoteReadOnly;
  });
}

function renderDepartments(departments) {
  const container = $("departments");
  container.replaceChildren();
  const showAll = $("show-capabilities").checked;
  const visible = showAll ? departments : departments.filter((department) => department.last_execution);
  if (!visible.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No real department execution recorded yet. Unused capabilities are hidden.";
    container.append(empty);
    return;
  }
  visible.forEach((department) => {
    const card = document.createElement("article");
    card.className = "department";
    const top = document.createElement("div");
    top.className = "department-top";
    const title = document.createElement("h4");
    title.textContent = department.name;
    const pill = document.createElement("span");
    setPill(pill, department.state, department.state);
    top.append(title, pill);
    const reason = document.createElement("p");
    reason.textContent = department.reason;
    const scope = document.createElement("p");
    scope.textContent = department.scope;
    const owner = document.createElement("small");
    owner.textContent = department.id === "desktop-voice" ? "Desktop adapter remains opt-in" : `Owner: ${department.owner}`;
    const execution = document.createElement("small");
    execution.className = "execution-evidence";
    execution.textContent = department.last_execution ? `Startup evidence: ${department.last_execution.step_id} (${department.last_execution.state})` : "Not executed by company startup";
    card.append(top, reason, scope, owner, execution);
    container.append(card);
  });
}

function renderRun(run) {
  const details = $("run-details");
  const timeline = $("run-timeline");
  details.replaceChildren();
  timeline.replaceChildren();
  if (!run) {
    setPill($("run-state"), "No run", "neutral");
    const row = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = "Status";
    const value = document.createElement("dd");
    value.textContent = "Start the factory to create a real run.";
    row.append(term, value);
    details.append(row);
    return;
  }
  setPill($("run-state"), run.state || "unknown", run.state || "neutral");
  const rows = [
    ["Blueprint", run.blueprint_id],
    ["Run ID", run.run_id],
    ["Progress", `${run.result?.completed_steps || 0}/${run.result?.total_steps || 0} steps`],
    ["Real steps", (run.result?.step_ids || []).join(" → ") || "No completed steps"],
    ["Run error", run.error ? JSON.stringify(run.error) : "None"],
  ];
  if (run.brief) rows.push(["Startup brief", run.brief]);
  Object.entries(run.result?.metrics || {}).forEach(([key, value]) => rows.push([key.replaceAll("_", " "), String(value)]));
  rows.forEach(([label, rawValue]) => {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = label;
    const value = document.createElement("dd");
    value.textContent = rawValue ?? "—";
    row.append(term, value);
    details.append(row);
  });
  (run.result?.timeline || []).forEach((step, index) => {
    const item = document.createElement("div");
    item.className = "timeline-item";
    const order = document.createElement("span");
    order.className = "timeline-order";
    order.textContent = String(index + 1);
    const name = document.createElement("strong");
    name.textContent = step.step_id || "unknown-step";
    const status = document.createElement("span");
    setPill(status, step.state || "unknown", step.state || "neutral");
    const evidence = document.createElement("small");
    evidence.textContent = step.error_code ? `Error: ${step.error_code}` : `Task: ${step.task_id || "unknown"}`;
    item.append(order, name, status, evidence);
    timeline.append(item);
  });
}

function renderDoctor(doctor) {
  setPill($("doctor-state"), doctor.ok ? "Healthy" : "Action needed", doctor.ok ? "ready" : "blocked");
  const container = $("doctor-details");
  container.replaceChildren();
  const rows = [];
  Object.entries(doctor.checks || {}).forEach(([name, passed]) => {
    if (!passed) rows.push({ text: `${name.replaceAll("_", " ")}: failed`, warning: true });
  });
  if (doctor.memory?.available !== undefined) {
    rows.push({ text: `${doctor.memory.available} MB available memory${doctor.memory.low ? " (low capacity; keep concurrency at 1)" : ""}`, warning: Boolean(doctor.memory.low) });
  }
  Object.entries(doctor.optional_dependencies || {}).forEach(([name, available]) => {
    rows.push({ text: `${name}: ${available ? "available" : "optional / not installed"}`, warning: !available && name === "keyring" });
  });
  (doctor.warnings || []).forEach((warning) => rows.push({ text: warning, warning: true }));
  if (!rows.length) rows.push({ text: "SQLite, configuration, workspace and credential checks passed.", warning: false });
  rows.slice(0, 12).forEach((item) => {
    const row = document.createElement("div");
    row.className = `health-item${item.warning ? " warning" : ""}`;
    row.textContent = item.text;
    container.append(row);
  });
}

function renderExperience(experience) {
  const container = $("experience-list");
  container.replaceChildren();
  const counts = experience?.counts || {};
  const pending = counts.pending || 0;
  setPill(
    $("experience-state"),
    pending ? `${pending} pending review` : `${counts.approved || 0} approved for recall`,
    pending ? "optional" : "ready",
  );
  const items = experience?.items || [];
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    const hiddenRemoteRecords = !experience?.approval_write && (pending + (counts.approved || 0) + (counts.skipped_sensitive || 0)) > 0;
    empty.textContent = hiddenRemoteRecords
      ? "Experience content is hidden on this non-loopback dashboard. Counts are real; review details on the local Windows dashboard."
      : "No captured task outcomes yet. Run real work to create reviewable experience.";
    container.append(empty);
    return;
  }
  items.forEach((item) => {
    const card = document.createElement("article");
    card.className = "experience-item";
    const header = document.createElement("div");
    header.className = "experience-header";
    const title = document.createElement("strong");
    title.textContent = `Task outcome: ${item.outcome || "recorded"}`;
    const status = document.createElement("span");
    setPill(status, item.approval_status, item.approval_status === "approved" ? "ready" : "optional");
    header.append(title, status);
    const content = document.createElement("p");
    content.textContent = item.content;
    const provenance = document.createElement("small");
    provenance.textContent = `Task ${item.task_id || "unknown"} · revision ${item.revision} · ${item.sensitivity}`;
    card.append(header, content, provenance);
    if (item.approval_status === "pending") {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.experienceApproval = item.memory_id;
      button.textContent = experience.approval_write ? "Approve for future model recall" : "Approval available on loopback only";
      button.disabled = state.busy || !experience.approval_write;
      button.addEventListener("click", () => approveExperience(item.memory_id));
      card.append(button);
    }
    container.append(card);
  });
}

function render(status) {
  state.status = status;
  const setup = status.setup;
  const factory = status.factory;
  setPill($("ready-pill"), status.ready ? "Factory ready" : "Setup / recovery needed", status.ready ? "ready" : "optional");
  setPill($("setup-state"), setup.configured ? setup.model || "Configured" : "Not configured", setup.configured ? "ready" : "neutral");
  setStep("runtime", status.doctor.ok ? "done" : "failed");
  setStep("credential", setup.configured ? "done" : "neutral");
  setStep("live", setup.live_healthy ? "done" : setup.configured ? "failed" : "neutral");
  setStep("factory", factory?.state === "succeeded" ? "done" : factory ? "failed" : "neutral");
  renderDepartments(status.departments || []);
  renderRun(factory);
  renderDoctor(status.doctor);
  renderExperience(status.experience);
  const remoteReadOnly = !status.security.credential_write;
  $("setup-button").disabled = state.busy || remoteReadOnly;
  $("api-key").disabled = remoteReadOnly;
  if (remoteReadOnly) {
    $("setup-state").textContent = "Remote: key entry disabled";
    showMessage("This dashboard is not bound to loopback. Credential and experience-approval changes are disabled; return to the local Windows dashboard.", "");
  }
  setBusy(state.busy);
}

async function refresh(showErrors = true) {
  try {
    const status = await api("/api/status");
    render(status);
    return status;
  } catch (error) {
    if (showErrors) showMessage(error.message, "danger");
    throw error;
  }
}

async function approveExperience(memoryId) {
  if (state.busy) return;
  const approved = window.confirm(
    "Allow this real task outcome to be recalled as untrusted historical context in future model requests? No model output or credentials are approved.",
  );
  if (!approved) return;
  setBusy(true);
  try {
    const result = await api("/api/experience/approve", {
      method: "POST",
      body: { memory_id: memoryId, confirmation: "APPROVE_TASK_EXPERIENCE" },
    });
    render(result.status);
    showMessage("Experience approved for bounded future recall. It remains untrusted data, not an instruction.", "success");
  } catch (error) {
    showMessage(error.message, "danger");
  } finally {
    setBusy(false);
  }
}

async function setupAndStart(event) {
  event.preventDefault();
  if (state.busy) return;
  const input = $("api-key");
  const secret = input.value;
  if (!secret) {
    showMessage("Paste a Gemini API key first. Voice input is intentionally not accepted for credentials.", "danger");
    input.focus();
    return;
  }
  state.pendingStart = false;
  $("voice-confirmation").classList.add("hidden");
  setBusy(true);
  clearStepActivity();
  setStep("credential", "active");
  setStep("live", "neutral");
  setStep("factory", "neutral");
  showMessage("Setup is running: official discovery, OS-vault write, one live readiness test, then the durable startup DAG. Do not close this window.", "");
  try {
    const result = await api("/api/setup", {
      method: "POST",
      body: { api_key: secret, confirmation: START_CONFIRMATION },
    });
    input.value = "";
    render(result.status);
    const factorySucceeded = result.factory.state === "succeeded";
    showMessage(factorySucceeded ? `Factory ready: ${result.setup.model} passed live readiness and the startup DAG succeeded.` : `${result.setup.model} passed live readiness, but factory startup needs recovery. Inspect the run details.`, factorySucceeded ? "success" : "danger");
  } catch (error) {
    try {
      const status = await refresh(false);
      if (status.setup.configured) input.value = "";
      if (!status.setup.configured) setStep("credential", "failed");
      else if (!status.setup.live_healthy) setStep("live", "failed");
      else setStep("factory", "failed");
    } catch { /* Preserve the actionable setup error. */ }
    showMessage(`${error.message} Refresh status before retrying; no blind retry was attempted.`, "danger");
  } finally {
    setBusy(false);
  }
}

async function startFactory() {
  if (state.busy) return;
  if (state.status && !state.status.security.credential_write) {
    showMessage("Factory start is disabled on this non-loopback dashboard. Return to the local Windows dashboard.", "danger");
    return;
  }
  if (!state.status?.setup?.configured) {
    showMessage("Enter an API key in Automatic setup first. The factory will not simulate model readiness.", "danger");
    $("api-key").focus();
    return;
  }
  if (state.status.ready && state.status.factory?.state === "succeeded") {
    showMessage("Factory is already ready. Refresh for current evidence; no duplicate DAG or extra live request was sent.", "success");
    return;
  }
  setBusy(true);
  clearStepActivity();
  setStep("live", "active");
  setStep("factory", "neutral");
  showMessage("Checking bounded live readiness before replaying the idempotent startup DAG…", "");
  try {
    const result = await api("/api/start", {
      method: "POST",
      body: { confirmation: START_CONFIRMATION },
    });
    render(result.status);
    state.pendingStart = false;
    $("voice-confirmation").classList.add("hidden");
    showMessage(result.factory.state === "succeeded" ? "Factory startup DAG succeeded with durable evidence." : "Factory run needs recovery; inspect the run details.", result.factory.state === "succeeded" ? "success" : "danger");
  } catch (error) {
    setStep("live", "failed");
    showMessage(`${error.message} No automatic retry was attempted.`, "danger");
    try { await refresh(false); } catch { /* Keep the original error visible. */ }
  } finally {
    setBusy(false);
  }
}

function requestStartConfirmation(source) {
  if (state.status && !state.status.security.credential_write) {
    showMessage("Factory start is disabled on this non-loopback dashboard. Return to the local Windows dashboard.", "danger");
    return;
  }
  if (!state.status?.setup?.configured) {
    showMessage("API-key setup is required before a start command. For credential safety, type or paste the key — never speak it.", "danger");
    $("api-key").focus();
    return;
  }
  state.pendingStart = true;
  $("voice-confirmation").classList.remove("hidden");
  const prefix = source === "voice" ? "Voice command recognized. " : "";
  showMessage(`${prefix}Say “confirm start factory” or press Confirm factory start. This permits one bounded live test and the fixed startup DAG with up to two additional model calls.`, "");
}

function handleCommand(rawCommand, source = "text") {
  const raw = String(rawCommand).trim();
  const compact = raw.replace(/\s+/g, "");
  const credentialLike = (
    /AIza[A-Za-z0-9_-]{20,}/i.test(compact)
    || /^[A-Za-z0-9_-]{24,}$/.test(compact)
    || /(?:api[_ -]?key|password|secret|token)\s*[:=]\s*\S+/i.test(raw)
  );
  if (credentialLike) {
    $("transcript").textContent = "Possible credential-like input discarded.";
    showMessage("Credential-like input was not echoed or submitted. Use the protected API-key field for setup; never speak credentials.", "danger");
    return;
  }
  if (raw.length > 200) {
    $("transcript").textContent = "Overlong command discarded.";
    showMessage("Commands are limited to 200 characters.", "danger");
    return;
  }
  const command = raw.toLowerCase().replace(/[.!?]+$/g, "");
  $("transcript").textContent = `${source === "voice" ? "Heard" : "Command"}: ${raw}`;
  if (!command) return;
  if (["confirm start factory", "confirm factory start", "confirm start", "confirm karo"].includes(command)) {
    if (state.pendingStart) startFactory();
    else showMessage("There is no pending start command. Say or type “start factory” first.", "");
    return;
  }
  if (["start factory", "start departments", "factory start", "start karo", "factory shuru karo", "shuru karo"].includes(command)) {
    requestStartConfirmation(source);
    return;
  }
  if (["status", "refresh", "factory status", "status batao", "haal batao"].includes(command)) {
    state.pendingStart = false;
    $("voice-confirmation").classList.add("hidden");
    refresh().then((status) => showMessage(status.ready ? "Factory is ready. Status refreshed." : "Status refreshed. Setup or recovery is still needed.", status.ready ? "success" : "")).catch(() => {});
    return;
  }
  if (["open setup", "setup", "api key"].includes(command)) {
    showMessage("Type or paste the API key in Automatic setup. Voice recognition deliberately does not capture credentials.", "");
    $("api-key").focus();
    return;
  }
  if (["cancel", "cancel start", "stop"].includes(command)) {
    state.pendingStart = false;
    $("voice-confirmation").classList.add("hidden");
    showMessage("Pending start cancelled. No provider request or factory run was started.", "");
    return;
  }
  showMessage("Supported commands: status; start factory; confirm start factory; open setup; cancel.", "");
}

function stopListening() {
  if (state.recognition && state.listening) state.recognition.stop();
}

async function prepareOnDeviceRecognition(Recognition, language) {
  if (typeof Recognition.available !== "function") return;
  const options = { langs: [language], processLocally: true };
  const availability = await Recognition.available(options);
  if (availability === "available") return;
  if (["downloadable", "downloading"].includes(availability) && typeof Recognition.install === "function") {
    $("transcript").textContent = `Preparing the on-device ${language} speech model. No microphone capture has started…`;
    const installed = await Recognition.install(options);
    if (installed === false) throw new Error("the on-device language model did not install");
    return;
  }
  throw new Error(`on-device recognition for ${language} is ${availability || "unavailable"}`);
}

async function startListening() {
  if (state.preparingVoice) return;
  if (state.listening) {
    stopListening();
    return;
  }
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    showMessage("This browser does not expose speech recognition. Use the text command box; no fake voice capability is enabled.", "danger");
    return;
  }
  const wantsLocal = $("local-speech").checked;
  const language = $("voice-language").value;
  state.preparingVoice = true;
  state.recognitionLocal = false;
  $("voice-button").disabled = true;
  $("voice-button-label").textContent = wantsLocal ? "Checking on-device speech…" : "Preparing microphone…";
  try {
    if (wantsLocal) await prepareOnDeviceRecognition(Recognition, language);
    const recognition = new Recognition();
    state.recognition = recognition;
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    recognition.lang = language;
    if (wantsLocal) {
      if (!("processLocally" in recognition)) {
        throw new Error("this browser does not expose on-device recognition controls");
      }
      recognition.processLocally = true;
      state.recognitionLocal = true;
    }
    recognition.onstart = () => {
      state.listening = true;
      $("voice-button").setAttribute("aria-pressed", "true");
      $("voice-button-label").textContent = "Listening — tap to stop";
      $("transcript").textContent = state.recognitionLocal ? "Listening with on-device recognition requested…" : "Listening with browser speech recognition; audio may be processed by the browser vendor…";
    };
    recognition.onresult = (event) => {
      let interim = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const transcript = event.results[index][0].transcript;
        if (event.results[index].isFinal) handleCommand(transcript, "voice");
        else interim += transcript;
      }
      if (interim) $("transcript").textContent = `Listening: ${interim}`;
    };
    recognition.onerror = (event) => {
      const localAdvice = state.recognitionLocal ? " The selected on-device language model may be unavailable; no remote fallback was attempted." : "";
      state.listening = false;
      $("voice-button").setAttribute("aria-pressed", "false");
      $("voice-button-label").textContent = "Push to talk";
      showMessage(`Voice recognition stopped: ${event.error}.${localAdvice} Use text commands or adjust microphone/browser permission.`, "danger");
    };
    recognition.onend = () => {
      state.listening = false;
      $("voice-button").setAttribute("aria-pressed", "false");
      $("voice-button-label").textContent = "Push to talk";
    };
    state.listening = true; // Includes the permission wait, so a second click can cancel it.
    $("voice-button").setAttribute("aria-pressed", "true");
    $("voice-button-label").textContent = "Waiting for microphone permission — tap to cancel";
    recognition.start();
  } catch (error) {
    state.listening = false;
    state.recognition = null;
    $("voice-button").setAttribute("aria-pressed", "false");
    $("voice-button-label").textContent = "Push to talk";
    const localAdvice = wantsLocal ? " No microphone capture or remote fallback was started. Uncheck the on-device preference only if you consent to browser/vendor audio processing." : " Use text commands or adjust microphone/browser permission.";
    showMessage(`Voice could not start: ${error.message}.${localAdvice}`, "danger");
  } finally {
    state.preparingVoice = false;
    $("voice-button").disabled = false;
  }
}

$("show-capabilities").addEventListener("change", () => {
  if (state.status) renderDepartments(state.status.departments || []);
});
$("setup-form").addEventListener("submit", setupAndStart);
$("start-button").addEventListener("click", startFactory);
$("refresh-button").addEventListener("click", () => refresh().then(() => showMessage("Status refreshed.", "")).catch(() => {}));
$("command-form").addEventListener("submit", (event) => {
  event.preventDefault();
  handleCommand($("command-input").value, "text");
  $("command-input").value = "";
});
$("voice-button").addEventListener("click", startListening);
$("voice-confirm-button").addEventListener("click", startFactory);
$("reveal-key").addEventListener("click", () => {
  const input = $("api-key");
  const reveal = input.type === "password";
  input.type = reveal ? "text" : "password";
  $("reveal-key").textContent = reveal ? "Hide" : "Show";
  $("reveal-key").setAttribute("aria-pressed", String(reveal));
});
$("voice-language").addEventListener("change", stopListening);
window.addEventListener("pagehide", () => {
  stopListening();
  $("api-key").value = "";
});

if (!token) {
  $("fatal-banner").textContent = "Private dashboard capability missing. Open the exact URL printed by the local launcher, including #token=…. The token is never accepted from a query string or browser storage.";
  $("fatal-banner").classList.remove("hidden");
}
setBusy(false);
refresh().catch(() => {});
