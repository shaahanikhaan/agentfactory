from __future__ import annotations

import http.client
import json
import threading
import unittest
from typing import Any

from tests.support import FactoryCase, FakeAdapter, FakeKeyring
from uaf.credentials import CredentialStore
from uaf.dashboard import (
    EXPERIENCE_CONFIRMATION,
    START_CONFIRMATION,
    DashboardService,
    _model_choice,
    create_dashboard_server,
)
from uaf.errors import PolicyDenied, ProviderError, UnavailableError, ValidationError
from uaf.onboarding import GeminiOnboarding
from uaf.providers import ProviderService

PASS_REVIEW = '{"verdict":"pass","reasons":[],"evidence":["checked"]}'


def discovered_model(model: str = "gemini-3.8-flash") -> dict[str, Any]:
    return {
        "name": f"models/{model}",
        "supportedGenerationMethods": ["generateContent"],
        "inputTokenLimit": 1_000_000,
        "outputTokenLimit": 64_000,
    }


class FakeDiscoveryHTTP:
    def __init__(self) -> None:
        self.calls = 0
        self.models = [discovered_model()]

    def get_json(self, _url: str, *, headers: dict[str, str], timeout: float) -> dict:
        assert headers["x-goog-api-key"].startswith("AIza")
        assert timeout > 0
        self.calls += 1
        return {"models": self.models}


