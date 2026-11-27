"""Single-target TLS-pinned HTTP reader for an explicitly approved broker lease.

This is a building block, not a network-enabled worker: the Compose fixture
profile has network_mode:none and no valid mTLS broker identity. Caller must
first validate an authorized lease and source terms.
"""

import http.client
import ipaddress
import socket
import ssl
from collections.abc import Callable
from typing import Protocol
from urllib.parse import urlsplit

from autoaxe_scraper.policy import SourcePolicy

MAX_HTML_BYTES = 1_000_000
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


def fetch_exact_html(
    policy: SourcePolicy,
    *,
    permit: Callable[[], None],
    resolve: Callable[..., list[tuple]] = socket.getaddrinfo,
    dial: Callable[[str, str], http.client.HTTPSConnection] = PinnedHTTPS,
) -> str:
    """Bounded fixed HTTPS GET. No proxy, redirect, cookie, JS, or credential use."""
    if policy.api_only or policy.mode != "http":
        raise SourceBlocked("API-only or browser rendering source requires a separate contract")
    url = urlsplit(policy.url)
    if url.scheme != "https" or not url.hostname:
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
                "Accept": "text/html",
                "Accept-Encoding": "identity",
                "User-Agent": "Auto-Axe/0.1 permission-gated research parser",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise SourceBlocked(f"provider returned HTTP {response.status}; no redirect fallback")
        content_type = (response.getheader("content-type", "") or "").lower()
        if not content_type.startswith("text/html"):
            raise SourceBlocked("unexpected content type")
        encoding = (response.getheader("content-encoding", "identity") or "identity").lower()
        if encoding != "identity":
            raise SourceBlocked("compressed HTML not enabled")
        size = response.getheader("content-length")
        if size and (not size.isdecimal() or int(size) > MAX_HTML_BYTES):
            raise SourceBlocked("HTML content length exceeds limit")
        body = response.read(MAX_HTML_BYTES + 1)
        if len(body) > MAX_HTML_BYTES:
            raise SourceBlocked("HTML stream exceeds limit")
        # Do not allow source revoke to race successful data collection.
        permit()
        try:
            return body.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise SourceBlocked("unsupported HTML encoding") from exc
    finally:
        connection.close()
