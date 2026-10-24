"""Typed contracts for durable tasks, tools, and agent handoffs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TaskState(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    VERIFYING = "verifying"
    RETRY_WAIT = "retry_wait"
    PAUSED_OFFLINE = "paused_offline"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNCERTAIN_SIDE_EFFECT = "uncertain_side_effect"


class RiskTier(StrEnum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


class Priority(StrEnum):
    INTERACTIVE = "interactive"
    NORMAL = "normal"
    BATCH = "batch"
    IDLE = "idle"


class CapabilityState(StrEnum):
    IMPLEMENTED = "implemented"
    IMPLEMENTED_OPTIONAL = "implemented_optional"
    PROTOTYPE = "prototype"
    PLANNED = "planned"


ALLOWED_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.QUEUED: frozenset(
        {TaskState.PLANNING, TaskState.CANCELLED, TaskState.PAUSED_OFFLINE}
    ),
    TaskState.PLANNING: frozenset(
        {
            TaskState.QUEUED,
            TaskState.RUNNING,
            TaskState.AWAITING_APPROVAL,
            TaskState.RETRY_WAIT,
            TaskState.PAUSED_OFFLINE,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.RUNNING: frozenset(
        {
            TaskState.QUEUED,
            TaskState.VERIFYING,
            TaskState.AWAITING_APPROVAL,
            TaskState.RETRY_WAIT,
            TaskState.PAUSED_OFFLINE,
            TaskState.FAILED,
            TaskState.CANCELLED,
            TaskState.UNCERTAIN_SIDE_EFFECT,
        }
    ),
    TaskState.VERIFYING: frozenset(
        {
            TaskState.QUEUED,
            TaskState.SUCCEEDED,
            TaskState.RUNNING,
            TaskState.RETRY_WAIT,
            TaskState.PAUSED_OFFLINE,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.AWAITING_APPROVAL: frozenset(
        {
            TaskState.QUEUED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.RETRY_WAIT: frozenset(
        {
            TaskState.QUEUED,
            TaskState.PLANNING,
            TaskState.PAUSED_OFFLINE,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.PAUSED_OFFLINE: frozenset(
        {
            TaskState.QUEUED,
            TaskState.PLANNING,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.UNCERTAIN_SIDE_EFFECT: frozenset(
        {
            TaskState.QUEUED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.FAILED: frozenset({TaskState.QUEUED}),
    TaskState.CANCELLED: frozenset({TaskState.QUEUED}),
    TaskState.SUCCEEDED: frozenset(),
}


@dataclass(slots=True)
class TaskContract:
    goal: str
    kind: str = "agent"
    parent_task_id: str | None = None
    correlation_id: str | None = None
    requester: str = "local-user"
    department: str = "executive"
    priority: Priority = Priority.NORMAL
    risk_tier: RiskTier = RiskTier.R0
    deadline: str | None = None
    input_data: dict[str, Any] = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    budget: dict[str, int] = field(default_factory=dict)
    expected_output_schema: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    depends_on: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ToolContext:
    task_id: str
    role: str
    step_id: str
    requester: str = "local-user"
    approved_digests: set[str] = field(default_factory=set)


@dataclass(slots=True)
class ToolResult:
    output: dict[str, Any]
    receipt: str | None = None
    uncertain: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentHandoff:
    role: str
    status: str
    output: dict[str, Any]
    evidence: list[str] = field(default_factory=list)
    model: str | None = None
    provider: str | None = None
