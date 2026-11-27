"""Exact period relationships, never a claim that an observation is a release vintage.

These are intentionally narrow title contracts for offline normalization. A title
without an explicit observation period, unsupported source or ambiguous schedule
stays unlinked. In particular FRED effective-date rates are not Fed decisions.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from autoaxe.domain.calendars import EventRevision, point_in_time

MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
MONTH_PATTERN = "(" + "|".join(MONTHS) + r") (\d{4})"
METRICS = {
    ("bls", "US_CPI"): ("index", r"\d{4}-(?:0[1-9]|1[0-2])"),
    ("bls", "US_NONFARM_PAYROLL"): ("thousand", r"\d{4}-(?:0[1-9]|1[0-2])"),
    ("bls", "US_UNEMPLOYMENT"): ("percent", r"\d{4}-(?:0[1-9]|1[0-2])"),
    ("bea", "US_PCE"): ("percent_mom", r"\d{4}M(?:0[1-9]|1[0-2])"),
    ("bea", "US_GDP"): ("percent_annual_rate", r"\d{4}Q[1-4]"),
    ("census", "US_RETAIL_SALES"): ("percent_mom_sa", r"\d{4}-(?:0[1-9]|1[0-2])"),
}
LinkStatus = Literal[
    "period_match", "unmatched", "ambiguous", "not_applicable", "context_incomplete"
]


@dataclass(frozen=True)
class PeriodIdentity:
    source_id: str
    metric_id: str
    reference_period: str


@dataclass(frozen=True)
class LinkResult:
    identity: PeriodIdentity | None
    status: LinkStatus
    schedule: EventRevision | None = None


def actual_identity(event: EventRevision) -> PeriodIdentity | None:
    if event.actual is None or event.calendar is not None:
        return None
    metric, sep, period = event.event_key.partition(":")
    contract = METRICS.get((event.source_id, metric))
    if (
        not sep
        or contract is None
        or event.unit != contract[0]
        or not re.fullmatch(contract[1], period)
    ):
        return None
    return PeriodIdentity(event.source_id, metric, period)


def schedule_identities(event: EventRevision) -> tuple[PeriodIdentity, ...]:
    evidence = event.calendar
    if (
        evidence is None
        or evidence.status not in ("confirmed", "unspecified")
        or not evidence.title
        or (event.scheduled_at is None and evidence.date_only is None)
    ):
        return ()
    source, title = event.source_id, evidence.title
    # No fuzzy titles, UID decoding, inferred month offsets or cross-source join.
    patterns = (
        ("bls", "Consumer Price Index for ", ("US_CPI",)),
        ("bls", "Employment Situation for ", ("US_NONFARM_PAYROLL", "US_UNEMPLOYMENT")),
        ("bea", "Personal Income and Outlays, ", ("US_PCE",)),
        ("census", "Advance Monthly Sales for Retail and Food Services, ", ("US_RETAIL_SALES",)),
    )
    for expected, prefix, metrics in patterns:
        if source != expected:
            continue
        match = re.fullmatch(re.escape(prefix) + MONTH_PATTERN, title)
        if match:
            month, year = match.groups()
            separator = "M" if source == "bea" else "-"
            period = f"{year}{separator}{MONTHS.index(month) + 1:02d}"
            return tuple(PeriodIdentity(source, metric, period) for metric in metrics)
    if source == "bea":
        match = re.fullmatch(
            r"Gross Domestic Product, (1st|2nd|3rd|4th) Quarter (\d{4})"
            r"(?: \((?:Advance|Second|Third) Estimate\))?",
            title,
        )
        if match:
            quarter, year = match.groups()
            return (PeriodIdentity(source, "US_GDP", f"{year}Q{quarter[0]}"),)
    return ()


def link_actuals(
    events: list[EventRevision],
    schedules: list[EventRevision],
    cutoff: datetime,
    *,
    incomplete_sources: frozenset[str] = frozenset(),
) -> dict[tuple[str, str], LinkResult]:
    """Join latest PIT-visible calendar revisions to actual observation identities.

    Even a unique match says only that the schedule and observation refer to the
    same period. It does not establish publication time, estimate vintage, or
    the time at which the actual value first became public.
    """
    index: dict[PeriodIdentity, list[EventRevision]] = {}
    for event in point_in_time(schedules, cutoff):
        for schedule_identity in schedule_identities(event):
            index.setdefault(schedule_identity, []).append(event)
    result = {}
    for event in point_in_time(events, cutoff):
        key = (event.source_id, event.event_key)
        identity = actual_identity(event)
        if identity is None:
            result[key] = LinkResult(None, "not_applicable")
            continue
        if event.source_id in incomplete_sources:
            result[key] = LinkResult(identity, "context_incomplete")
            continue
        matches = index.get(identity, [])
        if len(matches) > 1:
            result[key] = LinkResult(identity, "ambiguous")
            continue
        if not matches:
            result[key] = LinkResult(identity, "unmatched")
            continue
        schedule = matches[0]
        # Do not associate an already observed actual with a future scheduled
        # release. For date-only schedules compare provider-local dates only.
        if schedule.scheduled_at is not None:
            eligible = schedule.scheduled_at <= event.first_seen_at
        else:
            assert schedule.calendar is not None and schedule.calendar.date_only is not None
            eligible = (
                schedule.calendar.date_only
                <= event.first_seen_at.astimezone(ZoneInfo("America/New_York")).date()
            )
        result[key] = (
            LinkResult(identity, "period_match", schedule)
            if eligible
            else LinkResult(identity, "unmatched")
        )
    return result