class DashboardTests(FactoryCase):
    def setUp(self) -> None:
        super().setUp()
        self.secret = "AIza" + "d" * 32
        self.capability = "test-capability-" + "x" * 32
        self.vault = CredentialStore(keyring_module=FakeKeyring())
        self.app.credentials = self.vault
        self.app.diagnostics.credentials = self.vault
        self.adapter = FakeAdapter(["OK", "Bounded startup brief", PASS_REVIEW])
        self.app.providers = ProviderService(
            self.app.settings,
            self.db,
            environ={},
            adapters={"gemini": self.adapter},
            credential_store=self.vault,
            sleep=lambda _: None,
        )
        self.app.agents.providers = self.app.providers
        self.discovery = FakeDiscoveryHTTP()
        onboarding = GeminiOnboarding(self.app.config, self.vault, http=self.discovery)
        self.server = create_dashboard_server(
            self.app,
            port=0,
            token=self.capability,
            onboarding=onboarding,
        )
        self.port = int(self.server.server_address[1])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        super().tearDown()

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        capability: str | None = None,
        host: str | None = None,
        origin: str | None = None,
        content_type: str = "application/json",
        fetch_site: str | None = None,
    ) -> tuple[int, dict[str, str], Any]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        headers: dict[str, str] = {}
        if capability is not None:
            headers["X-UAF-Token"] = capability
        if host is not None:
            headers["Host"] = host
        if origin is not None:
            headers["Origin"] = origin
        if fetch_site is not None:
            headers["Sec-Fetch-Site"] = fetch_site
        raw_body = None
        if body is not None:
            raw_body = json.dumps(body)
            headers["Content-Type"] = content_type
        try:
            connection.request(method, path, body=raw_body, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            response_headers = {key.lower(): value for key, value in response.getheaders()}
            if response_headers.get("content-type", "").startswith("application/json"):
                payload: Any = json.loads(raw)
            else:
                payload = raw.decode("utf-8")
            return response.status, response_headers, payload
        finally:
            connection.close()

    def setup(self, **overrides: Any):
        payload = {"api_key": self.secret, "confirmation": START_CONFIRMATION, **overrides}
        return self.request(
            "POST",
            "/api/setup",
            body=payload,
            capability=self.capability,
            origin=f"http://127.0.0.1:{self.port}",
        )

    def test_static_assets_and_authenticated_status(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Ultimate Agent Factory", body)
        self.assertIn("default-src 'self'", headers["content-security-policy"])
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(headers["connection"], "close")
        self.assertNotIn("access-control-allow-origin", headers)
        self.assertIn("show-capabilities", body)
        self.assertIn("Actual department activity", body)
        self.assertIn("Real task outcomes", body)

        status, _, payload = self.request("GET", "/api/status", capability=self.capability)
        self.assertEqual(status, 200)
        self.assertFalse(payload["ready"])
        self.assertFalse(payload["setup"]["configured"])
        self.assertEqual(len(payload["departments"]), 12)
        states = {item["id"]: item["state"] for item in payload["departments"]}
        self.assertEqual(states["brain-pool"], "blocked")
        self.assertEqual(states["desktop-voice"], "optional")
        self.assertFalse(payload["voice"]["continuous"])
        self.assertFalse(payload["voice"]["approval_authority"])
        self.assertEqual(payload["experience"]["counts"]["pending"], 0)
        self.assertFalse(payload["experience"]["model_output_captured"])

    def test_status_names_failed_doctor_checks_for_recovery(self):
        self.workspace.rmdir()
        status, _, payload = self.request("GET", "/api/status", capability=self.capability)
        self.assertEqual(status, 200)
        self.assertFalse(payload["doctor"]["ok"])
        self.assertFalse(payload["doctor"]["checks"]["workspace_available"])
        _, _, script = self.request("GET", "/app.js")
        self.assertIn("doctor.checks", script)

    def test_host_capability_origin_and_json_boundaries(self):
        cases = [
            ({"capability": None}, 403, "capability_denied"),
            ({"host": "attacker.example"}, 403, "host_denied"),
            ({"origin": "https://attacker.example"}, 403, "origin_denied"),
            ({"fetch_site": "cross-site"}, 403, "cross_site_denied"),
            ({"content_type": "text/plain"}, 400, "validation_error"),
        ]
        for overrides, expected_status, expected_code in cases:
            with self.subTest(code=expected_code):
                options = {
                    "body": {"api_key": self.secret, "confirmation": START_CONFIRMATION},
                    "capability": self.capability,
                    **overrides,
                }
                status, _, payload = self.request("POST", "/api/setup", **options)
                self.assertEqual(status, expected_status)
                self.assertEqual(payload["error"]["code"], expected_code)
                self.assertNotIn(self.secret, str(payload))
        self.assertEqual(self.discovery.calls, 0)
        self.assertFalse(self.vault.status()["gemini_present"])

        status, _, payload = self.request(
            "GET", f"/api/status?token={self.capability}", capability=self.capability
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "validation_error")
        status, headers, _ = self.request("OPTIONS", "/api/status")
        self.assertEqual(status, 405)
        self.assertNotIn("access-control-allow-origin", headers)

    def test_one_key_setup_live_probe_and_idempotent_real_dag(self):
        private_name = "private-company-note.txt"
        (self.workspace / private_name).write_text("local only", encoding="utf-8")
        status, _, payload = self.setup()
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["setup"]["model"], "gemini-3.8-flash")
        self.assertTrue(payload["setup"]["setup_complete"])
        self.assertTrue(payload["setup"]["live_generation_tested"])
        self.assertTrue(payload["live"]["live"])
        self.assertEqual(payload["factory"]["state"], "succeeded")
        self.assertEqual(payload["factory"]["brief"], "Bounded startup brief")
        self.assertTrue(payload["status"]["ready"])
        self.assertEqual(payload["factory"]["result"]["completed_steps"], 3)
        self.assertEqual(payload["factory"]["result"]["metrics"]["model_calls"], 2)
        self.assertEqual(len(payload["factory"]["result"]["timeline"]), 3)
        self.assertEqual(payload["status"]["experience"]["counts"]["pending"], 3)
        self.assertEqual(self.vault.get("gemini"), self.secret)
        self.assertEqual(len(self.adapter.calls), 3)
        probe = self.adapter.calls[0][1]
        self.assertEqual(probe.max_output_tokens, 256)
        self.assertEqual(probe.metadata, {"thinking_level": "low"})
        run_id = payload["factory"]["run_id"]
        raw_run = self.app.factory.require(run_id)
        inventory = next(step for step in raw_run["steps"] if step["step_id"] == "inventory")
        self.assertIn(private_name, str(inventory["output"]))
        worker_prompt = self.adapter.calls[1][1].prompt
        self.assertNotIn(private_name, worker_prompt)
        self.assertNotIn("local only", worker_prompt)
        executions = {
            item["id"]: (item["last_execution"] or {}).get("step_id")
            for item in payload["status"]["departments"]
        }
        self.assertEqual(executions["brain-pool"], "live-readiness")
        self.assertEqual(executions["reliability"], "inventory")
        self.assertEqual(executions["orchestration"], "operations-brief")
        self.assertEqual(executions["quality"], "acceptance-record")
        self.assertIsNone(executions["executive"])
        self.assertNotIn(self.secret, str(payload))
        self.assertNotIn(self.secret, self.paths.config.read_text(encoding="utf-8"))
        self.assertNotIn(self.secret, str(self.db.query("SELECT * FROM audit_events")))
        self.assertEqual(self.db.one("SELECT COUNT(*) c FROM factory_runs")["c"], 1)
        self.assertEqual(
            self.db.one("SELECT COUNT(*) c FROM tasks WHERE state='succeeded'")["c"], 3
        )

        status, _, replay = self.request(
            "POST",
            "/api/start",
            body={"confirmation": START_CONFIRMATION},
            capability=self.capability,
        )
        self.assertEqual(status, 200, replay)
        self.assertEqual(replay["factory"]["run_id"], run_id)
        self.assertEqual(replay["factory"]["state"], "succeeded")
        self.assertEqual(self.db.one("SELECT COUNT(*) c FROM factory_runs")["c"], 1)
        self.assertEqual(
            len(self.adapter.calls), 4
        )  # New explicit probe; completed DAG is not repeated.
        self.assertEqual(replay["status"]["experience"]["counts"]["pending"], 3)

    def test_experience_review_is_explicit_idempotent_and_not_voice_authority(self):
        task = self.add_smoke("dashboard experience review")
        self.app.runner.run(task["task_id"])
        _, _, current = self.request("GET", "/api/status", capability=self.capability)
        item = current["experience"]["items"][0]
        self.assertEqual(item["approval_status"], "pending")

        status, _, denied = self.request(
            "POST",
            "/api/experience/approve",
            body={"memory_id": item["memory_id"], "confirmation": "yes"},
            capability=self.capability,
        )
        self.assertEqual(status, 400)
        self.assertEqual(denied["error"]["code"], "validation_error")
        body = {"memory_id": item["memory_id"], "confirmation": EXPERIENCE_CONFIRMATION}
        status, _, approved = self.request(
            "POST",
            "/api/experience/approve",
            body=body,
            capability=self.capability,
        )
        self.assertEqual(status, 200, approved)
        self.assertEqual(approved["approved"]["approval_status"], "approved")
        self.assertEqual(approved["status"]["experience"]["counts"]["approved"], 1)
        status, _, replay = self.request(
            "POST",
            "/api/experience/approve",
            body=body,
            capability=self.capability,
        )
        self.assertEqual(status, 200, replay)
        self.assertEqual(
            self.db.one("SELECT COUNT(*) c FROM audit_events WHERE action='memory.approve'")["c"],
            1,
        )

        _, _, script = self.request("GET", "/app.js")
        command_handler = script.split("function handleCommand", 1)[1].split(
            "function stopListening", 1
        )[0]
        self.assertNotIn("experience", command_handler.lower())
        self.assertNotIn("approve", command_handler.lower())
        self.assertIn("window.confirm", script)

    def test_live_failure_saves_config_but_never_claims_factory_ready(self):
        self.adapter.responses = [
            ProviderError("temporary outage", kind="provider_unavailable", retryable=True)
        ]
        status, _, payload = self.setup()
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"]["code"], "temporarily_unavailable")
        self.assertNotIn(self.secret, str(payload))
        self.assertEqual(len(self.adapter.calls), 3)
        self.assertTrue(self.vault.status()["gemini_present"])
        self.assertEqual(self.db.one("SELECT COUNT(*) c FROM factory_runs")["c"], 0)

        status, _, current = self.request("GET", "/api/status", capability=self.capability)
        self.assertEqual(status, 200)
        self.assertTrue(current["setup"]["configured"])
        self.assertFalse(current["setup"]["eligible"])  # Scoped provider cooldown is honored.
        self.assertFalse(current["setup"]["live_healthy"])
        self.assertFalse(current["ready"])
        self.assertIsNone(current["factory"])

    def test_confirmation_and_discovery_fail_closed_before_vault_write(self):
        status, _, payload = self.setup(confirmation="yes")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "validation_error")
        self.assertEqual(self.discovery.calls, 0)
        self.assertFalse(self.vault.status()["gemini_present"])

        self.discovery.models = [discovered_model("gemini-2.5-flash")]
        status, _, payload = self.setup()
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"]["code"], "temporarily_unavailable")
        self.assertFalse(self.vault.status()["gemini_present"])

    def test_model_priority_and_bounded_live_health(self):
        models = [
            {"model": "gemini-3.1-flash-lite"},
            {"model": "gemini-3.5-flash-lite"},
        ]
        self.assertEqual(_model_choice(models), "gemini-3.5-flash-lite")
        models.append({"model": "gemini-3.8-flash"})
        self.assertEqual(_model_choice(models), "gemini-3.8-flash")
        with self.assertRaises(UnavailableError):
            _model_choice([{"model": "gemini-2.5-flash"}])

        status, _, payload = self.setup()
        self.assertEqual(status, 200, payload)
        self.db.execute(
            "UPDATE provider_health SET checked_at='2000-01-01T00:00:00Z' WHERE provider='gemini'"
        )
        _, _, current = self.request("GET", "/api/status", capability=self.capability)
        self.assertFalse(current["setup"]["live_healthy"])
        self.assertFalse(current["ready"])
        brain = next(item for item in current["departments"] if item["id"] == "brain-pool")
        self.assertEqual(brain["last_execution"]["state"], "stale")

    def test_non_loopback_credential_writes_are_denied(self):
        task = self.add_smoke("loopback only experience content")
        self.app.runner.run(task["task_id"])
        service = DashboardService(self.app, allow_credentials=False, onboarding=None)
        remote_status = service.status()
        self.assertEqual(remote_status["experience"]["items"], [])
        self.assertEqual(remote_status["experience"]["counts"]["pending"], 1)
        with self.assertRaises(PolicyDenied):
            service.setup_and_start(self.secret, START_CONFIRMATION)
        with self.assertRaises(PolicyDenied):
            service.approve_experience("mem-test", EXPERIENCE_CONFIRMATION)
        with self.assertRaises(PolicyDenied):
            service.start(START_CONFIRMATION)
        self.assertEqual(self.discovery.calls, 0)
        self.assertEqual(len(self.adapter.calls), 0)
        with self.assertRaises(ValidationError):
            create_dashboard_server(self.app, host="192.0.2.1", port=0)
        with self.assertRaises(ValidationError):
            create_dashboard_server(self.app, host="localhost", port=0)
        with self.assertRaises(ValidationError):
            create_dashboard_server(self.app, port=70_000)

    def test_voice_is_optional_local_first_and_never_persistent(self):
        _, _, script = self.request("GET", "/app.js")
        self.assertIn("processLocally", script)
        self.assertIn("Recognition.available", script)
        self.assertIn("Recognition.install", script)
        self.assertIn("continuous = false", script)
        self.assertIn("confirm start factory", script)
        self.assertIn("credentialLike", script)
        self.assertIn("not echoed or submitted", script)
        self.assertIn("no remote fallback was attempted", script)
        self.assertIn('$("api-key").disabled = busy || remoteReadOnly', script)
        self.assertIn("Factory start is disabled on this non-loopback dashboard", script)
        self.assertIn("Experience content is hidden on this non-loopback dashboard", script)
        self.assertIn("doctor.checks", script)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("sessionStorage", script)
        self.assertNotIn("speechSynthesis", script)


if __name__ == "__main__":
    unittest.main()
