import json
from datetime import UTC, datetime

import httpx
import pytest

from autoaxe.adapters import binance_qqq_rest as qqq
from autoaxe.application.collection import FetchError, SourceUnavailable
from autoaxe.domain.market import Quality
from autoaxe.infrastructure.market_store import PermissionDenied

NOW = datetime(2026, 11, 27, 10, tzinfo=UTC)
MS = int(NOW.timestamp() * 1000) - 1000
DETAIL = {
    "symbol": "QQQUSDT",
    "pair": "QQQUSDT",
    "contractType": "TRADIFI_PERPETUAL",
    "status": "TRADING",
    "baseAsset": "QQQ",
    "quoteAsset": "USDT",
    "marginAsset": "USDT",
    "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.01"}],
}
TICKER = {"symbol": "QQQUSDT", "price": "700.01", "time": MS}


class Stream(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body = body

    async def __aiter__(self):
        yield self.body


def reply(data=None, *, body=None, status=200, headers=None):
    return httpx.Response(
        status,
        stream=Stream(body if body is not None else json.dumps(data).encode()),
        headers={"Content-Type": "application/json"} if headers is None else headers,
    )


async def fetch(handler, permit=lambda: None):
    return await qqq.fetch_snapshot(
        permit,
        network_opt_in=True,
        http_transport=httpx.MockTransport(handler),
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_fixed_pair_unsigned_no_other_symbols_persisted():
    events = []

    def handler(request):
        url = str(request.url.copy_with(query=None))
        events.append(url)
        assert request.method == "GET"
        assert "x-mbx-apikey" not in request.headers
        assert "authorization" not in request.headers
        if url == qqq.DETAIL_URL:
            assert not request.url.params
            return reply({"symbols": [{"symbol": "BTCUSDT"}, DETAIL]})
        assert url == qqq.TICKER_URL
        assert dict(request.url.params) == {"symbol": "QQQUSDT"}
        return reply(TICKER)

    item = await fetch(handler, lambda: events.append("permit"))
    assert events == ["permit", qqq.DETAIL_URL, "permit", "permit", qqq.TICKER_URL, "permit"]
    assert item.series_id == qqq.SERIES_ID and item.quality == Quality.UNKNOWN
    assert item.value == "700.01" and item.key == str(MS)
    assert item.metadata["instrument_type"] == "etf_linked_perpetual"
    assert item.metadata["session_verified"] is False and item.metadata["live_verified"] is False


@pytest.mark.parametrize(
    "bad",
    [
        {"baseAsset": "BTC"},
        {"marginAsset": "USDC"},
        {"quoteAsset": "USDC"},
        {"contractType": "CURRENT_QUARTER"},
        {"contractType": "PERPETUAL"},
        {"status": "SETTLING"},
        {"pair": "TQQQUSDT"},
        {"symbol": "TQQQUSDT"},
        {"filters": []},
    ],
)
@pytest.mark.asyncio
async def test_bad_detail_never_fetches_ticker(bad):
    calls = []

    def handler(request):
        calls.append(request)
        return reply({"symbols": [DETAIL | bad]})

    with pytest.raises((ValueError, SourceUnavailable)):
        await fetch(handler)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"symbol": "NAS100USDT"},
        {"price": "NaN"},
        {"price": 700.01},
        {"price": "-1"},
        {"price": True},
        {"time": MS // 1000},
        {"time": MS + 2000},
        {"time": True},
        {"time": 1700000000000},
    ],
)
@pytest.mark.asyncio
async def test_invalid_ticker_rejected(bad):
    def handler(request):
        if request.url.path.endswith("exchangeInfo"):
            return reply({"symbols": [DETAIL]})
        return reply(TICKER | bad)

    with pytest.raises(ValueError):
        await fetch(handler)


@pytest.mark.asyncio
async def test_opt_in_and_every_fence():
    calls = []

    def handler(request):
        calls.append(request)
        return reply({"symbols": [DETAIL]} if len(calls) == 1 else TICKER)

    with pytest.raises(SourceUnavailable):
        await qqq.fetch_snapshot(lambda: None, http_transport=httpx.MockTransport(handler))
    assert not calls
    for fail, expected in [(1, 0), (2, 1), (3, 1), (4, 2)]:
        count = 0
        calls.clear()

        def permit(fail=fail):
            nonlocal count
            count += 1
            if count == fail:
                raise PermissionDenied("revoked")

        with pytest.raises(PermissionDenied):
            await fetch(handler, permit)
        assert len(calls) == expected


@pytest.mark.parametrize("status", [302, 403, 418, 429, 451, 503])
@pytest.mark.asyncio
async def test_http_error_no_retry_redirect_and_after_fence(status):
    events = []

    def handler(request):
        events.append("request")
        return reply(
            {}, status=status, headers={"Retry-After": "900", "Location": "https://example.com"}
        )

    with pytest.raises(FetchError) as raised:
        await fetch(handler, lambda: events.append("permit"))
    assert raised.value.status == status and raised.value.retry_header == "900"
    assert events == ["permit", "request", "permit"]


@pytest.mark.asyncio
async def test_size_duplicate_and_http200_error():
    for body in (
        b"x" * (qqq.MAX_DETAIL_BYTES + 1),
        b'{"symbols":[],"symbols":[]}',
        b'{"code":-1121,"msg":"invalid symbol"}',
    ):
        with pytest.raises((ValueError, SourceUnavailable)):
            await fetch(lambda _, body=body: reply(body=body))
    with pytest.raises(SourceUnavailable):
        await fetch(lambda _: reply({"symbols": [DETAIL, DETAIL]}))


@pytest.mark.parametrize("headers", [{}, {"Content-Type": "text/html"}])
@pytest.mark.asyncio
async def test_wrong_media_type_rejected(headers):
    with pytest.raises(ValueError, match="media type"):
        await fetch(lambda _: reply({"symbols": [DETAIL]}, headers=headers))
