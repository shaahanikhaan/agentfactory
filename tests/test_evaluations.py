from __future__ import annotations

import json
import unittest

from tests.support import FactoryCase
from uaf.errors import ValidationError


class EvaluationTests(FactoryCase):
    def write_suite(self, suite: dict) -> str:
        path = self.root / "suite.json"
        path.write_text(json.dumps(suite))
        return str(path)

    def minimal_suite(self, expected_state: str = "succeeded") -> dict:
        return {
            "suite_id": "unit-suite",
            "version": "1",
            "description": "unit evaluation",
            "cases": [
                {
                    "case_id": "smoke",
                    "name": "smoke case",
                    "split": "held_out",
                    "task": {"goal": "evaluate", "kind": "smoke"},
                    "expect": {
                        "state": expected_state,
                        "checks": [{"path": "metrics.model_calls", "operator": "eq", "value": 0}],
                    },
                }
            ],
        }

    def test_core_suite_scores_expected_safe_behavior(self):
        report = self.app.evaluations.run()
        self.assertEqual(report["metrics"]["accuracy"], 1.0)
        self.assertEqual(report["metrics"]["passed_cases"], 8)
        self.assertEqual(report["metrics"]["held_out_accuracy"], 1.0)
        self.assertEqual(report["metrics"]["task_success_rate"], 0.5)
        self.assertEqual(report["metrics"]["total_model_calls"], 0)
        self.assertEqual(len(report["cases"]), 8)
        self.assertEqual(
            self.db.one(
                "SELECT COUNT(*) c FROM evaluation_case_results WHERE run_id=?", (report["run_id"],)
            )["c"],
            8,
        )

    def test_identical_suite_baseline_has_no_regression(self):
        baseline = self.app.evaluations.run()
        candidate = self.app.evaluations.run(baseline_run_id=baseline["run_id"])
        comparison = candidate["baseline_comparison"]
        self.assertTrue(comparison["regression_gate_passed"])
        self.assertEqual(comparison["regressions"], [])
        self.assertEqual(comparison["accuracy_delta"], 0.0)

    def test_real_code_regression_fails_same_suite_gate(self):
        suite_path = self.write_suite(self.minimal_suite())
        baseline = self.app.evaluations.run(suite_path)
        original = self.app.agents.smoke_worker
        self.app.agents.smoke_worker = lambda task: {"deterministic": False}
        try:
            candidate = self.app.evaluations.run(
                suite_path, baseline_run_id=baseline["run_id"], candidate_id="broken-change"
            )
        finally:
            self.app.agents.smoke_worker = original
        comparison = candidate["baseline_comparison"]
        self.assertEqual(candidate["metrics"]["accuracy"], 0.0)
        self.assertFalse(comparison["regression_gate_passed"])
        self.assertEqual(comparison["regressions"], ["unit-suite:smoke"])
        self.assertEqual(comparison["accuracy_delta"], -1.0)

    def test_different_suite_digest_cannot_be_a_baseline(self):
        baseline = self.app.evaluations.run(self.write_suite(self.minimal_suite()))
        changed = self.minimal_suite(expected_state="failed")
        with self.assertRaises(ValidationError):
            self.app.evaluations.run(self.write_suite(changed), baseline_run_id=baseline["run_id"])

    def test_malformed_or_executable_suite_is_rejected(self):
        suite = self.minimal_suite()
        suite["cases"][0]["scorer"] = "python:arbitrary.code"
        with self.assertRaises(ValidationError):
            self.app.evaluations.run(self.write_suite(suite))
        suite = self.minimal_suite()
        suite["cases"][0]["expect"]["checks"] = [
            {"path": "result.mode", "operator": "import", "value": "os"}
        ]
        with self.assertRaises(ValidationError):
            self.app.evaluations.run(self.write_suite(suite))
        suite = self.minimal_suite()
        suite["cases"][0]["task"]["input"] = {"api_key": "must-not-be-persisted"}
        with self.assertRaises(ValidationError):
            self.app.evaluations.run(self.write_suite(suite))
        suite = self.minimal_suite()
        suite["cases"][0]["split"] = []
        with self.assertRaises(ValidationError):
            self.app.evaluations.run(self.write_suite(suite))
        suite = self.minimal_suite()
        suite["cases"][0]["expect"]["checks"][0]["operator"] = []
        with self.assertRaises(ValidationError):
            self.app.evaluations.run(self.write_suite(suite))

    def test_model_suite_uses_runner_and_records_resource_usage(self):
        self.install_fake(["42", '{"verdict":"pass","reasons":[],"evidence":["exact answer"]}'])
        suite = self.minimal_suite()
        suite["cases"][0]["task"] = {"goal": "Return 42", "kind": "agent"}
        suite["cases"][0]["expect"]["checks"] = [
            {"path": "result.output", "operator": "eq", "value": "42"},
            {"path": "metrics.model_calls", "operator": "eq", "value": 2},
        ]
        report = self.app.evaluations.run(self.write_suite(suite))
        self.assertEqual(report["metrics"]["accuracy"], 1.0)
        self.assertEqual(report["metrics"]["total_model_calls"], 2)
        self.assertEqual(report["metrics"]["held_out_accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
