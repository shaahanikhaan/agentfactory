from __future__ import annotations

import unittest

from tests.support import FactoryCase
from uaf.errors import UnavailableError
from uaf.models import TaskContract, TaskState


class RunnerTests(FactoryCase):
    def test_offline_smoke_is_durable_and_not_fake_ai(self):
        task = self.add_smoke("prove offline durability")
        result = self.app.runner.run(task["task_id"])
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(result["result"]["mode"], "offline_deterministic")
        self.assertFalse(result["result"]["ai_generated"])
        self.assertEqual(self.tasks.model_call_count(task["task_id"]), 0)
        steps = self.tasks.steps(task["task_id"])
        self.assertEqual(
            [step["role"] for step in steps], ["manager", "supervisor", "worker", "reviewer"]
        )
        events = self.tasks.timeline(task["task_id"])["events"]
        self.assertEqual(len(events), 6)
        self.assertEqual(events[-1]["action"], "experience.capture")

    def test_cloud_worker_reviewer_success(self):
        adapter = self.install_fake(
            ["A bounded answer", '{"verdict":"pass","reasons":[],"evidence":["checked goal"]}']
        )
        task = self.tasks.add(TaskContract(goal="Answer accurately", kind="agent"))
        result = self.app.runner.run(task["task_id"])
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(result["result"]["output"], "A bounded answer")
        self.assertEqual(result["result"]["evidence"]["model_calls"], 2)
        self.assertEqual(len(adapter.calls), 2)

    def test_one_bounded_revision_cycle(self):
        self.install_fake(
            [
                "first draft",
                '{"verdict":"revise","reasons":["needs detail"],"evidence":["contract"]}',
                "revised draft",
                '{"verdict":"pass","reasons":[],"evidence":["detail present"]}',
            ]
        )
        task = self.tasks.add(TaskContract(goal="Write a detailed answer", kind="agent"))
        result = self.app.runner.run(task["task_id"])
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(result["result"]["revision"], 2)
        self.assertEqual(result["result"]["output"], "revised draft")
        self.assertEqual(self.tasks.model_call_count(task["task_id"]), 4)
        self.assertEqual(len(self.tasks.steps(task["task_id"])), 6)

    def test_invalid_reviewer_json_fails_without_claiming_success(self):
        self.install_fake(["answer", "not-json"])
        task = self.tasks.add(TaskContract(goal="Answer", kind="agent"))
        result = self.app.runner.run(task["task_id"])
        self.assertEqual(result["state"], "failed")
        self.assertIn("valid JSON", result["error"]["message"])

    def test_expected_output_schema_is_enforced(self):
        self.install_fake(
            [
                '{"answer":42}',
                '{"verdict":"pass","reasons":[],"evidence":["schema checked"]}',
            ]
        )
        task = self.tasks.add(
            TaskContract(
                goal="Return structured answer",
                kind="agent",
                expected_output_schema={
                    "type": "object",
                    "required": ["answer"],
                    "additionalProperties": False,
                    "properties": {"answer": {"type": "integer"}},
                },
            )
        )
        result = self.app.runner.run(task["task_id"])
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(result["result"]["output"], {"answer": 42})

    def test_offline_pause_resume_reuses_checkpoints(self):
        task = self.tasks.add(TaskContract(goal="Needs provider", kind="agent"))
        paused = self.app.runner.run(task["task_id"])
        self.assertEqual(paused["state"], "paused_offline")
        self.assertEqual(len(self.tasks.steps(task["task_id"])), 2)
        self.install_fake(
            ["online answer", '{"verdict":"pass","reasons":[],"evidence":["reviewed"]}']
        )
        self.tasks.resume(task["task_id"])
        result = self.app.runner.run(task["task_id"])
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(len(self.tasks.steps(task["task_id"])), 4)

    def test_interrupted_inflight_requires_explicit_resume(self):
        task = self.add_smoke()
        self.tasks.transition(task["task_id"], TaskState.PLANNING)
        with self.assertRaises(UnavailableError):
            self.app.runner.run(task["task_id"])
        resumed = self.tasks.resume(task["task_id"])
        self.assertEqual(resumed["state"], "queued")
        self.assertEqual(self.app.runner.run(task["task_id"])["state"], "succeeded")

    def test_model_budget_cannot_be_exceeded(self):
        self.install_fake(["answer", "not-json"])
        task = self.tasks.add(
            TaskContract(goal="Answer", kind="agent", budget={"max_model_calls": 1})
        )
        result = self.app.runner.run(task["task_id"])
        self.assertEqual(result["state"], "failed")
        self.assertEqual(self.tasks.model_call_count(task["task_id"]), 1)
        self.assertIn("budget", result["error"]["message"])

    def test_run_all_executes_real_queue(self):
        first = self.add_smoke("one")
        second = self.add_smoke("two")
        results = self.app.runner.run_all()
        self.assertEqual({row["task_id"] for row in results}, {first["task_id"], second["task_id"]})
        self.assertTrue(all(row["state"] == "succeeded" for row in results))


if __name__ == "__main__":
    unittest.main()
