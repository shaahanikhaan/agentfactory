"""Durable serial execution of immutable declarative agent DAGs."""

from __future__ import annotations

import re
from typing import Any

from uaf.blueprints import BlueprintRegistry, topological_order, validate_blueprint_inputs
from uaf.db import Database
from uaf.errors import (
    IdempotencyConflict,
    IntegrityError,
    StateTransitionError,
    UnavailableError,
    ValidationError,
)
from uaf.models import TaskContract, TaskState
from uaf.runner import TaskRunner
from uaf.tasks import TaskStore
from uaf.util import (
    bounded,
    canonical_json,
    json_data,
    new_id,
    payload_digest,
    redact_data,
    utc_now,
)

_TEMPLATE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")
_ACTIVE = {
    TaskState.QUEUED,
    TaskState.PLANNING,
    TaskState.RUNNING,
    TaskState.VERIFYING,
    TaskState.AWAITING_APPROVAL,
    TaskState.RETRY_WAIT,
    TaskState.PAUSED_OFFLINE,
}


class FactoryService:
    def __init__(
        self,
        db: Database,
        tasks: TaskStore,
        runner: TaskRunner,
        blueprints: BlueprintRegistry,
    ) -> None:
        self.db = db
        self.tasks = tasks
        self.runner = runner
        self.blueprints = blueprints

    def start(
        self,
        blueprint_id: str,
        goal: str,
        *,
        inputs: dict[str, Any] | None = None,
        requester: str = "local-user",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        blueprint = self.blueprints.require(blueprint_id)
        if not blueprint["enabled"]:
            raise ValidationError(
                "Blueprint is disabled; review and enable it before starting a run"
            )
        goal = goal.strip()
        bounded(goal, 20_000, label="factory goal")
        if not goal:
            raise ValidationError("Factory goal cannot be empty")
        inputs = {} if inputs is None else inputs
        if not isinstance(inputs, dict):
            raise ValidationError("Factory inputs must be a JSON object")
        try:
            if len(canonical_json(inputs)) > 32_000:
                raise ValidationError("Factory inputs exceed 32 KB")
        except ValueError as exc:
            raise ValidationError("Factory inputs contain a non-finite number") from exc
        bounded(requester, 200, label="requester")
        if idempotency_key:
            bounded(idempotency_key, 200, label="factory idempotency key")
        validate_blueprint_inputs(blueprint["spec"]["input_schema"], inputs)
        identity = payload_digest(
            {"blueprint_checksum": blueprint["checksum"], "goal": goal, "inputs": inputs}
        )
        if idempotency_key:
            existing = self.db.one(
                "SELECT * FROM factory_runs WHERE requester=? AND idempotency_key=?",
                (requester, idempotency_key),
            )
            if existing:
                old_input = json_data(existing["input_json"], {})
                if old_input.get("identity_digest") != identity:
                    raise IdempotencyConflict(
                        "Factory idempotency key belongs to a different blueprint or payload"
                    )
                return self.require(existing["run_id"])

        spec = blueprint["spec"]
        order = topological_order(spec["steps"])
        step_specs = {step["step_id"]: step for step in spec["steps"]}
        agents = {agent["agent_id"]: agent for agent in spec["agents"]}
        run_id = new_id("factory")
        now = utc_now()
        plan = {
            "topological_order": order,
            "output_from": spec["output"]["from"],
            "blueprint_checksum": blueprint["checksum"],
        }
        with self.db.transaction():
            self.db._conn.execute(
                "INSERT INTO factory_runs(run_id,blueprint_id,requester,idempotency_key,goal,input_json,"
                "plan_json,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'queued',?,?)",
                (
                    run_id,
                    blueprint_id,
                    requester,
                    idempotency_key,
                    goal,
                    canonical_json(redact_data({"inputs": inputs, "identity_digest": identity})),
                    canonical_json(plan),
                    now,
                    now,
                ),
            )
            task_ids = {}
            for step_id in order:
                step = step_specs[step_id]
                agent = agents[step["agent_id"]]
                raw_input = {
                    **step.get("input", {}),
                    "agent_profile": {
                        "name": agent.get("name", agent["agent_id"]),
                        "instructions": agent.get("instructions", ""),
                    },
                }
                constraints = [
                    *spec["defaults"].get("constraints", []),
                    *agent.get("constraints", []),
                    *step.get("constraints", []),
                ]
                dependencies = [task_ids[item] for item in step.get("depends_on", [])]
                task = self.tasks.add(
                    TaskContract(
                        requester=requester,
                        correlation_id=run_id,
                        goal=f"{step_id}: {step['goal']}",
                        kind=agent["kind"],
                        input_data=raw_input,
                        constraints=constraints,
                        depends_on=dependencies,
                        allowed_tools=agent.get("allowed_tools", []),
                        expected_output_schema=step.get("expected_output_schema", {}),
                        risk_tier=agent.get("risk_tier", "R0"),
                        priority=spec["defaults"].get("priority", "normal"),
                        department=agent.get(
                            "department", spec["defaults"].get("department", "executive")
                        ),
                        budget={
                            **spec["defaults"].get("budget", {}),
                            **agent.get("budget", {}),
                        },
                        idempotency_key=f"{run_id}:{step_id}",
                    )
                )
                task_ids[step_id] = task["task_id"]
                self.db._conn.execute(
                    "INSERT INTO factory_run_tasks(run_id,step_id,task_id,agent_id) VALUES(?,?,?,?)",
                    (run_id, step_id, task["task_id"], agent["agent_id"]),
                )
            self.db.audit(
                "factory.start",
                object_type="factory_run",
                object_id=run_id,
                actor=requester,
                metadata={"blueprint_id": blueprint_id, "steps": len(order)},
            )
        self._update(run_id, "running")
        return self._drive_with_recovery(run_id)

    def require(self, run_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM factory_runs WHERE run_id=?", (run_id,))
        if not row:
            raise ValidationError(f"Factory run does not exist: {run_id}")
        result = self._decode(row)
        result["steps"] = self._step_status(run_id)
        return result

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValidationError("Factory list limit must be between 1 and 100")
        return [
            self._decode(row)
            for row in self.db.query(
                "SELECT * FROM factory_runs ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        ]

    def resume(self, run_id: str, *, actor: str = "local-user") -> dict[str, Any]:
        run = self.require(run_id)
        if run["state"] == "succeeded":
            return run
        if run["state"] == "uncertain_side_effect":
            raise UnavailableError("Reconcile the uncertain task before resuming its factory run")
        for item in self._mappings(run_id):
            task = self.tasks.require(item["task_id"])
            state = TaskState(task["state"])
            if state == TaskState.UNCERTAIN_SIDE_EFFECT:
                raise UnavailableError(
                    "Reconcile the uncertain task before resuming its factory run"
                )
            if state in {
                TaskState.PLANNING,
                TaskState.RUNNING,
                TaskState.VERIFYING,
                TaskState.PAUSED_OFFLINE,
                TaskState.FAILED,
                TaskState.CANCELLED,
            }:
                self.tasks.resume(task["task_id"], actor=actor)
            elif state == TaskState.AWAITING_APPROVAL:
                try:
                    self.tasks.resume(task["task_id"], actor=actor)
                except UnavailableError as exc:
                    if "pending" not in str(exc).lower():
                        raise
        self._update(run_id, "running", error=None, clear_finished=True)
        self.db.audit(
            "factory.resume",
            object_type="factory_run",
            object_id=run_id,
            actor=actor,
        )
        return self._drive_with_recovery(run_id)

    def cancel(self, run_id: str, *, actor: str = "local-user") -> dict[str, Any]:
        run = self.require(run_id)
        if run["state"] in {"succeeded", "failed", "cancelled", "uncertain_side_effect"}:
            raise StateTransitionError(f"Cannot cancel a factory run in {run['state']}")
        for item in self._mappings(run_id):
            task = self.tasks.require(item["task_id"])
            state = TaskState(task["state"])
            if state == TaskState.UNCERTAIN_SIDE_EFFECT:
                raise UnavailableError(
                    "Uncertain side effects require reconciliation, not cancellation"
                )
            if state in _ACTIVE:
                self.tasks.cancel(task["task_id"], actor=actor)
        self._update(run_id, "cancelled", error={"code": "cancelled", "actor": actor})
        self.db.audit("factory.cancel", object_type="factory_run", object_id=run_id, actor=actor)
        return self.require(run_id)

    def _drive_with_recovery(self, run_id: str) -> dict[str, Any]:
        try:
            return self._drive(run_id)
        except (ValidationError, IntegrityError, StateTransitionError) as exc:
            self._update(
                run_id,
                "failed",
                error={
                    "code": exc.code,
                    "message": str(exc)[:2000],
                    "type": type(exc).__name__,
                },
            )
            return self.require(run_id)
        except BaseException as exc:
            # Preserve the original interruption while making its durable state discoverable.
            self._update(
                run_id,
                "interrupted",
                error={
                    "code": "interrupted",
                    "message": str(exc)[:2000],
                    "type": type(exc).__name__,
                    "resume_required": True,
                },
            )
            raise

    def _drive(self, run_id: str) -> dict[str, Any]:
        run = self.require(run_id)
        order = run["plan"]["topological_order"]
        mappings = {item["step_id"]: item for item in self._mappings(run_id)}
        spec = self.blueprints.require(run["blueprint_id"])["spec"]
        step_specs = {step["step_id"]: step for step in spec["steps"]}
        for step_id in order:
            mapping = mappings[step_id]
            task = self.tasks.require(mapping["task_id"])
            state = TaskState(task["state"])
            if state == TaskState.SUCCEEDED:
                continue
            if state in {TaskState.QUEUED, TaskState.RETRY_WAIT}:
                if not self.tasks.dependencies_satisfied(task["task_id"]):
                    self._update(
                        run_id,
                        "failed",
                        error={
                            "code": "dependency_not_satisfied",
                            "step_id": step_id,
                            "task_id": task["task_id"],
                        },
                    )
                    return self.require(run_id)
                task = self._materialize(run, mapping, step_specs[step_id])
                task = self.runner.run(task["task_id"])
                state = TaskState(task["state"])
                if state == TaskState.SUCCEEDED:
                    continue
            target = {
                TaskState.AWAITING_APPROVAL: "awaiting_approval",
                TaskState.RETRY_WAIT: "retry_wait",
                TaskState.PAUSED_OFFLINE: "paused_offline",
                TaskState.PLANNING: "interrupted",
                TaskState.RUNNING: "interrupted",
                TaskState.VERIFYING: "interrupted",
                TaskState.FAILED: "failed",
                TaskState.CANCELLED: "cancelled",
                TaskState.UNCERTAIN_SIDE_EFFECT: "uncertain_side_effect",
            }.get(state)
            if target is None:
                raise StateTransitionError(f"Unexpected factory task state: {state}")
            error = task.get("error") or {
                "code": target,
                "message": f"Factory step {step_id} is {target}",
            }
            self._update(
                run_id,
                target,
                error={"step_id": step_id, "task_id": task["task_id"], **error},
            )
            return self.require(run_id)
        self._update(run_id, "succeeded", error=None)
        self.db.audit(
            "factory.succeeded", object_type="factory_run", object_id=run_id, actor="runtime"
        )
        return self.require(run_id)

    def _materialize(
        self, run: dict[str, Any], mapping: dict[str, Any], step: dict[str, Any]
    ) -> dict[str, Any]:
        task = self.tasks.require(mapping["task_id"])
        if mapping["materialized"]:
            digest = payload_digest({"goal": task["goal"], "input": task["input"]})
            if digest != mapping["materialized_digest"]:
                raise IntegrityError("Materialized factory task payload does not match its digest")
            return task
        blueprint = self.blueprints.require(run["blueprint_id"])
        agent = next(
            item for item in blueprint["spec"]["agents"] if item["agent_id"] == mapping["agent_id"]
        )
        context = self._template_context(run)
        goal = _render(step["goal"], context)
        if not isinstance(goal, str):
            raise ValidationError("Materialized factory step goal must be a string")
        bounded(goal.strip(), 20_000, label="materialized step goal")
        rendered_input = _render(step.get("input", {}), context)
        if not isinstance(rendered_input, dict):
            raise ValidationError("Materialized factory step input must be an object")
        constraints = _render(task["input"].get("constraints", []), context)
        if not isinstance(constraints, list) or any(
            not isinstance(item, str) for item in constraints
        ):
            raise ValidationError("Materialized factory constraints must be strings")
        stored_input = {
            **rendered_input,
            "agent_profile": {
                "name": agent.get("name", agent["agent_id"]),
                "instructions": agent.get("instructions", ""),
            },
            "constraints": constraints,
            "depends_on": task["input"].get("depends_on", []),
        }
        if len(canonical_json(stored_input)) > 64_000:
            raise ValidationError("Materialized factory step input exceeds 64 KB")
        safe_input = redact_data(stored_input)
        digest = payload_digest({"goal": goal.strip(), "input": safe_input})
        with self.db.transaction():
            updated = self.db._conn.execute(
                "UPDATE tasks SET goal=?,input_json=?,updated_at=? WHERE task_id=? AND state IN ('queued','retry_wait')",
                (goal.strip(), canonical_json(safe_input), utc_now(), task["task_id"]),
            )
            if updated.rowcount != 1:
                raise StateTransitionError("Factory task changed before atomic materialization")
            mapped = self.db._conn.execute(
                "UPDATE factory_run_tasks SET materialized=1,materialized_digest=? WHERE run_id=? AND step_id=?",
                (digest, run["run_id"], step["step_id"]),
            )
            if mapped.rowcount != 1:
                raise StateTransitionError("Factory materialization mapping changed unexpectedly")
            self.db.audit(
                "factory.materialize",
                object_type="factory_run",
                object_id=run["run_id"],
                actor="runtime",
                metadata={"step_id": step["step_id"], "payload_digest": digest},
            )
        return self.tasks.require(task["task_id"])

    def _template_context(self, run: dict[str, Any]) -> dict[str, Any]:
        steps = {}
        for item in self._mappings(run["run_id"]):
            task = self.tasks.require(item["task_id"])
            result = task.get("result") or {}
            steps[item["step_id"]] = {
                "state": task["state"],
                "result": result,
                "output": result.get("output"),
            }
        return {"goal": run["goal"], "inputs": run["inputs"], "steps": steps}

    def _update(
        self,
        run_id: str,
        state: str,
        *,
        error: dict[str, Any] | None = None,
        clear_finished: bool = False,
    ) -> None:
        result = self._build_result(run_id, partial=state != "succeeded")
        now = utc_now()
        finished = (
            now if state in {"succeeded", "failed", "cancelled", "uncertain_side_effect"} else None
        )
        if clear_finished:
            finished = None
        self.db.execute(
            "UPDATE factory_runs SET state=?,result_json=?,error_json=?,updated_at=?,finished_at=? WHERE run_id=?",
            (
                state,
                canonical_json(redact_data(result)),
                canonical_json(redact_data(error)) if error is not None else None,
                now,
                finished,
                run_id,
            ),
        )

    def _build_result(self, run_id: str, *, partial: bool) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM factory_runs WHERE run_id=?", (run_id,))
        if not row:
            raise ValidationError("Factory run disappeared")
        plan = json_data(row["plan_json"], {})
        steps = self._step_status(run_id)
        selected = next(
            (item for item in steps if item["step_id"] == plan.get("output_from")), None
        )
        output = selected.get("output") if selected and not partial else None
        tasks = [self.tasks.require(item["task_id"]) for item in self._mappings(run_id)]
        return {
            "mode": "factory",
            "blueprint_id": row["blueprint_id"],
            "output": output,
            "partial": partial,
            "steps": steps,
            "metrics": {
                "model_calls": sum(
                    self.tasks.completed_model_call_count(task["task_id"]) for task in tasks
                ),
                "model_attempts": sum(
                    self.tasks.model_call_count(task["task_id"]) for task in tasks
                ),
                "tool_calls": sum(
                    self.db.one(
                        "SELECT COUNT(*) c FROM tool_invocations WHERE task_id=?",
                        (task["task_id"],),
                    )["c"]
                    for task in tasks
                ),
                "checkpoints": sum(len(self.tasks.steps(task["task_id"])) for task in tasks),
                "succeeded_steps": sum(task["state"] == "succeeded" for task in tasks),
                "total_steps": len(tasks),
            },
        }

    def _step_status(self, run_id: str) -> list[dict[str, Any]]:
        return [
            {
                "step_id": item["step_id"],
                "agent_id": item["agent_id"],
                "task_id": item["task_id"],
                "state": (task := self.tasks.require(item["task_id"]))["state"],
                "output": (task.get("result") or {}).get("output"),
                "error": task.get("error"),
                "materialized": bool(item["materialized"]),
            }
            for item in self._mappings(run_id)
        ]

    def _mappings(self, run_id: str) -> list[dict[str, Any]]:
        row = self.db.one("SELECT plan_json FROM factory_runs WHERE run_id=?", (run_id,))
        if not row:
            raise ValidationError("Factory run disappeared")
        order = json_data(row["plan_json"], {}).get("topological_order", [])
        mappings = {
            item["step_id"]: item
            for item in self.db.query("SELECT * FROM factory_run_tasks WHERE run_id=?", (run_id,))
        }
        if set(mappings) != set(order):
            raise IntegrityError("Factory run task mapping does not match its durable plan")
        return [mappings[step_id] for step_id in order]

    @staticmethod
    def _decode(row: dict[str, Any]) -> dict[str, Any]:
        stored_input = json_data(row["input_json"], {})
        return {
            "run_id": row["run_id"],
            "blueprint_id": row["blueprint_id"],
            "requester": row["requester"],
            "idempotency_key": row["idempotency_key"],
            "goal": row["goal"],
            "inputs": stored_input.get("inputs", {}),
            "plan": json_data(row["plan_json"], {}),
            "state": row["state"],
            "result": json_data(row["result_json"], None),
            "error": json_data(row["error_json"], None),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "finished_at": row["finished_at"],
        }


def _render(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        full = _TEMPLATE.fullmatch(value)
        if full:
            return _resolve_template(full.group(1), context)

        def replace(match: re.Match[str]) -> str:
            resolved = _resolve_template(match.group(1), context)
            return resolved if isinstance(resolved, str) else canonical_json(resolved)

        return _TEMPLATE.sub(replace, value)
    if isinstance(value, list):
        return [_render(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _render(item, context) for key, item in value.items()}
    return value


def _resolve_template(reference: str, context: dict[str, Any]) -> Any:
    if reference == "goal":
        return context["goal"]
    parts = reference.split(".")
    if parts[0] == "inputs":
        current: Any = context["inputs"]
        remainder = parts[1:]
    elif 3 <= len(parts) <= 9 and parts[0] == "steps" and parts[1] in context["steps"]:
        current = context["steps"][parts[1]]
        remainder = parts[2:]
    else:
        raise ValidationError(f"Unknown factory template reference: {reference}")
    for part in remainder:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise ValidationError(f"Factory template value is unavailable: {reference}")
    return current
