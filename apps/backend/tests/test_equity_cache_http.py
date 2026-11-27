from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

import httpx
import pytest

from autoaxe.adapters.equity_http import CHART, ApprovedHTTP
from autoaxe.adapters.equity_yahoo import fetch_daily, fetch_fundamentals
from autoaxe.application import equity_worker
from autoaxe.application.collection import FetchError
from autoaxe.domain.equity_cache import (
    confirmed_cache,
    expected_sessions,
    feature_snapshot,
    missing_ranges,
)
from autoaxe.domain.equity_calendar import load_calendar
from autoaxe.domain.equity_samples import history_candidates
from autoaxe.domain.volume import NEW_YORK

NOW = datetime(2026, 11, 27, 20, tzinfo=UTC)
CAL = load_calendar()


def contract():
    return ApprovedHTTP(
        "synthetic approved contract",
        datetime.now(UTC) + timedelta(days=1),
        "fixture-v1",
        {"NVDA": {"2026-11-25": "fixture final evidence"}},
    )


def response(day=date(2026, 11, 25)):
    stamp = int(datetime.combine(day, datetime.min.time(), NEW_YORK).timestamp())
    return {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {
                        "symbol": "NVDA",
                        "currency": "USD",
                        "exchangeTimezoneName": "America/New_York",
                        "dataGranularity": "1d",
                    },
                    "timestamp": [stamp],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100],
                                "high": [110],
                                "low": [90],
                                "close": [100],
                                "volume": [500],
                            }
                        ],
                        "adjclose": [{"adjclose": [50]}],
                    },
                }
            ],
        }
    }


def test_http_one_bounded_request_and_no_inferred_finality():
    calls = []

    def respond(req):
        calls.append(req)
        assert str(req.url).startswith(CHART + "/NVDA?")
        assert req.url.params["interval"] == "1d"
        return httpx.Response(200, json=response())

    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as client:
        permits = []
        rows = fetch_daily(
            "NVDA",
            lambda: permits.append(1),
            start=date(2026, 11, 25),
            end=date(2026, 11, 25),
            contract=contract(),
            client=client,
        )
        assert len(calls) == 1 and len(permits) == 3
        assert rows[0]["close"] == "50" and rows[0]["high"] == "55"
        assert rows[0]["provider_final"] is True
        c = contract()
        c.final_sessions.clear()
        rows = fetch_daily(
            "NVDA",
            lambda: None,
            start=date(2026, 11, 25),
            end=date(2026, 11, 25),
            contract=c,
            client=client,
        )
        assert rows[0]["provider_final"] is False
        assert history_candidates("NVDA", rows, NOW) == []


@pytest.mark.parametrize("status", [302, 403, 429])
def test_http_no_retry_or_redirect(status):
    calls = []

    def respond(req):
        calls.append(req)
        return httpx.Response(
            status, headers={"location": "https://example.com/", "retry-after": "60"}
        )

    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as client:
        with pytest.raises(FetchError) as error:
            fetch_daily(
                "NVDA",
                lambda: None,
                start=date(2026, 11, 25),
                end=date(2026, 11, 25),
                contract=contract(),
                client=client,
            )
        assert error.value.status == status and len(calls) == 1


def test_fundamental_only_approved_metrics_and_etf_no_request():
    def respond(req):
        assert req.url.path.endswith("/quoteSummary/NVDA")
        return httpx.Response(
            200,
            json={
                "quoteSummary": {
                    "error": None,
                    "result": [
                        {
                            "price": {"symbol": "NVDA", "currency": "USD"},
                            "summaryDetail": {"trailingPE": {"raw": 25}, "forwardPE": 20},
                            "defaultKeyStatistics": {"priceToBook": 5},
                            "financialData": {"returnOnEquity": 0.2},
                        }
                    ],
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as client:
        assert fetch_fundamentals("NVDA", lambda: None, contract=contract(), client=client) == {
            "trailingPE": "25",
            "forwardPE": "20",
            "priceToBook": "5",
            "returnOnEquity": "0.2",
        }
        assert fetch_fundamentals("QLD", lambda: None, client=client) == {}


def local_rows():
    days = expected_sessions("NVDA", NOW, CAL, {})
    rows = history_candidates(
        "NVDA",
        [
            {
                "session_at": datetime.combine(day, datetime.min.time(), NEW_YORK),
                "open": str(100 + i),
                "high": str(101 + i),
                "low": str(99 + i),
                "close": str(100 + i),
                "volume": "500",
                "provider_final": True,
            }
            for i, day in enumerate(days)
        ],
        NOW,
    )
    return days, rows


def test_cache_plan_holes_and_stable_ema_seed():
    days, rows = local_rows()
    cached = confirmed_cache(rows, "NVDA", NOW, CAL, None)
    assert len(days) == 200 and missing_ranges(days, cached) == []
    full = feature_snapshot(days, cached, NOW)
    assert full is not None
    assert full.metadata["features"]["SMA_200"]["quality"] == "valid"
    assert full.metadata["features"]["EMA_26"]["quality"] == "valid"
    missing = cached.pop(days[100])
    assert missing_ranges(days, cached) == [(days[100], days[100])]
    partial = feature_snapshot(days, cached, NOW)
    assert partial is not None and partial.metadata["features"]["EMA_26"]["value"] is None
    assert partial.metadata["features"]["SMA_200"]["value"] is None
    assert partial.metadata["features"]["SMA_5"]["value"] is not None
    cached[days[100]] = missing
    assert feature_snapshot(days, cached, NOW).metadata["features"] == full.metadata["features"]
    cached.pop(days[-1])
    absent = feature_snapshot(days, cached, NOW)
    assert absent.metadata["features"]["SMA_5"]["value"] is None
    assert absent.metadata["feature_target_session"] == days[-1].isoformat()


def test_worker_cache_complete_does_not_reserve_or_fetch(monkeypatch):
    _, rows = local_rows()
    monkeypatch.setattr(equity_worker, "utc_now", lambda: NOW)
    monkeypatch.setattr(equity_worker, "_local_bars", lambda *a: rows)
    monkeypatch.setattr(equity_worker, "_fundamental_due", lambda *a: False)
    monkeypatch.setattr(equity_worker, "_version", lambda *a, **kw: 7)
    never = MagicMock(side_effect=AssertionError("unexpected HTTP"))
    for name in ("fetch_daily", "fetch_fundamentals", "_reserve"):
        monkeypatch.setattr(equity_worker, name, never)
    monkeypatch.setattr(equity_worker, "ingest", MagicMock())
    monkeypatch.setattr(equity_worker, "record_health", MagicMock())
    assert equity_worker.daily_symbol(MagicMock(), "NVDA", 7, None)
    never.assert_not_called()
