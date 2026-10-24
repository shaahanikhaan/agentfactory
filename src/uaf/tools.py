"""Typed tools with per-invocation authorization, auditing, and bounded outputs."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from uaf.acceptance import (
    MAX_STARTUP_BRIEF_CHARS,
    MAX_STARTUP_INVENTORY_ENTRIES,
    evaluate_startup_acceptance,
)
from uaf.approvals import ApprovalService
from uaf.db import Database
from uaf.errors import SideEffectError, UAFError, ValidationError
from uaf.idempotency import IdempotencyLedger
from uaf.models import RiskTier, ToolContext, ToolResult
from uaf.policy import PolicyEngine
from uaf.repository import PythonRepositoryMap
from uaf.util import canonical_json, new_id, payload_digest, redact_data, utc_now
from uaf.workspace import Workspace


@dataclass(frozen=True, slots=True)
class ToolMetadata:
    name: str
    version: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk_tier: RiskTier
    allowed_roles: frozenset[str]
    timeout_seconds: int = 30
    idempotent: bool = True
    external_destinations: tuple[str, ...] = ()


class Tool(Protocol):
    def metadata(self) -> ToolMetadata: ...
    def execute(self, context: ToolContext, payload: dict[str, Any]) -> ToolResult: ...


def metadata_dict(metadata: ToolMetadata) -> dict[str, Any]:
    value = asdict(metadata)
    value["risk_tier"] = metadata.risk_tier.value
    value["allowed_roles"] = sorted(metadata.allowed_roles)
    value["external_destinations"] = list(metadata.external_destinations)
    return value


def validate_schema(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Small JSON Schema subset used by built-in contracts (no remote $ref/eval)."""
    kind = schema.get("type")
    if kind:
        expected = {
            "object": dict,
            "array": list,
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "null": type(None),
        }.get(kind)
        if expected is None:
            raise ValidationError(f"Unsupported schema type at {path}: {kind}")
        if not isinstance(value, expected) or (
            kind in {"integer", "number"} and isinstance(value, bool)
        ):
            raise ValidationError(f"{path} must be {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValidationError(f"{path} is not an allowed value")
    if kind == "string":
        if len(value) > schema.get("maxLength", 1_000_000):
            raise ValidationError(f"{path} exceeds maxLength")
        if len(value) < schema.get("minLength", 0):
            raise ValidationError(f"{path} is shorter than minLength")
    if kind in {"integer", "number"}:
        if "minimum" in schema and value < schema["minimum"]:
            raise ValidationError(f"{path} is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValidationError(f"{path} exceeds maximum")
    if kind == "array":
        if len(value) > schema.get("maxItems", 1_000):
            raise ValidationError(f"{path} exceeds maxItems")
        for index, item in enumerate(value):
            if "items" in schema:
                validate_schema(item, schema["items"], f"{path}[{index}]")
    if kind == "object":
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            raise ValidationError(f"{path} is missing required properties: {missing}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unknown = set(value) - set(properties)
            if unknown:
                raise ValidationError(f"{path} has unknown properties: {sorted(unknown)}")
        for key, item in value.items():
            if key in properties:
                validate_schema(item, properties[key], f"{path}.{key}")


class ToolRegistry:
    def __init__(
        self,
        db: Database,
        approvals: ApprovalService,
        ledger: IdempotencyLedger,
        *,
        max_output_chars: int = 32_000,
    ) -> None:
        self.db = db
        self.policy = PolicyEngine(db, approvals)
        self.ledger = ledger
        self.max_output_chars = max_output_chars
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        metadata = tool.metadata()
        if metadata.name in self._tools:
            raise ValidationError(f"Duplicate tool: {metadata.name}")
        validate_schema(metadata.input_schema, {"type": "object"})
        self._tools[metadata.name] = tool
        self.db.execute(
            "INSERT INTO tool_registry(name,version,metadata_json,risk_tier,enabled,updated_at) "
            "VALUES(?,?,?,?,1,?) ON CONFLICT(name) DO UPDATE SET version=excluded.version,"
            "metadata_json=excluded.metadata_json,risk_tier=excluded.risk_tier,updated_at=excluded.updated_at",
            (
                metadata.name,
                metadata.version,
                canonical_json(metadata_dict(metadata)),
                metadata.risk_tier.value,
                utc_now(),
            ),
        )

    def list(self) -> list[dict[str, Any]]:
        return [metadata_dict(tool.metadata()) for tool in self._tools.values()]

    def invoke(
        self,
        name: str,
        context: ToolContext,
        payload: dict[str, Any],
        *,
        task_allowed_tools: list[str],
        destination: str | None = None,
    ) -> dict[str, Any]:
        tool = self._tools.get(name)
        if not tool:
            raise ValidationError(f"Unknown or disabled tool: {name}")
        metadata = tool.metadata()
        validate_schema(payload, metadata.input_schema)
        target = destination or payload.get("path") or payload.get("url") or "local"
        self.policy.authorize(
            metadata=metadata,
            context=context,
            payload=payload,
            task_allowed_tools=task_allowed_tools,
            destination=str(target),
        )
        invocation_id = new_id("invoke")
        digest = payload_digest(payload)
        key = f"{context.task_id}:{context.step_id}:{name}"
        self.db.execute(
            "INSERT INTO tool_invocations(invocation_id,task_id,step_id,tool_name,payload_digest,"
            "status,actor_role,idempotency_key,created_at) VALUES(?,?,?,?,?,'started',?,?,?)",
            (
                invocation_id,
                context.task_id,
                context.step_id,
                name,
                digest,
                context.role,
                key,
                utc_now(),
            ),
        )
        started = time.monotonic()
        try:
            if metadata.risk_tier == RiskTier.R0:
                result = tool.execute(context, payload)
            else:

                def operation(_: str) -> dict[str, Any]:
                    tool_result = tool.execute(context, payload)
                    if tool_result.uncertain:
                        raise SideEffectError("Tool reported an uncertain outcome", uncertain=True)
                    return {"output": tool_result.output, "evidence": tool_result.evidence}

                ledger_result = self.ledger.execute(
                    scope=f"task:{context.task_id}",
                    key=key,
                    payload={
                        "tool": name,
                        "destination": target,
                        "payload": payload,
                    },
                    destination=str(target),
                    operation=operation,
                    supports_idempotency=metadata.idempotent,
                )
                result = ToolResult(**ledger_result["result"])
            validate_schema(result.output, metadata.output_schema)
            encoded = canonical_json(redact_data(result.output))
            if len(encoded) > self.max_output_chars:
                raise UAFError("Tool output exceeded the configured output budget")
            elapsed_ms = int((time.monotonic() - started) * 1000)
            self.db.execute(
                "UPDATE tool_invocations SET status='completed',result_json=?,finished_at=? "
                "WHERE invocation_id=?",
                (encoded, utc_now(), invocation_id),
            )
            self.db.audit(
                "tool.execute",
                actor=context.requester,
                role=context.role,
                object_type="tool",
                object_id=name,
                decision="completed",
                metadata={
                    "task_id": context.task_id,
                    "elapsed_ms": elapsed_ms,
                    "timeout_budget_seconds": metadata.timeout_seconds,
                },
            )
            return {
                "output": result.output,
                "evidence": result.evidence,
                "invocation_id": invocation_id,
            }
        except Exception as exc:
            code = exc.code if isinstance(exc, UAFError) else type(exc).__name__
            self.db.execute(
                "UPDATE tool_invocations SET status=?,error_code=?,finished_at=? WHERE invocation_id=?",
                (
                    "uncertain" if isinstance(exc, SideEffectError) and exc.uncertain else "failed",
                    code,
                    utc_now(),
                    invocation_id,
                ),
            )
            raise


class WorkspaceReadTool:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="workspace.read",
            version="1",
            description="Read a bounded UTF-8 workspace file",
            input_schema={
                "type": "object",
                "required": ["path"],
                "additionalProperties": False,
                "properties": {"path": {"type": "string", "minLength": 1, "maxLength": 500}},
            },
            output_schema={"type": "object", "required": ["path", "content", "sha256"]},
            risk_tier=RiskTier.R0,
            allowed_roles=frozenset({"worker", "supervisor", "reviewer"}),
        )

    def execute(self, context: ToolContext, payload: dict[str, Any]) -> ToolResult:
        return ToolResult(output=self.workspace.read_text(payload["path"]))


class WorkspaceListTool:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="workspace.list",
            version="1",
            description="List bounded non-sensitive workspace entries",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string", "default": ".", "maxLength": 500},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
                },
            },
            output_schema={"type": "object", "required": ["entries"]},
            risk_tier=RiskTier.R0,
            allowed_roles=frozenset({"worker", "supervisor", "reviewer"}),
        )

    def execute(self, context: ToolContext, payload: dict[str, Any]) -> ToolResult:
        return ToolResult(
            output=self.workspace.list(payload.get("path", "."), limit=payload.get("limit", 200))
        )


