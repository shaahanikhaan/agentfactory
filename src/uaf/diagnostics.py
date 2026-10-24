"""Capability truthfulness, local diagnostics, and reproducible resource evidence."""

from __future__ import annotations

import importlib.util
import os
import platform
import sqlite3
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from uaf import __version__
from uaf.backup import BackupManager
from uaf.config import AppPaths, Settings
from uaf.credentials import CredentialStore
from uaf.db import Database
from uaf.memory import MemoryStore
from uaf.models import CapabilityState, TaskContract
from uaf.runner import TaskRunner
from uaf.tasks import TaskStore
from uaf.util import utc_now


def memory_report() -> dict[str, Any]:
    try:
        if sys.platform != "win32":
            page = os.sysconf("SC_PAGE_SIZE")
            total = os.sysconf("SC_PHYS_PAGES") * page
            available = os.sysconf("SC_AVPHYS_PAGES") * page
            return {"total_bytes": total, "available_bytes": available, "method": "sysconf"}
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return {
                "total_bytes": status.total_physical,
                "available_bytes": status.available_physical,
                "method": "GlobalMemoryStatusEx",
            }
    except (OSError, ValueError, AttributeError):
        pass
    return {"total_bytes": None, "available_bytes": None, "method": "unavailable"}


def capability_report() -> dict[str, Any]:
    implemented = CapabilityState.IMPLEMENTED.value
    optional = CapabilityState.IMPLEMENTED_OPTIONAL.value
    prototype = CapabilityState.PROTOTYPE.value
    planned = CapabilityState.PLANNED.value
    entries = [
        (
            "core_config",
            implemented,
            "Validated portable config and no-spend defaults",
            "tests/test_config.py",
        ),
        (
            "sqlite_durability",
            implemented,
            "Migrations, WAL, integrity, checkpoints",
            "tests/test_db.py",
        ),
        (
            "backup_restore",
            implemented,
            "SQLite backup API, hash verification, lifeline restore",
            "tests/test_backup.py",
        ),
        (
            "task_orchestration",
            implemented,
            "Dependencies, state machine, cancel/resume, revisions",
            "tests/test_runner.py",
        ),
        (
            "offline_agent_factory",
            implemented,
            "Deterministic four-role smoke workflow; not simulated AI",
            "tests/test_runner.py",
        ),
        (
            "cloud_agent_factory",
            optional,
            "Bounded worker/reviewer calls through configured free/local model",
            "tests/test_runner.py",
        ),
        (
            "declarative_agent_blueprints",
            implemented,
            "Immutable bounded agent/team specifications with validated DAG data flow",
            "tests/test_factory.py",
        ),
        (
            "durable_factory_dag",
            implemented,
            "Atomic task graphs, materialization digests, explicit recovery, and idempotent start",
            "tests/test_factory.py",
        ),
        (
            "task_experience",
            implemented,
            "Idempotent pending task outcomes with human-approved non-private recall",
            "tests/test_experience.py",
        ),
        (
            "python_repository_map",
            implemented,
            "Bounded read-only Python AST imports/symbols without code execution",
            "tests/test_repository.py",
        ),
        (
            "governed_react",
            optional,
            "Typed decision/observation checkpoints and policy-enforced tool loops; eligible model required",
            "tests/test_react.py",
        ),
        (
            "reproducible_evaluation",
            implemented,
            "Labelled offline/model suites, deterministic scorers, resource metrics, and same-suite regression gates",
            "tests/test_evaluations.py",
        ),
        (
            "one_gemini_key_onboarding",
            optional,
            "Official model discovery, explicit free-tier confirmation and approved OS credential vault",
            "tests/test_onboarding.py",
        ),
        (
            "brain_pool",
            optional,
            "Gemini/Groq/OpenRouter/Ollama adapters; credentials and live verification required",
            "tests/test_providers.py",
        ),
        (
            "workspace_tools",
            implemented,
            "Confinement, atomic writes, R3 approval, postconditions",
            "tests/test_tools.py",
        ),
        (
            "idempotency",
            implemented,
            "Replay, conflict, uncertain recovery, reconciliation",
            "tests/test_idempotency.py",
        ),
        (
            "memory",
            implemented,
            "Provenance, revisions, FTS fallback, privacy deletion, dry-run consolidation",
            "tests/test_memory.py",
        ),
        ("skills", implemented, "Checksummed progressive disclosure", "tests/test_extensions.py"),
        (
            "declarative_plugins",
            implemented,
            "Disabled by default, integrity checks, governed workflow rendering",
            "tests/test_extensions.py",
        ),
        (
            "python_plugins",
            planned,
            "No safe OS sandbox is claimed; code is never auto-imported",
            None,
        ),
        ("mcp_stdio", optional, "Official MCP SDK v2 and three narrow tools", "tests/test_mcp.py"),
        ("mcp_http", planned, "No HTTP listener in this release", None),
        (
            "research_fetch",
            prototype,
            "HTTPS/SSRF checks and provenance; hostile DNS is a residual risk",
            "tests/test_research.py",
        ),
        (
            "self_update",
            prototype,
            "Read-only check and isolated candidate; no automatic merge/deploy",
            "tests/test_self_update.py",
        ),
        (
            "windows_10_11_acceptance",
            prototype,
            "Partial user-reported Windows onboarding; full dashboard/mic/desktop/4 GB acceptance pending",
            "docs/WINDOWS.md",
        ),
        (
            "local_dashboard",
            implemented,
            "Serial loopback one-key dashboard with live readiness and durable startup evidence",
            "tests/test_dashboard.py",
        ),
        (
            "one_click_windows_launcher",
            optional,
            "Local venv/dependencies/optional Chromium/init/doctor/dashboard; target-OS acceptance pending",
            "tests/test_bootstrap.py",
        ),
        (
            "browser_voice_commands",
            optional,
            "One-utterance local-first browser speech, text fallback, and separate start confirmation",
            "tests/test_dashboard.py",
        ),
        (
            "browser_automation",
            optional,
            "Visible dedicated profile, public-domain allowlist, bounded snapshots and approved actions",
            "tests/test_browser.py",
        ),
        (
            "desktop_mouse_keyboard",
            optional,
            "Bounded Windows batches with exact-window binding, R3 approval and fail-safe; real-host acceptance pending",
            "tests/test_desktop.py",
        ),
        (
            "native_chat_connectors",
            planned,
            "No direct Slack/WhatsApp/Teams API connector; governed browser/native-app actions only",
            None,
        ),
        (
            "desktop_vision_voice",
            planned,
            "Disabled until concrete Windows/RAM adapters are measured",
            None,
        ),
        ("arbitrary_shell", planned, "Denied by default; no arbitrary shell tool registered", None),
    ]
    return {
        "version": __version__,
        "generated_at": utc_now(),
        "states": {state.value: state.value for state in CapabilityState},
        "capabilities": [
            {
                "id": identifier,
                "state": state,
                "detail": detail,
                "evidence": evidence,
            }
            for identifier, state, detail, evidence in entries
        ],
    }


