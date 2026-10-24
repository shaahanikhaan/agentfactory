"""Portable paths and validated, secret-free local configuration."""

from __future__ import annotations

import copy
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from uaf.errors import ValidationError
from uaf.util import atomic_write_text, canonical_json, json_data

_FORBIDDEN_DESKTOP_APPLICATIONS = {
    "anydesk.exe",
    "bash.exe",
    "brave.exe",
    "chrome.exe",
    "cmd.exe",
    "conhost.exe",
    "control.exe",
    "explorer.exe",
    "firefox.exe",
    "iexplore.exe",
    "msconfig.exe",
    "msedge.exe",
    "mstsc.exe",
    "opera.exe",
    "powershell.exe",
    "pwsh.exe",
    "python.exe",
    "pythonw.exe",
    "regedit.exe",
    "rundll32.exe",
    "taskmgr.exe",
    "teamviewer.exe",
    "windowsterminal.exe",
    "wsl.exe",
}

_PROVIDER_DEFAULTS: dict[str, dict[str, Any]] = {
    "gemini": {"enabled": False, "credential_env": "GEMINI_API_KEY", "models": {}},
    "groq": {"enabled": False, "credential_env": "GROQ_API_KEY", "models": {}},
    "openrouter": {"enabled": False, "credential_env": "OPENROUTER_API_KEY", "models": {}},
    "ollama": {
        "enabled": False,
        "credential_env": None,
        "endpoint": "http://127.0.0.1:11434",
        "models": {},
    },
}


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{label} must be a boolean")
    return value


def _validate_string_list(
    values: Any, *, label: str, maximum: int, item_length: int
) -> None:
    if not isinstance(values, list) or len(values) > maximum:
        raise ValidationError(f"{label} allowlist must be a list of at most {maximum} entries")
    if any(
        not isinstance(value, str)
        or not value.strip()
        or len(value) > item_length
        or value != value.strip()
        for value in values
    ):
        raise ValidationError(f"{label} allowlist contains an invalid entry")
    if len(set(values)) != len(values):
        raise ValidationError(f"{label} allowlist entries must be unique")


@dataclass(frozen=True, slots=True)
class AppPaths:
    home: Path

    @classmethod
    def discover(cls, explicit: str | Path | None = None) -> AppPaths:
        if explicit:
            root = Path(explicit).expanduser()
        elif os.environ.get("UAF_HOME"):
            root = Path(os.environ["UAF_HOME"]).expanduser()
        elif sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
            root = Path(os.environ["LOCALAPPDATA"]) / "UltimateAgentFactory"
        elif os.environ.get("XDG_DATA_HOME"):
            root = Path(os.environ["XDG_DATA_HOME"]) / "ultimate-agent-factory"
        else:
            root = Path.home() / ".local" / "share" / "ultimate-agent-factory"
        return cls(root.absolute())

    @property
    def config(self) -> Path:
        return self.home / "config.json"

    @property
    def database(self) -> Path:
        return self.home / "uaf.db"

    @property
    def backups(self) -> Path:
        return self.home / "backups"

    @property
    def artifacts(self) -> Path:
        return self.home / "artifacts"

    @property
    def plugins(self) -> Path:
        return self.home / "plugins"

    @property
    def candidates(self) -> Path:
        return self.home / "candidates"

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    @property
    def file_backups(self) -> Path:
        return self.home / "file-backups"

    @property
    def browser_profile(self) -> Path:
        return self.home / "browser-profile"


@dataclass(slots=True)
class Budgets:
    max_workers: int = 1
    max_llm_concurrency: int = 1
    max_steps: int = 16
    max_delegations: int = 4
    max_tool_calls: int = 16
    max_model_calls: int = 4
    max_retries: int = 2
    max_prompt_chars: int = 32_000
    max_output_chars: int = 12_000
    max_tool_output_chars: int = 32_000
    max_queue: int = 1_000
    max_daily_calls: int = 100
    provider_timeout_seconds: int = 45
    task_wall_seconds: int = 600
    backup_retention: int = 20

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValidationError(f"Budget {name} must be a positive integer")
        if self.max_workers > 4 or self.max_llm_concurrency > 4:
            raise ValidationError("Concurrency above 4 requires a code-level resource review")
        if self.max_prompt_chars > 1_000_000 or self.max_output_chars > 200_000:
            raise ValidationError("Prompt/output budgets exceed the hard safety ceiling")