class WorkspacePythonMapTool:
    def __init__(self, workspace: Workspace) -> None:
        self.mapper = PythonRepositoryMap(workspace)

    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="workspace.python_map",
            version="1",
            description="Map bounded Python imports and symbols with stdlib AST; never executes code",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string", "default": ".", "maxLength": 500},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
            },
            output_schema={
                "type": "object",
                "required": ["path", "language", "modules", "truncated", "code_executed"],
            },
            risk_tier=RiskTier.R0,
            allowed_roles=frozenset({"worker", "supervisor", "reviewer"}),
        )

    def execute(self, context: ToolContext, payload: dict[str, Any]) -> ToolResult:
        output = self.mapper.build(payload.get("path", "."), limit=payload.get("limit", 40))
        return ToolResult(
            output=output,
            evidence={"parser": "stdlib_ast", "code_executed": False},
        )


class StartupAcceptanceTool:
    """Validate real company-startup evidence; never fabricate quality or execution."""

    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="factory.accept_startup",
            version="1",
            description="Validate bounded startup inventory, brief, states, and reviewer verdict",
            input_schema={
                "type": "object",
                "required": [
                    "inventory",
                    "brief",
                    "inventory_state",
                    "brief_state",
                    "review_verdict",
                ],
                "additionalProperties": False,
                "properties": {
                    "inventory": {"type": "object"},
                    "brief": {"type": "string", "maxLength": MAX_STARTUP_BRIEF_CHARS},
                    "inventory_state": {"type": "string", "maxLength": 40},
                    "brief_state": {"type": "string", "maxLength": 40},
                    "review_verdict": {"type": "string", "maxLength": 40},
                },
            },
            output_schema={
                "type": "object",
                "required": ["accepted", "postcondition", "checks", "evidence"],
                "properties": {
                    "accepted": {"type": "boolean"},
                    "postcondition": {"type": "boolean"},
                    "checks": {"type": "array", "maxItems": 5},
                    "evidence": {
                        "type": "object",
                        "required": [
                            "scope",
                            "checks_passed",
                            "checks_total",
                            "inventory_entries",
                            "brief_sha256",
                            "additional_execution_claimed",
                        ],
                    },
                },
            },
            risk_tier=RiskTier.R0,
            allowed_roles=frozenset({"worker", "reviewer"}),
        )

    def execute(self, context: ToolContext, payload: dict[str, Any]) -> ToolResult:
        output = evaluate_startup_acceptance(**payload)
        return ToolResult(
            output=output,
            evidence={
                "accepted": output["accepted"],
                "checks_passed": output["evidence"]["checks_passed"],
                "inventory_entry_ceiling": MAX_STARTUP_INVENTORY_ENTRIES,
                "additional_execution_claimed": False,
            },
        )


