"""Composition root; keeps CLI, MCP, and future UI on the same governed services."""

from __future__ import annotations

from uaf.agents import AgentRuntime
from uaf.approvals import ApprovalService
from uaf.backup import BackupManager
from uaf.blueprints import BlueprintRegistry
from uaf.browser import BrowserService, browser_tools
from uaf.config import AppPaths, ConfigManager, Settings
from uaf.credentials import CredentialStore
from uaf.db import Database
from uaf.desktop import DesktopService, desktop_tool
from uaf.diagnostics import Diagnostics
from uaf.evaluations import EvaluationService
from uaf.factory import FactoryService
from uaf.idempotency import IdempotencyLedger
from uaf.memory import MemoryStore
from uaf.plugins import PluginManager
from uaf.providers import ProviderService
from uaf.research import ResearchFetcher
from uaf.runner import TaskRunner
from uaf.skills import SkillLibrary
from uaf.tasks import TaskStore
from uaf.tools import build_tool_registry
from uaf.workspace import Workspace


class Application:
    def __init__(self, paths: AppPaths, *, verbose: bool = False) -> None:
        self.paths = paths
        self.config = ConfigManager(paths)
        self.settings: Settings = self.config.load()
        self.db = Database(paths.database, backup_dir=paths.backups)
        self.db.migrate()
        self.backups = BackupManager(self.db, paths.backups)
        self.tasks = TaskStore(self.db, self.settings.budgets)
        self.approvals = ApprovalService(self.db)
        self.ledger = IdempotencyLedger(self.db)
        self.workspace = Workspace(
            self.settings.workspace_path,
            paths.file_backups,
            max_bytes=self.settings.budgets.max_tool_output_chars * 32,
        )
        self.tools = build_tool_registry(
            self.db,
            self.approvals,
            self.ledger,
            self.workspace,
            max_output_chars=self.settings.budgets.max_tool_output_chars,
        )
        self.credentials = CredentialStore()
        self.browser = BrowserService(self.settings, paths.browser_profile)
        self.desktop = DesktopService(self.settings)
        for tool in browser_tools(self.browser):
            self.tools.register(tool)
        self.tools.register(desktop_tool(self.desktop))
        self.providers = ProviderService(
            self.settings, self.db, credential_store=self.credentials
        )
        self.agents = AgentRuntime(self.providers, self.tasks)
        self.runner = TaskRunner(self.db, self.tasks, self.agents, self.tools)
        self.blueprints = BlueprintRegistry(self.db, self.tools)
        self.blueprints.register_builtin()
        self.factory = FactoryService(self.db, self.tasks, self.runner, self.blueprints)
        self.evaluations = EvaluationService(self.db, self.tasks, self.runner, self.workspace)
        self.memory = MemoryStore(self.db, self.backups)
        self.skills = SkillLibrary(self.db)
        self.skills.register_builtin()
        self.plugins = PluginManager(self.db, paths.plugins)
        self.research = ResearchFetcher(self.settings, self.db)
        self.diagnostics = Diagnostics(
            paths,
            self.settings,
            self.db,
            self.tasks,
            self.memory,
            self.backups,
            credentials=self.credentials,
        )

    def close(self) -> None:
        self.browser.close()
        self.db.close()

    def __enter__(self) -> Application:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
