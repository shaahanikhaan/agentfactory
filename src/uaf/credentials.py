"""OS credential-vault access with insecure backends denied by default."""

from __future__ import annotations

import importlib
from typing import Any

from uaf.errors import UnavailableError, ValidationError

_SERVICE = "ultimate-agent-factory"
_SUPPORTED_BACKENDS = (
    "keyring.backends.Windows",
    "keyring.backends.macOS",
    "keyring.backends.SecretService",
    "keyring.backends.libsecret",
    "keyring.backends.KWallet",
)


def validate_secret(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("Credential must be text")
    secret = value.strip()
    if not 16 <= len(secret) <= 512 or any(character.isspace() for character in secret):
        raise ValidationError("Credential must be 16–512 non-whitespace characters")
    return secret


class CredentialStore:
    """Store only provider credentials in the OS vault, never in UAF config or SQLite."""

    def __init__(self, *, keyring_module: Any | None = None) -> None:
        self._keyring = keyring_module

    def _backend(self) -> Any:
        try:
            keyring = self._keyring or importlib.import_module("keyring")
            backend = keyring.get_keyring()
        except (ImportError, AttributeError, RuntimeError) as exc:
            raise UnavailableError(
                "Secure OS credential vault is unavailable; install UAF's setup extra"
            ) from exc
        module = type(backend).__module__
        if not any(module == item or module.startswith(item + ".") for item in _SUPPORTED_BACKENDS):
            raise UnavailableError(
                f"Credential backend is not an approved OS vault: {type(backend).__name__}"
            )
        return keyring

    def status(self) -> dict[str, Any]:
        try:
            keyring = self._backend()
            backend = type(keyring.get_keyring()).__name__
            return {
                "available": True,
                "backend": backend,
                "gemini_present": bool(keyring.get_password(_SERVICE, "gemini")),
            }
        except Exception:
            # Status is deliberately non-sensitive and must not break offline diagnostics.
            return {"available": False, "backend": None, "gemini_present": False}

    def set(self, provider: str, secret: str) -> None:
        self._validate_provider(provider)
        value = validate_secret(secret)
        keyring = self._backend()
        try:
            keyring.set_password(_SERVICE, provider, value)
        except Exception as exc:
            raise UnavailableError(
                "OS credential vault rejected the write; no secret was written to UAF files"
            ) from exc

    def get(self, provider: str) -> str | None:
        self._validate_provider(provider)
        try:
            keyring = self._backend()
            value = keyring.get_password(_SERVICE, provider)
        except UnavailableError:
            return None
        except Exception:
            return None
        if value is None:
            return None
        try:
            return validate_secret(value)
        except ValidationError:
            return None

    def delete(self, provider: str) -> bool:
        self._validate_provider(provider)
        keyring = self._backend()
        try:
            if keyring.get_password(_SERVICE, provider) is None:
                return False
            keyring.delete_password(_SERVICE, provider)
            return True
        except Exception as exc:
            raise UnavailableError("OS credential vault delete failed") from exc

    @staticmethod
    def _validate_provider(provider: str) -> None:
        if provider not in {"gemini", "groq", "openrouter"}:
            raise ValidationError("Only configured cloud providers can use the credential vault")
