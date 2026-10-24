"""Health/quota-aware model routing with a fail-closed no-spend policy."""

from __future__ import annotations

import contextlib
import os
import random
import time
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from uaf.config import Settings
from uaf.credentials import CredentialStore
from uaf.db import Database
from uaf.errors import ProviderError, UnavailableError, ValidationError
from uaf.providers.base import (
    GenerateRequest,
    GenerateResponse,
    ModelSpec,
    ProviderAdapter,
    ensure_model_name,
    parse_verified_date,
)
from uaf.providers.gemini import GeminiAdapter
from uaf.providers.http import JSONHttpClient
from uaf.providers.ollama import OllamaAdapter
from uaf.providers.openai_compat import OpenAICompatibleAdapter
from uaf.util import canonical_json, new_id, now_dt, parse_time, redact_data, utc_now

_OFFICIAL_SOURCE_HOSTS = {
    "gemini": {"ai.google.dev", "aistudio.google.com", "cloud.google.com"},
    "groq": {"console.groq.com", "groq.com"},
    "openrouter": {"openrouter.ai"},
    "ollama": set(),
}


class ProviderService:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        *,
        environ: dict[str, str] | None = None,
        adapters: dict[str, ProviderAdapter] | None = None,
        credential_store: CredentialStore | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        self.settings = settings
        self.db = db
        self.environ = environ if environ is not None else dict(os.environ)
        self.credential_store = credential_store
        self.sleep = sleep
        http = JSONHttpClient()
        timeout = settings.budgets.provider_timeout_seconds
        self.adapters: dict[str, ProviderAdapter] = adapters or {
            "gemini": GeminiAdapter(http, timeout=timeout),
            "groq": OpenAICompatibleAdapter(
                "groq",
                "https://api.groq.com/openai/v1/chat/completions",
                "GROQ_API_KEY",
                http,
                timeout=timeout,
            ),
            "openrouter": OpenAICompatibleAdapter(
                "openrouter",
                "https://openrouter.ai/api/v1/chat/completions",
                "OPENROUTER_API_KEY",
                http,
                timeout=timeout,
            ),
        }
        if adapters is None:
            # The rest of the application must still start with an invalid optional adapter.
            with contextlib.suppress(ValidationError):
                self.adapters["ollama"] = OllamaAdapter(
                    settings.providers["ollama"].get("endpoint", "http://127.0.0.1:11434"),
                    http,
                    timeout=timeout,
                )
        self.sync_registry()

    def _api_key(self, provider: str) -> str | None:
        variable = self.settings.providers[provider].get("credential_env")
        environment_value = self.environ.get(variable) if variable else None
        if environment_value:
            return environment_value
        if self.credential_store is not None and provider in {"gemini", "groq", "openrouter"}:
            return self.credential_store.get(provider)
        return None

    def sync_registry(self) -> None:
        now = utc_now()
        for provider, config in self.settings.providers.items():
            self.db.execute(
                "INSERT INTO provider_configs(provider,config_json,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(provider) DO UPDATE SET config_json=excluded.config_json,updated_at=excluded.updated_at",
                (provider, canonical_json(redact_data(config)), now),
            )
            for model, raw in config.get("models", {}).items():
                try:
                    spec = self._spec(provider, model, raw)
                except ValidationError:
                    continue
                self.db.execute(
                    "INSERT INTO model_capabilities(provider,model,capabilities_json,context_limit,"
                    "output_limit,free_tier_status,free_tier_source,verified_at,enabled,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(provider,model) DO UPDATE SET "
                    "capabilities_json=excluded.capabilities_json,context_limit=excluded.context_limit,"
                    "output_limit=excluded.output_limit,free_tier_status=excluded.free_tier_status,"
                    "free_tier_source=excluded.free_tier_source,verified_at=excluded.verified_at,"
                    "enabled=excluded.enabled,updated_at=excluded.updated_at",
                    (
                        provider,
                        model,
                        canonical_json(sorted(spec.capabilities)),
                        spec.context_limit,
                        spec.output_limit,
                        spec.free_tier_status,
                        spec.free_tier_source,
                        spec.verified_at,
                        int(spec.enabled),
                        now,
                    ),
                )

    @staticmethod
    def _spec(provider: str, model: str, raw: dict[str, Any]) -> ModelSpec:
        ensure_model_name(model)
        if not isinstance(raw, dict):
            raise ValidationError("Model configuration must be an object")
        capabilities = frozenset(str(item) for item in raw.get("capabilities", ["text"]))
        if not capabilities or len(capabilities) > 32:
            raise ValidationError("Model capabilities must be a bounded non-empty set")
        return ModelSpec(
            provider=provider,
            model=model,
            capabilities=capabilities,
            context_limit=int(raw.get("context_limit", 32_000)),
            output_limit=int(raw.get("output_limit", 4_096)),
            free_tier_status=str(raw.get("free_tier_status", "unverified")),
            free_tier_source=raw.get("free_tier_source"),
            verified_at=raw.get("verified_at"),
            enabled=bool(raw.get("enabled", True)),
            priority=int(raw.get("priority", 100)),
        )

    def _validate_eligibility(self, spec: ModelSpec, *, for_call: bool) -> None:
        config = self.settings.providers.get(spec.provider, {})
        if not config.get("enabled") or not spec.enabled:
            raise UnavailableError(f"{spec.provider}/{spec.model} is disabled")
        if spec.context_limit < 1 or spec.output_limit < 1 or spec.priority < 0:
            raise UnavailableError("Model limits/priority are invalid")
        if spec.provider not in self.adapters:
            raise UnavailableError(f"{spec.provider} adapter is unavailable or invalid")
        if spec.provider == "ollama":
            if spec.free_tier_status != "local":
                raise UnavailableError("Local models must be explicitly marked local")
        else:
            if not self._api_key(spec.provider):
                raise UnavailableError(f"Credential variable for {spec.provider} is not set")
            if spec.free_tier_status != "free":
                raise UnavailableError(
                    "Cloud model is not verified as free; paid fallback is forbidden"
                )
            if not spec.verified_at:
                raise UnavailableError("Cloud model has no free-tier verification date")
            age = (now_dt() - parse_verified_date(spec.verified_at)).days
            if age < -1 or age > self.settings.free_verification_max_age_days:
                raise UnavailableError(
                    "Cloud model free-tier verification is stale or future-dated"
                )
            source = urlparse(spec.free_tier_source or "")
            if (
                source.scheme != "https"
                or source.hostname not in _OFFICIAL_SOURCE_HOSTS[spec.provider]
            ):
                raise UnavailableError("Free-tier evidence must be an official provider HTTPS URL")
            if spec.provider == "openrouter" and not spec.model.endswith(":free"):
                raise UnavailableError(
                    "No-spend OpenRouter routing only permits explicit :free model IDs"
                )
            if for_call and not self.settings.network_allowed:
                raise UnavailableError(
                    "Cloud access is offline; enable network explicitly after reviewing data policy"
                )

    def list_models(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for provider, config in self.settings.providers.items():
            models = config.get("models", {})
            if not models:
                rows.append(
                    {
                        "provider": provider,
                        "model": None,
                        "enabled": bool(config.get("enabled")),
                        "eligible": False,
                        "reason": "no model configured",
                        "credential_env": config.get("credential_env"),
                    }
                )
                continue
            for model, raw in models.items():
                row: dict[str, Any] = {
                    "provider": provider,
                    "model": model,
                    "enabled": bool(config.get("enabled") and raw.get("enabled", True)),
                    "credential_env": config.get("credential_env"),
                    "free_tier_status": raw.get("free_tier_status", "unverified"),
                    "free_tier_source": raw.get("free_tier_source"),
                    "verified_at": raw.get("verified_at"),
                    "capabilities": raw.get("capabilities", ["text"]),
                    "priority": raw.get("priority", 100),
                }
                try:
                    spec = self._spec(provider, model, raw)
                    self._validate_eligibility(spec, for_call=False)
                    cooldown = self._cooldown(provider, model)
                    if cooldown:
                        raise UnavailableError(f"cooldown until {cooldown}")
                    row.update(
                        {"eligible": True, "reason": "configuration eligible; no live call made"}
                    )
                except Exception as exc:
                    row.update({"eligible": False, "reason": str(exc)})
                rows.append(row)
        return rows

    def _candidates(self, request: GenerateRequest) -> list[ModelSpec]:
        candidates = []
        reasons = []
        for provider, config in self.settings.providers.items():
            if request.provider and provider != request.provider:
                continue
            for model, raw in config.get("models", {}).items():
                if request.model and model != request.model:
                    continue
                try:
                    spec = self._spec(provider, model, raw)
                    self._validate_eligibility(spec, for_call=True)
                    if not request.required_capabilities.issubset(spec.capabilities):
                        raise UnavailableError("Model lacks required capabilities")
                    if self._cooldown(provider, model):
                        raise UnavailableError(f"Cooldown until {self._cooldown(provider, model)}")
                    if self._daily_calls(provider, model) >= self.settings.budgets.max_daily_calls:
                        raise UnavailableError("Configured daily request budget exhausted")
                    candidates.append(spec)
                except Exception as exc:
                    reasons.append(f"{provider}/{model}: {exc}")
        if not candidates:
            detail = "; ".join(reasons[:5]) or "no matching model configured"
            raise UnavailableError(f"No eligible free/local model: {detail}")
        return sorted(candidates, key=lambda spec: (spec.priority, spec.provider, spec.model))

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        if len(request.prompt) + len(request.system) > self.settings.budgets.max_prompt_chars:
            raise ValidationError("Provider prompt exceeds the global context budget")
        if request.max_output_chars > self.settings.budgets.max_output_chars:
            raise ValidationError("Requested output exceeds the global output budget")
        candidates = self._candidates(request)
        errors: list[str] = []
        attempts = 0
        max_attempts = self.settings.budgets.max_retries + 1
        for spec in candidates:
            while attempts < max_attempts:
                attempts += 1
                self._observe_request(spec)
                try:
                    response = self.adapters[spec.provider].generate(
                        spec, request, self._api_key(spec.provider)
                    )
                    if len(response.text) > request.max_output_chars:
                        raise ProviderError(
                            "Model output exceeded character budget", kind="output_limit"
                        )
                    self._record_success(spec, response.latency_ms)
                    return response
                except ProviderError as exc:
                    errors.append(f"{spec.provider}/{spec.model}: {exc.kind}")
                    self._record_failure(spec, exc)
                    if not exc.retryable:
                        break
                    if exc.kind == "rate_limit":
                        self._set_cooldown(spec, exc.retry_after or 300, exc.kind)
                        break
                    if attempts < max_attempts:
                        # Bounded exponential backoff with jitter for transient failures. Retry-After
                        # rate limits are persisted instead of being retried early.
                        delay = min(2.0, 0.25 * (2 ** (attempts - 1)))
                        # Jitter spreads retries; it is not used for a security decision.
                        self.sleep(delay + random.uniform(0, min(0.1, delay)))  # noqa: S311
                    else:
                        self._set_cooldown(spec, 60 * attempts, exc.kind)
            if attempts >= max_attempts:
                break
        raise UnavailableError(
            "All eligible model attempts failed: " + "; ".join(errors[-5:]),
            details={"attempts": attempts, "retryable": True},
        )

    def test(self, provider: str, *, live: bool = False) -> dict[str, Any]:
        if provider not in self.settings.providers:
            raise ValidationError(f"Unknown provider: {provider}")
        models = self.settings.providers[provider].get("models", {})
        if not models:
            raise UnavailableError(f"Provider {provider} has no configured model")
        model = next(iter(models))
        spec = self._spec(provider, model, models[model])
        self._validate_eligibility(spec, for_call=live)
        adapter = self.adapters[provider]
        if not live:
            health = adapter.health_check(spec, self._api_key(provider))
            return {
                "provider": provider,
                "model": model,
                "live": False,
                "status": health.status,
                "detail": health.detail,
            }
        response = self.generate(
            GenerateRequest(
                task_id="provider_diagnostic",
                role="diagnostic",
                system="You are a connectivity probe. Return a short plain-text response.",
                prompt="Reply with OK.",
                provider=provider,
                model=model,
                max_output_chars=100,
                max_output_tokens=8,
                priority="interactive",
            )
        )
        return {
            "provider": provider,
            "model": model,
            "live": True,
            "status": "completed",
            "latency_ms": response.latency_ms,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "response_preview": response.text[:100],
        }

    def _daily_calls(self, provider: str, model: str) -> int:
        day = (
            now_dt()
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        row = self.db.one(
            "SELECT COUNT(*) AS count FROM quota_observations WHERE provider=? AND model=? "
            "AND metric='request_attempt' AND observed_at>=?",
            (provider, model, day),
        )
        return int(row["count"] if row else 0)

    def _observe_request(self, spec: ModelSpec) -> None:
        self.db.execute(
            "INSERT INTO quota_observations(observation_id,provider,model,scope,metric,remaining,"
            "observed_at,metadata_json) VALUES(?,?,?,?,?,NULL,?,?)",
            (
                new_id("quota"),
                spec.provider,
                spec.model,
                "organization"
                if spec.provider == "groq"
                else "project"
                if spec.provider == "gemini"
                else "account",
                "request_attempt",
                utc_now(),
                canonical_json({"local_budget": True}),
            ),
        )

    def _record_success(self, spec: ModelSpec, latency_ms: int) -> None:
        self.db.execute(
            "INSERT INTO provider_health(provider,model,status,latency_ms,checked_at,consecutive_failures) "
            "VALUES(?,?,'healthy',?,?,0) ON CONFLICT(provider,model) DO UPDATE SET status='healthy',"
            "latency_ms=excluded.latency_ms,error_code=NULL,checked_at=excluded.checked_at,consecutive_failures=0",
            (spec.provider, spec.model, latency_ms, utc_now()),
        )

    def _record_failure(self, spec: ModelSpec, error: ProviderError) -> None:
        self.db.execute(
            "INSERT INTO provider_health(provider,model,status,error_code,checked_at,consecutive_failures) "
            "VALUES(?,?,'degraded',?,?,1) ON CONFLICT(provider,model) DO UPDATE SET status='degraded',"
            "error_code=excluded.error_code,checked_at=excluded.checked_at,"
            "consecutive_failures=provider_health.consecutive_failures+1",
            (spec.provider, spec.model, error.kind, utc_now()),
        )
        if error.kind in {"invalid_credentials", "invalid_model", "billing_or_credit_limit"}:
            self._set_cooldown(spec, 3600, error.kind)

    def _set_cooldown(self, spec: ModelSpec, seconds: float, reason: str) -> None:
        until = (
            (now_dt() + timedelta(seconds=max(1, min(seconds, 86_400))))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        scope = (
            "organization"
            if spec.provider == "groq"
            else "project"
            if spec.provider == "gemini"
            else "account"
        )
        self.db.execute(
            "INSERT INTO provider_cooldowns(provider,model,scope,until,reason,updated_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(provider,model,scope) DO UPDATE SET "
            "until=CASE WHEN excluded.until>provider_cooldowns.until THEN excluded.until "
            "ELSE provider_cooldowns.until END,reason=excluded.reason,updated_at=excluded.updated_at",
            (spec.provider, spec.model, scope, until, reason[:200], utc_now()),
        )

    def _cooldown(self, provider: str, model: str) -> str | None:
        row = self.db.one(
            "SELECT until FROM provider_cooldowns WHERE provider=? AND model=?", (provider, model)
        )
        if row and parse_time(row["until"]) > now_dt():
            return row["until"]
        return None

    def cooldowns(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM provider_cooldowns ORDER BY until DESC")

    def clear_cooldown(self, provider: str, model: str | None = None) -> None:
        if model:
            self.db.execute(
                "DELETE FROM provider_cooldowns WHERE provider=? AND model=?", (provider, model)
            )
        else:
            self.db.execute("DELETE FROM provider_cooldowns WHERE provider=?", (provider,))
