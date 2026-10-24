"""Strictly configured OpenAI-compatible adapters for Groq and OpenRouter."""

from __future__ import annotations

import time

from uaf.errors import ProviderError
from uaf.providers.base import (
    GenerateRequest,
    GenerateResponse,
    Health,
    ModelSpec,
    estimate_request_tokens,
)
from uaf.providers.http import JSONHttpClient
from uaf.util import utc_now


class OpenAICompatibleAdapter:
    def __init__(
        self,
        name: str,
        endpoint: str,
        credential_env: str,
        http: JSONHttpClient,
        *,
        timeout: int = 45,
    ) -> None:
        self.name = name
        self.endpoint = endpoint
        self.credential_env = credential_env
        self.http = http
        self.timeout = timeout

    def capabilities(self, spec: ModelSpec) -> frozenset[str]:
        return spec.capabilities

    def health_check(self, spec: ModelSpec, api_key: str | None) -> Health:
        return Health(
            status="configured" if api_key else "credential_missing",
            detail="Credential present; no network call made"
            if api_key
            else f"{self.credential_env} is not set",
            checked_at=utc_now(),
        )

    def generate(
        self, spec: ModelSpec, request: GenerateRequest, api_key: str | None
    ) -> GenerateResponse:
        if not api_key:
            raise ProviderError(f"{self.name} credential is missing", kind="invalid_credentials")
        started = time.monotonic()
        response = self.http.post_json(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "ultimate-agent-factory/0.1",
            },
            body={
                "model": spec.model,
                "messages": [
                    {"role": "system", "content": request.system},
                    {"role": "user", "content": request.prompt},
                ],
                "max_tokens": min(request.max_output_tokens, spec.output_limit),
                "temperature": 0.2,
                "stream": False,
            },
            timeout=self.timeout,
        )
        try:
            choice = response["choices"][0]
            text = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                f"{self.name} returned an invalid completion", kind="invalid_response"
            ) from exc
        if not isinstance(text, str) or not text:
            raise ProviderError(
                f"{self.name} returned empty/non-text content", kind="invalid_response"
            )
        usage = response.get("usage", {})
        return GenerateResponse(
            text=text,
            provider=self.name,
            model=spec.model,
            input_tokens=int(usage.get("prompt_tokens", estimate_request_tokens(request))),
            output_tokens=int(usage.get("completion_tokens", 0)),
            latency_ms=int((time.monotonic() - started) * 1000),
            usage={"total_tokens": usage.get("total_tokens")},
        )
