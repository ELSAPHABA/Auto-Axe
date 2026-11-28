"""Fixed DRAMeXchange HTTPS acquisition using Scrapling's HTTP FetcherSession.

The pinned Scrapling release does not expose curl_options in its public
constructor. Configure its per-session curl client before any request and
fail closed if that integration contract changes. No browser fallback.
"""

import socket
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import urlsplit

from curl_cffi import CurlOpt, CurlSslVersion
from curl_cffi.curl import CURL_WRITEFUNC_ERROR
from curl_cffi.requests import Session
from scrapling.fetchers import FetcherSession

from autoaxe_scraper.policy import fixed_target
from autoaxe_scraper.transport import (
    MAX_HTML_BYTES,
    TIMEOUT_SECONDS,
    ProviderHTTPError,
    SourceBlocked,
    public_addresses,
)


def _fetch_pinned_html(url: str, ip: str, *, verify: bool | str = True) -> str:
    """Internal transport. Production caller supplies only a fixed HTTPS URL
    and a validated numeric address; the CA argument supports local TLS tests.
    """
    target = urlsplit(url)
    host = target.hostname
    if target.scheme != "https" or not host or verify is False:
        raise SourceBlocked("verified HTTPS required")
    address = f"[{ip}]" if ":" in ip else ip
    resolve_entry = f"{host}:{target.port or 443}:{address}".encode("ascii")
    body = bytearray()
    oversized = False

    def consume(chunk: bytes) -> int:
        nonlocal oversized
        if len(body) + len(chunk) > MAX_HTML_BYTES:
            oversized = True
            return CURL_WRITEFUNC_ERROR
        body.extend(chunk)
        return len(chunk)

    with FetcherSession(
        impersonate=None,
        stealthy_headers=False,
        follow_redirects=False,
        retries=1,
        timeout=TIMEOUT_SECONDS,
        verify=True,
        headers={
            "Accept": "text/html",
            "User-Agent": "Auto-Axe/0.1 permission-gated research parser",
            "Connection": "close",
        },
    ) as fetcher:
        # One fresh curl session, with no shared DNS or proxy state. Pinning
        # must happen before get(); pre-resolving without RESOLVE is unsafe.
        client = getattr(fetcher, "_curl_session", None)
        if not isinstance(client, Session) or not isinstance(client.curl_options, dict):
            raise SourceBlocked("Scrapling pinned transport contract unavailable")
        client.trust_env = False
        client.curl_options.update(
            {
                CurlOpt.RESOLVE: [resolve_entry],
                CurlOpt.PROXY: b"",
                CurlOpt.NOPROXY: b"*",
                CurlOpt.SSLVERSION: CurlSslVersion.TLSv1_2,
                CurlOpt.HTTP_CONTENT_DECODING: 0,
                CurlOpt.SSL_VERIFYPEER: 1,
                CurlOpt.SSL_VERIFYHOST: 2,
            }
        )
        if isinstance(verify, str):
            client.curl_options[CurlOpt.CAINFO] = verify
        options: dict[str, Any] = {
            "content_callback": consume,
            "accept_encoding": "identity",
            "discard_cookies": True,
        }
        try:
            response = fetcher.get(url, **options)
        except Exception as exc:
            if oversized:
                raise SourceBlocked("source stream size limit exceeded") from exc
            raise OSError("DRAMeXchange HTTPS fetch failed") from exc

    if oversized:
        raise SourceBlocked("source stream size limit exceeded")
    if response.status != 200:
        raise ProviderHTTPError(response.status, response.headers.get("retry-after"))
    if response.url != url or response.history:
        raise SourceBlocked("source target changed")
    headers = {key.lower(): value for key, value in response.headers.items()}
    if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "text/html":
        raise SourceBlocked("unexpected content type")
    if headers.get("content-encoding", "identity").lower() != "identity":
        raise SourceBlocked("compressed HTML not enabled")
    size = headers.get("content-length")
    transfer = headers.get("transfer-encoding", "").lower().strip()
    if transfer not in ("", "chunked") or (transfer and size is not None):
        raise SourceBlocked("ambiguous or unsupported transfer encoding")
    if size is not None and (
        not size.isdecimal() or int(size) > MAX_HTML_BYTES or len(body) != int(size)
    ):
        raise SourceBlocked("source stream size mismatch or limit exceeded")
    try:
        return body.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise SourceBlocked("unsupported HTML encoding") from exc


def fetch_dramexchange_html(
    *,
    permit: Callable[[], None],
    resolve: Callable[..., Sequence[tuple[Any, ...]]] = socket.getaddrinfo,
) -> str:
    """One approved public request, no arbitrary source URL or fallback."""
    permit()
    target = fixed_target("dramexchange")
    host = urlsplit(target.url).hostname
    if host != "www.dramexchange.com" or target.mode != "http" or target.api_only:
        raise SourceBlocked("fixed DRAMeXchange policy required")
    addresses = public_addresses(host, resolve=resolve)
    permit()
    html = _fetch_pinned_html(target.url, addresses[0])
    permit()
    return html
