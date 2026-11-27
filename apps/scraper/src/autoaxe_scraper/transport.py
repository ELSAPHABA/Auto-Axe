"""Single-target TLS-pinned HTTP reader for an explicitly approved broker lease.

This is a building block, not a network-enabled worker: the Compose fixture
profile has network_mode:none and no valid mTLS broker identity. Caller must
first validate an authorized lease and source terms.
"""

import http.client
import ipaddress
import json
import socket
import ssl
from collections.abc import Callable
from typing import Any, Protocol
from urllib.parse import urlsplit

from autoaxe_scraper.policy import SourcePolicy

MAX_HTML_BYTES = 1_000_000
MAX_JSON_BYTES = 262_144
TIMEOUT_SECONDS = 8


class SourceBlocked(RuntimeError):
    pass


class Response(Protocol):
    status: int

    def getheader(self, name: str, default: str | None = None) -> str | None: ...

    def read(self, amt: int = -1) -> bytes: ...


def public_addresses(
    host: str, *, resolve: Callable[..., list[tuple]] = socket.getaddrinfo
) -> tuple[str, ...]:
    """Reject DNS answers with *any* non-global IP, not just selected endpoints."""
    results = resolve(host, 443, type=socket.SOCK_STREAM)
    if not results:
        raise SourceBlocked("DNS did not return a public destination")
    addresses = {str(ipaddress.ip_address(row[4][0])) for row in results}
    if not addresses or not all(ipaddress.ip_address(ip).is_global for ip in addresses):
        raise SourceBlocked("DNS response contains private or reserved addresses")
    return tuple(sorted(addresses))


class PinnedHTTPS(http.client.HTTPSConnection):
    """Connect to validated numeric IP; validate certificate against original host."""

    def __init__(self, host: str, ip: str) -> None:
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        super().__init__(host, port=443, timeout=TIMEOUT_SECONDS, context=context)
        self._verified_ip = ip
        self._pinned_context = context

    def connect(self) -> None:
        plain = socket.create_connection((self._verified_ip, 443), self.timeout)
        try:
            self.sock = self._pinned_context.wrap_socket(plain, server_hostname=self.host)
        except BaseException:
            plain.close()
            raise


def _fetch_exact(
    policy: SourcePolicy,
    *,
    permit: Callable[[], None],
    resolve: Callable[..., list[tuple]],
    dial: Callable[[str, str], http.client.HTTPSConnection],
    media: str,
) -> bytes:
    """One pinned target without credentials, redirects or decompression."""
    if policy.mode != "http" or (media == "html" and policy.api_only):
        raise SourceBlocked("API-only or browser rendering source requires a separate contract")
    if media == "json" and not policy.api_only:
        raise SourceBlocked("JSON fetch only available to fixed API-only source")
    url = urlsplit(policy.url)
    if (
        url.scheme != "https"
        or not url.hostname
        or (media == "json" and not url.path.startswith("/api/"))
    ):
        raise SourceBlocked("fixed HTTPS policy required")
    permit()
    addresses = public_addresses(url.hostname, resolve=resolve)
    # One validated numeric destination; no DNS re-resolution during TLS connect.
    connection = dial(url.hostname, addresses[0])
    try:
        target = url.path or "/"
        if url.query:
            target += "?" + url.query
        connection.request(
            "GET",
            target,
            headers={
                "Accept": "application/json" if media == "json" else "text/html",
                "Accept-Encoding": "identity",
                "User-Agent": "Auto-Axe/0.1 permission-gated research parser",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise SourceBlocked(f"provider returned HTTP {response.status}; no redirect fallback")
        content_type = (response.getheader("content-type", "") or "").lower()
        expected = "application/json" if media == "json" else "text/html"
        if not content_type.startswith(expected):
            raise SourceBlocked("unexpected content type")
        encoding = (response.getheader("content-encoding", "identity") or "identity").lower()
        if encoding != "identity":
            raise SourceBlocked("compressed HTML not enabled")
        size = response.getheader("content-length")
        limit = MAX_JSON_BYTES if media == "json" else MAX_HTML_BYTES
        if size and (not size.isdecimal() or int(size) > limit):
            raise SourceBlocked("source content length exceeds limit")
        body = response.read(limit + 1)
        if len(body) > limit:
            raise SourceBlocked("source stream exceeds limit")
        # Do not allow source revoke to race successful data collection.
        permit()
        return body
    finally:
        connection.close()


def fetch_exact_html(
    policy: SourcePolicy,
    *,
    permit: Callable[[], None],
    resolve: Callable[..., list[tuple]] = socket.getaddrinfo,
    dial: Callable[[str, str], http.client.HTTPSConnection] = PinnedHTTPS,
) -> str:
    """HTML retrieval; API-only sources never fall back to homepage scraping."""
    body = _fetch_exact(policy, permit=permit, resolve=resolve, dial=dial, media="html")
    try:
        return body.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise SourceBlocked("unsupported HTML encoding") from exc


def fetch_exact_json(
    policy: SourcePolicy,
    *,
    permit: Callable[[], None],
    resolve: Callable[..., list[tuple]] = socket.getaddrinfo,
    dial: Callable[[str, str], http.client.HTTPSConnection] = PinnedHTTPS,
) -> dict[str, Any]:
    """Bounded public JSON API read. Never follow HTML fallbacks."""
    body = _fetch_exact(policy, permit=permit, resolve=resolve, dial=dial, media="json")
    try:
        value: Any = json.loads(
            body, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON"))
        )
        if not isinstance(value, dict):
            raise ValueError("JSON object required")
        return value
    except (ValueError, UnicodeError) as exc:
        raise SourceBlocked("invalid API JSON document") from exc
