from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.support import FactoryCase
from uaf.browser import BrowserService, browser_tools, validate_public_host
from uaf.config import Settings
from uaf.errors import PolicyDenied, SideEffectError, ValidationError
from uaf.models import RiskTier, TaskContract
from uaf.tools import build_tool_registry
from uaf.util import canonical_json


class FakeLocator:
    def __init__(self, page, ref):
        self.page = page
        self.ref = ref
        self.click_calls = 0
        self.fill_calls = []
        self.click_error = None
        self.attributes = {"type": "text", "autocomplete": "off"}

    def count(self):
        element = next((item for item in self.page.elements if item["ref"] == self.ref), None)
        return int(
            element is not None
            and self.page.current_snapshot is not None
            and f'data-uaf-snapshot="{self.page.current_snapshot}"' in self.page.last_selector
        )

    def click(self, *, timeout):
        self.click_calls += 1
        if self.click_error:
            raise self.click_error

    def fill(self, text, *, timeout):
        self.fill_calls.append(text)
        if self.page.close_on_fill:
            self.page.closed = True

    def get_attribute(self, name):
        return self.attributes.get(name)


class FakePage:
    def __init__(self):
        self.url = "https://example.com/start"
        self.title_text = "Example"
        self.closed = False
        self.current_snapshot = None
        self.last_selector = ""
        self.elements = [
            {
                "ref": 1,
                "tag": "button",
                "type": "",
                "text": "Send message",
                "aria_label": "",
                "placeholder": "",
            }
        ]
        self.body_text = "Visible page text"
        self.close_on_fill = False
        self.locators = {}
        self.redirect_to = None
        self.goto_calls = []

    def is_closed(self):
        return self.closed

    def title(self):
        return self.title_text

    def goto(self, url, *, wait_until):
        self.goto_calls.append(url)
        self.url = self.redirect_to or url

    def evaluate(self, script, snapshot_id=None):
        if snapshot_id is None:
            return {"text": self.body_text, "elements": copy.deepcopy(self.elements)}
        self.current_snapshot = snapshot_id
        return None

    def locator(self, selector):
        self.last_selector = selector
        ref = int(selector.split('data-uaf-ref="')[1].split('"')[0])
        locator = self.locators.get(ref)
        if locator is None:
            locator = FakeLocator(self, ref)
            self.locators[ref] = locator
        self.last_selector = selector
        return locator

    def wait_for_timeout(self, milliseconds):
        return None


class FakeContext:
    def __init__(self, page):
        self.pages = [page]
        self.routes = []
        self.closed = False

    def set_default_timeout(self, value):
        self.timeout = value

    def set_default_navigation_timeout(self, value):
        self.navigation_timeout = value

    def route(self, pattern, callback):
        self.routes.append((pattern, callback))

    def new_page(self):
        return self.pages[0]

    def close(self):
        self.closed = True


class FakePlaywright:
    def __init__(self, context):
        self.context = context
        self.chromium = self
        self.launch_kwargs = None
        self.stopped = False

    def launch_persistent_context(self, **kwargs):
        self.launch_kwargs = kwargs
        return self.context

    def stop(self):
        self.stopped = True


