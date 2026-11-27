"""Explicitly authorized, bounded BLS Public Data API v1 collection.

No scheduler or public route invokes this module. It is a transport adapter,
not permission to operate: caller must verify and record source rights before
each request and before the resulting database transaction.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from autoaxe.adapters.macro_sources import BLS_IDS, parse_bls_actual
from autoaxe.domain.calendars import EventRevision
from autoaxe.domain.types import utc_datetime

BLS_ENDPOINT = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
MAX_RESPONSE_BYTES = 262_144
MAX_SERIES = 3


class OfficialSourceError(RuntimeError):
    """Retriable and non-retriable provider failures both fail closed."""


def collect_bls_v1(
    client: httpx.Client,
    *,
    authorize: Callable[[], None],
    series_ids: tuple[str, ...],
    received_at: datetime | None = None,
) -> list[EventRevision]:
    """Perform one v1 POST with no redirects, proxy fallback or token.

    The caller supplies a dedicated HTTPS client with trust_env=False and
    follow_redirects=False; we enforce both invariants here as defense in depth.
    """
    if not series_ids or len(series_ids) > MAX_SERIES or len(set(series_ids)) != len(series_ids):
        raise ValueError("invalid BLS series selection")
    if any(series not in BLS_IDS for series in series_ids):
        raise ValueError("unknown BLS series")
    if client.follow_redirects or client.trust_env:
        raise ValueError("BLS transport must disable redirects and environment proxies")
    authorize()
    try:
        with client.stream(
            "POST",
            BLS_ENDPOINT,
            json={"seriesid": list(series_ids)},
            headers={"Accept": "application/json", "User-Agent": "Auto-Axe/0.1 public BLS client"},
            follow_redirects=False,
            timeout=httpx.Timeout(10.0),
        ) as response:
            if response.status_code in (401, 403, 429):
                raise OfficialSourceError(f"BLS access denied or throttled: {response.status_code}")
            if response.status_code != 200:
                raise OfficialSourceError(f"BLS unavailable: {response.status_code}")
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type != "application/json":
                raise OfficialSourceError("BLS response is not JSON")
            length = response.headers.get("content-length")
            if length:
                if not length.isdecimal():
                    raise OfficialSourceError("invalid BLS content length")
                if int(length) > MAX_RESPONSE_BYTES:
                    raise OfficialSourceError("BLS body exceeds limit")
            parts: list[bytes] = []
            size = 0
            for part in response.iter_bytes():
                size += len(part)
                if size > MAX_RESPONSE_BYTES:
                    raise OfficialSourceError("BLS streaming body exceeds limit")
                parts.append(part)
            raw = b"".join(parts)
    except httpx.HTTPError as exc:
        raise OfficialSourceError("BLS transport unavailable") from exc
    authorize()  # Permission changes during an in-flight request fence the result.
    try:
        import json

        payload: dict[str, Any] = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("invalid BLS JSON root")
        clock = utc_datetime(received_at or datetime.now(UTC))
        events = parse_bls_actual(payload, clock)
        returned = {event.event_key.split(":", 1)[0] for event in events}
        requested = {BLS_IDS[item][0] for item in series_ids}
        if not events or not returned <= requested:
            raise ValueError("BLS returned no matching observations")
        return events
    except (ValueError, TypeError, KeyError) as exc:
        raise OfficialSourceError("invalid BLS release payload") from exc
