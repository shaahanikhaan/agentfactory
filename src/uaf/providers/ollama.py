"""Opt-in loopback-only Ollama adapter; no model footprint is assumed."""

from __future__ import annotations

import time
from urllib.parse import urlparse

from uaf.errors import ProviderError, ValidationError
from uaf.providers.base import (
    GenerateRequest,
    GenerateResponse,
    Health,
    ModelSpec,
    estimate_request_tokens,
)
from uaf.providers.http import JSONHttpClient
from uaf.util import utc_now


def validate_loopback_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise ValidationError("Local inference endpoint must be credential-free HTTP(S)")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValidationError(
            "This no-spend adapter only permits an explicit loopback Ollama endpoint"
        )
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValidationError("Ollama endpoint must be an origin without a path/query")
    return endpoint.rstrip("/")


class OllamaAdapter:
    name = "ollama"

    def __init__(self, endpoint: str, http: JSONHttpClient, *, timeout: int = 45) -> None:
        self.endpoint = validate_loopback_endpoint(endpoint)
        self.http = http
        self.timeout = timeout

    def capabilities(self, spec: ModelSpec) -> frozenset[str]:
        return spec.capabilities

    def health_check(self, spec: ModelSpec, api_key: str | None) -> Health:
        return Health(
            status="configured",
            detail="Loopback model configured; runtime/model RAM footprint requires a live local check",
            checked_at=utc_now(),
        )

    def generate(
        self, spec: ModelSpec, request: GenerateRequest, api_key: str | None
    ) -> GenerateResponse:
        started = time.monotonic()
        response = self.http.post_json(
            self.endpoint + "/api/chat",
            headers={"User-Agent": "ultimate-agent-factory/0.1"},
            body={
                "model": spec.model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": request.system},
                    {"role": "user", "content": request.prompt},
                ],
                "options": {"num_predict": min(request.max_output_tokens, spec.output_limit)},
            },
            timeout=self.timeout,
        )
        text = response.get("message", {}).get("content")
        if not isinstance(text, str) or not text:
            raise ProviderError("Ollama returned empty/non-text content", kind="invalid_response")
        return GenerateResponse(
            text=text,
            provider=self.name,
            model=spec.model,
            input_tokens=int(response.get("prompt_eval_count", estimate_request_tokens(request))),
            output_tokens=int(response.get("eval_count", 0)),
            latency_ms=int((time.monotonic() - started) * 1000),
            usage={"load_duration": response.get("load_duration")},
        )
