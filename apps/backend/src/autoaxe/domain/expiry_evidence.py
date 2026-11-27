"""Manual, source-scoped expiry evidence; no inferred sessions or contract listings.

Reviewed public documentation (2026-11-27):
OCC/OIC: https://www.optionseducation.org/referencelibrary/expiration-calendar
OCC holiday processing: https://infomemo.theocc.com/infomemos?number=56694
CME index: https://www.cmegroup.com/trading/equity-index/rolldates.html
CME SSF: https://www.cmegroup.com/articles/faqs/faq-single-stock-futures.html
Launch: https://www.cmegroup.com/media-room/press-releases/2026/6/30/cme_group_to_launchsinglestockfuturesonjuly27.html
Cboe SPX: https://www.cboe.com/tradable-products/sp-500/spx-options/spx-specifications

OCC distinguishes AM/PM, exercise/processing and holidays. CME roll is not
expiration; SSF launch/specification alone is not proof of an active contract
on a specific date. Standard quarterly expiry/settlement is the effective
session, NOT necessarily last trade (e.g. AM-settled SPX). No automatic holiday
shift, time inference, or assumption that missing SSF means NO.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from autoaxe.domain.calendars import (
    FAMILIES,
    FamilyState,
    Witching,
    classify_witching,
    third_friday,
)
from autoaxe.domain.types import utc_datetime

Family = Literal["EQUITY_OPTION", "INDEX_OPTION", "INDEX_FUTURE", "SINGLE_STOCK_FUTURE"]
Source = Literal["occ", "cme"]
Decision = Literal["checked", "rejected"]
ET = ZoneInfo("America/New_York")
SOURCES = {
    "EQUITY_OPTION": "occ",
    "INDEX_OPTION": "occ",
    "INDEX_FUTURE": "cme",
    "SINGLE_STOCK_FUTURE": "cme",
}
HOSTS = {
    "occ": {"www.theocc.com", "theocc.com", "infomemo.theocc.com", "www.optionseducation.org"},
    "cme": {"www.cmegroup.com", "cmegroup.com"},
}


def check_candidate(day: date) -> None:
    if day.month not in (3, 6, 9, 12) or third_friday(day.year, day.month) != day:
        raise ValueError("not a standard quarterly candidate")


@dataclass(frozen=True)
class ExpiryClaim:
    candidate_date: date
    family: Family
    source_id: Source
    evidence_key: str
    status: FamilyState
    session_date: date
    contract_ref: str | None
    nominal_expiry_date: date | None
    last_trade_at: datetime | None
    processing_at: datetime | None
    settlement_at: datetime | None
    settlement_basis: Literal["AM", "PM", "OTHER"] | None
    source_url: str
    evidence_ref: str
    family_coverage: bool
    last_trade_date: date | None = None
    processing_date: date | None = None
    settlement_date: date | None = None

    def __post_init__(self) -> None:
        check_candidate(self.candidate_date)
        if SOURCES.get(self.family) != self.source_id:
            raise ValueError("wrong official source for family")
        url = urlsplit(self.source_url)
        if (
            url.scheme != "https"
            or url.hostname not in HOSTS[self.source_id]
            or url.username is not None
            or url.password is not None
            or url.port is not None
            or not url.path
            or url.path == "/"
            or len(self.source_url) > 2048
        ):
            raise ValueError("official document URL required")
        if (
            not self.evidence_key.strip()
            or len(self.evidence_key) > 128
            or not self.evidence_ref.strip()
            or len(self.evidence_ref) > 2000
            or (self.contract_ref is not None and not 0 < len(self.contract_ref.strip()) <= 256)
            or not isinstance(self.status, FamilyState)
            or type(self.family_coverage) is not bool
            or self.settlement_basis not in (None, "AM", "PM", "OTHER")
        ):
            raise ValueError("invalid evidence")
        # Bound the association to this quarterly window; do not move the
        # candidate to another day by rule. Exact session is supplied by review.
        if abs((self.session_date - self.candidate_date).days) > 7:
            raise ValueError("session outside quarterly candidate window")
        for stamp in (self.last_trade_at, self.processing_at, self.settlement_at):
            if stamp is not None:
                utc_datetime(stamp)
        # Official notices frequently provide a date only. Keep it as such
        # instead of inventing a time. If both are present, they must agree.
        for day, stamp in (
            (self.last_trade_date, self.last_trade_at),
            (self.processing_date, self.processing_at),
            (self.settlement_date, self.settlement_at),
        ):
            if day is not None and stamp is not None and day != stamp.astimezone(ET).date():
                raise ValueError("date/timestamp mismatch")
        if self.status == FamilyState.YES:
            if not self.contract_ref or self.nominal_expiry_date is None:
                raise ValueError("confirmed family needs active standard contract and expiry date")
            if abs((self.nominal_expiry_date - self.candidate_date).days) > 7:
                raise ValueError("expiry outside quarterly candidate window")
            if (
                self.settlement_at is not None
                and self.settlement_at.astimezone(ET).date() != self.session_date
            ):
                raise ValueError("settlement/session mismatch")
        else:
            if any(
                value is not None
                for value in (
                    self.contract_ref,
                    self.nominal_expiry_date,
                    self.last_trade_at,
                    self.processing_at,
                    self.settlement_at,
                    self.settlement_basis,
                    self.last_trade_date,
                    self.processing_date,
                    self.settlement_date,
                )
            ):
                raise ValueError("nonpositive family evidence cannot assert contract details")
            if self.status == FamilyState.NO and not self.family_coverage:
                raise ValueError("absence requires explicit family-wide coverage, not one contract")


@dataclass(frozen=True)
class ReviewedExpiry:
    claim: ExpiryClaim
    revision: int
    first_seen_at: datetime
    available_at: datetime
    permission_version: int

    def __post_init__(self) -> None:
        utc_datetime(self.first_seen_at)
        utc_datetime(self.available_at)
        if (
            self.available_at < self.first_seen_at
            or min(self.revision, self.permission_version) < 1
        ):
            raise ValueError("invalid review provenance")


@dataclass(frozen=True)
class ExpiryClassification:
    session_date: date | None
    event_type: Witching
    family_status: dict[str, FamilyState]
    conflicted: bool


def classify_reviewed(
    candidate_date: date, records: list[ReviewedExpiry], as_of: datetime
) -> list[ExpiryClassification]:
    """Only checked evidence known at cutoff; conflicting assertions fail closed.

    The candidate is not an effective session unless reviewed evidence exists.
    No absence inferred from another family or a displaced contract.
    """
    check_candidate(candidate_date)
    utc_datetime(as_of)
    latest: dict[tuple[str, str, str], ReviewedExpiry] = {}
    for record in records:
        claim = record.claim
        if claim.candidate_date != candidate_date or record.available_at > as_of:
            continue
        key = (claim.source_id, claim.family, claim.evidence_key)
        previous = latest.get(key)
        if previous is None or record.revision > previous.revision:
            latest[key] = record
        elif previous.revision == record.revision and previous != record:
            raise ValueError("conflicting duplicate revision")
    dates = sorted(
        {r.claim.session_date for r in latest.values() if r.claim.status == FamilyState.YES}
    )
    if not dates:
        return [
            ExpiryClassification(
                None, Witching.PENDING, dict.fromkeys(FAMILIES, FamilyState.UNKNOWN), False
            )
        ]
    result = []
    for day in dates:
        states = dict.fromkeys(FAMILIES, FamilyState.UNKNOWN)
        conflict = False
        for family in FAMILIES:
            values = {
                r.claim.status
                for r in latest.values()
                if r.claim.session_date == day and r.claim.family == family
            } - {FamilyState.UNKNOWN}
            if len(values) > 1:
                conflict = True
            elif values:
                states[family] = values.pop()
        kind = Witching.PENDING if conflict else classify_witching(states)
        result.append(ExpiryClassification(day, kind, states, conflict))
    return result
