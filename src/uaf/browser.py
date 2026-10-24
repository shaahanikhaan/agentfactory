"""Optional visible-browser automation confined to a dedicated, allowlisted profile."""

from __future__ import annotations

import contextlib
import importlib
import ipaddress
import os
import re
import socket
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

from uaf.config import Settings
from uaf.errors import PolicyDenied, SideEffectError, UnavailableError, ValidationError
from uaf.models import RiskTier, ToolContext, ToolResult
from uaf.tools import ToolMetadata
from uaf.util import canonical_json, redact_text, reject_secret_data, sha256_text

_SENSITIVE_PATH = re.compile(
    r"(?:^|[/_.-])(?:api[-_]?keys?|credentials?|secrets?|passwords?|tokens?)(?:$|[/_.-])",
    re.IGNORECASE,
)
_SNAPSHOT_SCRIPT = r"""
() => {
  const clean = (value, limit) => String(value || "").slice(0, limit);
  const nodes = Array.from(document.querySelectorAll(
    "a,button,input,textarea,select,[role=button],[contenteditable=true]"
  )).filter((element) => {
    if (!element.getClientRects().length) return false;
    const type = String(element.getAttribute("type") || "").toLowerCase();
    return type !== "password" && type !== "file" && type !== "hidden";
  }).slice(0, 80);
  const elements = nodes.map((element, index) => {
    return {
      ref: index + 1,
      tag: clean(element.tagName, 30).toLowerCase(),
      type: clean(element.getAttribute("type"), 40),
      text: clean(element.innerText || element.value, 300),
      aria_label: clean(element.getAttribute("aria-label"), 200),
      placeholder: clean(element.getAttribute("placeholder"), 200)
    };
  });
  return {text: clean(document.body ? document.body.innerText : "", 12000), elements};
}
"""
_TAG_SCRIPT = r"""
(snapshotId) => {
  const nodes = Array.from(document.querySelectorAll(
    "a,button,input,textarea,select,[role=button],[contenteditable=true]"
  )).filter((element) => {
    if (!element.getClientRects().length) return false;
    const type = String(element.getAttribute("type") || "").toLowerCase();
    return type !== "password" && type !== "file" && type !== "hidden";
  }).slice(0, 80);
  nodes.forEach((element, index) => {
    element.setAttribute("data-uaf-ref", String(index + 1));
    element.setAttribute("data-uaf-snapshot", snapshotId);
  });
}
"""


def validate_public_host(hostname: str) -> None:
    try:
        addresses = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise PolicyDenied("Browser domain DNS resolution failed") from exc
    if not addresses:
        raise PolicyDenied("Browser domain has no usable addresses")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise PolicyDenied("Browser navigation to a non-public address is forbidden")


