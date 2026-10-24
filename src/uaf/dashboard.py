"""Loopback-first dashboard and one-key governed factory startup.

The browser is only a client. API keys go directly to the local onboarding service;
voice recognition never becomes approval authority. The HTTP boundary requires a
random per-launch capability, validates Host/Origin, and never enables CORS.
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import threading
import webbrowser
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .agents import DEPARTMENT_CHARTERS
from .app import Application
from .credentials import validate_secret
from .errors import PolicyDenied, UAFError, UnavailableError, ValidationError
from .onboarding import DEFAULT_PRICING_SOURCE, GeminiOnboarding
from .util import bounded, canonical_json, redact_data, redact_text

logger = logging.getLogger(__name__)

MAX_REQUEST_BYTES = 16_384
MODEL_PRIORITY = (
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
)
START_CONFIRMATION = "START_FREE_FACTORY"
EXPERIENCE_CONFIRMATION = "APPROVE_TASK_EXPERIENCE"
STARTUP_BLUEPRINT = "company-startup@1"
STARTUP_IDEMPOTENCY = "dashboard-company-start-v2"
STARTUP_STEP_DEPARTMENTS = {
    "inventory": "reliability",
    "operations-brief": "orchestration",
    "acceptance-record": "quality",
}
ASSET_TYPES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


def _model_choice(discovered: list[dict[str, Any]]) -> str:
    available = {str(item.get("model", "")) for item in discovered}
    for model in MODEL_PRIORITY:
        if model in available:
            return model
    raise UnavailableError(
        "Official discovery did not return a currently supported stable Flash model. "
        "No model was selected and no credential was saved."
    )


def _run_summary(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if run is None:
        return None
    result = run.get("result") or {}
    metrics = result.get("metrics") or {}
    steps = result.get("steps") or []
    return {
        "run_id": run.get("run_id"),
        "blueprint_id": run.get("blueprint_id"),
        "state": run.get("state"),
        "result": {
            "completed_steps": metrics.get("succeeded_steps", 0),
            "total_steps": metrics.get("total_steps", 0),
            "step_ids": [step.get("step_id") for step in steps if step.get("state") == "succeeded"],
            "timeline": [
                {
                    "step_id": step.get("step_id"),
                    "task_id": step.get("task_id"),
                    "state": step.get("state"),
                    "error_code": (step.get("error") or {}).get("code"),
                }
                for step in steps
            ],
            "metrics": metrics,
        },
        "brief": result.get("output")[:2000] if isinstance(result.get("output"), str) else None,
        "error": run.get("error"),
    }


@dataclass(frozen=True, slots=True)
class DashboardSecurity:
    """Security posture is explicit and shown in the read-only status response."""

    credentials_write: bool
    exposed_non_loopback: bool


class DashboardService:
    """Use the same onboarding, provider, diagnostics, and factory services as the CLI."""

    def __init__(
        self,
        app: Application,
        *,
        allow_credentials: bool = True,
        onboarding: GeminiOnboarding | None = None,
    ) -> None:
        self.app = app
        self.security = DashboardSecurity(
            credentials_write=allow_credentials,
            exposed_non_loopback=not allow_credentials,
        )
        self.onboarding = onboarding or GeminiOnboarding(app.config, app.credentials)
        self._start_lock = threading.Lock()

    def _reload_settings(self) -> None:
        settings = self.app.config.load()
        self.app.settings = settings
        self.app.providers.settings = settings
        self.app.providers.sync_registry()
        self.app.browser.settings = settings
        self.app.desktop.settings = settings
        self.app.diagnostics.settings = settings

    def _selected_model(self) -> dict[str, Any] | None:
        models = [
            row
            for row in self.app.providers.list_models()
            if row.get("provider") == "gemini" and row.get("model")
        ]
        eligible = [row for row in models if row.get("eligible")]
        return (eligible or models or [None])[0]

    def _live_healthy(self, model: str | None) -> bool:
        if not model:
            return False
        row = self.app.db.one(
            "SELECT status, checked_at FROM provider_health "
            "WHERE provider = 'gemini' AND model = ?",
            (model,),
        )
        if not row or row["status"] != "healthy":
            return False
        try:
            checked = datetime.fromisoformat(str(row["checked_at"]).replace("Z", "+00:00"))
            age = (datetime.now(UTC) - checked).total_seconds()
        except (TypeError, ValueError):
            return False
        return 0 <= age <= 86_400

    def status(self) -> dict[str, Any]:
        self._reload_settings()
        doctor = self.app.diagnostics.doctor()
        selected = self._selected_model()
        model = str(selected["model"]) if selected else None
        credential_present = bool(self.app.credentials.get("gemini"))
        configured = bool(selected and credential_present)
        eligible = bool(selected and selected.get("eligible"))
        live_healthy = self._live_healthy(model) if configured else False
        latest = next(
            (
                run
                for run in self.app.factory.list(limit=100)
                if run.get("requester") == "dashboard"
                and run.get("idempotency_key") == STARTUP_IDEMPOTENCY
            ),
            None,
        )
        factory_succeeded = bool(latest and latest.get("state") == "succeeded")
        execution_by_department: dict[str, dict[str, Any]] = {}
        for step in ((latest or {}).get("result") or {}).get("steps") or []:
            department = STARTUP_STEP_DEPARTMENTS.get(str(step.get("step_id")))
            if department:
                execution_by_department[department] = {
                    "step_id": step.get("step_id"),
                    "state": step.get("state"),
                }
        if live_healthy or latest:
            execution_by_department["brain-pool"] = {
                "step_id": "live-readiness",
                "state": "succeeded" if live_healthy else "stale",
            }
        departments: list[dict[str, Any]] = []
        for department_id, charter in DEPARTMENT_CHARTERS.items():
            if department_id == "brain-pool":
                state = "ready" if configured and eligible and live_healthy else "blocked"
                reason = (
                    "Eligible model and successful live readiness probe."
                    if state == "ready"
                    else "API-key setup and a successful live readiness probe are required."
                )
            elif department_id == "desktop-voice":
                state = "optional"
                reason = "Desktop control stays disabled until enabled; voice is browser feature-detected."
            elif not doctor["ok"]:
                state = "blocked"
                reason = "Local doctor checks must pass first."
            else:
                state = "ready"
                reason = "Core local runtime checks passed."
            departments.append(
                {
                    "id": department_id,
                    "name": department_id.replace("-", " ").title(),
                    "state": state,
                    "reason": reason,
                    "owner": charter["owner"],
                    "scope": charter["scope"],
                    "last_execution": execution_by_department.get(department_id),
                }
            )
        return {
            "ready": bool(
                doctor["ok"] and configured and eligible and live_healthy and factory_succeeded
            ),
            "setup": {
                "configured": configured,
                "eligible": eligible,
                "model": model,
                "live_healthy": live_healthy,
                "eligible_reason": selected.get("reason") if selected else None,
                "free_tier_attested": bool(selected and selected.get("free_tier_status") == "free"),
            },
            "factory": _run_summary(latest),
            "experience": {
                "items": (
                    self.app.experience.list(limit=6) if self.security.credentials_write else []
                ),
                "counts": self.app.experience.counts(),
                "recall_policy": "human_approved_non_private_task_outcomes_only",
                "model_output_captured": False,
                "approval_write": self.security.credentials_write,
            },
            "departments": departments,
            "doctor": {
                "ok": doctor["ok"],
                "checks": doctor["checks"],
                "warnings": doctor["warnings"],
                "memory": doctor["memory"],
                "optional_dependencies": doctor["optional_dependencies"],
            },
            "voice": {
                "mode": "push_to_talk",
                "continuous": False,
                "recognition": "browser_feature_detection",
                "local_processing": "optional_when_supported",
                "permission_required": True,
                "approval_authority": False,
            },
            "security": {
                "credential_write": self.security.credentials_write,
                "non_loopback_exposure": self.security.exposed_non_loopback,
                "paid_fallback": False,
                "r2_r3_approval": "unchanged",
            },
            "attestation": {
                "source": selected.get("free_tier_source") if selected else None,
                "verified_at": selected.get("verified_at") if selected else None,
                "model_priority": MODEL_PRIORITY,
            },
        }

    def _live_and_start(self) -> tuple[dict[str, Any], dict[str, Any]]:
        self._reload_settings()
        selected = self._selected_model()
        if not selected or not selected.get("eligible"):
            raise ValidationError(
                "No eligible Gemini credential is configured. Complete API-key setup first."
            )
        model = str(selected["model"])
        # One bounded live diagnostic is explicit user consent for a free-tier request.
        # A failure is returned as failure; the factory is not marked started.
        live = self.app.providers.test("gemini", model=model, live=True)
        run = self.app.factory.start(
            STARTUP_BLUEPRINT,
            "Start reliability, orchestration, and quality with verified company evidence",
            inputs={"path": ".", "limit": 50},
            requester="dashboard",
            idempotency_key=STARTUP_IDEMPOTENCY,
        )
        if run["state"] in {"paused_offline", "interrupted", "retry_wait", "failed"}:
            # This fixed R0 DAG contains bounded local inventory, a privacy-safe
            # worker/reviewer brief, and deterministic acceptance. Explicit user retry may
            # resume it; approvals and uncertain side effects are deliberately excluded.
            run = self.app.factory.resume(str(run["run_id"]), actor="dashboard")
        return live, run

    def approve_experience(self, memory_id: str, confirmation: str) -> dict[str, Any]:
        if not self.security.credentials_write:
            raise PolicyDenied("Experience approval is available only on the loopback dashboard.")
        if confirmation != EXPERIENCE_CONFIRMATION:
            raise ValidationError("Explicit experience-approval confirmation is required.")
        bounded(memory_id, 200, label="memory_id")
        return self.app.experience.approve(memory_id, actor="local-user")

    def setup_and_start(self, secret: str, confirmation: str) -> dict[str, Any]:
        if not self.security.credentials_write:
            raise PolicyDenied(
                "Credential writes are disabled on non-loopback dashboard exposure. "
                "Use the local Windows dashboard."
            )
        if confirmation != START_CONFIRMATION:
            raise ValidationError(
                f"Explicit confirmation {START_CONFIRMATION} is required for setup and startup."
            )
        secret = validate_secret(secret)
        if not self._start_lock.acquire(blocking=False):
            raise UnavailableError("Another setup or factory start is already in progress.")
        try:
            discovered = self.onboarding.discover(secret, network_confirmed=True)
            model = _model_choice(discovered)
            setup = self.onboarding.complete(
                secret,
                discovered,
                model=model,
                source=DEFAULT_PRICING_SOURCE,
                verified_at=datetime.now(UTC).date().isoformat(),
                free_confirmed=True,
            )
            self._reload_settings()
            self.app.db.audit(
                "setup.gemini_one_key",
                actor="local-user",
                role="runtime",
                object_type="provider",
                object_id="gemini",
                decision="configured",
                metadata={
                    "model": model,
                    "credential_storage": "os_vault",
                    "official_discovery": True,
                    "automatic_model": True,
                },
            )
            live, run = self._live_and_start()
            setup["live_generation_tested"] = live["status"] == "completed"
            setup["setup_complete"] = setup["live_generation_tested"]
            return {
                "setup": setup,
                "live": live,
                "factory": _run_summary(run),
                "status": self.status(),
            }
        finally:
            self._start_lock.release()

    def start(self, confirmation: str) -> dict[str, Any]:
        if not self.security.credentials_write:
            raise PolicyDenied("Factory start is available only on the loopback dashboard.")
        if confirmation != START_CONFIRMATION:
            raise ValidationError(
                f"Explicit confirmation {START_CONFIRMATION} is required to start the factory."
            )
        if not self._start_lock.acquire(blocking=False):
            raise UnavailableError("Another setup or factory start is already in progress.")
        try:
            live, run = self._live_and_start()
            return {
                "live": live,
                "factory": _run_summary(run),
                "status": self.status(),
            }
        finally:
            self._start_lock.release()


class DashboardHTTPServer(HTTPServer):
    """Serial request handling keeps the 4 GB/CPU-only profile bounded."""

    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        service: DashboardService,
        *,
        token: str,
        allowed_hosts: set[str],
    ) -> None:
        self.service = service
        self.token = token
        self.allowed_hosts = {item.lower() for item in allowed_hosts}
        self.assets = Path(__file__).with_name("dashboard_assets")
        super().__init__(address, DashboardHandler)


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: Any) -> None:
        # Never log query strings, fragments, capabilities, or request bodies.
        return

    def _security_headers(self, content_type: str, length: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.close_connection = True
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Permissions-Policy", "microphone=(self)")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; media-src 'self' blob:; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )

    def _bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self._security_headers(content_type, len(body))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        self._bytes(
            status,
            canonical_json(payload).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _error(self, status: int, code: str, message: str, details: dict | None = None) -> None:
        self._json(status, {"error": {"code": code, "message": message, "details": details or {}}})

    def _host_allowed(self) -> bool:
        host = self.headers.get("Host", "").strip().lower()
        return bool(host and len(host) <= 255 and host in self.server.allowed_hosts)

    def _api_allowed(self) -> bool:
        if not self._host_allowed():
            self._error(403, "host_denied", "Unrecognized Host header.")
            return False
        capability = self.headers.get("X-UAF-Token", "")
        if not hmac.compare_digest(capability, self.server.token):
            self._error(
                403, "capability_denied", "A valid per-launch dashboard capability is required."
            )
            return False
        fetch_site = self.headers.get("Sec-Fetch-Site", "").strip().lower()
        if fetch_site == "cross-site":
            self._error(403, "cross_site_denied", "Cross-site dashboard requests are denied.")
            return False
        origin = self.headers.get("Origin")
        if origin:
            host = self.headers.get("Host", "").strip().lower()
            allowed_origins = {f"http://{host}", f"https://{host}"}
            if origin.rstrip("/").lower() not in allowed_origins:
                self._error(
                    403, "origin_denied", "The request Origin does not match this dashboard."
                )
                return False
        return True

    def _read_json(self) -> dict[str, Any]:
        if self.headers.get("Transfer-Encoding"):
            raise ValidationError("Transfer-Encoding is not accepted; use a bounded JSON body.")
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ValidationError("Content-Type must be application/json.")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValidationError("A bounded Content-Length is required.")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValidationError("Content-Length must be an integer.") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ValidationError(f"JSON body must be 1..{MAX_REQUEST_BYTES} bytes.")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("Request body must be valid UTF-8 JSON.") from exc
        if not isinstance(payload, dict):
            raise ValidationError("JSON body must be an object.")
        return payload

    def _dispatch(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.query or parsed.fragment:
            raise ValidationError("Query strings are not accepted by dashboard endpoints.")
        path = parsed.path
        if self.command in {"GET", "HEAD"} and path in ASSET_TYPES:
            if not self._host_allowed():
                self._error(403, "host_denied", "Unrecognized Host header.")
                return
            filename, content_type = ASSET_TYPES[path]
            body = (self.server.assets / filename).read_bytes()
            self._bytes(200, body, content_type)
            return
        if not self._api_allowed():
            return
        if self.command == "GET" and path == "/api/status":
            self._json(200, self.server.service.status())
            return
        if self.command == "POST" and path == "/api/experience/approve":
            payload = self._read_json()
            approved = self.server.service.approve_experience(
                str(payload.get("memory_id", "")), str(payload.get("confirmation", ""))
            )
            self._json(200, {"approved": approved, "status": self.server.service.status()})
            return
        if self.command == "POST" and path in {"/api/setup", "/api/start"}:
            payload = self._read_json()
            if path == "/api/setup":
                result = self.server.service.setup_and_start(
                    str(payload.get("api_key", "")),
                    str(payload.get("confirmation", "")),
                )
            else:
                result = self.server.service.start(str(payload.get("confirmation", "")))
            self._json(200, result)
            return
        self._error(404, "not_found", "Dashboard endpoint not found.")

    def _handle(self) -> None:
        try:
            self._dispatch()
        except UAFError as exc:
            status = 400
            if isinstance(exc, PolicyDenied):
                status = 403
            elif isinstance(exc, UnavailableError) or exc.code == "provider_error":
                status = 503
            self._error(status, exc.code, redact_text(str(exc)), redact_data(exc.details))
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            # Do not attach traceback text on a credential-handling route: exception messages
            # from third-party code are outside our redaction contract.
            logger.error("Dashboard request failed (%s)", type(exc).__name__)
            self._error(
                500, "internal_error", "Dashboard request failed; inspect the local redacted log."
            )

    def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler API
        self._handle()

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib HTTP handler API
        self._handle()

    def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler API
        self._handle()

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib HTTP handler API
        self._error(405, "cors_disabled", "Cross-origin dashboard access is disabled.")


def create_dashboard_server(
    app: Application,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
    allowed_hosts: set[str] | None = None,
    onboarding: GeminiOnboarding | None = None,
) -> DashboardHTTPServer:
    """Create a server; loopback is the only mode that accepts credential writes."""

    if not 0 <= port <= 65_535:
        raise ValidationError("Dashboard port must be between 0 and 65535.")
    # Credential writes require a literal loopback bind; hostname resolution is not
    # treated as proof because hosts-file/DNS configuration can change it.
    loopback = host in {"127.0.0.1", "::1"}
    if not loopback and not allowed_hosts:
        raise ValidationError(
            "Non-loopback dashboard exposure requires an explicit Host allowlist. "
            "It remains read-only for credentials."
        )
    capability = token or secrets.token_urlsafe(32)
    if len(capability) < 32:
        raise ValidationError("Dashboard capability must contain at least 32 characters.")
    service = DashboardService(app, allow_credentials=loopback, onboarding=onboarding)
    server = DashboardHTTPServer(
        (host, port),
        service,
        token=capability,
        allowed_hosts=allowed_hosts or set(),
    )
    actual_port = int(server.server_address[1])
    if loopback:
        server.allowed_hosts.update(
            {
                f"127.0.0.1:{actual_port}",
                f"localhost:{actual_port}",
                f"[::1]:{actual_port}",
            }
        )
        if actual_port == 80:
            server.allowed_hosts.update({"127.0.0.1", "localhost"})
    return server


def serve_dashboard(
    app: Application,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    allowed_hosts: set[str] | None = None,
) -> int:
    server = create_dashboard_server(app, host=host, port=port, allowed_hosts=allowed_hosts)
    actual_port = int(server.server_address[1])
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host  # noqa: S104 - display URL only
    if ":" in browser_host and not browser_host.startswith("["):
        browser_host = f"[{browser_host}]"
    url = f"http://{browser_host}:{actual_port}/#token={server.token}"
    print(f"UAF dashboard: {url}", flush=True)
    print(
        "Keep this URL private. API keys are accepted only on loopback; "
        "voice requires microphone permission and never bypasses approvals.",
        flush=True,
    )
    if open_browser:
        webbrowser.open(url, new=2)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
    return 0
