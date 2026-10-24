from __future__ import annotations

import copy
import json
import unittest

from tests.support import FactoryCase
from uaf.acceptance import evaluate_startup_acceptance

PASS_REVIEW = '{"verdict":"pass","reasons":[],"evidence":["reviewed"]}'


def valid_acceptance_input() -> dict:
    return {
        "inventory": {
            "path": ".",
            "truncated": False,
            "entries": [
                {"name": "notes.txt", "type": "file", "bytes": 12},
                {"name": "src", "type": "directory", "bytes": None},
            ],
        },
        "brief": "Bounded startup recommendations and uncertainties.",
        "inventory_state": "succeeded",
        "brief_state": "succeeded",
        "review_verdict": "pass",
    }


class StartupAcceptanceTests(FactoryCase):
    def test_real_contract_checks_reject_missing_or_false_evidence(self):
        accepted = evaluate_startup_acceptance(**valid_acceptance_input())
        self.assertTrue(accepted["accepted"])
        self.assertTrue(accepted["postcondition"])
        self.assertEqual(accepted["evidence"]["checks_passed"], 5)
        self.assertEqual(accepted["evidence"]["inventory_entries"], 2)
        self.assertNotIn("notes.txt", json.dumps(accepted["evidence"]))

        cases = {
            "brief_nonempty_and_bounded": {"brief": "   "},
            "independent_reviewer_passed": {"review_verdict": "revise"},
            "upstream_states_succeeded": {"inventory_state": "failed"},
            "inventory_contract_valid": {"inventory": {"path": ".", "entries": []}},
            "inventory_entries_bounded": {
                "inventory": {
                    "path": ".",
                    "truncated": True,
                    "entries": [
                        {"name": f"file-{index}.txt", "type": "file", "bytes": 0}
                        for index in range(201)
                    ],
                }
            },
        }
        for failed_check, override in cases.items():
            with self.subTest(check=failed_check):
                payload = valid_acceptance_input()
                payload.update(override)
                result = evaluate_startup_acceptance(**payload)
                self.assertFalse(result["accepted"])
                self.assertFalse(result["postcondition"])
                states = {item["id"]: item["passed"] for item in result["checks"]}
                self.assertFalse(states[failed_check])

    def test_company_v2_uses_real_acceptance_tool(self):
        adapter = self.install_fake(["Bounded startup brief", PASS_REVIEW])
        run = self.app.factory.start(
            "company-startup@2",
            "Start a quality-gated company",
            inputs={"path": ".", "limit": 50},
        )
        self.assertEqual(run["state"], "succeeded", run)
        self.assertEqual(run["result"]["metrics"]["succeeded_steps"], 3)
        self.assertEqual(run["result"]["metrics"]["model_calls"], 2)
        self.assertEqual(run["result"]["metrics"]["tool_calls"], 2)
        self.assertEqual(len(adapter.calls), 2)
        acceptance = next(
            step for step in run["result"]["steps"] if step["step_id"] == "acceptance-record"
        )
        self.assertTrue(acceptance["output"]["accepted"])
        self.assertEqual(acceptance["output"]["evidence"]["checks_passed"], 5)
        self.assertFalse(acceptance["output"]["evidence"]["additional_execution_claimed"])

    def test_reviewer_pass_cannot_make_blank_brief_factory_ready(self):
        adapter = self.install_fake(["   ", PASS_REVIEW])
        run = self.app.factory.start(
            "company-startup@2",
            "Reject empty startup evidence",
            inputs={"path": ".", "limit": 50},
        )
        self.assertEqual(run["state"], "failed", run)
        acceptance = next(
            step for step in run["result"]["steps"] if step["step_id"] == "acceptance-record"
        )
        self.assertEqual(acceptance["state"], "failed")
        invocation = self.db.one(
            "SELECT result_json FROM tool_invocations "
            "WHERE tool_name='factory.accept_startup' ORDER BY created_at DESC LIMIT 1"
        )
        output = json.loads(invocation["result_json"])
        self.assertFalse(output["accepted"])
        self.assertFalse(output["postcondition"])
        self.assertEqual(len(adapter.calls), 2)

    def test_company_v2_coexists_with_an_existing_v1_registration(self):
        current = self.app.blueprints.require("company-startup@2")
        old = copy.deepcopy(current["spec"])
        old["version"] = "1"
        self.app.blueprints.register(old, builtin=True)
        self.app.blueprints.register_builtin()
        self.assertEqual(self.app.blueprints.require("company-startup@1")["version"], "1")
        self.assertEqual(self.app.blueprints.require("company-startup@2")["version"], "2")


if __name__ == "__main__":
    unittest.main()
