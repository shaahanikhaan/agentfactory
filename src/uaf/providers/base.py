"""Narrow provider contracts; vendors never appear in orchestration policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from uaf.errors import ValidationError
from uaf.util import estimate_tokens


@dataclass(frozen=True, slots=True)
class ModelSpec:
    provider: str
    model: str
    capabilities: frozenset[str]
    context_limit: int = 32_000
    output_limit: int = 4_096
    free_tier_status: str = "unverified"
    free_tier_source: str | None = None
    verified_at: str | None = None
    enabled: bool = True
    priority: int = 100


@dataclass(slots=True)
class GenerateRequest:
    task_id: str
    role: str
    prompt: str
    system: str
    required_capabilities: frozenset[str] = frozenset({"text"})
    max_output_chars: int = 12_000
    max_output_tokens: int = 2_048
    provider: str | None = None
    model: str | None = None
    priority: str = "normal"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GenerateResponse:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Health:
    status: str
    detail: str
    checked_at: str
    latency_ms: int | None = None


class ProviderAdapter(Protocol):
    name: str

    def capabilities(self, spec: ModelSpec) -> frozenset[str]: ...
    def generate(
        self, spec: ModelSpec, request: GenerateRequest, api_key: str | None
    ) -> GenerateResponse: ...
    def health_check(self, spec: ModelSpec, api_key: str | None) -> Health: ...


def estimate_request_tokens(request: GenerateRequest) -> int:
    return estimate_tokens(request.system) + estimate_tokens(request.prompt)


def ensure_model_name(model: str) -> None:
    if not model or len(model) > 200 or any(ch.isspace() for ch in model):
        raise ValidationError(
            "Model identifier must be non-empty, bounded, and contain no whitespace"
        )
    if any(ord(ch) < 32 for ch in model):
        raise ValidationError("Model identifier contains control characters")


def parse_verified_date(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value + "T00:00:00+00:00").astimezone(UTC)
    except (ValueError, TypeError) as exc:
        raise ValidationError("Free-tier verified_at must be YYYY-MM-DD") from exc
