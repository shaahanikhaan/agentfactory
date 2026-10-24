"""Controlled plugin discovery with executable declarative workflows, not auto-imports."""

from __future__ import annotations

import importlib.metadata
import json
import re
from pathlib import Path
from typing import Any

from uaf.db import Database
from uaf.errors import IntegrityError, PolicyDenied, UnavailableError, ValidationError
from uaf.tools import validate_schema
from uaf.util import canonical_json, json_data, sha256_text, utc_now

_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_TEMPLATE = re.compile(r"\{\{([a-zA-Z][a-zA-Z0-9_]*)\}\}")


class PluginManager:
    def __init__(self, db: Database, plugin_root: Path) -> None:
        self.db = db
        self.plugin_root = Path(plugin_root)
        self.plugin_root.mkdir(parents=True, exist_ok=True)

    def discover(self) -> list[str]:
        registered = []
        for manifest in sorted(self.plugin_root.glob("*/plugin.json")):
            registered.append(self.register(manifest))
        return registered

    def entry_point_metadata(self) -> list[dict[str, str]]:
        """Read metadata only. Entry-point loading would execute arbitrary Python code."""
        rows = []
        try:
            points = importlib.metadata.entry_points(group="uaf.plugins")
        except Exception:
            return []
        for point in points:
            rows.append(
                {
                    "name": point.name,
                    "value": point.value,
                    "distribution": getattr(point.dist, "name", "unknown"),
                    "status": "disabled_python_code_not_imported",
                }
            )
        return rows

    def register(self, manifest_path: Path) -> str:
        manifest_path = Path(manifest_path).resolve()
        if not manifest_path.is_file() or manifest_path.stat().st_size > 64_000:
            raise ValidationError("Plugin manifest is missing or exceeds 64 KB")
        try:
            raw = manifest_path.read_bytes()
            manifest = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError(f"Invalid plugin manifest: {exc}") from exc
        required = {
            "plugin_id",
            "name",
            "version",
            "api_version",
            "kind",
            "permissions",
            "license",
            "source",
            "workflow",
            "workflow_sha256",
            "input_schema",
        }
        if required - set(manifest):
            raise ValidationError(f"Plugin manifest missing: {sorted(required - set(manifest))}")
        plugin_id = manifest["plugin_id"]
        if not isinstance(plugin_id, str) or not _ID.fullmatch(plugin_id):
            raise ValidationError("Invalid plugin identifier")
        if manifest["api_version"] != "1":
            raise ValidationError("Plugin API is incompatible; supported version is 1")
        if manifest["kind"] != "declarative-workflow":
            raise PolicyDenied(
                "Only declarative workflows are loadable; Python plugins remain disabled"
            )
        workflow = manifest["workflow"]
        if sha256_text(canonical_json(workflow)) != manifest["workflow_sha256"]:
            raise IntegrityError("Plugin workflow checksum mismatch")
        self._validate_workflow(workflow, manifest["permissions"])
        validate_schema(manifest["input_schema"], {"type": "object"})
        manifest_digest = sha256_text(raw.decode("utf-8"))
        existing = self.db.one("SELECT * FROM plugin_registry WHERE plugin_id=?", (plugin_id,))
        enabled = bool(
            existing and existing["enabled"] and existing["manifest_digest"] == manifest_digest
        )
        status = "validated" if enabled or not existing else "updated_disabled"
        self.db.execute(
            "INSERT INTO plugin_registry(plugin_id,name,version,api_version,manifest_path,manifest_digest,"
            "entry_hash,permissions_json,enabled,trust_acknowledged,status,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,0,0,?,?) ON CONFLICT(plugin_id) DO UPDATE SET name=excluded.name,"
            "version=excluded.version,api_version=excluded.api_version,manifest_path=excluded.manifest_path,"
            "manifest_digest=excluded.manifest_digest,entry_hash=excluded.entry_hash,"
            "permissions_json=excluded.permissions_json,enabled=excluded.enabled,status=excluded.status,"
            "updated_at=excluded.updated_at",
            (
                plugin_id,
                manifest["name"],
                str(manifest["version"]),
                "1",
                str(manifest_path),
                manifest_digest,
                manifest["workflow_sha256"],
                canonical_json(manifest["permissions"]),
                status,
                utc_now(),
            ),
        )
        self.db.audit(
            "plugin.register",
            object_type="plugin",
            object_id=plugin_id,
            decision=status,
            metadata={"kind": manifest["kind"], "license": manifest["license"]},
        )
        return plugin_id

    @staticmethod
    def _validate_workflow(workflow: Any, permissions: Any) -> None:
        if not isinstance(workflow, dict) or set(workflow) != {"tool", "arguments"}:
            raise ValidationError("Declarative workflow must contain exactly tool and arguments")
        if not isinstance(workflow["tool"], str) or workflow["tool"] not in permissions:
            raise PolicyDenied("Plugin workflow tool is not present in its permissions")
        if not isinstance(permissions, list) or len(permissions) > 8:
            raise ValidationError("Plugin permissions must be a bounded list")
        if not workflow["tool"].startswith("workspace."):
            raise PolicyDenied("This plugin API only permits explicitly governed workspace tools")
        canonical_json(workflow["arguments"])

    def _manifest(self, row: dict[str, Any], *, verify: bool = True) -> dict[str, Any]:
        path = Path(row["manifest_path"])
        if not path.is_file():
            raise IntegrityError("Plugin manifest is missing")
        raw = path.read_bytes()
        if verify and sha256_text(raw.decode("utf-8")) != row["manifest_digest"]:
            raise IntegrityError("Plugin manifest tampering detected; re-register and review")
        try:
            manifest = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise IntegrityError("Plugin manifest is unreadable") from exc
        if sha256_text(canonical_json(manifest.get("workflow"))) != row["entry_hash"]:
            raise IntegrityError("Plugin workflow tampering detected")
        return manifest

    def list(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM plugin_registry ORDER BY plugin_id")
        result = []
        for row in rows:
            row["permissions"] = json_data(row.pop("permissions_json"), [])
            try:
                self._manifest(row)
                row["integrity"] = "verified"
            except Exception as exc:
                row["integrity"] = str(exc)
                row["enabled"] = False
            result.append(row)
        return result

    def enable(self, plugin_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        if not confirmed:
            raise ValidationError("Plugin enablement requires explicit confirmation")
        row = self._require(plugin_id)
        manifest = self._manifest(row)
        self._validate_workflow(manifest["workflow"], manifest["permissions"])
        self.db.execute(
            "UPDATE plugin_registry SET enabled=1,trust_acknowledged=1,status='enabled',updated_at=? "
            "WHERE plugin_id=?",
            (utc_now(), plugin_id),
        )
        self.db.audit(
            "plugin.enable",
            actor="local-user",
            role="human",
            object_type="plugin",
            object_id=plugin_id,
            decision="enabled",
            metadata={"permissions": manifest["permissions"]},
        )
        return self._require(plugin_id)

    def disable(self, plugin_id: str) -> dict[str, Any]:
        self._require(plugin_id)
        self.db.execute(
            "UPDATE plugin_registry SET enabled=0,status='disabled',updated_at=? WHERE plugin_id=?",
            (utc_now(), plugin_id),
        )
        self.db.audit(
            "plugin.disable",
            actor="local-user",
            role="human",
            object_type="plugin",
            object_id=plugin_id,
            decision="disabled",
        )
        return self._require(plugin_id)

    def render(self, plugin_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        row = self._require(plugin_id)
        if not row["enabled"]:
            raise UnavailableError("Plugin is disabled")
        manifest = self._manifest(row)
        validate_schema(inputs, manifest["input_schema"])
        arguments = self._render_value(manifest["workflow"]["arguments"], inputs)
        if not isinstance(arguments, dict):
            raise ValidationError("Rendered plugin arguments must be an object")
        return {"tool": manifest["workflow"]["tool"], "arguments": arguments}

    def _render_value(self, value: Any, inputs: dict[str, Any]) -> Any:
        if isinstance(value, str):
            full = _TEMPLATE.fullmatch(value)
            if full:
                key = full.group(1)
                if key not in inputs:
                    raise ValidationError(f"Missing plugin input: {key}")
                return inputs[key]

            def replace(match: re.Match) -> str:
                key = match.group(1)
                if key not in inputs:
                    raise ValidationError(f"Missing plugin input: {key}")
                replacement = inputs[key]
                if not isinstance(replacement, (str, int, float, bool)):
                    raise ValidationError("Embedded plugin placeholders require scalar values")
                return str(replacement)

            return _TEMPLATE.sub(replace, value)
        if isinstance(value, list):
            return [self._render_value(item, inputs) for item in value]
        if isinstance(value, dict):
            return {key: self._render_value(item, inputs) for key, item in value.items()}
        return value

    def _require(self, plugin_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM plugin_registry WHERE plugin_id=?", (plugin_id,))
        if not row:
            raise ValidationError(f"Unknown plugin: {plugin_id}")
        return row
