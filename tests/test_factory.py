from __future__ import annotations

import copy
import unittest

from tests.support import FactoryCase
from uaf.errors import IdempotencyConflict, IntegrityError, ValidationError

PASS_REVIEW = '{"verdict":"pass","reasons":[],"evidence":["checked"]}'


class FactoryTests(FactoryCase):
    def spec(self, name: str, agents: list[dict], steps: list[dict], **extra) -> dict:
        return {
            "name": name,
            "version": "1",
            "description": "test blueprint",
            "agents": agents,
            "steps": steps,
            **extra,
        }

    def register_enabled(self, spec: dict) -> str:
        blueprint = self.app.blueprints.register(spec)
        self.app.blueprints.set_enabled(blueprint["blueprint_id"], True)
        return blueprint["blueprint_id"]

    def test_builtin_offline_dag_and_idempotent_start(self):
        with self.assertRaises(ValidationError):
            self.app.factory.start("offline-workspace-inventory@1", "bad input", inputs=[])
        inputs = {"path": ".", "limit": 20}
        run = self.app.factory.start(
            "offline-workspace-inventory@1",
            "inventory test",
            inputs=inputs,
            idempotency_key="inventory-key",
        )
        self.assertEqual(run["state"], "succeeded")
        self.assertEqual(run["result"]["metrics"]["model_calls"], 0)
        self.assertEqual(run["result"]["metrics"]["tool_calls"], 1)
        self.assertEqual(run["result"]["metrics"]["checkpoints"], 8)
        self.assertEqual(run["result"]["output"]["path"], ".")
        self.assertEqual([step["step_id"] for step in run["steps"]], ["inventory", "record"])
        for step in run["steps"]:
            self.assertEqual(self.tasks.require(step["task_id"])["correlation_id"], run["run_id"])
        repeated = self.app.factory.start(
            "offline-workspace-inventory@1",
            "inventory test",
            inputs=inputs,
            idempotency_key="inventory-key",
        )
        self.assertEqual(repeated["run_id"], run["run_id"])
        with self.assertRaises(IdempotencyConflict):
            self.app.factory.start(
                "offline-workspace-inventory@1",
                "different payload",
                inputs=inputs,
                idempotency_key="inventory-key",
            )

    def test_custom_dag_binds_upstream_output_to_downstream_input(self):
        spec = self.spec(
            "file-dag",
            [
                {
                    "agent_id": "files",
                    "kind": "tool",
                    "allowed_tools": ["workspace.write", "workspace.read"],
                    "risk_tier": "R1",
                },
                {"agent_id": "record", "kind": "smoke"},
            ],
            [
                {
                    "step_id": "write",
                    "agent_id": "files",
                    "goal": "Write source",
                    "input": {
                        "tool": "workspace.write",
                        "arguments": {"path": "dag/result.txt", "content": "{{ inputs.content }}"},
                    },
                },
                {
                    "step_id": "read",
                    "agent_id": "files",
                    "goal": "Read {{ steps.write.output.path }} after {{ steps.write.state }}",
                    "depends_on": ["write"],
                    "input": {
                        "tool": "workspace.read",
                        "arguments": {"path": "{{ steps.write.output.path }}"},
                    },
                },
                {
                    "step_id": "record",
                    "agent_id": "record",
                    "goal": "Record {{ steps.read.output.content }}",
                    "depends_on": ["read"],
                },
            ],
            output={"from": "read"},
        )
        blueprint_id = self.register_enabled(spec)
        run = self.app.factory.start(blueprint_id, "flow", inputs={"content": "hello dag"})
        self.assertEqual(run["state"], "succeeded")
        self.assertEqual(run["result"]["output"]["content"], "hello dag")
        self.assertEqual(run["result"]["metrics"]["tool_calls"], 2)
        read_task = self.tasks.require(run["steps"][1]["task_id"])
        self.assertEqual(read_task["goal"], "Read dag/result.txt after succeeded")
        self.assertEqual(read_task["input"]["arguments"]["path"], "dag/result.txt")
        self.assertEqual(self.tasks.require(run["steps"][2]["task_id"])["goal"], "Record hello dag")

    def test_custom_blueprint_is_disabled_and_immutable(self):
        spec = self.spec(
            "immutable",
            [{"agent_id": "smoke", "kind": "smoke"}],
            [{"step_id": "only", "agent_id": "smoke", "goal": "smoke"}],
        )
        blueprint = self.app.blueprints.register(spec)
        self.assertFalse(blueprint["enabled"])
        with self.assertRaises(ValidationError):
            self.app.factory.start(blueprint["blueprint_id"], "not yet")
        changed = copy.deepcopy(spec)
        changed["description"] = "changed without a version"
        with self.assertRaises(IntegrityError):
            self.app.blueprints.register(changed)

    def test_cycle_hidden_dataflow_and_unknown_tools_are_rejected(self):
        agent = {"agent_id": "smoke", "kind": "smoke"}
        cyclic = self.spec(
            "cyclic",
            [agent],
            [
                {"step_id": "a", "agent_id": "smoke", "goal": "a", "depends_on": ["b"]},
                {"step_id": "b", "agent_id": "smoke", "goal": "b", "depends_on": ["a"]},
            ],
        )
        with self.assertRaises(ValidationError):
            self.app.blueprints.register(cyclic)
        hidden = self.spec(
            "hidden-flow",
            [agent],
            [
                {"step_id": "a", "agent_id": "smoke", "goal": "a"},
                {"step_id": "b", "agent_id": "smoke", "goal": "{{ steps.a.output }}"},
            ],
        )
        with self.assertRaises(ValidationError):
            self.app.blueprints.register(hidden)
        unknown_tool = self.spec(
            "unknown-tool",
            [{"agent_id": "bad", "kind": "tool", "allowed_tools": ["shell.exec"]}],
            [{"step_id": "bad", "agent_id": "bad", "goal": "bad", "input": {"tool": "shell.exec"}}],
        )
        with self.assertRaises(ValidationError):
            self.app.blueprints.register(unknown_tool)
        wrong_type = self.spec(
            "wrong-type",
            [{"agent_id": "bad", "kind": []}],
            [{"step_id": "bad", "agent_id": "bad", "goal": "bad"}],
        )
        with self.assertRaises(ValidationError):
            self.app.blueprints.register(wrong_type)
        secret = self.spec(
            "secret-blueprint",
            [agent],
            [
                {
                    "step_id": "a",
                    "agent_id": "smoke",
                    "goal": "do not persist credentials",
                    "input": {"context": {"api_key": "should-not-be-stored"}},
                }
            ],
        )
        with self.assertRaises(ValidationError):
            self.app.blueprints.register(secret)

    def test_r3_factory_pauses_and_resumes_after_exact_approval(self):
        (self.workspace / "delete.txt").write_text("approved")
        spec = self.spec(
            "approved-delete",
            [
                {
                    "agent_id": "delete",
                    "kind": "tool",
                    "allowed_tools": ["workspace.delete"],
                    "risk_tier": "R3",
                }
            ],
            [
                {
                    "step_id": "delete",
                    "agent_id": "delete",
                    "goal": "Delete governed file",
                    "input": {"tool": "workspace.delete", "arguments": {"path": "delete.txt"}},
                }
            ],
        )
        blueprint_id = self.register_enabled(spec)
        run = self.app.factory.start(blueprint_id, "approval flow")
        self.assertEqual(run["state"], "awaiting_approval")
        self.assertTrue((self.workspace / "delete.txt").exists())
        task_id = run["steps"][0]["task_id"]
        approval_id = self.tasks.require(task_id)["approval_id"]
        still_waiting = self.app.factory.resume(run["run_id"])
        self.assertEqual(still_waiting["state"], "awaiting_approval")
        self.app.approvals.decide(approval_id, approve=True, actor="human")
        completed = self.app.factory.resume(run["run_id"])
        self.assertEqual(completed["state"], "succeeded")
        self.assertFalse((self.workspace / "delete.txt").exists())

    def test_offline_agent_run_resumes_without_duplicate_tasks(self):
        spec = self.spec(
            "offline-agent",
            [{"agent_id": "writer", "kind": "agent", "instructions": "Be concise"}],
            [{"step_id": "write", "agent_id": "writer", "goal": "Answer {{ goal }}"}],
        )
        blueprint_id = self.register_enabled(spec)
        paused = self.app.factory.start(blueprint_id, "offline question")
        self.assertEqual(paused["state"], "paused_offline")
        self.assertEqual(paused["result"]["metrics"]["model_calls"], 0)
        self.assertEqual(paused["result"]["metrics"]["model_attempts"], 1)
        task_id = paused["steps"][0]["task_id"]
        self.install_fake(["answer", PASS_REVIEW])
        completed = self.app.factory.resume(paused["run_id"])
        self.assertEqual(completed["state"], "succeeded")
        self.assertEqual(completed["result"]["output"], "answer")
        self.assertEqual(completed["steps"][0]["task_id"], task_id)
        self.assertEqual(self.db.one("SELECT COUNT(*) c FROM factory_run_tasks")["c"], 1)

    def test_react_and_agent_team_pass_bounded_evidence(self):
        (self.workspace / "evidence.txt").write_text("durable evidence")
        spec = self.spec(
            "evidence-team",
            [
                {
                    "agent_id": "reader",
                    "kind": "react",
                    "allowed_tools": ["workspace.read"],
                    "instructions": "Read the requested file before answering",
                },
                {
                    "agent_id": "analyst",
                    "kind": "agent",
                    "instructions": "Analyze only supplied evidence",
                },
            ],
            [
                {"step_id": "read", "agent_id": "reader", "goal": "Read {{ inputs.path }}"},
                {
                    "step_id": "analyze",
                    "agent_id": "analyst",
                    "goal": "Analyze the reader result",
                    "depends_on": ["read"],
                    "input": {"context": {"evidence": "{{ steps.read.output }}"}},
                },
            ],
        )
        blueprint_id = self.register_enabled(spec)
        adapter = self.install_fake(
            [
                '{"action":"tool","tool":"workspace.read","arguments":{"path":"evidence.txt"}}',
                '{"action":"final","answer":"durable evidence"}',
                PASS_REVIEW,
                "bounded analysis",
                PASS_REVIEW,
            ]
        )
        run = self.app.factory.start(blueprint_id, "evidence flow", inputs={"path": "evidence.txt"})
        self.assertEqual(run["state"], "succeeded")
        self.assertEqual(run["result"]["output"], "bounded analysis")
        self.assertEqual(run["result"]["metrics"]["model_calls"], 5)
        self.assertEqual(run["result"]["metrics"]["tool_calls"], 1)
        analyst_prompt = adapter.calls[3][1].prompt
        self.assertIn("durable evidence", analyst_prompt)
        self.assertIn("EXTERNAL_UNTRUSTED_CONTENT", analyst_prompt)

    def test_failed_dependency_never_executes_downstream_step(self):
        spec = self.spec(
            "failed-flow",
            [
                {"agent_id": "read", "kind": "tool", "allowed_tools": ["workspace.read"]},
                {"agent_id": "record", "kind": "smoke"},
            ],
            [
                {
                    "step_id": "read",
                    "agent_id": "read",
                    "goal": "Read missing",
                    "input": {"tool": "workspace.read", "arguments": {"path": "missing.txt"}},
                },
                {
                    "step_id": "after",
                    "agent_id": "record",
                    "goal": "must not run",
                    "depends_on": ["read"],
                },
            ],
        )
        blueprint_id = self.register_enabled(spec)
        run = self.app.factory.start(blueprint_id, "failure flow")
        self.assertEqual(run["state"], "failed")
        self.assertEqual(run["steps"][0]["state"], "failed")
        self.assertEqual(run["steps"][1]["state"], "queued")
        self.assertFalse(run["steps"][1]["materialized"])
        self.assertEqual(self.tasks.steps(run["steps"][1]["task_id"]), [])

    def test_materialized_payload_tampering_fails_closed(self):
        spec = self.spec(
            "tamper-check",
            [{"agent_id": "writer", "kind": "agent"}],
            [{"step_id": "write", "agent_id": "writer", "goal": "Answer {{ goal }}"}],
        )
        blueprint_id = self.register_enabled(spec)
        paused = self.app.factory.start(blueprint_id, "original goal")
        task_id = paused["steps"][0]["task_id"]
        self.db.execute(
            "UPDATE tasks SET input_json='{\"tampered\":true}' WHERE task_id=?", (task_id,)
        )
        failed = self.app.factory.resume(paused["run_id"])
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["error"]["code"], "integrity_error")

    def test_interruption_is_explicit_and_resume_reuses_task_identity(self):
        spec = self.spec(
            "interrupted-flow",
            [{"agent_id": "smoke", "kind": "smoke"}, {"agent_id": "writer", "kind": "agent"}],
            [
                {"step_id": "first", "agent_id": "smoke", "goal": "first"},
                {
                    "step_id": "second",
                    "agent_id": "writer",
                    "goal": "second",
                    "depends_on": ["first"],
                },
            ],
        )
        blueprint_id = self.register_enabled(spec)

        def interrupt(_request):
            raise KeyboardInterrupt

        self.install_fake([interrupt])
        with self.assertRaises(KeyboardInterrupt):
            self.app.factory.start(blueprint_id, "interruption flow")
        run = self.app.factory.list(limit=1)[0]
        self.assertEqual(run["state"], "interrupted")
        detailed = self.app.factory.require(run["run_id"])
        second_id = detailed["steps"][1]["task_id"]
        self.assertEqual(len(self.tasks.steps(second_id)), 2)
        self.install_fake(["recovered", PASS_REVIEW])
        recovered = self.app.factory.resume(run["run_id"])
        self.assertEqual(recovered["state"], "succeeded")
        self.assertEqual(recovered["steps"][1]["task_id"], second_id)
        self.assertEqual(len(self.tasks.steps(second_id)), 4)


if __name__ == "__main__":
    unittest.main()
