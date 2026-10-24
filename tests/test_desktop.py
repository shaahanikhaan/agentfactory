from __future__ import annotations

import unittest

from tests.support import FactoryCase
from uaf.config import Settings
from uaf.desktop import DesktopService, desktop_tool
from uaf.errors import PolicyDenied, SideEffectError, UnavailableError, ValidationError
from uaf.models import RiskTier, TaskContract
from uaf.tools import build_tool_registry


class FakeWindow:
    def __init__(self, driver, title, handle, process="C:\\Apps\\notepad.exe"):
        self.driver = driver
        self.title = title
        self._hWnd = handle
        self.process = process
        self.activations = 0

    def activate(self):
        self.activations += 1
        self.driver.active = self


class FakeDesktopDriver:
    def __init__(self):
        self.FAILSAFE = False
        self.PAUSE = 0
        self.windows = []
        self.active = None
        self.calls = []
        self.on_write = None
        self.target = self.add_window("Untitled - Notepad", 1)

    def add_window(self, title, handle, process="C:\\Apps\\notepad.exe"):
        window = FakeWindow(self, title, handle, process)
        self.windows.append(window)
        return window

    def getAllWindows(self):
        return self.windows

    def getActiveWindow(self):
        return self.active

    def size(self):
        return (800, 600)

    def moveTo(self, x, y, *, duration):
        self.calls.append(("move", x, y, duration))

    def click(self, *, x, y, clicks, button):
        self.calls.append(("click", x, y, clicks, button))

    def write(self, text, *, interval):
        self.calls.append(("type", text, interval))
        if self.on_write:
            self.on_write()

    def press(self, key):
        self.calls.append(("press", key))

    def hotkey(self, *keys):
        self.calls.append(("hotkey", *keys))

    def scroll(self, clicks):
        self.calls.append(("scroll", clicks))


class DesktopServiceTests(unittest.TestCase):
    def setUp(self):
        self.driver = FakeDesktopDriver()
        self.settings = Settings(
            workspace="/tmp/workspace",
            desktop_enabled=True,
            desktop_allowed_applications=["notepad.exe"],
        )
        self.service = DesktopService(
            self.settings,
            driver=self.driver,
            platform_name="nt",
            process_resolver=lambda window: window.process,
            sleep=lambda seconds: None,
        )

    def payload(self, actions):
        return {
            "application": "notepad.exe",
            "window_title": "Untitled - Notepad",
            "actions": actions,
        }

    def test_exact_window_batch_and_mandatory_fail_safe(self):
        result = self.service.execute(
            self.payload(
                [
                    {"kind": "move", "x": 10, "y": 20},
                    {"kind": "click", "x": 10, "y": 20, "clicks": 1},
                    {"kind": "type", "text": "hello"},
                    {"kind": "hotkey", "keys": ["ctrl", "s"]},
                    {"kind": "scroll", "clicks": -2},
                    {"kind": "wait", "milliseconds": 50},
                ]
            )
        )
        self.assertEqual(result["executed_actions"], 6)
        self.assertTrue(result["postcondition"])
        self.assertTrue(self.driver.FAILSAFE)
        self.assertEqual(self.driver.PAUSE, 0.15)
        self.assertEqual(self.driver.target.activations, 1)
        self.assertEqual(self.driver.calls[2], ("type", "hello", 0.02))

    def test_invalid_actions_are_rejected_before_window_activation(self):
        invalid = [
            [{"kind": "click", "x": 900, "y": 20}],
            [{"kind": "type", "text": "Salām"}],
            [{"kind": "type", "text": "x" * 1001}],
            [{"kind": "type", "text": "token: supersecret"}],
            [{"kind": "hotkey", "keys": ["ctrl", "v"]}],
            [{"kind": "hotkey", "keys": ["alt", "f4"]}],
            [{"kind": "hotkey", "keys": ["delete", "alt", "ctrl"]}],
            [{"kind": "wait", "milliseconds": 5000}],
            [{"kind": "press", "key": "enter"}] * 13,
        ]
        for actions in invalid:
            with self.subTest(actions=actions), self.assertRaises(
                (ValidationError, PolicyDenied)
            ):
                self.service.execute(self.payload(actions))
        self.assertEqual(self.driver.target.activations, 0)
        self.assertEqual(self.driver.calls, [])

    def test_wrong_or_ambiguous_window_is_denied(self):
        with self.assertRaises(PolicyDenied):
            self.service.execute(
                {
                    "application": "other.exe",
                    "window_title": "Untitled - Notepad",
                    "actions": [{"kind": "press", "key": "enter"}],
                }
            )
        self.driver.add_window("Untitled - Notepad", 2)
        with self.assertRaises(PolicyDenied):
            self.service.execute(self.payload([{"kind": "press", "key": "enter"}]))
        self.assertEqual(self.driver.calls, [])

    def test_focus_change_marks_partial_batch_uncertain(self):
        other = self.driver.add_window("Other", 2, "C:\\Apps\\other.exe")
        self.driver.on_write = lambda: setattr(self.driver, "active", other)
        with self.assertRaises(SideEffectError) as caught:
            self.service.execute(
                self.payload(
                    [{"kind": "type", "text": "partial"}, {"kind": "press", "key": "enter"}]
                )
            )
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(self.driver.calls, [("type", "partial", 0.02)])

    def test_disabled_or_non_windows_host_fails_closed(self):
        self.settings.desktop_enabled = False
        with self.assertRaises(PolicyDenied):
            self.service.execute(self.payload([{"kind": "press", "key": "enter"}]))
        self.settings.desktop_enabled = True
        service = DesktopService(self.settings, platform_name="posix")
        with self.assertRaises(UnavailableError):
            service.execute(self.payload([{"kind": "press", "key": "enter"}]))

    def test_shell_browser_and_remote_apps_are_not_allowlistable(self):
        for application in ("cmd.exe", "powershell.exe", "chrome.exe", "anydesk.exe"):
            with self.subTest(application=application), self.assertRaises(ValidationError):
                Settings(
                    workspace="/tmp/workspace",
                    desktop_allowed_applications=[application],
                ).validate()


