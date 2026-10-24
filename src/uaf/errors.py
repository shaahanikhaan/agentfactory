"""Stable, redacted error taxonomy used at application boundaries."""

from __future__ import annotations


class UAFError(Exception):
    """Base class for expected user-facing failures."""

    code = "uaf_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class ValidationError(UAFError):
    code = "validation_error"


class StateTransitionError(UAFError):
    code = "illegal_state_transition"


class PolicyDenied(UAFError):
    code = "policy_denied"


class ApprovalRequired(UAFError):
    code = "approval_required"

    def __init__(self, approval_id: str, message: str) -> None:
        super().__init__(message, details={"approval_id": approval_id})
        self.approval_id = approval_id


class ProviderError(UAFError):
    code = "provider_error"

    def __init__(
        self,
        message: str,
        *,
        kind: str = "unknown",
        retryable: bool = False,
        retry_after: float | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(
            message,
            details={
                "kind": kind,
                "retryable": retryable,
                "retry_after": retry_after,
                "status": status,
            },
        )
        self.kind = kind
        self.retryable = retryable
        self.retry_after = retry_after
        self.status = status


class UnavailableError(UAFError):
    code = "temporarily_unavailable"


class IdempotencyConflict(UAFError):
    code = "idempotency_conflict"


class SideEffectError(UAFError):
    code = "side_effect_error"

    def __init__(self, message: str, *, uncertain: bool = False) -> None:
        super().__init__(message, details={"uncertain": uncertain})
        self.uncertain = uncertain


class IntegrityError(UAFError):
    code = "integrity_error"


class OptionalDependencyError(UAFError):
    code = "optional_dependency_missing"
