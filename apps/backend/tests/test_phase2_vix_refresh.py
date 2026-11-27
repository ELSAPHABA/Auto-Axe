import base64
import importlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from autoaxe.adapters.providers import normalize_yahoo
from autoaxe.adapters.vix_ws import decode_frame, normalize_quote
from autoaxe.application.vix_refresh import TTL_SECONDS, refresh_vix
from autoaxe.domain.catalog import catalog
from autoaxe.domain.market import Quality
from autoaxe.infrastructure.market_store import PermissionDenied

NOW = datetime(2026, 11, 27, 10, tzinfo=UTC)


def quote(age):
    return {
        "id": "^VIX",
        "price": 20.5,
        "time": int((NOW - timedelta(seconds=age)).timestamp() * 1000),
    }


def test_quote_ttl_and_unverified_not_live():
    assert catalog()["VIX"].ttl == catalog()["VIX_YAHOO_WS"].ttl == TTL_SECONDS == 10
    assert normalize_quote(quote(0), NOW).quality == Quality.UNKNOWN
    assert normalize_quote(quote(10), NOW).quality == Quality.UNKNOWN
    assert normalize_quote(quote(10.001), NOW).quality == Quality.STALE
    with pytest.raises(ValueError, match="future"):
        normalize_quote(quote(-1), NOW)
    assert (
        normalize_yahoo("VIX", symbol="^VIX", close=20, stamp=NOW, received=NOW).quality
        == Quality.UNKNOWN
    )


@pytest.mark.parametrize(
    "change", [{"id": "VXX"}, {"time": 0}, {"time": True}, {"price": "NaN"}, {"price": 0}]
)
def test_quote_rejects_invalid(change):
    with pytest.raises(ValueError):
        normalize_quote({**quote(0), **change}, NOW)


def test_actual_installed_protobuf_schema_fixture():
    protobuf = importlib.import_module("yfinance.pricing_pb2")
    msg = protobuf.PricingData(id="^VIX", time=quote(1)["time"], price=20.5)
    raw = json.dumps({"message": base64.b64encode(msg.SerializeToString()).decode()})
    result = decode_frame(raw, NOW)
    assert result is not None and result.value == "20.5"
    assert result.source_event_at == NOW - timedelta(seconds=1)
    assert result.quality == Quality.UNKNOWN
    assert decode_frame("{}", NOW) is None
    with pytest.raises(ValueError):
        decode_frame('{"message":"invalid!"}', NOW)


@pytest.mark.asyncio
async def test_default_disabled_before_db():
    with pytest.raises(PermissionDenied):
        await refresh_vix("not a dsn")
