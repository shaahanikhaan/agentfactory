"""Reproducible, data-driven task evaluation and same-suite regression gates."""

from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Any

from uaf.db import Database
from uaf.errors import UAFError, ValidationError
from uaf.models import TaskContract, TaskState
from uaf.runner import TaskRunner
from uaf.tasks import TaskStore
from uaf.util import (
    canonical_json,
    json_data,
    new_id,
    redact_data,
    reject_secret_data,
    sha256_text,
    utc_now,
)
from uaf.workspace import Workspace

_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+){0,8}$")
_OPERATORS = {"eq", "contains", "not_contains", "exists", "lte", "gte"}


class EvaluationService:
    def __init__(
        self,
        db: Database,
        tasks: TaskStore,
        runner: TaskRunner,
        workspace: Workspace,
    ) -> None:
        self.db = db
        self.tasks = tasks
        self.runner = runner
        self.workspace = workspace

    def load_suite(self, path: str | Path | None = None) -> tuple[dict[str, Any], str]:
        source = (
            Path(path).expanduser().resolve()
            if path is not None
            else Path(__file__).parent / "data" / "evals" / "core.json"
        )
        try:
            if source.stat().st_size > 1_000_000:
                raise ValidationError("Evaluation suite exceeds the 1 MB limit")
            suite = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(f"Cannot load evaluation suite: {exc}") from exc
        self._validate_suite(suite)
        try:
            digest = sha256_text(canonical_json(suite))
        except ValueError as exc:
            raise ValidationError("Evaluation suite contains a non-finite number") from exc
        return suite, digest

    def run(
        self,
        suite_path: str | Path | None = None,
        *,
        baseline_run_id: str | None = None,
        candidate_id: str | None = None,
    ) -> dict[str, Any]:
        suite, digest = self.load_suite(suite_path)
        if baseline_run_id:
            baseline = self.require(baseline_run_id, include_cases=False)
            baseline_suite = baseline["suite"]
            if baseline_suite["digest"] != digest:
                raise ValidationError("Regression baseline must use the identical suite digest")
        run_id = new_id("eval")
        created_at = utc_now()
        initial_evidence = {
            "status": "running",
            "suite": self._suite_identity(suite, digest),
            "candidate_id": candidate_id,
        }
        self.db.execute(
            "INSERT INTO evaluation_runs(run_id,candidate_id,metric,score,evidence_json,created_at) "
            "VALUES(?,?,'overall',0,?,?)",
            (run_id, candidate_id, canonical_json(initial_evidence), created_at),
        )
        case_reports = []
        for case in suite["cases"]:
            case_reports.append(self._run_case(run_id, suite["suite_id"], case))
        report = self._report(run_id, suite, digest, candidate_id, case_reports, created_at)
        evidence = {"status": "completed", **report}
        self.db.execute(
            "UPDATE evaluation_runs SET score=?,evidence_json=? WHERE run_id=?",
            (report["metrics"]["accuracy"], canonical_json(redact_data(evidence)), run_id),
        )
        if baseline_run_id:
            report["baseline_comparison"] = self.compare(run_id, baseline_run_id)
            evidence = {"status": "completed", **report}
            self.db.execute(
                "UPDATE evaluation_runs SET evidence_json=? WHERE run_id=?",
                (canonical_json(redact_data(evidence)), run_id),
            )
        self.db.audit(
            "evaluation.run",
            object_type="evaluation_run",
            object_id=run_id,
            actor="evaluation",
            metadata={
                "suite_digest": digest,
                "cases": len(case_reports),
                "accuracy": report["metrics"]["accuracy"],
                "model_calls": report["metrics"]["total_model_calls"],
            },
        )
        return self.require(run_id)

    def require(self, run_id: str, *, include_cases: bool = True) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM evaluation_runs WHERE run_id=?", (run_id,))
        if not row:
            raise ValidationError(f"Evaluation run does not exist: {run_id}")
        evidence = json_data(row["evidence_json"], {})
        report = {
            "run_id": run_id,
            "candidate_id": row["candidate_id"],
            "metric": row["metric"],
            "score": row["score"],
            "created_at": row["created_at"],
            **evidence,
        }
        if include_cases and evidence.get("status") == "completed":
            report["cases"] = [
                self._decode_case(item)
                for item in self.db.query(
                    "SELECT * FROM evaluation_case_results WHERE run_id=? ORDER BY case_id",
                    (run_id,),
                )
            ]
        return report

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if not 1 <= limit <= 200:
            raise ValidationError("Evaluation list limit must be between 1 and 200")
        return [
            self.require(row["run_id"], include_cases=False)
            for row in self.db.query(
                "SELECT run_id FROM evaluation_runs ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        ]

    def compare(self, candidate_run_id: str, baseline_run_id: str) -> dict[str, Any]:
        candidate = self.require(candidate_run_id, include_cases=False)
        baseline = self.require(baseline_run_id, include_cases=False)
        if candidate["suite"]["digest"] != baseline["suite"]["digest"]:
            raise ValidationError("Only identical suite digests can be compared")
        candidate_cases = self._case_map(candidate_run_id)
        baseline_cases = self._case_map(baseline_run_id)
        regressions = sorted(
            case_id
            for case_id, old in baseline_cases.items()
            if old["passed"] and not candidate_cases.get(case_id, {}).get("passed", False)
        )
        improvements = sorted(
            case_id
            for case_id, old in baseline_cases.items()
            if not old["passed"] and candidate_cases.get(case_id, {}).get("passed", False)
        )
        missing = sorted(set(baseline_cases) - set(candidate_cases))
        new = sorted(set(candidate_cases) - set(baseline_cases))
        delta = candidate["score"] - baseline["score"]
        passed = (
            not regressions
            and not missing
            and all(item["passed"] for item in candidate_cases.values())
        )
        return {
            "baseline_run_id": baseline_run_id,
            "candidate_run_id": candidate_run_id,
            "accuracy_delta": round(delta, 6),
            "regressions": regressions,
            "improvements": improvements,
            "missing_cases": missing,
            "new_cases": new,
            "regression_gate_passed": passed,
        }

    def _run_case(self, run_id: str, suite_id: str, case: dict[str, Any]) -> dict[str, Any]:
        full_case_id = f"{suite_id}:{case['case_id']}"
        self.db.execute(
            "INSERT INTO evaluation_cases(case_id,name,input_json,expected_json,tags_json) "
            "VALUES(?,?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET name=excluded.name,"
            "input_json=excluded.input_json,expected_json=excluded.expected_json,tags_json=excluded.tags_json",
            (
                full_case_id,
                case["name"],
                canonical_json(case),
                canonical_json(case["expect"]),
                canonical_json(case.get("tags", [])),
            ),
        )
        started = time.monotonic()
        task_id = None
        actual: dict[str, Any] = {"state": "error"}
        metrics = {"model_calls": 0, "model_attempts": 0, "tool_calls": 0, "checkpoints": 0}
        try:
            for fixture in case.get("fixtures", []):
                self.workspace.write_text(fixture["path"], fixture["content"])
            task_spec = case["task"]
            contract = TaskContract(
                requester="evaluation",
                goal=task_spec["goal"],
                kind=task_spec["kind"],
                input_data=task_spec.get("input", {}),
                constraints=task_spec.get("constraints", []),
                allowed_tools=task_spec.get("allowed_tools", []),
                expected_output_schema=task_spec.get("expected_output_schema", {}),
                risk_tier=task_spec.get("risk_tier", "R0"),
                priority=task_spec.get("priority", "batch"),
                department=task_spec.get("department", "quality"),
                budget=task_spec.get("budget", {}),
            )
            task = self.tasks.add(contract)
            task_id = task["task_id"]
            for _ in range(case.get("repeat", 1)):
                task = self.runner.run(task_id)
            metrics = {
                "model_calls": self.tasks.completed_model_call_count(task_id),
                "model_attempts": self.tasks.model_call_count(task_id),
                "tool_calls": self.db.one(
                    "SELECT COUNT(*) c FROM tool_invocations WHERE task_id=?", (task_id,)
                )["c"],
                "checkpoints": len(self.tasks.steps(task_id)),
            }
            actual = {
                "state": task["state"],
                "result": task.get("result"),
                "error": task.get("error"),
                "approval_id": task.get("approval_id"),
                "metrics": metrics,
            }
        except (UAFError, OSError, TypeError, ValueError) as exc:
            actual = {
                "state": "error",
                "error": {
                    "code": exc.code if isinstance(exc, UAFError) else type(exc).__name__,
                    "message": str(exc)[:2000],
                },
                "metrics": metrics,
            }
        metrics["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
        actual["metrics"] = metrics
        failures = self._score(actual, case["expect"])
        passed = not failures
        evidence = {
            "task_id": task_id,
            "failures": failures,
            "tags": case.get("tags", []),
            "repeat": case.get("repeat", 1),
        }
        created_at = utc_now()
        self.db.execute(
            "INSERT INTO evaluation_case_results(run_id,case_id,split,passed,score,expected_json,"
            "actual_json,metrics_json,evidence_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                full_case_id,
                case["split"],
                int(passed),
                1.0 if passed else 0.0,
                canonical_json(case["expect"]),
                canonical_json(redact_data(actual)),
                canonical_json(metrics),
                canonical_json(redact_data(evidence)),
                created_at,
            ),
        )
        return {
            "case_id": full_case_id,
            "name": case["name"],
            "split": case["split"],
            "passed": passed,
            "score": 1.0 if passed else 0.0,
            "expected": case["expect"],
            "actual": actual,
            "metrics": metrics,
            "evidence": evidence,
        }

    def _score(self, actual: dict[str, Any], expected: dict[str, Any]) -> list[str]:
        failures = []
        if actual.get("state") != expected["state"]:
            failures.append(f"state expected {expected['state']!r}, got {actual.get('state')!r}")
        for check in expected.get("checks", []):
            path = check["path"]
            found, value = _path_value(actual, path)
            operator = check["operator"]
            if operator == "exists":
                ok = found and value is not None
            elif not found:
                ok = False
            elif operator == "eq":
                ok = value == check.get("value") and type(value) is type(check.get("value"))
            elif operator == "contains":
                expected_value = check.get("value")
                ok = isinstance(value, str | list | dict) and _contains(value, expected_value)
            elif operator == "not_contains":
                ok = not (
                    isinstance(value, str | list | dict) and _contains(value, check.get("value"))
                )
            elif operator == "lte":
                ok = _number(value) and _number(check.get("value")) and value <= check["value"]
            elif operator == "gte":
                ok = _number(value) and _number(check.get("value")) and value >= check["value"]
            else:  # validated before execution; fail closed if storage is tampered with
                ok = False
            if not ok:
                failures.append(
                    f"check {path} {operator} failed; actual={str(value)[:300]!r}, found={found}"
                )
        return failures

    def _report(
        self,
        run_id: str,
        suite: dict[str, Any],
        digest: str,
        candidate_id: str | None,
        cases: list[dict[str, Any]],
        created_at: str,
    ) -> dict[str, Any]:
        count = len(cases)
        passed = sum(item["passed"] for item in cases)
        durations = sorted(item["metrics"]["duration_ms"] for item in cases)

        def split_accuracy(split: str) -> float | None:
            selected = [item for item in cases if item["split"] == split]
            return (
                round(sum(item["passed"] for item in selected) / len(selected), 6)
                if selected
                else None
            )

        return {
            "run_id": run_id,
            "suite": self._suite_identity(suite, digest),
            "candidate_id": candidate_id,
            "created_at": created_at,
            "metrics": {
                "accuracy": round(passed / count, 6),
                "development_accuracy": split_accuracy("development"),
                "held_out_accuracy": split_accuracy("held_out"),
                "task_success_rate": round(
                    sum(item["actual"].get("state") == "succeeded" for item in cases) / count, 6
                ),
                "passed_cases": passed,
                "total_cases": count,
                "mean_duration_ms": round(sum(durations) / count, 3),
                "p95_duration_ms": durations[math.ceil(len(durations) * 0.95) - 1],
                "total_model_calls": sum(item["metrics"]["model_calls"] for item in cases),
                "total_model_attempts": sum(item["metrics"]["model_attempts"] for item in cases),
                "total_tool_calls": sum(item["metrics"]["tool_calls"] for item in cases),
                "total_checkpoints": sum(item["metrics"]["checkpoints"] for item in cases),
            },
        }

    @staticmethod
    def _suite_identity(suite: dict[str, Any], digest: str) -> dict[str, Any]:
        return {
            "suite_id": suite["suite_id"],
            "version": suite["version"],
            "description": suite["description"],
            "digest": digest,
        }

    @staticmethod
    def _decode_case(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "case_id": row["case_id"],
            "split": row["split"],
            "passed": bool(row["passed"]),
            "score": row["score"],
            "expected": json_data(row["expected_json"], {}),
            "actual": json_data(row["actual_json"], {}),
            "metrics": json_data(row["metrics_json"], {}),
            "evidence": json_data(row["evidence_json"], {}),
        }

    def _case_map(self, run_id: str) -> dict[str, dict[str, Any]]:
        return {
            row["case_id"]: {"passed": bool(row["passed"])}
            for row in self.db.query(
                "SELECT case_id,passed FROM evaluation_case_results WHERE run_id=?", (run_id,)
            )
        }

    @staticmethod
    def _validate_suite(suite: Any) -> None:
        reject_secret_data(suite, label="evaluation suite")
        if not isinstance(suite, dict):
            raise ValidationError("Evaluation suite must be a JSON object")
        required = {"suite_id", "version", "description", "cases"}
        if set(suite) != required:
            raise ValidationError(f"Evaluation suite fields must be exactly {sorted(required)}")
        for key in ("suite_id", "version", "description"):
            if not isinstance(suite[key], str) or not suite[key].strip():
                raise ValidationError(f"Evaluation {key} must be a non-empty string")
        if len(suite["suite_id"]) > 100 or len(suite["version"]) > 30:
            raise ValidationError("Evaluation suite identity is too long")
        cases = suite["cases"]
        if not isinstance(cases, list) or not 1 <= len(cases) <= 100:
            raise ValidationError("Evaluation suite requires 1..100 cases")
        identifiers = set()
        case_fields = {"case_id", "name", "split", "tags", "task", "expect", "fixtures", "repeat"}
        task_fields = {
            "goal",
            "kind",
            "input",
            "constraints",
            "allowed_tools",
            "expected_output_schema",
            "risk_tier",
            "priority",
            "department",
            "budget",
        }
        for case in cases:
            if not isinstance(case, dict) or not {
                "case_id",
                "name",
                "split",
                "task",
                "expect",
            } <= set(case):
                raise ValidationError(
                    "Every evaluation case requires id, name, split, task, and expect"
                )
            if not set(case) <= case_fields:
                raise ValidationError(
                    f"Unknown evaluation case fields: {sorted(set(case) - case_fields)}"
                )
            case_id = case["case_id"]
            if not isinstance(case_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", case_id):
                raise ValidationError("Invalid evaluation case identifier")
            if case_id in identifiers:
                raise ValidationError(f"Duplicate evaluation case: {case_id}")
            identifiers.add(case_id)
            if not isinstance(case["name"], str) or not 1 <= len(case["name"]) <= 300:
                raise ValidationError("Evaluation case name must be 1..300 characters")
            if not isinstance(case["split"], str) or case["split"] not in {
                "development",
                "held_out",
            }:
                raise ValidationError("Evaluation split must be development or held_out")
            if not isinstance(case.get("tags", []), list) or len(case.get("tags", [])) > 20:
                raise ValidationError("Evaluation tags must be a bounded list")
            repeat = case.get("repeat", 1)
            if not isinstance(repeat, int) or isinstance(repeat, bool) or not 1 <= repeat <= 3:
                raise ValidationError("Evaluation repeat must be an integer from 1 to 3")
            task = case["task"]
            if not isinstance(task, dict) or not {"goal", "kind"} <= set(task):
                raise ValidationError("Evaluation task requires goal and kind")
            if not set(task) <= task_fields:
                raise ValidationError(
                    f"Unknown evaluation task fields: {sorted(set(task) - task_fields)}"
                )
            if not isinstance(task["kind"], str) or task["kind"] not in {
                "agent",
                "react",
                "smoke",
                "tool",
            }:
                raise ValidationError("Unsupported evaluation task kind")
            for key, expected_type in (
                ("input", dict),
                ("constraints", list),
                ("allowed_tools", list),
                ("expected_output_schema", dict),
                ("budget", dict),
            ):
                if key in task and not isinstance(task[key], expected_type):
                    raise ValidationError(f"Evaluation task {key} has the wrong type")
            fixtures = case.get("fixtures", [])
            if not isinstance(fixtures, list) or len(fixtures) > 10:
                raise ValidationError("Evaluation fixtures must contain at most 10 files")
            for fixture in fixtures:
                if (
                    not isinstance(fixture, dict)
                    or set(fixture) != {"path", "content"}
                    or not isinstance(fixture["path"], str)
                    or not isinstance(fixture["content"], str)
                    or len(fixture["content"]) > 100_000
                ):
                    raise ValidationError("Invalid evaluation file fixture")
            expect = case["expect"]
            if not isinstance(expect, dict) or not set(expect) <= {"state", "checks"}:
                raise ValidationError("Evaluation expect only supports state and checks")
            states = {state.value for state in TaskState}
            if not isinstance(expect.get("state"), str) or expect.get("state") not in states:
                raise ValidationError("Evaluation expected state is invalid")
            checks = expect.get("checks", [])
            if not isinstance(checks, list) or len(checks) > 20:
                raise ValidationError("Evaluation checks must contain at most 20 entries")
            for check in checks:
                if not isinstance(check, dict) or not {"path", "operator"} <= set(check):
                    raise ValidationError("Evaluation check requires path and operator")
                if not set(check) <= {"path", "operator", "value"}:
                    raise ValidationError("Unknown evaluation check field")
                if not isinstance(check["path"], str) or not _PATH.fullmatch(check["path"]):
                    raise ValidationError("Invalid evaluation check path")
                if not isinstance(check["operator"], str) or check["operator"] not in _OPERATORS:
                    raise ValidationError("Unsupported deterministic evaluation operator")
                if check["operator"] != "exists" and "value" not in check:
                    raise ValidationError("Evaluation check requires an expected value")


def _path_value(value: Any, path: str) -> tuple[bool, Any]:
    current = value
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False, None
    return True, current


def _contains(actual: Any, expected: Any) -> bool:
    if isinstance(actual, dict):
        return expected in actual
    try:
        return expected in actual
    except (TypeError, ValueError):
        return False


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
