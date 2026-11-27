from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from autoaxe.domain.calendars import FamilyState, Witching
from autoaxe.domain.expiry_dte import (
    ProductSessionCalendar,
    calendar_expiry_dte,
    calendar_witching_dte,
    product_session_dte,
)
from autoaxe.domain.expiry_evidence import ExpiryClaim, ExpiryClassification, ReviewedExpiry

NOW = datetime(2026, 6, 17, 1, tzinfo=UTC)  # June 16 ET.
DAY = date(2026, 6, 18)


def test_reviewed_product_dte_not_nominal_or_generic_calendar():
    claim = ExpiryClaim(
        candidate_date=date(2026, 6, 19),
        family="INDEX_FUTURE",
        source_id="cme",
        evidence_key="fixture",
        status=FamilyState.YES,
        session_date=DAY,
        contract_ref="SYNTHETIC",
        nominal_expiry_date=date(2026, 6, 19),
        last_trade_at=None,
        processing_at=None,
        settlement_at=None,
        settlement_basis=None,
        source_url="https://www.cmegroup.com/example",
        evidence_ref="fixture evidence",
        family_coverage=False,
        settlement_date=DAY,
    )
    record = ReviewedExpiry(claim, 1, NOW - timedelta(days=1), NOW, 2)
    calendar = ProductSessionCalendar(
        "cme",
        "INDEX_FUTURE",
        "SYNTHETIC",
        2,
        date(2026, 6, 16),
        DAY,
        (date(2026, 6, 17), DAY),
        NOW,
        "fixture-only",
    )
    assert calendar_expiry_dte(record, NOW) == 2
    assert product_session_dte(record, calendar, NOW) == 2
    assert product_session_dte(record, None, NOW) is None
    assert product_session_dte(record, replace(calendar, contract_ref="OTHER"), NOW) is None
    assert product_session_dte(record, replace(calendar, permission_version=3), NOW) is None
    assert (
        product_session_dte(record, replace(calendar, available_at=NOW + timedelta(days=1)), NOW)
        is None
    )
    assert (
        product_session_dte(record, replace(calendar, coverage_start=date(2026, 6, 17)), NOW)
        is None
    )
    assert (
        product_session_dte(record, replace(calendar, sessions=(date(2026, 6, 17),)), NOW) is None
    )
    assert calendar_expiry_dte(record, NOW - timedelta(seconds=1)) is None
    same_day = datetime(2026, 6, 18, 15, tzinfo=UTC)
    assert calendar_expiry_dte(record, same_day) == 0
    assert product_session_dte(record, calendar, same_day) == 0
    assert calendar_expiry_dte(record, same_day + timedelta(days=1)) is None


def test_witching_dte_unconfirmed_or_conflicted_unknown():
    confirmed = ExpiryClassification(DAY, Witching.TRIPLE, {}, False)
    assert calendar_witching_dte(confirmed, NOW) == 2
    assert calendar_witching_dte(replace(confirmed, conflicted=True), NOW) is None
    assert calendar_witching_dte(replace(confirmed, event_type=Witching.PENDING), NOW) is None