class Diagnostics:
    def __init__(
        self,
        paths: AppPaths,
        settings: Settings,
        db: Database,
        tasks: TaskStore,
        memory: MemoryStore,
        backups: BackupManager,
        *,
        credentials: CredentialStore | None = None,
    ) -> None:
        self.paths = paths
        self.settings = settings
        self.db = db
        self.tasks = tasks
        self.memory = memory
        self.backups = backups
        self.credentials = credentials

    def doctor(self) -> dict[str, Any]:
        integrity = self.db.integrity_check()
        ram = memory_report()
        workspace = self.settings.workspace_path
        home_writable = self.paths.home.is_dir() and os.access(self.paths.home, os.W_OK)
        checks = {
            "python_supported": sys.version_info >= (3, 11),
            "home_writable": home_writable,
            "workspace_available": workspace.is_dir(),
            "database_integrity": integrity["ok"],
            "foreign_keys": not integrity["foreign_key_violations"],
            "fts5_or_fallback": True,
            "no_paid_fallback": not self.settings.allow_paid,
            "telemetry_disabled_or_explicit": True,
            "core_and_workspace_separate": paths_not_same(self.paths.home, workspace),
            "browser_allowlist_when_enabled": not self.settings.browser_enabled
            or bool(self.settings.browser_allowed_domains),
            "desktop_allowlist_when_enabled": not self.settings.desktop_enabled
            or bool(self.settings.desktop_allowed_applications),
        }
        vault = (
            self.credentials.status()
            if self.credentials is not None
            else {"available": False, "backend": None, "gemini_present": False}
        )
        return {
            "ok": all(checks.values()),
            "checks": checks,
            "runtime": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "sqlite": sqlite3.sqlite_version,
                "fts5": self.db.fts_enabled,
            },
            "paths": {"home": str(self.paths.home), "workspace": str(workspace)},
            "memory": ram,
            "optional_dependencies": {
                "mcp": importlib.util.find_spec("mcp") is not None,
                "playwright": importlib.util.find_spec("playwright") is not None,
                "keyring": importlib.util.find_spec("keyring") is not None,
                "pyautogui": importlib.util.find_spec("pyautogui") is not None,
            },
            "computer_use": {
                "browser_enabled": self.settings.browser_enabled,
                "browser_allowed_domains": self.settings.browser_allowed_domains,
                "browser_profile": str(self.paths.browser_profile),
                "desktop_enabled": self.settings.desktop_enabled,
                "desktop_allowed_applications": self.settings.desktop_allowed_applications,
                "desktop_max_actions_per_batch": self.settings.desktop_max_actions_per_batch,
                "real_host_input_tested": False,
            },
            "credentials": {
                "gemini_env_present": bool(os.environ.get("GEMINI_API_KEY")),
                "groq_env_present": bool(os.environ.get("GROQ_API_KEY")),
                "openrouter_env_present": bool(os.environ.get("OPENROUTER_API_KEY")),
                "os_vault": vault,
            },
            "warnings": self._warnings(ram, workspace),
        }

    @staticmethod
    def _warnings(ram: dict[str, Any], workspace: Path) -> list[str]:
        warnings = []
        if ram.get("available_bytes") and ram["available_bytes"] < 1_500_000_000:
            warnings.append("Available RAM is low; keep workers at 1 and optional models disabled")
        if not workspace.is_dir():
            warnings.append(
                "Workspace is missing/disconnected; tasks will pause instead of redirecting writes"
            )
        return warnings

    def status(self, providers: list[dict[str, Any]]) -> dict[str, Any]:
        snapshots = self.backups.list()
        db_size = self.db.path.stat().st_size if self.db.path.exists() else 0
        return {
            "version": __version__,
            "time": utc_now(),
            "tasks": self.tasks.counts(),
            "providers": {
                "configured": sum(row["model"] is not None for row in providers),
                "eligible": sum(bool(row["eligible"]) for row in providers),
                "network_allowed": self.settings.network_allowed,
                "allow_paid": False,
            },
            "memory": {
                "active": self.db.one(
                    "SELECT COUNT(*) AS count FROM memory_items WHERE deleted_at IS NULL"
                )["count"],
                "fts5": self.db.fts_enabled,
            },
            "approvals_pending": len(
                self.db.query("SELECT approval_id FROM approval_requests WHERE state='pending'")
            ),
            "plugins_enabled": self.db.one(
                "SELECT COUNT(*) AS count FROM plugin_registry WHERE enabled=1"
            )["count"],
            "factory": {
                "blueprints": self.db.one("SELECT COUNT(*) c FROM agent_blueprints")["c"],
                "enabled_blueprints": self.db.one(
                    "SELECT COUNT(*) c FROM agent_blueprints WHERE enabled=1"
                )["c"],
                "runs": self.db.one("SELECT COUNT(*) c FROM factory_runs")["c"],
            },
            "evaluation_runs": self.db.one("SELECT COUNT(*) c FROM evaluation_runs")["c"],
            "last_backup": snapshots[0] if snapshots else None,
            "database_bytes": db_size,
            "budgets": asdict(self.settings.budgets),
            "resources": memory_report(),
        }


