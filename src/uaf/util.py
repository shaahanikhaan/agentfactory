"""Low-dependency helpers shared by all UAF layers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from uaf.errors import ValidationError

_SECRET_KEYS = {"api_key", "apikey", "authorization", "password", "secret", "token"}
_SECRET_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[a-z0-9._~+/=-]{8,}"),
    re.compile(r"\b(AIza[0-9A-Za-z_-]{20,})\b"),
    re.compile(r"\b((?:sk|gsk|or)-[A-Za-z0-9_-]{12,})\b"),
    re.compile(r"(?i)((?:api[_-]?key|password|secret|token)\s*[:=]\s*)[^\s,;]+"),
]


def now_dt() -> datetime:
    return datetime.now(UTC)


def utc_now() -> str:
    return now_dt().isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Invalid ISO timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValidationError("Timestamp must include a timezone")
    return parsed.astimezone(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def json_data(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def payload_digest(value: Any) -> str:
    return sha256_text(canonical_json(value))


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, data: bytes, *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if private and os.name != "nt":
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str, *, private: bool = False) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), private=private)


def bounded(value: str, limit: int, *, label: str = "text") -> str:
    if limit < 1:
        raise ValidationError(f"{label} limit must be positive")
    if len(value) > limit:
        raise ValidationError(f"{label} exceeds {limit} characters")
    return value


def estimate_tokens(text: str) -> int:
    """Conservative routing estimate, not a provider tokenizer."""
    return max(1, math.ceil(len(text) / 4)) if text else 0


def redact_text(value: str, secrets: list[str] | None = None) -> str:
    redacted = value
    for secret in secrets or []:
        if secret and len(secret) >= 4:
            redacted = redacted.replace(secret, "[REDACTED]")
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(
            lambda m: (m.group(1) if m.lastindex else "") + "[REDACTED]", redacted
        )
    return redacted


def reject_secret_data(value: Any, *, label: str = "data") -> None:
    """Fail before persisted declarative definitions become a credential store."""
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValidationError(f"Non-string object key is forbidden in {label}")
            normalized = key.lower().replace("-", "_")
            if normalized in _SECRET_KEYS or normalized.endswith("_api_key"):
                raise ValidationError(f"Secret-like key is forbidden in {label}: {key}")
            reject_secret_data(item, label=label)
    elif isinstance(value, list):
        for item in value:
            reject_secret_data(item, label=label)
    elif isinstance(value, str) and redact_text(value) != value:
        raise ValidationError(f"Secret-like content is forbidden in {label}")


def redact_data(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = key.lower().replace("-", "_")
            if normalized in _SECRET_KEYS or normalized.endswith("_api_key"):
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_data(item)
        return result
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def coerce_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValidationError(f"Expected a boolean, got {value!r}")
