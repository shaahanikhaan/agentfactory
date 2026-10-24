"""Gemini generateContent adapter using a header credential and fixed HTTPS origin."""

from __future__ import annotations

import time
from urllib.parse import quote

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


class GeminiAdapter:
    name = "gemini"
    origin = "https://generativelanguage.googleapis.com"

    def __init__(self, http: JSONHttpClient, *, timeout: int = 45) -> None:
        self.http = http
        self.timeout = timeout

    def capabilities(self, spec: ModelSpec) -> frozenset[str]:
        return spec.capabilities

    def health_check(self, spec: ModelSpec, api_key: str | None) -> Health:
        return Health(
            status="configured" if api_key else "credential_missing",
            detail="Credential present; no network call made"
            if api_key
            else "GEMINI_API_KEY is not set",
            checked_at=utc_now(),
        )

    def generate(
        self, spec: ModelSpec, request: GenerateRequest, api_key: str | None
    ) -> GenerateResponse:
        if not api_key:
            raise ProviderError("Gemini credential is missing", kind="invalid_credentials")
        url = f"{self.origin}/v1beta/models/{quote(spec.model, safe='')}:generateContent"
        started = time.monotonic()
        response = self.http.post_json(
            url,
            headers={"x-goog-api-key": api_key, "User-Agent": "ultimate-agent-factory/0.1"},
            body={
                "systemInstruction": {"parts": [{"text": request.system}]},
                "contents": [{"role": "user", "parts": [{"text": request.prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": min(request.max_output_tokens, spec.output_limit),
                    "temperature": 0.2,
                },
            },
            timeout=self.timeout,
        )
        candidates = response.get("candidates")
        if not candidates:
            reason = response.get("promptFeedback", {}).get("blockReason")
            raise ProviderError(
                "Gemini returned no candidate" + (" (content blocked)" if reason else ""),
                kind="content_filter" if reason else "invalid_response",
            )
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        if not text:
            raise ProviderError("Gemini returned an empty candidate", kind="invalid_response")
        usage = response.get("usageMetadata", {})
        return GenerateResponse(
            text=text,
            provider=self.name,
            model=spec.model,
            input_tokens=int(usage.get("promptTokenCount", estimate_request_tokens(request))),
            output_tokens=int(usage.get("candidatesTokenCount", 0)),
            latency_ms=int((time.monotonic() - started) * 1000),
            usage={"total_tokens": usage.get("totalTokenCount")},
        )
