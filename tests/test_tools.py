from __future__ import annotations

import unittest

from tests.support import FactoryCase
from uaf.errors import PolicyDenied, UnavailableError, ValidationError
from uaf.models import TaskContract, ToolContext
from uaf.tools import validate_schema


class ToolTests(FactoryCase):
    def _task(self, tool="workspace.write", path="note.txt", content="hello"):
        arguments = (
            {"path": path} if tool == "workspace.delete" else {"path": path, "content": content}
        )
        return self.tasks.add(
            TaskContract(
                goal=f"Exercise {tool}",
                kind="tool",
                input_data={"tool": tool, "arguments": arguments},
                allowed_tools=[tool],
                risk_tier="R3" if tool == "workspace.delete" else "R1",
            )
        )

    def test_write_read_list_and_postcondition(self):
        task = self._task()
        result = self.app.runner.run(task["task_id"])
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual((self.workspace / "note.txt").read_text(), "hello")
        read_task = self.tasks.add(
            TaskContract(
                goal="read",
                kind="tool",
                input_data={"tool": "workspace.read", "arguments": {"path": "note.txt"}},
                allowed_tools=["workspace.read"],
            )
        )
        read_result = self.app.runner.run(read_task["task_id"])
        self.assertEqual(read_result["result"]["output"]["content"], "hello")

    def test_list_truncation_is_true_only_when_visible_entries_remain(self):
        for name in ("a.txt", "b.txt"):
            (self.workspace / name).write_text(name, encoding="utf-8")
        exact = self.app.workspace.list(limit=2)
        self.assertEqual(len(exact["entries"]), 2)
        self.assertFalse(exact["truncated"])
        (self.workspace / "c.txt").write_text("c", encoding="utf-8")
        remaining = self.app.workspace.list(limit=2)
        self.assertEqual(len(remaining["entries"]), 2)
        self.assertTrue(remaining["truncated"])

    def test_path_traversal_absolute_and_sensitive_paths_denied(self):
        for path in ("../outside", "/etc/passwd", "C:\\Windows\\win.ini", ".env", ".git/config"):
            with self.subTest(path=path), self.assertRaises(ValidationError):
                self.app.workspace.read_text(path)

    def test_symlink_escape_denied(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("outside")
        link = self.workspace / "link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation unavailable on this platform")
        with self.assertRaises(ValidationError):
            self.app.workspace.read_text("link/secret.txt")

    def test_disconnected_workspace_pauses_instead_of_redirect(self):
        missing = self.app.workspace.__class__(self.root / "removed-usb", self.paths.file_backups)
        with self.assertRaises(UnavailableError):
            missing.write_text("file.txt", "must not redirect")

    def test_task_allowlist_and_role_are_enforced(self):
        task = self._task()
        context = ToolContext(task_id=task["task_id"], role="reviewer", step_id="s")
        with self.assertRaises(PolicyDenied):
            self.app.tools.invoke(
                "workspace.write",
                context,
                {"path": "note.txt", "content": "hello"},
                task_allowed_tools=["workspace.write"],
            )
        worker = ToolContext(task_id=task["task_id"], role="worker", step_id="s")
        with self.assertRaises(PolicyDenied):
            self.app.tools.invoke(
                "workspace.write",
                worker,
                {"path": "note.txt", "content": "hello"},
                task_allowed_tools=[],
            )
        self.assertFalse((self.workspace / "note.txt").exists())

    def test_r3_approval_resume_and_backup(self):
        (self.workspace / "note.txt").write_text("delete me")
        task = self._task("workspace.delete", "note.txt", "")
        waiting = self.app.runner.run(task["task_id"])
        self.assertEqual(waiting["state"], "awaiting_approval")
        self.assertTrue((self.workspace / "note.txt").exists())
        approval = self.app.approvals.require(waiting["approval_id"])
        with self.assertRaises(PolicyDenied):
            self.app.approvals.decide(approval["approval_id"], approve=True, actor="worker")
        self.app.approvals.decide(approval["approval_id"], approve=True, actor="human")
        self.tasks.resume(task["task_id"])
        result = self.app.runner.run(task["task_id"])
        self.assertEqual(result["state"], "succeeded")
        self.assertFalse((self.workspace / "note.txt").exists())
        self.assertTrue(result["result"]["evidence"]["reversible_backup"])

    def test_approval_rejection_prevents_side_effect(self):
        (self.workspace / "note.txt").write_text("keep")
        task = self._task("workspace.delete", "note.txt", "")
        waiting = self.app.runner.run(task["task_id"])
        self.app.approvals.decide(waiting["approval_id"], approve=False, actor="human", reason="no")
        failed = self.tasks.resume(task["task_id"])
        self.assertEqual(failed["state"], "failed")
        self.assertEqual((self.workspace / "note.txt").read_text(), "keep")

    def test_schema_rejects_unknown_and_wrong_types(self):
        schema = {
            "type": "object",
            "required": ["count"],
            "additionalProperties": False,
            "properties": {"count": {"type": "integer", "minimum": 1}},
        }
        validate_schema({"count": 1}, schema)
        for value in ({"count": True}, {"count": 0}, {"count": 1, "extra": 2}, {}):
            with self.assertRaises(ValidationError):
                validate_schema(value, schema)


if __name__ == "__main__":
    unittest.main()