class BrowserServiceTests(unittest.TestCase):
    def setUp(self):
        self.page = FakePage()
        self.context = FakeContext(self.page)
        self.settings = Settings(
            workspace="/tmp/workspace",
            network_allowed=True,
            browser_enabled=True,
            browser_allowed_domains=["example.com"],
        )
        self.service = BrowserService(
            self.settings,
            Path("/tmp/profile"),
            context_factory=lambda: self.context,
            host_validator=lambda hostname: None,
            sleep=lambda seconds: None,
        )

    def tearDown(self):
        self.service.close()

    def payload(self, snapshot, **extra):
        return {
            "url": snapshot["url"],
            "snapshot_id": snapshot["snapshot_id"],
            "ref": 1,
            "expected_label": "Send message",
            **extra,
        }

    def test_real_adapter_launch_contract_is_visible_and_dedicated(self):
        playwright = FakePlaywright(self.context)
        factory = SimpleNamespace(start=lambda: playwright)
        module = SimpleNamespace(sync_playwright=lambda: factory)
        with tempfile.TemporaryDirectory() as temporary:
            service = BrowserService(
                self.settings,
                Path(temporary) / "dedicated-profile",
                host_validator=lambda hostname: None,
            )
            with patch("uaf.browser.importlib.import_module", return_value=module):
                service._ensure_context()
            kwargs = playwright.launch_kwargs
            self.assertFalse(kwargs["headless"])
            self.assertFalse(kwargs["accept_downloads"])
            self.assertEqual(kwargs["permissions"], [])
            self.assertEqual(kwargs["service_workers"], "block")
            self.assertEqual(kwargs["user_data_dir"], str(service.profile_dir))
            self.assertTrue(service.profile_dir.is_dir())
            service.close()
            self.assertTrue(playwright.stopped)

    def test_disabled_browser_and_unsafe_urls_fail_before_launch(self):
        self.settings.browser_enabled = False
        with self.assertRaises(PolicyDenied):
            self.service.navigate("https://example.com")
        self.assertEqual(self.page.goto_calls, [])
        self.settings.browser_enabled = True
        unsafe = [
            "http://example.com",
            "https://evil.example",
            "https://example.com@127.0.0.1/",
            "https://example.com/api-keys",
            "https://example.com/?api_key=secret",
            "https://example.com:444/",
            "https://example.com:not-a-port/",
        ]
        for url in unsafe:
            with self.subTest(url=url), self.assertRaises((PolicyDenied, ValidationError)):
                self.service.navigate(url)
        self.assertEqual(self.page.goto_calls, [])

    def test_non_public_dns_addresses_are_denied(self):
        with patch(
            "uaf.browser.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("127.0.0.1", 443))],
        ), self.assertRaises(PolicyDenied):
            validate_public_host("example.com")

    def test_snapshot_is_redacted_bounded_and_supports_exact_click(self):
        self.page.body_text = "token: supersecret\n" + "x" * 20000
        self.service.navigate("https://example.com/start")
        snapshot = self.service.snapshot()
        self.assertNotIn("supersecret", snapshot["text"])
        self.assertLessEqual(len(snapshot["text"]), 12000)
        result = self.service.click(self.payload(snapshot))
        self.assertTrue(result["postcondition"])
        self.assertEqual(self.page.locators[1].click_calls, 1)

    def test_wrong_label_stale_snapshot_and_redirect_are_denied(self):
        snapshot = self.service.snapshot()
        with self.assertRaises(PolicyDenied):
            self.service.click(self.payload(snapshot, expected_label="Wrong button"))
        self.assertEqual(self.page.locators, {})
        self.page.body_text += "\nPage changed"
        self.service.snapshot()
        with self.assertRaises(PolicyDenied):
            self.service.click(self.payload(snapshot))
        self.assertEqual(self.page.locators, {})
        self.page.redirect_to = "https://evil.example/redirect"
        with self.assertRaises(PolicyDenied):
            self.service.navigate("https://example.com/start")

    def test_password_secret_text_and_uncertain_click_are_conservative(self):
        snapshot = self.service.snapshot()
        locator = self.service._locator(self.payload(snapshot))
        locator.attributes["type"] = "password"
        with self.assertRaises(PolicyDenied):
            self.service.type(self.payload(snapshot, text="not-written"))
        self.assertEqual(locator.fill_calls, [])
        locator.attributes["type"] = "text"
        with self.assertRaises(ValidationError):
            self.service.type(self.payload(snapshot, text="token: supersecret"))
        locator.click_error = RuntimeError("simulated driver failure")
        with self.assertRaises(SideEffectError) as caught:
            self.service.click(self.payload(snapshot))
        self.assertTrue(caught.exception.uncertain)

    def test_post_fill_inspection_failure_is_uncertain(self):
        snapshot = self.service.snapshot()
        self.page.close_on_fill = True
        with self.assertRaises(SideEffectError) as caught:
            self.service.type(self.payload(snapshot, text="typed once"))
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(self.page.locators[1].fill_calls, ["typed once"])

    def test_snapshot_output_stays_inside_registry_budget(self):
        self.page.elements = [
            {
                "ref": index,
                "tag": "button",
                "type": "",
                "text": "x" * 300,
                "aria_label": "y" * 200,
                "placeholder": "z" * 200,
            }
            for index in range(1, 81)
        ]
        snapshot = self.service.snapshot()
        self.assertLess(len(canonical_json(snapshot)), 32000)
        self.assertLess(len(snapshot["elements"]), 80)

    def test_manual_session_wait_is_bounded(self):
        with self.assertRaises(ValidationError):
            self.service.open_for_user("https://example.com", wait_seconds=301)
        result = self.service.open_for_user("https://example.com", wait_seconds=1)
        self.assertTrue(result["snapshot_id"].startswith("snapshot_"))


