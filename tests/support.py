from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any

from uaf.agents import AgentRuntime
from uaf.app import Application
from uaf.config import AppPaths
from uaf.providers import GenerateResponse, Health, ProviderService
from uaf.util import utc_now


class _FakeWinVault:
    pass


_FakeWinVault.__module__ = "keyring.backends.Windows"


class FakeKeyring:
    def __init__(self) -> None:
        self.backend = _FakeWinVault()
        self.values: dict[tuple[str, str], str] = {}

    def get_keyring(self):
        return self.backend

    def set_password(self, service, username, value):
        self.values[(service, username)] = value

    def get_password(self, service, username):
        return self.values.get((service, username))

    def delete_password(self, service, username):
        del self.values[(service, username)]


class FakeAdapter:
    name = "gemini"

    def __init__(self, responses: list[Any] | None = None) -> None:
        self.responses = list(responses or ["worker answer"])
        self.calls = []

    def capabilities(self, spec):
        return spec.capabilities

    def health_check(self, spec, api_key):
        return Health("configured", "fake adapter; no network", utc_now())

    def generate(self, spec, request, api_key):
        self.calls.append((spec, request, api_key))
        value = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(value, Exception):
            raise value
        if callable(value):
            value = value(request)
        return GenerateResponse(str(value), self.name, spec.model, 10, 5, 3, {"fake": True})


class FactoryCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.paths = AppPaths.discover(self.root / "home")
        self.workspace = self.root / "workspace"
        self.app = Application(self.paths)
        self.app.config.initialize(self.workspace)
        # Recreate only workspace-dependent state after explicit test workspace setup.
        from uaf.tools import build_tool_registry
        from uaf.workspace import Workspace

        self.app.settings.workspace = str(self.workspace)
        self.workspace.mkdir(exist_ok=True)
        self.app.workspace = Workspace(self.workspace, self.paths.file_backups)
        self.app.tools = build_tool_registry(
            self.app.db, self.app.approvals, self.app.ledger, self.app.workspace
        )
        from uaf.browser import browser_tools
        from uaf.desktop import desktop_tool

        for tool in browser_tools(self.app.browser):
            self.app.tools.register(tool)
        self.app.tools.register(desktop_tool(self.app.desktop))
        self.app.runner.tools = self.app.tools
        self.app.evaluations.workspace = self.app.workspace
        self.db = self.app.db
        self.tasks = self.app.tasks

    def tearDown(self) -> None:
        self.app.close()
        self.temporary.cleanup()

    def install_fake(
        self, adapter: FakeAdapter | list[Any] | None = None, **model_config: Any
    ) -> FakeAdapter:
        if isinstance(adapter, list):
            adapter = FakeAdapter(adapter)
        adapter = adapter or FakeAdapter()
        self.app.settings.network_allowed = True
        self.app.settings.providers["gemini"].update(
            {
                "enabled": True,
                "models": {
                    "fake-free": {
                        "enabled": True,
                        "free_tier_status": "free",
                        "free_tier_source": "https://ai.google.dev/gemini-api/docs/pricing",
                        "verified_at": date.today().isoformat(),
                        "capabilities": ["text", "json", "coding"],
                        **model_config,
                    }
                },
            }
        )
        service = ProviderService(
            self.app.settings,
            self.db,
            environ={"GEMINI_API_KEY": "test-secret"},
            adapters={"gemini": adapter},
            sleep=lambda _: None,
        )
        self.app.providers = service
        self.app.agents = AgentRuntime(service, self.tasks, experience=self.app.experience)
        self.app.runner.agents = self.app.agents
        return adapter

    def add_smoke(self, goal: str = "Run durable test"):
        from uaf.models import TaskContract

        return self.tasks.add(TaskContract(goal=goal, kind="smoke"))