class BrowserService:
    def __init__(
        self,
        settings: Settings,
        profile_dir: Path,
        *,
        context_factory: Callable[[], Any] | None = None,
        host_validator: Callable[[str], None] = validate_public_host,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.profile_dir = profile_dir
        self.context_factory = context_factory
        self.host_validator = host_validator
        self.sleep = sleep
        self._playwright: Any | None = None
        self._context: Any | None = None
        self._page: Any | None = None
        self._snapshot_labels: dict[str, dict[int, str]] = {}

    def _enabled(self) -> None:
        if not self.settings.browser_enabled:
            raise PolicyDenied("Browser automation is disabled; enable it explicitly")
        if not self.settings.network_allowed:
            raise PolicyDenied("Browser automation requires explicit network access")
        if not self.settings.browser_allowed_domains:
            raise PolicyDenied("Browser domain allowlist is empty")

    def _validate_url(self, url: str) -> str:
        self._enabled()
        if not isinstance(url, str) or not 8 <= len(url) <= 2_048:
            raise ValidationError("Browser URL must be bounded text")
        parsed = urlparse(url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValidationError("Browser URL contains an invalid port") from exc
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or port not in {None, 443}
        ):
            raise PolicyDenied("Only HTTPS browser URLs on port 443 without userinfo are allowed")
        hostname = parsed.hostname.lower().rstrip(".")
        if not self._domain_allowed(hostname):
            raise PolicyDenied(f"Browser domain is not allowlisted: {hostname}")
        if _SENSITIVE_PATH.search(parsed.path):
            raise PolicyDenied("Browser automation is blocked on credential/security pages")
        for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
            normalized = key.lower().replace("-", "_")
            if normalized in {"key", "api_key", "token", "secret", "password"} or normalized.endswith(
                ("_api_key", "_token", "_secret", "_password")
            ):
                raise PolicyDenied("Credential-like URL query parameters are forbidden")
        self.host_validator(hostname)
        return url

    def _domain_allowed(self, hostname: str) -> bool:
        for entry in self.settings.browser_allowed_domains:
            if entry.startswith("*."):
                if hostname.endswith("." + entry[2:]):
                    return True
            elif hostname == entry:
                return True
        return False

    def _route(self, route: Any) -> None:
        try:
            self._validate_url(route.request.url)
        except Exception:
            route.abort()
            return
        route.continue_()

    def _ensure_context(self) -> Any:
        self._enabled()
        if self._context is not None:
            return self._context
        try:
            if self.context_factory is not None:
                self._context = self.context_factory()
            else:
                module = importlib.import_module("playwright.sync_api")
                self._playwright = module.sync_playwright().start()
                self.profile_dir.mkdir(parents=True, exist_ok=True)
                if os.name != "nt":
                    os.chmod(self.profile_dir, 0o700)
                self._context = self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    headless=False,
                    accept_downloads=False,
                    permissions=[],
                    service_workers="block",
                    viewport={"width": 1280, "height": 720},
                    ignore_https_errors=False,
                )
            self._context.set_default_timeout(10_000)
            self._context.set_default_navigation_timeout(20_000)
            self._context.route("**/*", self._route)
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
            return self._context
        except Exception as exc:
            self.close()
            if isinstance(exc, (PolicyDenied, ValidationError)):
                raise
            raise UnavailableError(
                "Visible Chromium could not start; install the browser extra and Playwright Chromium"
            ) from exc

    def _active_page(self) -> Any:
        self._ensure_context()
        if self._page is None or self._page.is_closed():
            raise UnavailableError("Dedicated browser page is closed")
        return self._page

    def navigate(self, url: str) -> dict[str, Any]:
        target = self._validate_url(url)
        page = self._active_page()
        try:
            page.goto(target, wait_until="domcontentloaded")
            self._validate_url(page.url)
        except Exception as exc:
            if isinstance(exc, (PolicyDenied, ValidationError)):
                raise
            raise UnavailableError("Browser navigation failed; no external success is claimed") from exc
        return {"url": page.url, "title": redact_text(page.title())[:300]}

    def snapshot(self) -> dict[str, Any]:
        page = self._active_page()
        current_url = page.url
        self._validate_url(current_url)
        title = page.title()
        try:
            raw = page.evaluate(_SNAPSHOT_SCRIPT)
        except Exception as exc:
            raise UnavailableError("Bounded browser snapshot failed") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("elements"), list):
            raise ValidationError("Browser snapshot returned an invalid shape")
        snapshot_id = "snapshot_" + sha256_text(
            canonical_json({"url": current_url, "title": title, "snapshot": raw})
        )[:32]
        try:
            page.evaluate(_TAG_SCRIPT, snapshot_id)
        except Exception as exc:
            raise UnavailableError("Browser element tagging failed") from exc
        if page.url != current_url:
            raise UnavailableError("Browser page changed during snapshot; retry the read")
        elements = []
        for element in raw["elements"][:80]:
            if not isinstance(element, dict):
                continue
            candidate = {
                key: redact_text(str(element.get(key, "")))[:300]
                if key != "ref"
                else element.get("ref")
                for key in ("ref", "tag", "type", "text", "aria_label", "placeholder")
            }
            if len(canonical_json([*elements, candidate])) > 12_000:
                break
            elements.append(candidate)
        self._snapshot_labels[snapshot_id] = {
            int(element["ref"]): str(
                element["aria_label"] or element["text"] or element["placeholder"]
            )[:300]
            for element in elements
            if isinstance(element.get("ref"), int)
        }
        while len(self._snapshot_labels) > 4:
            self._snapshot_labels.pop(next(iter(self._snapshot_labels)))
        return {
            "url": current_url,
            "title": redact_text(title)[:300],
            "snapshot_id": snapshot_id,
            "text": redact_text(str(raw.get("text", "")))[:12_000],
            "elements": elements,
            "postcondition": True,
        }

    def open_for_user(self, url: str, *, wait_seconds: int) -> dict[str, Any]:
        if not 1 <= wait_seconds <= 300:
            raise ValidationError("Browser user session must be between 1 and 300 seconds")
        self.navigate(url)
        self.sleep(wait_seconds)
        return self.snapshot()

    def _locator(self, payload: dict[str, Any]) -> Any:
        page = self._active_page()
        expected_url = self._validate_url(str(payload.get("url", "")))
        snapshot_id = str(payload.get("snapshot_id", ""))
        ref = payload.get("ref")
        if (
            not snapshot_id.startswith("snapshot_")
            or len(snapshot_id) > 100
            or not isinstance(ref, int)
            or isinstance(ref, bool)
        ):
            raise ValidationError("A valid snapshot_id and integer element ref are required")
        if not 1 <= ref <= 80:
            raise ValidationError("Browser element ref is outside the snapshot budget")
        if page.url != expected_url:
            try:
                page.goto(expected_url, wait_until="domcontentloaded")
            except Exception as exc:
                raise UnavailableError("Approved browser URL could not be restored") from exc
            if page.url != expected_url:
                raise PolicyDenied("Approved browser URL redirected; a fresh approval is required")
        current = self.snapshot()
        if current["snapshot_id"] != snapshot_id:
            raise PolicyDenied("Browser content changed; take a fresh snapshot and approval")
        expected_label = payload.get("expected_label")
        labels = self._snapshot_labels.get(snapshot_id, {})
        if (
            not isinstance(expected_label, str)
            or not expected_label
            or len(expected_label) > 300
            or labels.get(ref) != expected_label
        ):
            raise PolicyDenied("Browser element label does not match the fresh snapshot")
        locator = page.locator(
            f'[data-uaf-ref="{ref}"][data-uaf-snapshot="{snapshot_id}"]'
        )
        if locator.count() != 1:
            raise PolicyDenied("Browser element is stale or ambiguous; take a fresh snapshot")
        return locator

    def click(self, payload: dict[str, Any]) -> dict[str, Any]:
        page = self._active_page()
        locator = self._locator(payload)
        try:
            locator.click(timeout=10_000)
            page.wait_for_timeout(250)
            self._validate_url(page.url)
        except Exception as exc:
            raise SideEffectError(
                "Browser click outcome is uncertain; inspect the visible page before retrying",
                uncertain=True,
            ) from exc
        return {"url": page.url, "postcondition": True}

    def type(self, payload: dict[str, Any]) -> dict[str, Any]:
        locator = self._locator(payload)
        text = payload.get("text")
        if not isinstance(text, str) or len(text) > 4_000 or "\x00" in text:
            raise ValidationError("Browser text must be at most 4,000 characters without NUL")
        reject_secret_data(text, label="browser text")
        try:
            input_type = (locator.get_attribute("type") or "").lower()
            autocomplete = (locator.get_attribute("autocomplete") or "").lower()
        except Exception as exc:
            raise UnavailableError("Browser field properties could not be inspected") from exc
        if input_type in {"password", "file", "hidden"} or autocomplete in {
            "current-password",
            "new-password",
            "one-time-code",
            "cc-number",
            "cc-csc",
        }:
            raise PolicyDenied("Browser automation cannot fill credential/payment fields")
        try:
            locator.fill(text, timeout=10_000)
            page = self._active_page()
            self._validate_url(page.url)
            current_url = page.url
        except Exception as exc:
            raise SideEffectError(
                "Browser text entry outcome is uncertain; inspect before retrying",
                uncertain=True,
            ) from exc
        return {
            "url": current_url,
            "characters": len(text),
            "postcondition": True,
        }

    def close(self) -> None:
        context, playwright = self._context, self._playwright
        self._context = None
        self._playwright = None
        self._page = None
        self._snapshot_labels.clear()
        if context is not None:
            with contextlib.suppress(Exception):
                context.close()
        if playwright is not None:
            with contextlib.suppress(Exception):
                playwright.stop()


