"""Deterministic company-startup acceptance over real upstream evidence.

These checks do not claim semantic proof or additional execution. They ensure that
startup readiness is backed by completed upstream states, a bounded inventory,
non-empty planning output, and an actual independent reviewer pass.
"""

from __future__ import annotations

from typing import Any

from uaf.util import sha256_text

MAX_STARTUP_BRIEF_CHARS = 2_000
MAX_STARTUP_INVENTORY_ENTRIES = 200


def _inventory_contract_valid(inventory: Any) -> bool:
    if not isinstance(inventory, dict):
        return False
    if not isinstance(inventory.get("path"), str) or not inventory["path"]:
        return False
    if not isinstance(inventory.get("truncated"), bool):
        return False
    entries = inventory.get("entries")
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if not isinstance(entry, dict):
            return False
        if not isinstance(entry.get("name"), str) or not entry["name"]:
            return False
        if entry.get("type") not in {"file", "directory"}:
            return False
        size = entry.get("bytes")
        if entry["type"] == "file":
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                return False
        elif size is not None:
            return False
    return True


def evaluate_startup_acceptance(
    *,
    inventory: Any,
    brief: Any,
    inventory_state: Any,
    brief_state: Any,
    review_verdict: Any,
) -> dict[str, Any]:
    """Return a durable, non-semantic acceptance result without executing source."""

    entries = inventory.get("entries") if isinstance(inventory, dict) else None
    inventory_valid = _inventory_contract_valid(inventory)
    checks = [
        {
            "id": "upstream_states_succeeded",
            "passed": inventory_state == "succeeded" and brief_state == "succeeded",
        },
        {"id": "inventory_contract_valid", "passed": inventory_valid},
        {
            "id": "inventory_entries_bounded",
            "passed": isinstance(entries, list) and len(entries) <= MAX_STARTUP_INVENTORY_ENTRIES,
        },
        {
            "id": "brief_nonempty_and_bounded",
            "passed": isinstance(brief, str)
            and bool(brief.strip())
            and len(brief) <= MAX_STARTUP_BRIEF_CHARS,
        },
        {"id": "independent_reviewer_passed", "passed": review_verdict == "pass"},
    ]
    accepted = all(check["passed"] for check in checks)
    return {
        "accepted": accepted,
        "postcondition": accepted,
        "checks": checks,
        "evidence": {
            "scope": "deterministic_upstream_contract_checks",
            "checks_passed": sum(check["passed"] for check in checks),
            "checks_total": len(checks),
            "inventory_entries": len(entries) if isinstance(entries, list) else None,
            "brief_sha256": sha256_text(brief) if isinstance(brief, str) else None,
            "additional_execution_claimed": False,
        },
    }
