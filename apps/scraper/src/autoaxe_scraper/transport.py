"""Single-target TLS-pinned HTTP reader for an explicitly approved collection.

The generic worker verifies its broker lease; the dedicated PizzINT reader has
its own permission and cadence checks. The fixture profile remains offline.
"""

import http.client
import ipaddress
import json
import socket
import ssl
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import urlsplit

from autoaxe_scraper.policy import SourcePolicy, fixed_target

MAX_HTML_BYTES = 1_000_000
MAX_JSON_BYTES = 262_144
TIMEOUT_SECONDS = 8


class SourceBlocked(RuntimeError):
    pass


class ProviderHTTPError(SourceBlocked):
    def __init__(self, status: int, retry_header: str | None) -> None:
        super().__init__(f"provider returned HTTP {status}; no redirect fallback")
        self.status = status
        self.retry_header = retry_header


class Response(Protocol):
    status: int

    def getheader(self, name: str, default: str | None = None) -> str | None: ...

    def read(self, amt: int = -1) -> bytes: ...


def public_addresses(
    host: str, *, resolve: Callable[..., Sequence[tuple[Any, ...]]] = socket.getaddrinfo
) -> tuple[str, ...]:
    """Reject DNS answers with *any* non-global IP, not just selected endpoints."""
    results = resolve(host, 443, type=socket.SOCK_STREAM)
    if not results:
        raise SourceBlocked("DNS did not return a public destination")
    parsed = {ipaddress.ip_address(row[4][0]) for row in results}
    if not parsed or any(
        not ip.is_global
        or ip.is_multicast
        or ip.is_reserved
        or (isinstance(ip, ipaddress.IPv6Address) and (ip.ipv4_mapped or ip.scope_id))
        for ip in parsed
    ):
        raise SourceBlocked("DNS response contains private or reserved addresses")
    return tuple(sorted(str(ip) for ip in parsed))


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
    resolve: Callable[..., Sequence[tuple[Any, ...]]],
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
        or (
            media == "json"
            and (
                policy.source_id not in {"cnn", "pizzint"}
                or policy != fixed_target(policy.source_id)
            )
        )
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
            raise ProviderHTTPError(response.status, response.getheader("retry-after"))
        content_type = (response.getheader("content-type", "") or "").lower()
        expected = "application/json" if media == "json" else "text/html"
        if content_type.split(";", 1)[0].strip() != expected:
            raise SourceBlocked("unexpected content type")
        encoding = (response.getheader("content-encoding", "identity") or "identity").lower()
        if encoding != "identity":
            raise SourceBlocked("compressed HTML not enabled")
        size = response.getheader("content-length")
        limit = MAX_JSON_BYTES if media == "json" else MAX_HTML_BYTES
        transfer = (response.getheader("transfer-encoding", "") or "").lower().strip()
        if transfer not in ("", "chunked") or (transfer and size is not None):
            raise SourceBlocked("ambiguous or unsupported transfer encoding")
        if size is not None and (not size.isdecimal() or int(size) > limit):
            raise SourceBlocked("source content length exceeds limit")
        body = response.read(limit + 1)
        if len(body) > limit or (size is not None and len(body) != int(size)):
            raise SourceBlocked("source stream size mismatch or limit exceeded")
        # Do not allow source revoke to race successful data collection.
        permit()
        return body
    finally:
        connection.close()


def fetch_exact_html(
    policy: SourcePolicy,
    *,
    permit: Callable[[], None],
    resolve: Callable[..., Sequence[tuple[Any, ...]]] = socket.getaddrinfo,
    dial: Callable[[str, str], http.client.HTTPSConnection] = PinnedHTTPS,
) -> str:
    """HTML retrieval; API-only sources never fall back to homepage scraping."""
    body = _fetch_exact(policy, permit=permit, resolve=resolve, dial=dial, media="html")
    try:
        return body.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise SourceBlocked("unsupported HTML encoding") from exc


def fetch_pizzint_doughcon(
    *,
    permit: Callable[[], None],
    resolve: Callable[..., Sequence[tuple[Any, ...]]] = socket.getaddrinfo,
    dial: Callable[[str, str], http.client.HTTPSConnection] = PinnedHTTPS,
) -> dict[str, Any]:
    """Return only DOUGHCON and minimal provenance from the fixed public API.

    The provider sends a full dashboard response. Other fields are discarded
    in memory and never returned, logged or persisted by this adapter.
    """
    body = _fetch_exact(
        fixed_target("pizzint"), permit=permit, resolve=resolve, dial=dial, media="json"
    )
    try:
        value: Any = json.loads(
            body, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON"))
        )
        if not isinstance(value, dict):
            raise ValueError("JSON object required")
        level = value.get("defcon_level")
        stamp = value.get("timestamp")
        if value.get("success") is not True or type(level) is not int or not 1 <= level <= 5:
            raise ValueError("invalid DOUGHCON level")
        if not isinstance(stamp, str):
            raise ValueError("missing API timestamp")
        source_at = datetime.fromisoformat(stamp)
        if source_at.tzinfo is None or source_at > datetime.now(UTC):
            raise ValueError("invalid API timestamp")
        return {
            "series_id": "PENTAGON_PIZZA_PIZZINT",
            "value": str(level),
            "source_event_at": source_at.astimezone(UTC).isoformat(),
            "quality": "manual_review_required",
            "automated_trading_allowed": False,
        }
    except (ValueError, UnicodeError, OverflowError) as exc:
        raise SourceBlocked("invalid DOUGHCON API document") from exc


def parse_cnn_json(body: bytes) -> dict[str, Any]:
    """Normalize current reading, comparisons, component scores and graph points."""
    from autoaxe_scraper.cnn_graphs import details, number

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    try:
        root = json.loads(
            body,
            parse_float=Decimal,
            object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
        )
        quote = root["fear_and_greed"]
        score, rating, raw_stamp = quote["score"], quote["rating"], quote["timestamp"]
        if type(score) not in (int, Decimal) or not 0 <= score <= 100:
            raise ValueError("invalid CNN score")
        if not isinstance(rating, str) or rating.title() not in (
            "Extreme Fear",
            "Fear",
            "Neutral",
            "Greed",
            "Extreme Greed",
        ):
            raise ValueError("invalid CNN rating")
        if not isinstance(raw_stamp, str):
            raise ValueError("missing CNN timestamp")
        stamp = datetime.fromisoformat(raw_stamp)
        if stamp.utcoffset() is None or stamp > datetime.now(UTC):
            raise ValueError("invalid CNN timestamp")
        return {
            "series_id": "CNN_FEAR_GREED_CNN",
            "value": number(score, score=True),
            "category": rating.title(),
            "source_event_at": stamp.astimezone(UTC).isoformat(),
            "quality": "manual_review_required",
            "automated_trading_allowed": False,
            "details": details(root, datetime.now(UTC)),
        }
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError) as exc:
        raise SourceBlocked("invalid CNN JSON document") from exc


def fetch_cnn_fear_greed(
    *,
    permit: Callable[[], None],
    resolve: Callable[..., Sequence[tuple[Any, ...]]] = socket.getaddrinfo,
    dial: Callable[[str, str], http.client.HTTPSConnection] = PinnedHTTPS,
) -> dict[str, Any]:
    body = _fetch_exact(
        fixed_target("cnn"), permit=permit, resolve=resolve, dial=dial, media="json"
    )
    return parse_cnn_json(body)
