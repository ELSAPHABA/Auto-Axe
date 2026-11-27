from datetime import UTC, date, datetime, timedelta

import pytest

from autoaxe.domain.calendars import FamilyState, Witching
from autoaxe.domain.expirations import (
    ExpirationEvidence,
    classify_expiration,
    trading_session_dte,
)

NOW = datetime(2026, 11, 26, 15, tzinfo=UTC)


def test_actual_exchange_sessions_not_calendar_days():
    sessions = [date(2026, 11, 27), date(2026, 11, 30), date(2026, 12, 1)]
    assert trading_session_dte(NOW, date(2026, 12, 1), sessions) == 3
    assert trading_session_dte(NOW, None, sessions) is None
    with pytest.raises(ValueError):
        trading_session_dte(NOW, date(2026, 12, 1), [sessions[1], sessions[0]])


def test_missing_fourth_family_must_be_pending_not_quadruple():
    day = date(2026, 12, 18)
    confirmed = [
        ExpirationEvidence(
            family=family,
            source_id="fixture",
            contract="SYNTHETIC",
            nominal_expiration_at=NOW + timedelta(days=22),
            last_trade_at=NOW + timedelta(days=22),
            processing_at=None,
            settlement_at=None,
            effective_session_date=day,
            first_seen_at=NOW,
            source_url="https://example.com/fixture",
            status=FamilyState.YES,
        )
        for family in ("EQUITY_OPTION", "INDEX_OPTION", "INDEX_FUTURE")
    ]
    kind, states = classify_expiration(confirmed, day)
    assert kind == Witching.PENDING and states["SINGLE_STOCK_FUTURE"] == FamilyState.UNKNOWN
    fourth = ExpirationEvidence(
        family="SINGLE_STOCK_FUTURE",
        source_id="fixture",
        contract="SYNTHETIC",
        nominal_expiration_at=NOW + timedelta(days=22),
        last_trade_at=NOW + timedelta(days=22),
        processing_at=None,
        settlement_at=None,
        effective_session_date=day,
        first_seen_at=NOW,
        source_url="https://example.com/fixture",
        status=FamilyState.NO,
    )
    assert classify_expiration([*confirmed, fourth], day)[0] == Witching.TRIPLE