class BrowserToolApprovalTests(FactoryCase):
    def setUp(self):
        super().setUp()
        self.page = FakePage()
        self.context = FakeContext(self.page)
        self.app.settings.network_allowed = True
        self.app.settings.browser_enabled = True
        self.app.settings.browser_allowed_domains = ["example.com"]
        self.app.browser = BrowserService(
            self.app.settings,
            self.paths.browser_profile,
            context_factory=lambda: self.context,
            host_validator=lambda hostname: None,
        )
        self.app.tools = build_tool_registry(
            self.db, self.app.approvals, self.app.ledger, self.app.workspace
        )
        for tool in browser_tools(self.app.browser):
            self.app.tools.register(tool)
        self.app.runner.tools = self.app.tools

    def test_click_is_r3_and_resume_revalidates_after_browser_restart(self):
        snapshot = self.app.browser.snapshot()
        payload = {
            "url": snapshot["url"],
            "snapshot_id": snapshot["snapshot_id"],
            "ref": 1,
            "expected_label": "Send message",
        }
        task = self.tasks.add(
            TaskContract(
                goal="Send an explicitly approved browser action",
                kind="tool",
                risk_tier=RiskTier.R3,
                input_data={"tool": "browser.click", "arguments": payload},
                allowed_tools=["browser.click"],
            )
        )
        waiting = self.app.runner.run(task["task_id"])
        self.assertEqual(waiting["state"], "awaiting_approval")
        self.assertEqual(self.page.locators, {})
        approval = self.app.approvals.require(waiting["approval_id"])
        self.assertEqual(approval["risk_tier"], "R3")
        self.assertEqual(approval["payload"]["expected_label"], "Send message")
        self.app.approvals.decide(waiting["approval_id"], approve=True, actor="human")

        # Simulate CLI/process exit while approval is pending. The approved digest must
        # be revalidated against a fresh page, not trusted from process memory.
        self.app.browser.close()
        self.page = FakePage()
        self.page.url = "about:blank"
        self.context = FakeContext(self.page)
        self.app.browser = BrowserService(
            self.app.settings,
            self.paths.browser_profile,
            context_factory=lambda: self.context,
            host_validator=lambda hostname: None,
        )
        self.app.tools = build_tool_registry(
            self.db, self.app.approvals, self.app.ledger, self.app.workspace
        )
        for tool in browser_tools(self.app.browser):
            self.app.tools.register(tool)
        self.app.runner.tools = self.app.tools

        self.tasks.resume(task["task_id"])
        result = self.app.runner.run(task["task_id"])
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(self.page.goto_calls, [snapshot["url"]])
        self.assertEqual(self.page.locators[1].click_calls, 1)

    def test_unavailable_browser_does_not_fake_success(self):
        self.app.settings.browser_enabled = False
        with self.assertRaises(PolicyDenied):
            self.app.browser.snapshot()
        self.assertFalse(self.context.closed)


if __name__ == "__main__":
    unittest.main()