@dataclass(slots=True)
class Settings:
    workspace: str
    network_allowed: bool = False
    mcp_enabled: bool = False
    telemetry_enabled: bool = False
    browser_enabled: bool = False
    browser_allowed_domains: list[str] = field(default_factory=list)
    desktop_enabled: bool = False
    desktop_allowed_applications: list[str] = field(default_factory=list)
    desktop_max_actions_per_batch: int = 12
    allow_paid: bool = False
    free_verification_max_age_days: int = 30
    budgets: Budgets = field(default_factory=Budgets)
    providers: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {name: dict(value) for name, value in _PROVIDER_DEFAULTS.items()}
    )

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace).expanduser().absolute()

    def validate(self) -> None:
        if self.allow_paid:
            raise ValidationError("UAF's no-spend build does not permit allow_paid=true")
        if not self.workspace:
            raise ValidationError("A workspace path is required")
        if not 1 <= self.free_verification_max_age_days <= 365:
            raise ValidationError("Free-tier verification max age must be between 1 and 365 days")
        for name in (
            "network_allowed",
            "mcp_enabled",
            "telemetry_enabled",
            "browser_enabled",
            "desktop_enabled",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValidationError(f"{name} must be a boolean")
        self.budgets.validate()
        if (
            not isinstance(self.desktop_max_actions_per_batch, int)
            or isinstance(self.desktop_max_actions_per_batch, bool)
            or not 1 <= self.desktop_max_actions_per_batch <= 20
        ):
            raise ValidationError("Desktop batch size must be between 1 and 20")
        _validate_string_list(
            self.browser_allowed_domains, label="Browser domain", maximum=32, item_length=253
        )
        for domain in self.browser_allowed_domains:
            candidate = domain[2:] if domain.startswith("*.") else domain
            if (
                domain != domain.lower()
                or ".." in candidate
                or not candidate
                or any(
                    not part
                    or not all(ch.isascii() and (ch.isalnum() or ch == "-") for ch in part)
                    for part in candidate.split(".")
                )
                or any(part.startswith("-") or part.endswith("-") for part in candidate.split("."))
            ):
                raise ValidationError(f"Invalid browser domain allowlist entry: {domain}")
        _validate_string_list(
            self.desktop_allowed_applications,
            label="Desktop application",
            maximum=16,
            item_length=260,
        )
        for application in self.desktop_allowed_applications:
            if (
                application != application.lower()
                or not application.endswith(".exe")
                or application in {".exe"}
                or any(ord(ch) < 32 or ch in "\\/:*?\"<>|" for ch in application)
                or application in _FORBIDDEN_DESKTOP_APPLICATIONS
            ):
                raise ValidationError(
                    "Desktop applications must be safe lowercase executable basenames; "
                    "shells, browsers, interpreters, system and remote-control tools are forbidden"
                )
        for name, config in self.providers.items():
            if name not in _PROVIDER_DEFAULTS:
                raise ValidationError(f"Unknown provider: {name}")
            if not isinstance(config.get("models", {}), dict):
                raise ValidationError(f"Provider {name} models must be an object")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "workspace": self.workspace,
            "network_allowed": self.network_allowed,
            "mcp_enabled": self.mcp_enabled,
            "telemetry_enabled": self.telemetry_enabled,
            "browser_enabled": self.browser_enabled,
            "browser_allowed_domains": list(self.browser_allowed_domains),
            "desktop_enabled": self.desktop_enabled,
            "desktop_allowed_applications": list(self.desktop_allowed_applications),
            "desktop_max_actions_per_batch": self.desktop_max_actions_per_batch,
            "allow_paid": False,
            "free_verification_max_age_days": self.free_verification_max_age_days,
            "budgets": asdict(self.budgets),
            "providers": copy.deepcopy(self.providers),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Settings:
        if raw.get("schema_version", 1) != 1:
            raise ValidationError("Unsupported configuration schema")
        if raw.get("allow_paid", False):
            raise ValidationError("Paid fallback is disabled by product policy")
        providers = {name: dict(value) for name, value in _PROVIDER_DEFAULTS.items()}
        for name, value in raw.get("providers", {}).items():
            if name not in providers or not isinstance(value, dict):
                raise ValidationError(f"Invalid provider configuration: {name}")
            providers[name].update(value)
        settings = cls(
            workspace=str(raw.get("workspace", "")),
            network_allowed=_boolean(raw.get("network_allowed", False), "network_allowed"),
            mcp_enabled=_boolean(raw.get("mcp_enabled", False), "mcp_enabled"),
            telemetry_enabled=_boolean(raw.get("telemetry_enabled", False), "telemetry_enabled"),
            browser_enabled=_boolean(raw.get("browser_enabled", False), "browser_enabled"),
            browser_allowed_domains=raw.get("browser_allowed_domains", []),
            desktop_enabled=_boolean(raw.get("desktop_enabled", False), "desktop_enabled"),
            desktop_allowed_applications=raw.get("desktop_allowed_applications", []),
            desktop_max_actions_per_batch=raw.get("desktop_max_actions_per_batch", 12),
            allow_paid=False,
            free_verification_max_age_days=int(raw.get("free_verification_max_age_days", 30)),
            budgets=Budgets(**raw.get("budgets", {})),
            providers=providers,
        )
        settings.validate()
        return settings


class ConfigManager:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    def exists(self) -> bool:
        return self.paths.config.is_file()

    def initialize(self, workspace: str | Path | None = None, *, online: bool = False) -> Settings:
        if self.exists():
            settings = self.load()
            if workspace is not None or online:
                if workspace is not None:
                    settings.workspace = str(Path(workspace).expanduser().absolute())
                settings.network_allowed = settings.network_allowed or online
                self.save(settings)
            return settings
        root = (
            Path(workspace).expanduser().absolute() if workspace else self.paths.home / "workspace"
        )
        settings = Settings(workspace=str(root), network_allowed=online)
        settings.validate()
        self.paths.home.mkdir(parents=True, exist_ok=True)
        for directory in (
            self.paths.backups,
            self.paths.artifacts,
            self.paths.plugins,
            self.paths.candidates,
            self.paths.logs,
            self.paths.file_backups,
            root,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self.save(settings)
        return settings

    def load(self) -> Settings:
        if not self.exists():
            return self.initialize()
        try:
            raw = json_data(self.paths.config.read_text(encoding="utf-8"), {})
        except (OSError, ValueError) as exc:
            raise ValidationError(f"Cannot read configuration: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValidationError("Configuration root must be an object")
        self._reject_secrets(raw)
        return Settings.from_dict(raw)

    def save(self, settings: Settings) -> None:
        settings.validate()
        raw = settings.to_dict()
        self._reject_secrets(raw)
        atomic_write_text(self.paths.config, canonical_json(raw) + "\n", private=True)

    def set(self, key: str, value: Any) -> Settings:
        settings = self.load()
        if key == "workspace":
            settings.workspace = str(Path(str(value)).expanduser().absolute())
        elif key in {
            "network_allowed",
            "mcp_enabled",
            "telemetry_enabled",
            "browser_enabled",
            "desktop_enabled",
        }:
            if not isinstance(value, bool):
                raise ValidationError(f"{key} requires a boolean")
            setattr(settings, key, value)
        elif key in {"browser_allowed_domains", "desktop_allowed_applications"}:
            if not isinstance(value, list):
                raise ValidationError(f"{key} requires a JSON list")
            setattr(settings, key, value)
        elif key == "desktop_max_actions_per_batch":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValidationError(f"{key} requires an integer")
            settings.desktop_max_actions_per_batch = value
        elif key.startswith("budgets."):
            name = key.removeprefix("budgets.")
            if name not in asdict(settings.budgets):
                raise ValidationError(f"Unknown budget: {name}")
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValidationError("Budget values must be integers")
            setattr(settings.budgets, name, value)
        elif key == "allow_paid":
            raise ValidationError("No-spend policy cannot be changed through configuration")
        else:
            raise ValidationError(f"Configuration key is not writable: {key}")
        self.save(settings)
        return settings

    @staticmethod
    def _reject_secrets(raw: Any) -> None:
        if isinstance(raw, dict):
            for key, value in raw.items():
                normalized = key.lower().replace("-", "_")
                if normalized in {
                    "api_key",
                    "apikey",
                    "secret",
                    "password",
                    "token",
                    "authorization",
                }:
                    raise ValidationError(f"Secret-like configuration key is forbidden: {key}")
                ConfigManager._reject_secrets(value)
        elif isinstance(raw, list):
            for value in raw:
                ConfigManager._reject_secrets(value)
