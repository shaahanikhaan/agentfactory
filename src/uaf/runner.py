"""Deterministic durable orchestration; agents are bounded steps, not authorities."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from uaf.agents import AgentRuntime
from uaf.db import Database
from uaf.errors import (
    ApprovalRequired,
    SideEffectError,
    StateTransitionError,
    UAFError,
    UnavailableError,
    ValidationError,
)
from uaf.models import TaskState, ToolContext
from uaf.tasks import TaskStore
from uaf.tools import ToolRegistry
from uaf.util import json_data, now_dt, parse_time, redact_data


class _CancelledExecution(Exception):
    pass


class TaskRunner:
    def __init__(
        self,
        db: Database,
        tasks: TaskStore,
        agents: AgentRuntime,
        tools: ToolRegistry,
    ) -> None:
        self.db = db
        self.tasks = tasks
        self.agents = agents
        self.tools = tools

    def run(self, task_id: str) -> dict[str, Any]:
        task = self.tasks.require(task_id)
        state = TaskState(task["state"])
        if state == TaskState.SUCCEEDED:
            return task
        if state in {TaskState.PLANNING, TaskState.RUNNING, TaskState.VERIFYING}:
            raise UnavailableError("Task has an interrupted in-flight state; use task resume first")
        if state in {TaskState.FAILED, TaskState.CANCELLED, TaskState.PAUSED_OFFLINE}:
            raise UnavailableError(f"Task is {state}; use task resume before running it")
        if state == TaskState.AWAITING_APPROVAL:
            raise UnavailableError("Task is awaiting approval; decide it and then use task resume")
        if state == TaskState.UNCERTAIN_SIDE_EFFECT:
            raise UnavailableError("Task needs side-effect reconciliation, not a blind rerun")
        if (
            state == TaskState.RETRY_WAIT
            and task["retry_at"]
            and parse_time(task["retry_at"]) > now_dt()
        ):
            return task
        if not self.tasks.dependencies_satisfied(task_id):
            task["waiting_for_dependencies"] = True
            return task
        try:
            task = self.tasks.transition(task_id, TaskState.PLANNING)
            self._assert_active(task_id)
            plan = self._step(task, "manager", 1, self.agents.manager)
            task = self.tasks.transition(task_id, TaskState.RUNNING)
            self._assert_active(task_id)
            work_order = self._step(
                task, "supervisor", 2, lambda current: self.agents.supervisor(current, plan)
            )
            if task["kind"] == "smoke":
                return self._run_smoke(task, work_order)
            if task["kind"] == "agent":
                return self._run_agent(task, work_order)
            if task["kind"] == "react":
                return self._run_react(task, work_order)
            if task["kind"] == "tool":
                return self._run_tool(task, work_order)
            raise ValidationError(f"Unsupported task kind: {task['kind']}")
        except _CancelledExecution:
            return self.tasks.require(task_id)
        except ApprovalRequired as exc:
            current = self.tasks.require(task_id)
            if TaskState(current["state"]) == TaskState.CANCELLED:
                return current
            return self.tasks.transition(
                task_id,
                TaskState.AWAITING_APPROVAL,
                approval_id=exc.approval_id,
                error={"code": exc.code, "message": str(exc), "approval_id": exc.approval_id},
            )
        except SideEffectError as exc:
            if exc.uncertain:
                return self.tasks.transition(
                    task_id,
                    TaskState.UNCERTAIN_SIDE_EFFECT,
                    error={"code": exc.code, "message": str(exc), "reconcile_required": True},
                )
            return self._fail(task_id, exc)
        except UnavailableError as exc:
            current = self.tasks.require(task_id)
            if TaskState(current["state"]) == TaskState.CANCELLED:
                return current
            if exc.details.get("retryable") is False:
                return self._fail(task_id, exc)
            if exc.details.get("retryable"):
                delay = min(60, 2 ** max(1, current["attempt"]))
                retry_at = (
                    (now_dt() + timedelta(seconds=delay))
                    .isoformat(timespec="milliseconds")
                    .replace("+00:00", "Z")
                )
                return self.tasks.mark_retry(
                    task_id,
                    retry_at,
                    {
                        "code": exc.code,
                        "message": str(exc),
                    },
                )
            if TaskState(current["state"]) in {
                TaskState.PLANNING,
                TaskState.RUNNING,
                TaskState.VERIFYING,
            }:
                return self.tasks.transition(
                    task_id,
                    TaskState.PAUSED_OFFLINE,
                    error={"code": exc.code, "message": str(exc)},
                )
            return self._fail(task_id, exc)
        except Exception as exc:
            return self._fail(task_id, exc)

    def _run_smoke(self, task: dict[str, Any], work_order: dict[str, Any]) -> dict[str, Any]:
        worker = self._step(task, "worker", 3, self.agents.smoke_worker)
        self.tasks.transition(task["task_id"], TaskState.VERIFYING)
        review = self._step(
            task, "reviewer", 4, lambda current: self.agents.smoke_reviewer(current, worker)
        )
        if review["verdict"] != "pass":
            raise ValidationError("Offline smoke review failed")
        return self.tasks.transition(
            task["task_id"],
            TaskState.SUCCEEDED,
            result={
                "mode": "offline_deterministic",
                "ai_generated": False,
                "output": worker["message"],
                "review": review,
                "evidence": {"model_calls": 0, "checkpoints": 4, "work_order": work_order},
            },
        )

    def _run_agent(self, task: dict[str, Any], work_order: dict[str, Any]) -> dict[str, Any]:
        worker: dict[str, Any] = {}
        review: dict[str, Any] = {}
        for revision in (1, 2):
            step_base = 3 if revision == 1 else 5
            worker = self._step(
                task,
                f"worker:{revision}",
                step_base,
                lambda current, r=revision, previous=worker, previous_review=review or None: (
                    self.agents.cloud_worker(
                        current,
                        work_order,
                        revision=r,
                        previous_output=previous.get("text", ""),
                        review=previous_review,
                    )
                ),
            )
            self.tasks.transition(task["task_id"], TaskState.VERIFYING)
            review = self._step(
                task,
                f"reviewer:{revision}",
                step_base + 1,
                lambda current, r=revision, worker_result=worker: self.agents.cloud_reviewer(
                    current, worker_result, revision=r
                ),
            )
            if review["verdict"] == "pass":
                return self.tasks.transition(
                    task["task_id"],
                    TaskState.SUCCEEDED,
                    result={
                        "mode": "provider",
                        "ai_generated": True,
                        "output": worker["parsed"],
                        "provider": worker["provider"],
                        "model": worker["model"],
                        "review": review,
                        "revision": revision,
                        "evidence": {"model_calls": self.tasks.model_call_count(task["task_id"])},
                    },
                )
            if review["verdict"] == "fail" or revision == 2:
                raise ValidationError(
                    "Reviewer rejected worker output: " + "; ".join(review.get("reasons", []))
                )
            self.tasks.transition(task["task_id"], TaskState.RUNNING)
            self._assert_active(task["task_id"])
        raise ValidationError("Reviewer revision loop exhausted")

    def _run_react(self, task: dict[str, Any], work_order: dict[str, Any]) -> dict[str, Any]:
        max_turns = min(3, task["budget"]["max_model_calls"] - 1)
        if max_turns < 1:
            raise UnavailableError(
                "ReAct requires at least one worker call and one reviewer call",
                details={"retryable": False},
            )
        catalog = [
            metadata for metadata in self.tools.list() if metadata["name"] in task["allowed_tools"]
        ]
        history: list[dict[str, Any]] = []
        for turn in range(1, max_turns + 1):
            sequence = 3 + (turn - 1) * 2
            decision = self._step(
                task,
                f"react:decision:{turn}",
                sequence,
                lambda current, t=turn, prior=history: self.agents.react_decision(
                    current,
                    work_order,
                    history=prior,
                    tool_catalog=catalog,
                ),
            )
            action = decision["decision"]
            if action["action"] == "final":
                answer = action["answer"]
                worker = {**decision, "parsed": answer}
                self.tasks.transition(task["task_id"], TaskState.VERIFYING)
                review = self._step(
                    task,
                    "reviewer",
                    9,
                    lambda current, result=worker: self.agents.cloud_reviewer(current, result),
                )
                if review["verdict"] != "pass":
                    raise ValidationError(
                        "Reviewer rejected ReAct output: " + "; ".join(review.get("reasons", []))
                    )
                return self.tasks.transition(
                    task["task_id"],
                    TaskState.SUCCEEDED,
                    result={
                        "mode": "react",
                        "ai_generated": True,
                        "output": answer,
                        "provider": decision["provider"],
                        "model": decision["model"],
                        "review": review,
                        "turns": turn,
                        "tool_calls": len(history),
                        "evidence": {
                            "model_calls": self.tasks.model_call_count(task["task_id"]),
                            "durable_decisions": turn,
                        },
                    },
                )

            if len(history) >= task["budget"]["max_tool_calls"]:
                raise ValidationError("ReAct tool-call budget exhausted")
            step_id = f"{task['task_id']}:react:observation:{turn}"

            def observe(
                _: dict[str, Any], selected=action, observation_step=step_id
            ) -> dict[str, Any]:
                context = ToolContext(
                    task_id=task["task_id"],
                    role="worker",
                    step_id=observation_step,
                    requester=task["requester"],
                )
                invocation = self.tools.invoke(
                    selected["tool"],
                    context,
                    selected["arguments"],
                    task_allowed_tools=task["allowed_tools"],
                )
                return {
                    "tool": selected["tool"],
                    "output": invocation["output"],
                    "evidence": invocation.get("evidence", {}),
                    "invocation_id": invocation["invocation_id"],
                }

            observation = self._step(
                task,
                f"react:observation:{turn}",
                sequence + 1,
                observe,
            )
            history.append({"decision": action, "observation": observation})
        raise ValidationError("ReAct turn budget exhausted before a final answer")

    def _run_tool(self, task: dict[str, Any], work_order: dict[str, Any]) -> dict[str, Any]:
        name = task["input"]["tool"]
        arguments = task["input"].get("arguments", {})
        step_id = f"{task['task_id']}:worker:1"

        def execute(_: dict[str, Any]) -> dict[str, Any]:
            context = ToolContext(
                task_id=task["task_id"],
                role="worker",
                step_id=step_id,
                requester=task["requester"],
            )
            return self.tools.invoke(
                name, context, arguments, task_allowed_tools=task["allowed_tools"]
            )

        worker = self._step(task, "worker:1", 3, execute)
        self.tasks.transition(task["task_id"], TaskState.VERIFYING)

        def review(_: dict[str, Any]) -> dict[str, Any]:
            output = worker.get("output", {})
            passed = output.get("postcondition", True) is not False
            return {
                "verdict": "pass" if passed else "fail",
                "reasons": [] if passed else ["Tool postcondition was false"],
                "evidence": [
                    f"invocation:{worker['invocation_id']}",
                    "runtime policy and schema checked",
                ],
            }

        review = self._step(task, "reviewer", 4, review)
        if review["verdict"] != "pass":
            raise ValidationError("Tool result review failed")
        return self.tasks.transition(
            task["task_id"],
            TaskState.SUCCEEDED,
            result={
                "mode": "tool",
                "ai_generated": False,
                "output": worker["output"],
                "review": review,
                "evidence": worker.get("evidence", {}),
            },
        )

    def _step(
        self,
        task: dict[str, Any],
        logical_step: str,
        sequence: int,
        operation: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        self._assert_active(task["task_id"])
        step_id = f"{task['task_id']}:{logical_step}"
        existing = self.tasks.completed_step(task["task_id"], step_id)
        if existing:
            return json_data(existing["result_json"], {})
        if len(self.tasks.steps(task["task_id"])) >= task["budget"]["max_steps"]:
            raise UnavailableError("Task step budget exhausted", details={"retryable": False})
        result = operation(task)
        if not isinstance(result, dict):
            raise ValidationError(f"Agent step {logical_step} returned a non-object result")
        self.tasks.checkpoint(
            task["task_id"],
            step_id=step_id,
            sequence=sequence,
            role=logical_step.split(":", 1)[0],
            input_data={
                "goal": task["goal"],
                "kind": task["kind"],
                "step": logical_step,
            },
            result=result,
        )
        return result

    def _assert_active(self, task_id: str) -> None:
        task = self.tasks.require(task_id)
        state = TaskState(task["state"])
        if state == TaskState.CANCELLED or task["cancel_requested"]:
            if state != TaskState.CANCELLED:
                self.tasks.transition(task_id, TaskState.CANCELLED)
            raise _CancelledExecution
        if task["deadline"] and parse_time(task["deadline"]) <= now_dt():
            raise ValidationError("Task deadline expired before execution")
        if task["started_at"]:
            elapsed = (now_dt() - parse_time(task["started_at"])).total_seconds()
            if elapsed > task["budget"]["task_wall_seconds"]:
                raise UnavailableError(
                    "Task wall-time budget exhausted", details={"retryable": False}
                )

    def _fail(self, task_id: str, exc: Exception) -> dict[str, Any]:
        current = self.tasks.require(task_id)
        state = TaskState(current["state"])
        if state in {TaskState.CANCELLED, TaskState.SUCCEEDED, TaskState.FAILED}:
            return current
        code = exc.code if isinstance(exc, UAFError) else type(exc).__name__
        error = {"code": code, "message": str(exc)[:2000], "type": type(exc).__name__}
        if TaskState.FAILED not in {
            TaskState.PLANNING,
            TaskState.RUNNING,
            TaskState.VERIFYING,
            TaskState.RETRY_WAIT,
            TaskState.PAUSED_OFFLINE,
        }:
            # Check the actual allowed transition through the store for less common states.
            try:
                return self.tasks.transition(task_id, TaskState.FAILED, error=error)
            except StateTransitionError:
                return current
        return self.tasks.transition(task_id, TaskState.FAILED, error=redact_data(error))

    def run_all(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValidationError("Run-all limit must be between 1 and 100")
        completed = []
        for _ in range(limit):
            task = self.tasks.next_runnable()
            if not task:
                break
            result = self.run(task["task_id"])
            completed.append(result)
            if TaskState(result["state"]) in {TaskState.QUEUED, TaskState.RETRY_WAIT}:
                break
        return completed
