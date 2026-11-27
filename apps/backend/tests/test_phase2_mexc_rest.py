import json
from datetime import UTC, datetime

import httpx
import pytest

from autoaxe.adapters import mexc_rest
from autoaxe.application.collection import FetchError, SourceUnavailable
from autoaxe.domain.market import Quality
from autoaxe.infrastructure.market_store import PermissionDenied

NOW = datetime(2026, 11, 27, 10, tzinfo=UTC)
MS = int(NOW.timestamp() * 1000) - 1000
DETAIL = {
    "symbol": "NAS100_USDT",
    "state": 0,
    "type": 2,
    "futureType": 1,
    "baseCoin": "NAS100",
    "quoteCoin": "USDT",
    "settleCoin": "USDT",
    "id": 123,
    "contractSize": "0.01",
    "priceUnit": "0.1",
}
TICKER = {"symbol": "NAS100_USDT", "contractId": 123, "lastPrice": "28001.1234", "timestamp": MS}


class Stream(httpx.AsyncByteStream):
    def __init__(self, raw):
        self.raw = raw

    async def __aiter__(self):
        yield self.raw


def response(data=None, *, status=200, code=0, success=True, raw=None, headers=None):
    if raw is None:
        raw = json.dumps({"success": success, "code": code, "data": data}).encode()
    return httpx.Response(status, stream=Stream(raw), headers=headers)


async def fetch(handler, permit=lambda: None, **kwargs):
    return await mexc_rest.fetch_snapshot(
        permit,
        network_opt_in=True,
        http_transport=httpx.MockTransport(handler),
        clock=lambda: NOW,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_fixed_endpoints_and_fences():
    events = []

    def handler(request):
        assert request.method == "GET"
        assert dict(request.url.params) == {"symbol": "NAS100_USDT"}
        assert "authorization" not in request.headers and "apikey" not in request.headers
        assert request.headers["accept-encoding"] == "identity"
        path = str(request.url.copy_with(query=None))
        events.append(path)
        if path == mexc_rest.DETAIL_URL:
            return response(DETAIL)
        assert path == mexc_rest.TICKER_URL
        # Ensure decimal numbers are parsed without a binary-float roundtrip.
        raw = (
            json.dumps({"success": True, "code": 0, "data": TICKER})
            .replace('"28001.1234"', "28001.1234567890123456789")
            .encode()
        )
        return response(raw=raw)

    item = await fetch(handler, lambda: events.append("permit"))
    assert events == [
        "permit",
        mexc_rest.DETAIL_URL,
        "permit",
        "permit",
        mexc_rest.TICKER_URL,
        "permit",
    ]
    assert item.series_id == mexc_rest.SERIES_ID
    assert item.value == "28001.1234567890123456789"
    assert item.key == str(MS) and item.quality == Quality.UNKNOWN
    assert item.source_event_at.timestamp() * 1000 == MS
    assert item.received_at == item.available_at == NOW
    assert item.metadata["live_verified"] is False
    assert item.metadata["session_verified"] is False
    assert item.metadata["pair_type"] == 2


@pytest.mark.asyncio
async def test_disabled_and_permission_revocation():
    calls = []

    def handler(request):
        calls.append(request)
        return response(DETAIL if len(calls) == 1 else TICKER)

    with pytest.raises(SourceUnavailable, match="not enabled"):
        await mexc_rest.fetch_snapshot(lambda: None, http_transport=httpx.MockTransport(handler))
    assert not calls
    for denied_check, expected_requests in [(1, 0), (2, 1), (3, 1), (4, 2)]:
        calls.clear()
        count = 0

        def permit(denied_check=denied_check):
            nonlocal count
            count += 1
            if count == denied_check:
                raise PermissionDenied("revoked")

        with pytest.raises(PermissionDenied):
            await fetch(handler, permit)
        assert len(calls) == expected_requests


@pytest.mark.parametrize(
    "override",
    [
        {"state": 4},
        {"state": False},
        {"futureType": 2},
        {"type": 3},
        {"quoteCoin": "USD1"},
        {"settleCoin": "USD"},
        {"baseCoin": "QQQ"},
        {"symbol": "BTC_USDT"},
        {"id": 0},
        {"contractSize": "0"},
    ],
)
@pytest.mark.asyncio
async def test_bad_detail_stops_before_ticker(override):
    calls = []

    def handler(request):
        calls.append(request)
        return response(DETAIL | override)

    with pytest.raises((ValueError, SourceUnavailable)):
        await fetch(handler)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "override",
    [
        {"contractId": 999},
        {"symbol": "NAS100_USD1"},
        {"timestamp": MS // 1000},
        {"timestamp": MS + 2000},
        {"timestamp": True},
        {"lastPrice": "-1"},
        {"lastPrice": "NaN"},
        {"lastPrice": True},
        {"lastPrice": None},
    ],
)
@pytest.mark.asyncio
async def test_invalid_ticker(override):
    def handler(request):
        if request.url.path.endswith("/country"):
            return response(DETAIL)
        return response(TICKER | override)

    with pytest.raises(ValueError):
        await fetch(handler)


@pytest.mark.parametrize(
    "status,code,expected",
    [
        (302, 0, 302),
        (429, 0, 429),
        (403, 0, 403),
        (200, 510, 429),
        (200, 511, 403),
        (200, 801, 503),
    ],
)
@pytest.mark.asyncio
async def test_errors_no_redirect_retry_and_post_fence(status, code, expected):
    events = []

    def handler(request):
        events.append("request")
        return response(
            status=status,
            code=code,
            success=False,
            headers={"Location": "https://example.com", "Retry-After": "60"},
        )

    with pytest.raises(FetchError) as raised:
        await fetch(handler, lambda: events.append("permit"))
    assert raised.value.status == expected
    assert events == ["permit", "request", "permit"]
    if status != 200:
        assert raised.value.retry_header == "60"


@pytest.mark.parametrize(
    "raw",
    [
        b'{"success":true,"code":0,"code":0,"data":{}}',
        b'{"success":true,"code":0,"data":{"symbol":"NAS100_USDT","contractSize":NaN}}',
        b"x" * (mexc_rest.MAX_BYTES + 1),
    ],
)
@pytest.mark.asyncio
async def test_malformed_oversize(raw):
    with pytest.raises(ValueError):
        await fetch(lambda _: response(raw=raw))


@pytest.mark.asyncio
async def test_http_failure_post_fence_and_no_retry():
    events = []

    def handler(request):
        events.append("request")
        raise httpx.ConnectError("synthetic disconnect")

    with pytest.raises(httpx.ConnectError):
        await fetch(handler, lambda: events.append("permit"))
    assert events == ["permit", "request", "permit"]
