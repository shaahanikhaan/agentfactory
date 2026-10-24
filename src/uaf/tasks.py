"""Durable task envelopes, legal transitions, dependencies, and checkpoints."""

from __future__ import annotations

from typing import Any

from uaf.config import Budgets
from uaf.db import Database
from uaf.errors import IdempotencyConflict, StateTransitionError, UnavailableError, ValidationError
from uaf.models import (
    ALLOWED_TRANSITIONS,
    Priority,
    RiskTier,
    TaskContract,
    TaskState,
)
from uaf.util import (
    bounded,
    canonical_json,
    json_data,
    new_id,
    parse_time,
    payload_digest,
    redact_data,
    utc_now,
)


class TaskStore:
    def __init__(self, db: Database, budgets: Budgets | None = None) -> None:
        self.db = db
        self.budgets = budgets or Budgets()

    def add(self, contract: TaskContract) -> dict[str, Any]:
        bounded(contract.goal.strip(), 20_000, label="goal")
        if not contract.goal.strip():
            raise ValidationError("Task goal cannot be empty")
        if contract.kind not in {"agent", "react", "smoke", "tool"}:
            raise ValidationError("Task kind must be agent, react, smoke, or tool")
        if contract.kind == "tool" and not contract.input_data.get("tool"):
            raise ValidationError("Tool tasks require input_data.tool")
        if contract.deadline:
            parse_time(contract.deadline)
        if len(contract.depends_on) > 32 or len(contract.allowed_tools) > 32:
            raise ValidationError("Too many dependencies or allowed tools")
        task_id = new_id("task")
        correlation_id = contract.correlation_id or new_id("corr")
        now = utc_now()
        budget = {
            "max_steps": self.budgets.max_steps,
            "max_model_calls": self.budgets.max_model_calls,
            "max_tool_calls": self.budgets.max_tool_calls,
            "max_output_chars": self.budgets.max_output_chars,
            "task_wall_seconds": self.budgets.task_wall_seconds,
            "max_attempts": min(3, self.budgets.max_retries + 1),
            **contract.budget,
        }
        for name, value in budget.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValidationError(f"Invalid task budget: {name}")
        if budget["max_steps"] > self.budgets.max_steps:
            raise ValidationError("Task cannot exceed the global step budget")
        if budget["max_model_calls"] > self.budgets.max_model_calls:
            raise ValidationError("Task cannot exceed the global model-call budget")
        if budget["max_tool_calls"] > self.budgets.max_tool_calls:
            raise ValidationError("Task cannot exceed the global tool-call budget")
        if budget["max_attempts"] > min(3, self.budgets.max_retries + 1):
            raise ValidationError("Task cannot exceed the global attempt budget")
        if budget["max_output_chars"] > self.budgets.max_output_chars:
            raise ValidationError("Task cannot exceed the global output budget")
        stored_input = dict(contract.input_data)
        stored_input.update(
            {
                "constraints": contract.constraints,
                "depends_on": contract.depends_on,
            }
        )
        identity_payload = {
            "goal": contract.goal.strip(),
            "kind": contract.kind,
            "input": stored_input,
        }
        with self.db.transaction():
            queued = self.db._conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE state IN "
                "('queued','planning','running','verifying','awaiting_approval','retry_wait')"
            ).fetchone()[0]
            if queued >= self.budgets.max_queue:
                raise UnavailableError("Task queue is full; run or cancel existing tasks first")
            if contract.idempotency_key:
                existing = self.db._conn.execute(
                    "SELECT * FROM tasks WHERE requester=? AND idempotency_key=?",
                    (contract.requester, contract.idempotency_key),
                ).fetchone()
                if existing:
                    old_payload = {
                        "goal": existing["goal"],
                        "kind": existing["kind"],
                        "input": json_data(existing["input_json"], {}),
                    }
                    if payload_digest(old_payload) != payload_digest(identity_payload):
                        raise IdempotencyConflict(
                            "The task idempotency key already belongs to a different payload"
                        )
                    return self._decode(dict(existing))
            if (
                contract.parent_task_id
                and not self.db._conn.execute(
                    "SELECT 1 FROM tasks WHERE task_id=?", (contract.parent_task_id,)
                ).fetchone()
            ):
                raise ValidationError("Parent task does not exist")
            for dependency in contract.depends_on:
                if not self.db._conn.execute(
                    "SELECT 1 FROM tasks WHERE task_id=?", (dependency,)
                ).fetchone():
                    raise ValidationError(f"Dependency does not exist: {dependency}")
            self.db._conn.execute(
                "INSERT INTO tasks(task_id,parent_task_id,correlation_id,requester,goal,kind,state,"
                "priority,risk_tier,department,deadline,budget_json,input_json,allowed_tools_json,"
                "expected_output_schema_json,idempotency_key,attempt,max_attempts,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?)",
                (
                    task_id,
                    contract.parent_task_id,
                    correlation_id,
                    contract.requester,
                    contract.goal.strip(),
                    contract.kind,
                    TaskState.QUEUED.value,
                    Priority(contract.priority).value,
                    RiskTier(contract.risk_tier).value,
                    contract.department,
                    contract.deadline,
                    canonical_json(budget),
                    canonical_json(redact_data(stored_input)),
                    canonical_json(contract.allowed_tools),
                    canonical_json(contract.expected_output_schema),
                    contract.idempotency_key,
                    budget["max_attempts"],
                    now,
                    now,
                ),
            )
            for dependency in contract.depends_on:
                self.db._conn.execute(
                    "INSERT INTO task_dependencies(task_id,depends_on_task_id) VALUES(?,?)",
                    (task_id, dependency),
                )
            self.db.audit(
                "task.add",
                object_type="task",
                object_id=task_id,
                actor=contract.requester,
                metadata={"kind": contract.kind, "risk": str(contract.risk_tier)},
            )
        return self.get(task_id) or {}

    def _decode(self, row: dict[str, Any]) -> dict[str, Any]:
        row["input"] = json_data(row.get("input_json"), {})
        row["budget"] = json_data(row.get("budget_json"), {})
        row["allowed_tools"] = json_data(row.get("allowed_tools_json"), [])
        row["expected_output_schema"] = json_data(row.get("expected_output_schema_json"), {})
        row["result"] = json_data(row.get("result_json"), None)
        row["error"] = json_data(row.get("error_json"), None)
        row["dependencies"] = (
            [
                item["depends_on_task_id"]
                for item in self.db.query(
                    "SELECT depends_on_task_id FROM task_dependencies WHERE task_id=? ORDER BY depends_on_task_id",
                    (row["task_id"],),
                )
            ]
            if row.get("task_id")
            else []
        )
        return row

    def get(self, task_id: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM tasks WHERE task_id=?", (task_id,))
        return self._decode(row) if row else None

    def require(self, task_id: str) -> dict[str, Any]:
        task = self.get(task_id)
        if not task:
            raise ValidationError(f"Unknown task: {task_id}")
        return task

    def list(self, state: str | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValidationError("List limit must be between 1 and 500")
        if state:
            TaskState(state)
            rows = self.db.query(
                "SELECT * FROM tasks WHERE state=? ORDER BY created_at DESC LIMIT ?", (state, limit)
            )
        else:
            rows = self.db.query("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._decode(row) for row in rows]

    def next_runnable(self) -> dict[str, Any] | None:
        rows = self.db.query(
            "SELECT * FROM tasks WHERE state IN ('queued','retry_wait') "
            "AND (retry_at IS NULL OR retry_at<=?) "
            "ORDER BY CASE priority WHEN 'interactive' THEN 0 WHEN 'normal' THEN 1 "
            "WHEN 'batch' THEN 2 ELSE 3 END, created_at LIMIT 20",
            (utc_now(),),
        )
        for row in rows:
            task = self._decode(row)
            if self.dependencies_satisfied(task["task_id"]):
                return task
        return None

    def dependencies_satisfied(self, task_id: str) -> bool:
        pending = self.db.one(
            "SELECT COUNT(*) AS count FROM task_dependencies d JOIN tasks t "
            "ON t.task_id=d.depends_on_task_id WHERE d.task_id=? AND t.state<>'succeeded'",
            (task_id,),
        )
        return not pending or pending["count"] == 0

    def transition(
        self,
        task_id: str,
        target: TaskState | str,
        *,
        result: Any = None,
        error: Any = None,
        approval_id: str | None = None,
        retry_at: str | None = None,
        actor: str = "runtime",
    ) -> dict[str, Any]:
        target = TaskState(target)
        with self.db.transaction():
            row = self.db._conn.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if not row:
                raise ValidationError(f"Unknown task: {task_id}")
            current = TaskState(row["state"])
            if target not in ALLOWED_TRANSITIONS[current]:
                raise StateTransitionError(f"Illegal task transition: {current} -> {target}")
            now = utc_now()
            finished = (
                now
                if target
                in {
                    TaskState.SUCCEEDED,
                    TaskState.FAILED,
                    TaskState.CANCELLED,
                    TaskState.UNCERTAIN_SIDE_EFFECT,
                }
                else row["finished_at"]
            )
            started = row["started_at"] or (now if target == TaskState.RUNNING else None)
            new_result = (
                canonical_json(redact_data(result)) if result is not None else row["result_json"]
            )
            new_error = (
                canonical_json(redact_data(error))
                if error is not None
                else (
                    None
                    if target in {TaskState.PLANNING, TaskState.RUNNING, TaskState.QUEUED}
                    else row["error_json"]
                )
            )
            new_approval = (
                approval_id
                if approval_id is not None
                else (
                    None
                    if target in {TaskState.QUEUED, TaskState.PLANNING, TaskState.RUNNING}
                    else row["approval_id"]
                )
            )
            attempts = row["attempt"] + 1 if target == TaskState.PLANNING else row["attempt"]
            self.db._conn.execute(
                "UPDATE tasks SET state=?,result_json=?,error_json=?,approval_id=?,retry_at=?,"
                "attempt=?,started_at=?,finished_at=?,updated_at=? WHERE task_id=? AND state=?",
                (
                    target.value,
                    new_result,
                    new_error,
                    new_approval,
                    retry_at,
                    attempts,
                    started,
                    finished,
                    now,
                    task_id,
                    current.value,
                ),
            )
            self.db.audit(
                "task.transition",
                actor=actor,
                role="runtime",
                object_type="task",
                object_id=task_id,
                decision=f"{current}->{target}",
                metadata={"attempt": attempts},
            )
        return self.require(task_id)

    def cancel(self, task_id: str, *, actor: str = "local-user") -> dict[str, Any]:
        task = self.require(task_id)
        current = TaskState(task["state"])
        if current in {TaskState.SUCCEEDED, TaskState.FAILED, TaskState.CANCELLED}:
            raise StateTransitionError(f"Cannot cancel a task in {current}")
        with self.db.transaction():
            self.db._conn.execute(
                "UPDATE tasks SET cancel_requested=1,updated_at=? WHERE task_id=?",
                (utc_now(), task_id),
            )
        if TaskState.CANCELLED not in ALLOWED_TRANSITIONS[current]:
            raise StateTransitionError(f"Cannot cancel a task in {current}")
        return self.transition(task_id, TaskState.CANCELLED, actor=actor)

    def resume(self, task_id: str, *, actor: str = "local-user") -> dict[str, Any]:
        task = self.require(task_id)
        state = TaskState(task["state"])
        if state == TaskState.UNCERTAIN_SIDE_EFFECT:
            effects = self.db.query(
                "SELECT state FROM idempotency_ledger WHERE scope=?", (f"task:{task_id}",)
            )
            if not effects or any(
                row["state"] in {"uncertain", "reserved"} for row in effects
            ):
                raise UnavailableError(
                    "Reconcile every uncertain side effect before resuming this task"
                )
        if state == TaskState.AWAITING_APPROVAL:
            approval = self.db.one(
                "SELECT state FROM approval_requests WHERE approval_id=?", (task["approval_id"],)
            )
            if not approval or approval["state"] == "pending":
                raise UnavailableError("Approval is still pending")
            if approval["state"] != "approved":
                return self.transition(
                    task_id,
                    TaskState.FAILED,
                    error={
                        "code": "approval_rejected",
                        "message": "Approval was rejected or expired",
                    },
                    actor=actor,
                )
        if TaskState.QUEUED not in ALLOWED_TRANSITIONS[state]:
            raise StateTransitionError(f"Cannot resume a task in {state}")
        if (
            state in {TaskState.FAILED, TaskState.CANCELLED}
            and task["attempt"] >= task["max_attempts"]
        ):
            raise UnavailableError(
                "Task attempt budget is exhausted; create a reviewed follow-up task"
            )
        with self.db.transaction():
            self.db._conn.execute(
                "UPDATE tasks SET cancel_requested=0,retry_at=NULL WHERE task_id=?", (task_id,)
            )
        return self.transition(task_id, TaskState.QUEUED, actor=actor)

    def checkpoint(
        self,
        task_id: str,
        *,
        step_id: str,
        sequence: int,
        role: str,
        input_data: Any,
        result: Any,
        replay_of: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= sequence <= self.budgets.max_steps:
            raise UnavailableError("Checkpoint sequence exceeds the step budget")
        safe_input = redact_data(input_data)
        safe_result = redact_data(result)
        checksum = payload_digest({"input": safe_input, "result": safe_result})
        now = utc_now()
        with self.db.transaction():
            existing = self.db._conn.execute(
                "SELECT * FROM task_steps WHERE task_id=? AND step_id=?", (task_id, step_id)
            ).fetchone()
            if existing and existing["state"] == "completed":
                if existing["checksum"] != checksum:
                    raise StateTransitionError(
                        "A stable checkpoint cannot be overwritten with new evidence"
                    )
                return dict(existing)
            self.db._conn.execute(
                "INSERT INTO task_steps(step_id,task_id,sequence,role,state,input_json,result_json,"
                "checksum,replay_of,started_at,finished_at) VALUES(?,?,?,?,? ,?,?,?,?,?,?) "
                "ON CONFLICT(step_id) DO UPDATE SET state='completed',result_json=excluded.result_json,"
                "checksum=excluded.checksum,finished_at=excluded.finished_at",
                (
                    step_id,
                    task_id,
                    sequence,
                    role,
                    "completed",
                    canonical_json(safe_input),
                    canonical_json(safe_result),
                    checksum,
                    replay_of,
                    now,
                    now,
                ),
            )
        return self.db.one("SELECT * FROM task_steps WHERE step_id=?", (step_id,)) or {}

    def completed_step(self, task_id: str, step_id: str) -> dict[str, Any] | None:
        return self.db.one(
            "SELECT * FROM task_steps WHERE task_id=? AND step_id=? AND state='completed'",
            (task_id, step_id),
        )

    def steps(self, task_id: str) -> list[dict[str, Any]]:
        self.require(task_id)
        rows = self.db.query(
            "SELECT * FROM task_steps WHERE task_id=? ORDER BY sequence", (task_id,)
        )
        for row in rows:
            row["input"] = json_data(row["input_json"], {})
            row["result"] = json_data(row["result_json"], None)
        return rows

    def timeline(self, task_id: str) -> dict[str, Any]:
        task = self.require(task_id)
        events = self.db.query(
            "SELECT * FROM audit_events WHERE object_type='task' AND object_id=? ORDER BY timestamp",
            (task_id,),
        )
        for event in events:
            event["metadata"] = json_data(event["metadata_json"], {})
        return {"task": task, "steps": self.steps(task_id), "events": events}

    def mark_retry(self, task_id: str, retry_at: str, error: Any) -> dict[str, Any]:
        parse_time(retry_at)
        task = self.require(task_id)
        if task["attempt"] >= task["max_attempts"]:
            return self.transition(task_id, TaskState.FAILED, error=error)
        return self.transition(task_id, TaskState.RETRY_WAIT, error=error, retry_at=retry_at)

    def record_agent_run(self, **values: Any) -> str:
        run_id = new_id("run")
        allowed = {
            "task_id",
            "step_id",
            "role",
            "provider",
            "model",
            "prompt_hash",
            "input_tokens_estimate",
            "output_tokens_estimate",
            "latency_ms",
            "status",
            "error_code",
            "result_ref",
        }
        data = {key: values.get(key) for key in allowed}
        self.db.execute(
            "INSERT INTO agent_runs(run_id,task_id,step_id,role,provider,model,prompt_hash,"
            "input_tokens_estimate,output_tokens_estimate,latency_ms,status,error_code,result_ref,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                data["task_id"],
                data["step_id"],
                data["role"],
                data["provider"],
                data["model"],
                data["prompt_hash"],
                data["input_tokens_estimate"],
                data["output_tokens_estimate"],
                data["latency_ms"],
                data["status"],
                data["error_code"],
                data["result_ref"],
                utc_now(),
            ),
        )
        return run_id

    def finish_agent_run(
        self,
        run_id: str,
        *,
        status: str,
        provider: str | None = None,
        model: str | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
        error_code: str | None = None,
        result_ref: str | None = None,
    ) -> None:
        self.db.execute(
            "UPDATE agent_runs SET status=?,provider=COALESCE(?,provider),model=COALESCE(?,model),"
            "output_tokens_estimate=?,latency_ms=?,error_code=?,result_ref=? WHERE run_id=?",
            (status, provider, model, output_tokens, latency_ms, error_code, result_ref, run_id),
        )

    def model_call_count(self, task_id: str) -> int:
        """Count all routing attempts; this is the non-bypassable model-attempt budget."""
        row = self.db.one("SELECT COUNT(*) AS count FROM agent_runs WHERE task_id=?", (task_id,))
        return int(row["count"] if row else 0)

    def completed_model_call_count(self, task_id: str) -> int:
        """Count provider responses, excluding routing failures before a completed call."""
        row = self.db.one(
            "SELECT COUNT(*) AS count FROM agent_runs WHERE task_id=? AND status='completed'",
            (task_id,),
        )
        return int(row["count"] if row else 0)

    def counts(self) -> dict[str, int]:
        return {
            row["state"]: row["count"]
            for row in self.db.query("SELECT state,COUNT(*) AS count FROM tasks GROUP BY state")
        }
