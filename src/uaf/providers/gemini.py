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
    parse_token_count,
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
        generation_config: dict[str, object] = {
            "maxOutputTokens": min(request.max_output_tokens, spec.output_limit),
            "temperature": 0.2,
        }
        thinking_level = request.metadata.get("thinking_level")
        if thinking_level is not None:
            supports_levels = spec.model.startswith(("gemini-3.", "gemini-4-", "gemini-4."))
            if (
                not isinstance(thinking_level, str)
                or thinking_level not in {"low", "medium", "high"}
                or not supports_levels
            ):
                raise ProviderError(
                    "Gemini thinking level is invalid or unsupported for this model",
                    kind="invalid_request",
                    retryable=False,
                )
            generation_config["thinkingConfig"] = {"thinkingLevel": thinking_level}
        response = self.http.post_json(
            url,
            headers={"x-goog-api-key": api_key, "User-Agent": "ultimate-agent-factory/0.1"},
            body={
                "systemInstruction": {"parts": [{"text": request.system}]},
                "contents": [{"role": "user", "parts": [{"text": request.prompt}]}],
                "generationConfig": generation_config,
            },
            timeout=self.timeout,
        )
        if not isinstance(response, dict):
            raise ProviderError("Gemini returned a non-object response", kind="invalid_response")
        candidates = response.get("candidates")
        if not candidates:
            feedback = response.get("promptFeedback")
            reason = feedback.get("blockReason") if isinstance(feedback, dict) else None
            raise ProviderError(
                "Gemini returned no candidate" + (" (content blocked)" if reason else ""),
                kind="content_filter" if reason else "invalid_response",
            )
        if not isinstance(candidates, list) or not isinstance(candidates[0], dict):
            raise ProviderError("Gemini returned an invalid candidate", kind="invalid_response")
        content = candidates[0].get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            raise ProviderError("Gemini returned invalid content parts", kind="invalid_response")
        text = "".join(
            part.get("text", "")
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
        if not text:
            raise ProviderError("Gemini returned an empty candidate", kind="invalid_response")
        usage = response.get("usageMetadata", {})
        if not isinstance(usage, dict):
            raise ProviderError("Gemini returned invalid usage metadata", kind="invalid_response")
        return GenerateResponse(
            text=text,
            provider=self.name,
            model=spec.model,
            input_tokens=parse_token_count(
                usage.get("promptTokenCount"),
                default=estimate_request_tokens(request),
                provider=self.name,
                field="input",
            ),
            output_tokens=parse_token_count(
                usage.get("candidatesTokenCount"),
                default=0,
                provider=self.name,
                field="output",
            ),
            latency_ms=int((time.monotonic() - started) * 1000),
            usage={"total_tokens": usage.get("totalTokenCount")},
        )
