"""Interactive-friendly, one-Gemini-key onboarding without paid auto-configuration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from uaf.config import ConfigManager, Settings
from uaf.credentials import CredentialStore, validate_secret
from uaf.errors import UnavailableError, ValidationError
from uaf.providers.base import ensure_model_name, parse_verified_date
from uaf.providers.http import JSONHttpClient

_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=100"
_DEFAULT_PRICING_SOURCE = "https://ai.google.dev/gemini-api/docs/pricing"


class GeminiOnboarding:
    def __init__(
        self,
        config: ConfigManager,
        credentials: CredentialStore,
        *,
        http: Any | None = None,
    ) -> None:
        self.config = config
        self.credentials = credentials
        self.http = http or JSONHttpClient()

    def discover(self, secret: str, *, network_confirmed: bool) -> list[dict[str, Any]]:
        if not network_confirmed:
            raise UnavailableError("Explicit network confirmation is required for model discovery")
        api_key = validate_secret(secret)
        settings = self.config.load()
        response = self.http.get_json(
            _MODELS_URL,
            headers={
                "x-goog-api-key": api_key,
                "User-Agent": "ultimate-agent-factory/0.1",
            },
            timeout=settings.budgets.provider_timeout_seconds,
        )
        raw_models = response.get("models")
        if not isinstance(raw_models, list) or len(raw_models) > 100:
            raise ValidationError("Gemini model discovery returned an invalid bounded list")
        models = []
        for raw in raw_models:
            if not isinstance(raw, dict):
                continue
            name = raw.get("name", "")
            methods = raw.get("supportedGenerationMethods", raw.get("supportedActions", []))
            if (
                not isinstance(name, str)
                or not name.startswith("models/")
                or not isinstance(methods, list)
                or "generateContent" not in methods
            ):
                continue
            model = name.removeprefix("models/")
            ensure_model_name(model)
            context_limit = raw.get("inputTokenLimit")
            output_limit = raw.get("outputTokenLimit")
            if (
                not isinstance(context_limit, int)
                or isinstance(context_limit, bool)
                or not isinstance(output_limit, int)
                or isinstance(output_limit, bool)
                or not 1 <= context_limit <= 10_000_000
                or not 1 <= output_limit <= 1_000_000
            ):
                continue
            models.append(
                {
                    "model": model,
                    "display_name": str(raw.get("displayName", model))[:200],
                    "context_limit": context_limit,
                    "output_limit": output_limit,
                    "free_tier_status": "unverified",
                }
            )
        if not models:
            raise UnavailableError(
                "No generateContent models with bounded metadata were returned for this key"
            )
        return sorted(models, key=lambda item: item["model"])

    def complete(
        self,
        secret: str,
        discovered: list[dict[str, Any]],
        *,
        model: str,
        free_confirmed: bool,
        source: str = _DEFAULT_PRICING_SOURCE,
        verified_at: str | None = None,
    ) -> dict[str, Any]:
        api_key = validate_secret(secret)
        if not free_confirmed:
            raise ValidationError(
                "Model availability is not free-tier evidence; explicitly verify current pricing"
            )
        parsed_source = urlparse(source)
        if (
            parsed_source.scheme != "https"
            or parsed_source.hostname
            not in {
                "ai.google.dev",
                "aistudio.google.com",
                "cloud.google.com",
            }
            or parsed_source.username
            or parsed_source.password
            or parsed_source.query
            or parsed_source.fragment
            or len(source) > 2_048
        ):
            raise ValidationError(
                "Gemini free-tier evidence must be a clean official HTTPS URL without query/userinfo"
            )
        verification_date = verified_at or datetime.now().astimezone().date().isoformat()
        verified = parse_verified_date(verification_date).date()
        settings = self.config.load()
        age = (datetime.now(UTC).date() - verified).days
        if age < -1 or age > settings.free_verification_max_age_days:
            raise ValidationError("Free-tier verification date is stale or future-dated")
        selected = next((item for item in discovered if item.get("model") == model), None)
        if selected is None:
            raise ValidationError("Selected model was not returned by this key's discovery request")
        ensure_model_name(model)
        context_limit = selected.get("context_limit")
        output_limit = selected.get("output_limit")
        if (
            not isinstance(context_limit, int)
            or isinstance(context_limit, bool)
            or not isinstance(output_limit, int)
            or isinstance(output_limit, bool)
            or not 1 <= context_limit <= 10_000_000
            or not 1 <= output_limit <= 1_000_000
        ):
            raise ValidationError("Selected model metadata is invalid or outside bounded limits")

        previous = settings.to_dict()
        previous_secret = self.credentials.get("gemini")
        self.credentials.set("gemini", api_key)
        try:
            settings.network_allowed = True
            gemini = settings.providers["gemini"]
            gemini["enabled"] = True
            gemini["models"] = {
                model: {
                    "capabilities": ["text", "json", "coding"],
                    "context_limit": selected["context_limit"],
                    "output_limit": selected["output_limit"],
                    "free_tier_status": "free",
                    "free_tier_source": source,
                    "verified_at": verification_date,
                    "enabled": True,
                    "priority": 100,
                }
            }
            self.config.save(settings)
        except Exception:
            self.config.save(Settings.from_dict(previous))
            if previous_secret is None:
                self.credentials.delete("gemini")
            else:
                self.credentials.set("gemini", previous_secret)
            raise
        return {
            "provider": "gemini",
            "model": model,
            "credential_storage": "os_vault",
            "credential_env_fallback": "GEMINI_API_KEY",
            "network_allowed": True,
            "free_tier_status": "user_verified_free",
            "free_tier_source": source,
            "verified_at": verification_date,
            "other_provider_keys_required": [],
            "live_generation_tested": False,
        }