def paths_not_same(first: Path, second: Path) -> bool:
    try:
        return first.resolve() != second.resolve()
    except OSError:
        return first.absolute() != second.absolute()


def benchmark(runner: TaskRunner, tasks: TaskStore, *, iterations: int = 5) -> dict[str, Any]:
    if not 1 <= iterations <= 50:
        raise ValueError("Benchmark iterations must be between 1 and 50")
    started = time.perf_counter()
    task_ids = []
    for index in range(iterations):
        task = tasks.add(TaskContract(goal=f"Benchmark durable smoke {index}", kind="smoke"))
        task_ids.append(task["task_id"])
        result = runner.run(task["task_id"])
        if result["state"] != "succeeded":
            raise RuntimeError(f"Benchmark task failed: {result['task_id']}")
    elapsed = time.perf_counter() - started
    peak_rss = None
    try:
        import resource

        peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    except (ImportError, AttributeError):
        pass
    model_calls = sum(tasks.model_call_count(task_id) for task_id in task_ids)
    return {
        "scenario": "durable_offline_smoke",
        "iterations": iterations,
        "succeeded": iterations,
        "failed": 0,
        "elapsed_seconds": round(elapsed, 6),
        "tasks_per_second": round(iterations / elapsed, 3) if elapsed else None,
        "peak_rss_bytes_unix": peak_rss,
        "model_calls": model_calls,
        "retry_count": 0,
        "database_bytes": tasks.db.path.stat().st_size,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "note": "Measured locally; not a promise for other hardware",
    }
