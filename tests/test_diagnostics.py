from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import FactoryCase
from uaf.diagnostics import benchmark, capability_report


class DiagnosticsTests(FactoryCase):
    def test_capability_report_has_valid_states_and_existing_evidence(self):
        report = capability_report()
        states = {entry["state"] for entry in report["capabilities"]}
        self.assertEqual(states, {"implemented", "implemented_optional", "prototype", "planned"})
        by_id = {entry["id"]: entry for entry in report["capabilities"]}
        self.assertEqual(by_id["local_dashboard"]["state"], "implemented")
        self.assertEqual(by_id["browser_voice_commands"]["state"], "implemented_optional")
        self.assertEqual(by_id["one_click_windows_launcher"]["state"], "implemented_optional")
        root = Path(__file__).parent.parent
        for entry in report["capabilities"]:
            if entry["evidence"] and entry["evidence"].startswith(("tests/", "docs/")):
                self.assertTrue((root / entry["evidence"]).exists(), entry["evidence"])

    def test_doctor_reports_only_credential_presence(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "diagnostic-test-secret"}, clear=False):
            report = self.app.diagnostics.doctor()
        self.assertTrue(report["credentials"]["gemini_env_present"])
        self.assertNotIn("diagnostic-test-secret", json.dumps(report))
        self.assertTrue(report["ok"])

    def test_benchmark_reports_real_successes_and_zero_model_calls(self):
        result = benchmark(self.app.runner, self.tasks, iterations=2)
        self.assertEqual(result["succeeded"], 2)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["model_calls"], 0)
        self.assertGreater(result["tasks_per_second"], 0)
        self.assertEqual(self.tasks.counts()["succeeded"], 2)
        status = self.app.diagnostics.status([])
        self.assertEqual(status["factory"]["blueprints"], 2)
        self.assertEqual(status["evaluation_runs"], 0)


if __name__ == "__main__":
    unittest.main()
