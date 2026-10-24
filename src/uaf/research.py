"""Bounded research fetch with source provenance and untrusted-content separation."""

from __future__ import annotations

import html.parser
import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from uaf.config import Settings
from uaf.db import Database
from uaf.errors import UnavailableError, ValidationError
from uaf.policy import wrap_untrusted
from uaf.util import canonical_json, json_data, new_id, sha256_bytes, utc_now


class _TextExtractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._ignored = 0
        self._title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "template", "svg"}:
            self._ignored += 1
        if tag == "title":
            self._title = True
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "template", "svg"} and self._ignored:
            self._ignored -= 1
        if tag == "title":
            self._title = False
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored:
            return
        if self._title:
            self.title_parts.append(data)
        self.parts.append(data)

    @property
    def title(self) -> str:
        return " ".join("".join(self.title_parts).split())[:500]

    @property
    def text(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


@dataclass(slots=True)
class FetchResult:
    source_id: str
    url: str
    title: str
    content: str
    content_hash: str
    accessed_at: str
    model_context: str
    metadata: dict[str, Any]


class ResearchFetcher:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        *,
        opener: Any = None,
        resolver: Callable[..., Any] = socket.getaddrinfo,
        max_bytes: int = 1_000_000,
        max_chars: int = 200_000,
    ) -> None:
        self.settings = settings
        self.db = db
        self.opener = opener or urllib.request.build_opener(_NoRedirect())
        self.resolver = resolver
        self.max_bytes = max_bytes
        self.max_chars = max_chars

    def validate_url(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValidationError("Research fetch requires an HTTPS URL")
        if parsed.username or parsed.password:
            raise ValidationError("Credentials in research URLs are forbidden")
        if parsed.port not in {None, 443}:
            raise ValidationError("Research fetch only permits the standard HTTPS port")
        try:
            direct_ip = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            direct_ip = None
        if direct_ip and self._forbidden_ip(direct_ip):
            raise ValidationError("Research fetch blocks private, local, and reserved destinations")
        try:
            addresses = self.resolver(parsed.hostname, 443, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise UnavailableError("Research hostname could not be resolved") from exc
        if not addresses:
            raise UnavailableError("Research hostname returned no addresses")
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if self._forbidden_ip(ip):
                raise ValidationError(
                    "Research fetch blocks private, local, and reserved destinations"
                )
        return url

    @staticmethod
    def _forbidden_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )

    def fetch(self, url: str) -> FetchResult:
        if not self.settings.network_allowed:
            raise UnavailableError("Research fetch is offline; enable network explicitly")
        current = self.validate_url(url)
        response = None
        for redirect in range(4):
            # validate_url has already restricted scheme, port, and DNS answers.
            request = urllib.request.Request(  # noqa: S310
                current,
                headers={
                    "User-Agent": "UltimateAgentFactory/0.1 (+local research; respects source terms)",
                    "Accept": "text/html,text/plain,application/json,text/markdown;q=0.9",
                },
            )
            try:
                response = self.opener.open(request, timeout=20)
            except urllib.error.HTTPError as exc:
                if exc.code in {301, 302, 303, 307, 308}:
                    location = exc.headers.get("Location")
                    if not location or redirect == 3:
                        raise UnavailableError(
                            "Research redirect limit or location was invalid"
                        ) from exc
                    current = self.validate_url(urllib.parse.urljoin(current, location))
                    continue
                raise UnavailableError(f"Research source returned HTTP {exc.code}") from None
            except (TimeoutError, urllib.error.URLError) as exc:
                raise UnavailableError("Research source was unreachable or timed out") from exc
            break
        if response is None:
            raise UnavailableError("Research fetch did not obtain a response")
        with response:
            status = getattr(response, "status", 200)
            if status < 200 or status >= 300:
                raise UnavailableError(f"Research source returned HTTP {status}")
            content_type = response.headers.get_content_type().lower()
            allowed = {
                "text/html",
                "text/plain",
                "application/json",
                "text/markdown",
                "application/xhtml+xml",
            }
            if content_type not in allowed:
                raise ValidationError(f"Unsupported research content type: {content_type}")
            data = response.read(self.max_bytes + 1)
        if len(data) > self.max_bytes:
            raise ValidationError(f"Research response exceeds {self.max_bytes} bytes")
        charset = response.headers.get_content_charset() or "utf-8"
        try:
            decoded = data.decode(charset, errors="replace")
        except LookupError as exc:
            raise ValidationError("Research response used an unknown character encoding") from exc
        title = urllib.parse.urlparse(current).hostname or "source"
        if content_type in {"text/html", "application/xhtml+xml"}:
            parser = _TextExtractor()
            try:
                parser.feed(decoded)
                parser.close()
            except Exception as exc:
                raise ValidationError("HTML extraction failed safely") from exc
            text = parser.text
            title = parser.title or title
        else:
            text = decoded
        text = text.replace("\x00", "")[: self.max_chars]
        if not text.strip():
            raise ValidationError("Research source contained no extractable text")
        accessed = utc_now()
        source_id = new_id("source")
        metadata = {
            "final_url": current,
            "content_type": content_type,
            "bytes": len(data),
            "truncated": len(decoded) > self.max_chars,
            "trust": "untrusted_external_data",
            "ssrf_note": "DNS and redirect validation reduce but do not eliminate hostile-DNS risk",
        }
        digest = sha256_bytes(data)
        self.db.execute(
            "INSERT INTO research_sources(source_id,url,title,accessed_at,content_hash,content_text,"
            "metadata_json) VALUES(?,?,?,?,?,?,?)",
            (source_id, current, title, accessed, digest, text, canonical_json(metadata)),
        )
        self.db.audit(
            "research.fetch",
            object_type="source",
            object_id=source_id,
            decision="stored_untrusted",
            metadata={"url": current, "content_type": content_type, "bytes": len(data)},
        )
        return FetchResult(
            source_id=source_id,
            url=current,
            title=title,
            content=text,
            content_hash=digest,
            accessed_at=accessed,
            model_context=wrap_untrusted(current, text),
            metadata=metadata,
        )

    def get(self, source_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM research_sources WHERE source_id=?", (source_id,))
        if not row:
            raise ValidationError(f"Unknown research source: {source_id}")
        row["metadata"] = json_data(row["metadata_json"], {})
        row["model_context"] = wrap_untrusted(row["url"], row["content_text"])
        return row

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if not 1 <= limit <= 200:
            raise ValidationError("Source list limit must be between 1 and 200")
        rows = self.db.query(
            "SELECT source_id,url,title,accessed_at,content_hash,metadata_json FROM research_sources "
            "ORDER BY accessed_at DESC LIMIT ?",
            (limit,),
        )
        for row in rows:
            row["metadata"] = json_data(row.pop("metadata_json"), {})
        return rows