def browser_tools(service: BrowserService) -> list[Any]:
    roles = frozenset({"worker"})
    common_url = {"type": "string", "minLength": 8, "maxLength": 2_048}
    snapshot_properties = {
        "url": common_url,
        "snapshot_id": {"type": "string", "minLength": 9, "maxLength": 100},
        "ref": {"type": "integer", "minimum": 1, "maximum": 80},
        "expected_label": {"type": "string", "minLength": 1, "maxLength": 300},
    }
    output_url = {
        "type": "object",
        "required": ["url", "postcondition"],
        "properties": {
            "url": {"type": "string"},
            "postcondition": {"type": "boolean"},
            "characters": {"type": "integer"},
        },
    }

    class Navigate:
        def metadata(self) -> ToolMetadata:
            return ToolMetadata(
                "browser.navigate",
                "1",
                "Navigate the dedicated visible browser to an allowlisted public HTTPS URL",
                {
                    "type": "object",
                    "required": ["url"],
                    "additionalProperties": False,
                    "properties": {"url": common_url},
                },
                {"type": "object"},
                RiskTier.R0,
                roles,
                timeout_seconds=30,
                external_destinations=tuple(service.settings.browser_allowed_domains),
            )

        def execute(self, context: ToolContext, payload: dict[str, Any]) -> ToolResult:
            result = service.navigate(payload["url"])
            return ToolResult(output={**result, "postcondition": True})

    class Snapshot:
        def metadata(self) -> ToolMetadata:
            return ToolMetadata(
                "browser.snapshot",
                "1",
                "Read bounded redacted text and numbered visible elements from the current page",
                {"type": "object", "additionalProperties": False, "properties": {}},
                {"type": "object"},
                RiskTier.R0,
                roles,
                timeout_seconds=20,
            )

        def execute(self, context: ToolContext, payload: dict[str, Any]) -> ToolResult:
            result = service.snapshot()
            return ToolResult(
                output=result,
                evidence={"snapshot_id": result["snapshot_id"], "url": result["url"]},
            )

    class Click:
        def metadata(self) -> ToolMetadata:
            return ToolMetadata(
                "browser.click",
                "1",
                "Click one element from an exact fresh snapshot; human approval required",
                {
                    "type": "object",
                    "required": ["url", "snapshot_id", "ref", "expected_label"],
                    "additionalProperties": False,
                    "properties": snapshot_properties,
                },
                output_url,
                RiskTier.R3,
                roles,
                timeout_seconds=30,
                idempotent=False,
                external_destinations=tuple(service.settings.browser_allowed_domains),
            )

        def execute(self, context: ToolContext, payload: dict[str, Any]) -> ToolResult:
            return ToolResult(output=service.click(payload))

    class Type:
        def metadata(self) -> ToolMetadata:
            return ToolMetadata(
                "browser.type",
                "1",
                "Fill one non-credential element from an exact fresh snapshot; approval required",
                {
                    "type": "object",
                    "required": ["url", "snapshot_id", "ref", "expected_label", "text"],
                    "additionalProperties": False,
                    "properties": {
                        **snapshot_properties,
                        "text": {"type": "string", "maxLength": 4_000},
                    },
                },
                output_url,
                RiskTier.R2,
                roles,
                timeout_seconds=30,
                idempotent=False,
                external_destinations=tuple(service.settings.browser_allowed_domains),
            )

        def execute(self, context: ToolContext, payload: dict[str, Any]) -> ToolResult:
            return ToolResult(output=service.type(payload))

    return [Navigate(), Snapshot(), Click(), Type()]
