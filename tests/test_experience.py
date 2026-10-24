from __future__ import annotations

import unittest

from tests.support import FactoryCase
from uaf.errors import PolicyDenied
from uaf.models import TaskContract

PASS_REVIEW = '{"verdict":"pass","reasons":[],"evidence":["checked"]}'


class ExperienceTests(FactoryCase):
    def test_capture_is_pending_idempotent_and_human_approval_enables_recall(self):
        task = self.add_smoke("parser retry policy")
        result = self.app.runner.run(task["task_id"])
        self.assertEqual(result["state"], "succeeded")
        captured = self.app.experience.list()
        self.assertEqual(len(captured), 1)
        memory_id = captured[0]["memory_id"]
        self.assertEqual(captured[0]["approval_status"], "pending")
        self.assertEqual(self.app.experience.recall("parser retry policy"), [])

        self.app.runner.run(task["task_id"])
        self.assertEqual(len(self.app.experience.list()), 1)
        self.assertEqual(
            self.db.one("SELECT COUNT(*) c FROM experience_captures")["c"],
            1,
        )
        with self.assertRaises(PolicyDenied):
            self.app.experience.approve(memory_id, actor="worker")

        approved = self.app.experience.approve(memory_id, actor="local-user")
        self.assertEqual(approved["approval_status"], "approved")
        recalled = self.app.experience.recall("parser retry policy")
        self.assertEqual([item["memory_id"] for item in recalled], [memory_id])

        adapter = self.install_fake(["fresh answer", PASS_REVIEW])
        agent_task = self.tasks.add(TaskContract(goal="parser retry policy", kind="agent"))
        completed = self.app.runner.run(agent_task["task_id"])
        self.assertEqual(completed["state"], "succeeded")
        worker_prompt = adapter.calls[0][1].prompt
        self.assertIn("approved-task-experience", worker_prompt)
        self.assertIn(memory_id, worker_prompt)
        self.assertIn("EXTERNAL_UNTRUSTED_CONTENT", worker_prompt)

    def test_sensitive_capture_is_skipped_without_blocking_task_or_recapture(self):
        secret = "AIza" + "s" * 32
        task = self.add_smoke(f"Inspect credential {secret}")
        result = self.app.runner.run(task["task_id"])
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(self.app.experience.list(), [])
        capture = self.db.one("SELECT * FROM experience_captures")
        self.assertEqual(capture["status"], "skipped_sensitive")
        self.assertNotIn(secret, str(self.db.query("SELECT content FROM memory_items")))

        replay = self.app.experience.capture_task(result)
        self.assertEqual(replay["status"], "replayed")
        self.assertEqual(self.db.one("SELECT COUNT(*) c FROM experience_captures")["c"], 1)

    def test_privacy_delete_is_not_undone_by_terminal_task_replay(self):
        task = self.add_smoke("delete durable experience")
        result = self.app.runner.run(task["task_id"])
        memory_id = self.app.experience.list()[0]["memory_id"]
        self.app.experience.approve(memory_id, actor="local-user")
        self.app.memory.delete(memory_id, actor="local-user", confirmed=True)

        replay = self.app.experience.capture_task(result)
        self.assertEqual(replay["status"], "replayed")
        self.assertEqual(replay["memory_id"], memory_id)
        self.assertEqual(self.db.one("SELECT COUNT(*) c FROM memory_items")["c"], 1)
        self.assertEqual(self.app.experience.recall("delete durable experience"), [])

    def test_private_records_and_task_opt_out_never_enter_model_context(self):
        self.app.memory.add(
            "private parser retry policy note",
            memory_type="task",
            sensitivity="private",
            approved=True,
            provenance={"capture": "task_outcome_v1", "outcome": "failed"},
        )
        self.assertEqual(self.app.experience.recall("parser retry policy"), [])

        task = self.add_smoke("memory free startup goal")
        self.app.runner.run(task["task_id"])
        memory_id = next(
            item["memory_id"]
            for item in self.app.experience.list()
            if item["task_id"] == task["task_id"]
        )
        self.app.experience.approve(memory_id, actor="local-user")
        adapter = self.install_fake(["private answer", PASS_REVIEW])
        opted_out = self.tasks.add(
            TaskContract(
                goal="memory free startup goal",
                kind="agent",
                input_data={"memory_recall": False},
            )
        )
        self.app.runner.run(opted_out["task_id"])
        prompt = adapter.calls[0][1].prompt
        self.assertNotIn("approved-task-experience", prompt)
        self.assertNotIn(memory_id, prompt)

    def test_failed_attempt_is_real_experience_not_a_success_claim(self):
        task = self.add_smoke("record failed review")
        original = self.app.agents.smoke_reviewer
        self.app.agents.smoke_reviewer = lambda _task, _worker: {
            "verdict": "fail",
            "reasons": ["deliberate test rejection"],
            "evidence": [],
        }
        try:
            result = self.app.runner.run(task["task_id"])
        finally:
            self.app.agents.smoke_reviewer = original
        self.assertEqual(result["state"], "failed")
        experience = self.app.experience.list()
        self.assertEqual(len(experience), 1)
        self.assertEqual(experience[0]["outcome"], "failed")
        self.assertIn("Historical task outcome: failed", experience[0]["content"])


if __name__ == "__main__":
    unittest.main()