class DesktopToolApprovalTests(FactoryCase):
    def setUp(self):
        super().setUp()
        self.driver = FakeDesktopDriver()
        self.app.settings.desktop_enabled = True
        self.app.settings.desktop_allowed_applications = ["notepad.exe"]
        self.app.desktop = DesktopService(
            self.app.settings,
            driver=self.driver,
            platform_name="nt",
            process_resolver=lambda window: window.process,
            sleep=lambda seconds: None,
        )
        self.app.tools = build_tool_registry(
            self.db, self.app.approvals, self.app.ledger, self.app.workspace
        )
        self.app.tools.register(desktop_tool(self.app.desktop))
        self.app.runner.tools = self.app.tools

    def task(self):
        return self.tasks.add(
            TaskContract(
                goal="Execute one approved desktop batch",
                kind="tool",
                risk_tier=RiskTier.R3,
                input_data={
                    "tool": "desktop.execute",
                    "arguments": {
                        "application": "notepad.exe",
                        "window_title": "Untitled - Notepad",
                        "actions": [
                            {"kind": "type", "text": "approved text"},
                            {"kind": "press", "key": "enter"},
                        ],
                    },
                },
                allowed_tools=["desktop.execute"],
            )
        )

    def approve(self, task):
        waiting = self.app.runner.run(task["task_id"])
        self.assertEqual(waiting["state"], "awaiting_approval")
        self.assertEqual(self.driver.calls, [])
        self.app.approvals.decide(waiting["approval_id"], approve=True, actor="human")
        self.tasks.resume(task["task_id"])

    def test_r3_approval_precedes_real_adapter_call(self):
        task = self.task()
        self.approve(task)
        result = self.app.runner.run(task["task_id"])
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(self.driver.calls[0], ("type", "approved text", 0.02))
        self.assertEqual(self.driver.calls[1], ("press", "enter"))

    def test_partial_failure_requires_reconciliation_not_resume_retry(self):
        other = self.driver.add_window("Other", 2, "C:\\Apps\\other.exe")
        self.driver.on_write = lambda: setattr(self.driver, "active", other)
        task = self.task()
        self.approve(task)
        result = self.app.runner.run(task["task_id"])
        self.assertEqual(result["state"], "uncertain_side_effect")
        self.assertEqual(self.driver.calls, [("type", "approved text", 0.02)])
        ledger = self.db.one(
            "SELECT state,key FROM idempotency_ledger WHERE scope=?",
            (f"task:{task['task_id']}",),
        )
        self.assertEqual(ledger["state"], "uncertain")
        with self.assertRaises(UnavailableError):
            self.tasks.resume(task["task_id"])
        self.assertEqual(self.driver.calls, [("type", "approved text", 0.02)])

        self.app.ledger.reconcile(
            scope=f"task:{task['task_id']}",
            key=ledger["key"],
            observed=True,
            evidence={"note": "Human verified the complete batch in Notepad"},
            result={
                "output": {
                    "application": "notepad.exe",
                    "window_title": "Untitled - Notepad",
                    "executed_actions": 2,
                    "postcondition": True,
                },
                "evidence": {"reconciled": True},
            },
            actor="local-human",
        )
        self.tasks.resume(task["task_id"])
        recovered = self.app.runner.run(task["task_id"])
        self.assertEqual(recovered["state"], "succeeded")
        self.assertEqual(recovered["result"]["output"]["executed_actions"], 2)
        self.assertEqual(self.driver.calls, [("type", "approved text", 0.02)])


if __name__ == "__main__":
    unittest.main()