class WorkspaceWriteTool:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="workspace.write",
            version="1",
            description="Atomically write a bounded UTF-8 file",
            input_schema={
                "type": "object",
                "required": ["path", "content"],
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 500},
                    "content": {"type": "string", "maxLength": 1_000_000},
                },
            },
            output_schema={"type": "object", "required": ["path", "sha256", "postcondition"]},
            risk_tier=RiskTier.R1,
            allowed_roles=frozenset({"worker"}),
            idempotent=True,
        )

    def execute(self, context: ToolContext, payload: dict[str, Any]) -> ToolResult:
        output = self.workspace.write_text(payload["path"], payload["content"])
        return ToolResult(output=output, evidence={"postcondition": output["postcondition"]})


class WorkspaceDeleteTool:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="workspace.delete",
            version="1",
            description="Back up and delete one regular file",
            input_schema={
                "type": "object",
                "required": ["path"],
                "additionalProperties": False,
                "properties": {"path": {"type": "string", "minLength": 1, "maxLength": 500}},
            },
            output_schema={"type": "object", "required": ["path"]},
            risk_tier=RiskTier.R3,
            allowed_roles=frozenset({"worker"}),
            idempotent=True,
        )

    def execute(self, context: ToolContext, payload: dict[str, Any]) -> ToolResult:
        output = self.workspace.delete_file(payload["path"])
        return ToolResult(
            output=output, evidence={"reversible_backup": output.get("backup_artifact")}
        )


def build_tool_registry(
    db: Database,
    approvals: ApprovalService,
    ledger: IdempotencyLedger,
    workspace: Workspace,
    *,
    max_output_chars: int = 32_000,
) -> ToolRegistry:
    registry = ToolRegistry(db, approvals, ledger, max_output_chars=max_output_chars)
    registry.register(WorkspaceListTool(workspace))
    registry.register(WorkspacePythonMapTool(workspace))
    registry.register(StartupAcceptanceTool())
    registry.register(WorkspaceReadTool(workspace))
    registry.register(WorkspaceWriteTool(workspace))
    registry.register(WorkspaceDeleteTool(workspace))
    return registry
