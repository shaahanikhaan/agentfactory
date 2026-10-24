"""Bounded standard-library JSON HTTP transport with redacted provider errors."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any

from uaf.errors import ProviderError
from uaf.util import canonical_json, now_dt


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


class JSONHttpClient:
    def __init__(self, *, max_response_bytes: int = 2_000_000) -> None:
        self.max_response_bytes = max_response_bytes
        self.opener = urllib.request.build_opener(_NoRedirect())

    def get_json(self, url: str, *, headers: dict[str, str], timeout: int) -> dict[str, Any]:
        request = urllib.request.Request(  # noqa: S310
            url,
            headers={**headers, "Accept": "application/json"},
            method="GET",
        )
        return self._open_json(request, timeout)

    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any],
        timeout: int,
    ) -> dict[str, Any]:
        # Adapters validate fixed HTTPS endpoints or loopback-only local inference URLs.
        request = urllib.request.Request(  # noqa: S310
            url,
            data=canonical_json(body).encode("utf-8"),
            headers={**headers, "Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        return self._open_json(request, timeout)

    def _open_json(self, request: urllib.request.Request, timeout: int) -> dict[str, Any]:
        try:
            with self.opener.open(request, timeout=timeout) as response:
                if response.status < 200 or response.status >= 300:
                    raise self._status_error(response.status, dict(response.headers))
                data = response.read(self.max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            # Do not copy the response body: providers can echo request data or credentials.
            raise self._status_error(exc.code, dict(exc.headers)) from None
        except TimeoutError as exc:
            raise ProviderError(
                "Provider request timed out", kind="timeout", retryable=True
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise ProviderError(
                    "Provider request timed out", kind="timeout", retryable=True
                ) from exc
            raise ProviderError(
                "Provider network connection failed", kind="network", retryable=True
            ) from exc
        if len(data) > self.max_response_bytes:
            raise ProviderError("Provider response exceeded byte budget", kind="response_too_large")
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("Provider returned invalid JSON", kind="invalid_response") from exc
        if not isinstance(value, dict):
            raise ProviderError("Provider response root was not an object", kind="invalid_response")
        return value

    @staticmethod
    def _status_error(status: int, headers: dict[str, Any]) -> ProviderError:
        normalized = {str(key).lower(): value for key, value in headers.items()}
        retry_after = parse_retry_after(normalized.get("retry-after"))
        mapping = {
            400: ("invalid_request", False),
            401: ("invalid_credentials", False),
            402: ("billing_or_credit_limit", False),
            403: ("permission_denied", False),
            404: ("invalid_model", False),
            408: ("timeout", True),
            409: ("conflict", False),
            413: ("request_too_large", False),
            422: ("invalid_request", False),
            429: ("rate_limit", True),
            500: ("provider_internal", True),
            502: ("provider_unavailable", True),
            503: ("provider_unavailable", True),
            504: ("timeout", True),
        }
        kind, retryable = mapping.get(status, ("http_error", 500 <= status < 600))
        return ProviderError(
            f"Provider HTTP {status}: {kind}",
            kind=kind,
            retryable=retryable,
            retry_after=retry_after,
            status=status,
        )


def parse_retry_after(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(float(value), 86_400.0))
    except (TypeError, ValueError):
        try:
            target = parsedate_to_datetime(str(value))
            if target.tzinfo is None:
                target = target.replace(tzinfo=UTC)
            return max(0.0, min((target - now_dt()).total_seconds(), 86_400.0))
        except (TypeError, ValueError, OverflowError):
            return None
