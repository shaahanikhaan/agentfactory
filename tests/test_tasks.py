from __future__ import annotations

import unittest

from tests.support import FactoryCase
from uaf.errors import IdempotencyConflict, StateTransitionError, UnavailableError
from uaf.models import TaskContract, TaskState


class TaskTests(FactoryCase):
    def test_idempotent_add_and_payload_conflict(self):
        contract = TaskContract(goal="same", kind="smoke", idempotency_key="stable")
        first = self.tasks.add(contract)
        second = self.tasks.add(contract)
        self.assertEqual(first["task_id"], second["task_id"])
        with self.assertRaises(IdempotencyConflict):
            self.tasks.add(TaskContract(goal="different", kind="smoke", idempotency_key="stable"))

    def test_illegal_transition_is_rejected(self):
        task = self.add_smoke()
        with self.assertRaises(StateTransitionError):
            self.tasks.transition(task["task_id"], TaskState.SUCCEEDED)
        self.assertEqual(self.tasks.require(task["task_id"])["state"], "queued")

    def test_dependencies_gate_queue(self):
        parent = self.add_smoke("parent")
        child = self.tasks.add(
            TaskContract(goal="child", kind="smoke", depends_on=[parent["task_id"]])
        )
        runnable = {row["task_id"] for row in [self.tasks.next_runnable()] if row}
        self.assertIn(parent["task_id"], runnable)
        self.assertNotIn(child["task_id"], runnable)
        self.app.runner.run(parent["task_id"])
        self.assertTrue(self.tasks.dependencies_satisfied(child["task_id"]))

    def test_cancel_and_explicit_resume(self):
        task = self.add_smoke()
        cancelled = self.tasks.cancel(task["task_id"])
        self.assertEqual(cancelled["state"], "cancelled")
        resumed = self.tasks.resume(task["task_id"])
        self.assertEqual(resumed["state"], "queued")
        self.assertEqual(self.app.runner.run(task["task_id"])["state"], "succeeded")

    def test_checkpoint_cannot_be_overwritten(self):
        task = self.add_smoke()
        values = dict(
            step_id="stable", sequence=1, role="worker", input_data={"x": 1}, result={"y": 2}
        )
        self.tasks.checkpoint(task["task_id"], **values)
        self.tasks.checkpoint(task["task_id"], **values)
        with self.assertRaises(StateTransitionError):
            self.tasks.checkpoint(task["task_id"], **{**values, "result": {"y": 3}})

    def test_uncertain_task_cannot_blindly_resume(self):
        task = self.add_smoke()
        self.tasks.transition(task["task_id"], TaskState.PLANNING)
        self.tasks.transition(task["task_id"], TaskState.RUNNING)
        self.tasks.transition(task["task_id"], TaskState.UNCERTAIN_SIDE_EFFECT)
        with self.assertRaises(UnavailableError):
            self.tasks.resume(task["task_id"])


if __name__ == "__main__":
    unittest.main()
