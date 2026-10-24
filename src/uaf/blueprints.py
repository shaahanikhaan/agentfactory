"""Immutable, declarative agent-team blueprints with validated DAG data flow."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from uaf.db import Database
from uaf.errors import IntegrityError, ValidationError
from uaf.tools import ToolRegistry, validate_schema
from uaf.util import canonical_json, json_data, reject_secret_data, sha256_text, utc_now

_IDENTIFIER = re.compile(r"[a-z][a-z0-9-]{0,40}")
_NAME = re.compile(r"[a-z][a-z0-9-]{0,63}")
_TEMPLATE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")


class BlueprintRegistry:
    def __init__(self, db: Database, tools: ToolRegistry) -> None:
        self.db = db
        self.tools = tools

    def register_builtin(self) -> str:
        path = Path(__file__).parent / "data" / "blueprints" / "offline-inventory.json"
        return self.register(path, builtin=True)["blueprint_id"]

    def register(
        self, source: str | Path | dict[str, Any], *, builtin: bool = False
    ) -> dict[str, Any]:
        if isinstance(source, dict):
            spec = source
        else:
            path = Path(source).expanduser().resolve()
            try:
                if path.stat().st_size > 64_000:
                    raise ValidationError("Agent blueprint exceeds the 64 KB limit")
                spec = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValidationError(f"Cannot load agent blueprint: {exc}") from exc
        normalized = self.validate(spec)
        try:
            encoded = canonical_json(normalized)
        except ValueError as exc:
            raise ValidationError("Blueprint contains a non-finite number") from exc
        if len(encoded) > 64_000:
            raise ValidationError("Canonical agent blueprint exceeds 64 KB")
        checksum = sha256_text(encoded)
        blueprint_id = f"{normalized['name']}@{normalized['version']}"
        existing = self.db.one(
            "SELECT * FROM agent_blueprints WHERE blueprint_id=?", (blueprint_id,)
        )
        if existing:
            if existing["checksum"] != checksum:
                raise IntegrityError(
                    "Blueprint name/version is immutable; register a new version for changed content"
                )
            return self.require(blueprint_id)
        now = utc_now()
        self.db.execute(
            "INSERT INTO agent_blueprints(blueprint_id,name,version,description,spec_json,checksum,"
            "enabled,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                blueprint_id,
                normalized["name"],
                normalized["version"],
                normalized["description"],
                encoded,
                checksum,
                int(builtin),
                "validated" if builtin else "disabled",
                now,
                now,
            ),
        )
        self.db.audit(
            "blueprint.register",
            object_type="agent_blueprint",
            object_id=blueprint_id,
            metadata={"checksum": checksum, "builtin": builtin},
        )
        return self.require(blueprint_id)

    def require(self, blueprint_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM agent_blueprints WHERE blueprint_id=?", (blueprint_id,))
        if not row:
            raise ValidationError(f"Agent blueprint does not exist: {blueprint_id}")
        return self._decode(row)

    def list(self) -> list[dict[str, Any]]:
        return [
            self._decode(row, include_spec=False)
            for row in self.db.query("SELECT * FROM agent_blueprints ORDER BY name, version")
        ]

    def set_enabled(self, blueprint_id: str, enabled: bool) -> dict[str, Any]:
        self.require(blueprint_id)
        self.db.execute(
            "UPDATE agent_blueprints SET enabled=?,status=?,updated_at=? WHERE blueprint_id=?",
            (int(enabled), "validated" if enabled else "disabled", utc_now(), blueprint_id),
        )
        self.db.audit(
            "blueprint.enable" if enabled else "blueprint.disable",
            object_type="agent_blueprint",
            object_id=blueprint_id,
        )
        return self.require(blueprint_id)

    def validate(self, spec: Any) -> dict[str, Any]:
        reject_secret_data(spec, label="agent blueprint")
        if not isinstance(spec, dict):
            raise ValidationError("Agent blueprint must be a JSON object")
        required = {"name", "version", "description", "agents", "steps"}
        optional = {"input_schema", "defaults", "output"}
        if not required <= set(spec) or not set(spec) <= required | optional:
            raise ValidationError("Blueprint has missing or unknown top-level fields")
        if not isinstance(spec["name"], str) or not _NAME.fullmatch(spec["name"]):
            raise ValidationError("Invalid blueprint name")
        if not isinstance(spec["version"], str) or not re.fullmatch(
            r"[A-Za-z0-9.-]{1,20}", spec["version"]
        ):
            raise ValidationError("Invalid blueprint version")
        if not isinstance(spec["description"], str) or not 1 <= len(spec["description"]) <= 1000:
            raise ValidationError("Blueprint description must be 1..1000 characters")
        normalized = dict(spec)
        normalized.setdefault("input_schema", {})
        normalized.setdefault("defaults", {})
        if not isinstance(normalized["input_schema"], dict):
            raise ValidationError("Blueprint input_schema must be an object")
        defaults = normalized["defaults"]
        if not isinstance(defaults, dict) or not set(defaults) <= {
            "constraints",
            "department",
            "priority",
            "budget",
        }:
            raise ValidationError("Invalid blueprint defaults")
        _string_list(defaults.get("constraints", []), "default constraints")
        if not isinstance(defaults.get("budget", {}), dict):
            raise ValidationError("Default budget must be an object")
        _validate_budget(defaults.get("budget", {}))
        priority = defaults.get("priority", "normal")
        if not isinstance(priority, str) or priority not in {
            "interactive",
            "normal",
            "batch",
            "idle",
        }:
            raise ValidationError("Invalid default task priority")
        if not isinstance(defaults.get("department", "executive"), str):
            raise ValidationError("Default department must be a string")

        agents = spec["agents"]
        if not isinstance(agents, list) or not 1 <= len(agents) <= 8:
            raise ValidationError("Blueprint requires 1..8 agents")
        agent_map = {}
        known_tools = {item["name"] for item in self.tools.list()}
        for agent in agents:
            if not isinstance(agent, dict):
                raise ValidationError("Every blueprint agent must be an object")
            required_agent = {"agent_id", "kind"}
            optional_agent = {
                "name",
                "instructions",
                "allowed_tools",
                "risk_tier",
                "budget",
                "constraints",
                "department",
            }
            if (
                not required_agent <= set(agent)
                or not set(agent) <= required_agent | optional_agent
            ):
                raise ValidationError("Blueprint agent has missing or unknown fields")
            agent_id = agent["agent_id"]
            if not isinstance(agent_id, str) or not _IDENTIFIER.fullmatch(agent_id):
                raise ValidationError("Invalid blueprint agent identifier")
            if agent_id in agent_map:
                raise ValidationError(f"Duplicate blueprint agent: {agent_id}")
            if not isinstance(agent["kind"], str) or agent["kind"] not in {
                "agent",
                "react",
                "smoke",
                "tool",
            }:
                raise ValidationError("Unsupported blueprint agent kind")
            instructions = agent.get("instructions", "")
            if not isinstance(instructions, str) or len(instructions) > 8_000:
                raise ValidationError(
                    "Agent instructions must be a string of at most 8000 characters"
                )
            if not isinstance(agent.get("name", agent_id), str):
                raise ValidationError("Agent name must be a string")
            allowed = agent.get("allowed_tools", [])
            _string_list(allowed, "agent allowed_tools")
            if len(allowed) > 16 or len(set(allowed)) != len(allowed):
                raise ValidationError("Agent tool allowlist must be unique and bounded")
            unknown = set(allowed) - known_tools
            if unknown:
                raise ValidationError(f"Blueprint references unregistered tools: {sorted(unknown)}")
            if agent["kind"] in {"agent", "smoke"} and allowed:
                raise ValidationError(f"{agent['kind']} agents cannot declare tool authority")
            if agent["kind"] == "tool" and not allowed:
                raise ValidationError("Tool agents require an explicit non-empty tool allowlist")
            risk_tier = agent.get("risk_tier", "R0")
            if not isinstance(risk_tier, str) or risk_tier not in {"R0", "R1", "R2", "R3"}:
                raise ValidationError("Invalid agent risk tier")
            if not isinstance(agent.get("budget", {}), dict):
                raise ValidationError("Agent budget must be an object")
            _validate_budget(agent.get("budget", {}))
            _string_list(agent.get("constraints", []), "agent constraints")
            agent_map[agent_id] = agent

        steps = spec["steps"]
        if not isinstance(steps, list) or not 1 <= len(steps) <= 12:
            raise ValidationError("Blueprint requires 1..12 steps")
        step_map = {}
        for step in steps:
            if not isinstance(step, dict):
                raise ValidationError("Every blueprint step must be an object")
            required_step = {"step_id", "agent_id", "goal"}
            optional_step = {"depends_on", "input", "expected_output_schema", "constraints"}
            if not required_step <= set(step) or not set(step) <= required_step | optional_step:
                raise ValidationError("Blueprint step has missing or unknown fields")
            step_id = step["step_id"]
            if not isinstance(step_id, str) or not _IDENTIFIER.fullmatch(step_id):
                raise ValidationError("Invalid blueprint step identifier")
            if step_id in step_map:
                raise ValidationError(f"Duplicate blueprint step: {step_id}")
            if not isinstance(step["agent_id"], str) or step["agent_id"] not in agent_map:
                raise ValidationError(f"Step references unknown agent: {step['agent_id']}")
            if not isinstance(step["goal"], str) or not step["goal"].strip():
                raise ValidationError("Blueprint step goal must be a non-empty string")
            dependencies = step.get("depends_on", [])
            _string_list(dependencies, "step dependencies")
            if len(dependencies) > 12 or len(set(dependencies)) != len(dependencies):
                raise ValidationError("Step dependencies must be unique and bounded")
            if not isinstance(step.get("input", {}), dict):
                raise ValidationError("Step input must be an object")
            agent = agent_map[step["agent_id"]]
            if agent["kind"] == "tool":
                selected_tool = step.get("input", {}).get("tool")
                if not isinstance(selected_tool, str) or selected_tool not in agent.get(
                    "allowed_tools", []
                ):
                    raise ValidationError(
                        "Tool steps require a static input.tool inside the agent allowlist"
                    )
            if not isinstance(step.get("expected_output_schema", {}), dict):
                raise ValidationError("Step expected_output_schema must be an object")
            _string_list(step.get("constraints", []), "step constraints")
            step_map[step_id] = step
        for step in steps:
            for dependency in step.get("depends_on", []):
                if dependency not in step_map:
                    raise ValidationError(f"Unknown step dependency: {dependency}")
                if dependency == step["step_id"]:
                    raise ValidationError("A blueprint step cannot depend on itself")
        order = topological_order(steps)
        normalized["output"] = spec.get("output", {"from": order[-1]})
        if (
            not isinstance(normalized["output"], dict)
            or set(normalized["output"]) != {"from"}
            or not isinstance(normalized["output"]["from"], str)
            or normalized["output"]["from"] not in step_map
        ):
            raise ValidationError("Blueprint output.from must name one valid step")
        ancestors = _ancestors(steps)
        for step in steps:
            values = [step["goal"], step.get("input", {}), step.get("constraints", [])]
            for value in values:
                for reference in _template_references(value):
                    if (
                        reference == "goal"
                        or reference == "inputs"
                        or reference.startswith("inputs.")
                    ):
                        continue
                    parts = reference.split(".")
                    if (
                        not 3 <= len(parts) <= 9
                        or parts[0] != "steps"
                        or parts[1] not in step_map
                        or parts[2] not in {"output", "result", "state"}
                    ):
                        raise ValidationError(f"Invalid blueprint template reference: {reference}")
                    if parts[1] not in ancestors[step["step_id"]]:
                        raise ValidationError(
                            f"Step {step['step_id']} must declare {parts[1]} as an upstream dependency"
                        )
        return normalized

    @staticmethod
    def _decode(row: dict[str, Any], *, include_spec: bool = True) -> dict[str, Any]:
        result = {
            "blueprint_id": row["blueprint_id"],
            "name": row["name"],
            "version": row["version"],
            "description": row["description"],
            "checksum": row["checksum"],
            "enabled": bool(row["enabled"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if include_spec:
            result["spec"] = json_data(row["spec_json"], {})
        return result


def topological_order(steps: list[dict[str, Any]]) -> list[str]:
    position = {step["step_id"]: index for index, step in enumerate(steps)}
    remaining = {step["step_id"]: set(step.get("depends_on", [])) for step in steps}
    order = []
    while remaining:
        ready = sorted(
            (step_id for step_id, dependencies in remaining.items() if not dependencies),
            key=position.__getitem__,
        )
        if not ready:
            raise ValidationError("Blueprint dependency graph contains a cycle")
        for step_id in ready:
            order.append(step_id)
            del remaining[step_id]
            for dependencies in remaining.values():
                dependencies.discard(step_id)
    return order


def _ancestors(steps: list[dict[str, Any]]) -> dict[str, set[str]]:
    dependencies = {step["step_id"]: set(step.get("depends_on", [])) for step in steps}
    ancestors = {}

    def visit(step_id: str, visiting: set[str]) -> set[str]:
        if step_id in ancestors:
            return ancestors[step_id]
        if step_id in visiting:
            raise ValidationError("Blueprint dependency graph contains a cycle")
        found = set(dependencies[step_id])
        for dependency in dependencies[step_id]:
            found |= visit(dependency, visiting | {step_id})
        ancestors[step_id] = found
        return found

    for step_id in dependencies:
        visit(step_id, set())
    return ancestors


def _template_references(value: Any) -> list[str]:
    references = []
    if isinstance(value, str):
        matches = list(_TEMPLATE.finditer(value))
        references.extend(match.group(1) for match in matches)
        residue = _TEMPLATE.sub("", value)
        if "{{" in residue or "}}" in residue:
            raise ValidationError("Malformed blueprint template expression")
    elif isinstance(value, list):
        for item in value:
            references.extend(_template_references(item))
    elif isinstance(value, dict):
        for item in value.values():
            references.extend(_template_references(item))
    return references


def _string_list(value: Any, label: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValidationError(f"{label} must be a list of strings")


def _validate_budget(budget: dict[str, Any]) -> None:
    allowed = {
        "max_attempts",
        "max_model_calls",
        "max_steps",
        "max_tool_calls",
        "task_wall_seconds",
        "max_output_chars",
    }
    if not set(budget) <= allowed:
        raise ValidationError(f"Unknown blueprint budget fields: {sorted(set(budget) - allowed)}")
    for name, value in budget.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValidationError(f"Invalid blueprint budget: {name}")
    if budget.get("max_attempts", 1) > 3 or budget.get("max_output_chars", 1) > 12_000:
        raise ValidationError("Blueprint exceeds the attempt or output safety ceiling")


def validate_blueprint_inputs(schema: dict[str, Any], inputs: dict[str, Any]) -> None:
    validate_schema(inputs, schema)
