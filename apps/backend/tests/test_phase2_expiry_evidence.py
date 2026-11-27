from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autoaxe.adapters.expiry_api import ExpiryClaimView, router
from autoaxe.domain.calendars import FAMILIES, FamilyState, Witching
from autoaxe.domain.expiry_evidence import ExpiryClaim, ReviewedExpiry, classify_reviewed
from autoaxe.infrastructure import expiry_store
from autoaxe.infrastructure.market_store import PermissionDenied

NOW = datetime(2026, 11, 27, 10, tzinfo=UTC)
DAY = date(2026, 12, 18)
URLS = {
    "occ": "https://www.optionseducation.org/referencelibrary/expiration-calendar",
    "cme": "https://www.cmegroup.com/trading/equity-index/rolldates.html",
}


def claim(family="EQUITY_OPTION", *, status=FamilyState.YES, **overrides):
    source = "occ" if family.endswith("_OPTION") else "cme"
    data = dict(
        candidate_date=DAY,
        family=family,
        source_id=source,
        evidence_key="standard-quarter",
        status=status,
        session_date=DAY,
        contract_ref="SYNTHETIC" if status == FamilyState.YES else None,
        nominal_expiry_date=DAY if status == FamilyState.YES else None,
        last_trade_at=None,
        processing_at=None,
        settlement_at=None,
        settlement_basis=None,
        source_url=URLS[source],
        evidence_ref="Synthetic test; not actual contract evidence",
        family_coverage=status == FamilyState.NO,
    )
    return ExpiryClaim(**(data | overrides))


def reviewed(c, *, revision=1, available=NOW):
    return ReviewedExpiry(c, revision, NOW, available, 1)


def test_candidates_not_confirmed_and_unknown_fourth_is_pending():
    pending = classify_reviewed(DAY, [], NOW)[0]
    assert pending.session_date is None and pending.event_type == Witching.PENDING
    core = [reviewed(claim(f)) for f in FAMILIES[:3]]
    assert classify_reviewed(DAY, core, NOW)[0].event_type == Witching.PENDING
    absent = reviewed(claim(FAMILIES[3], status=FamilyState.NO))
    assert classify_reviewed(DAY, [*core, absent], NOW)[0].event_type == Witching.TRIPLE
    present = reviewed(claim(FAMILIES[3]))
    assert classify_reviewed(DAY, [*core, present], NOW)[0].event_type == Witching.QUADRUPLE
    conflict = reviewed(claim(FAMILIES[3], status=FamilyState.NO, evidence_key="contradiction"))
    result = classify_reviewed(DAY, [*core, present, conflict], NOW)[0]
    assert result.conflicted and result.event_type == Witching.PENDING
    assert result.family_status[FAMILIES[3]] == FamilyState.UNKNOWN


def test_pit_revision_changes_session_not_backdated():
    original = reviewed(claim())
    moved = reviewed(
        replace(original.claim, session_date=DAY - timedelta(days=1)),
        revision=2,
        available=NOW + timedelta(hours=1),
    )
    assert classify_reviewed(DAY, [original, moved], NOW)[0].session_date == DAY
    assert classify_reviewed(DAY, [original, moved], NOW + timedelta(hours=1))[0].session_date == (
        DAY - timedelta(days=1)
    )
    split = classify_reviewed(
        DAY, [moved, reviewed(claim("INDEX_OPTION"))], NOW + timedelta(hours=1)
    )
    assert len(split) == 2
    assert all(x.event_type == Witching.PENDING for x in split)


def test_expiry_not_last_trade_or_processing_time_and_no_guessed_timestamps():
    am = claim(
        "INDEX_OPTION",
        last_trade_at=datetime(2026, 12, 17, 22, tzinfo=UTC),
        settlement_at=datetime(2026, 12, 18, 14, 30, tzinfo=UTC),
        settlement_basis="AM",
        processing_at=datetime(2026, 12, 19, 1, tzinfo=UTC),
    )
    assert classify_reviewed(DAY, [reviewed(am)], NOW)[0].session_date == DAY
    assert claim().last_trade_at is None
    assert (
        ExpiryClaimView.model_validate(asdict(am))
        .model_dump(mode="json")["last_trade_at"]
        .endswith("Z")
    )
    with pytest.raises(ValueError, match="settlement/session"):
        replace(am, session_date=DAY - timedelta(days=1))


def test_juneteenth_date_only_processing_not_timestamp_or_expiry_rewrite():
    # OCC memo 56694 documents a 2026-06-19 nominal expiry and 06-18 processing.
    # Synthetic contract reference: this is NOT a claim about a particular listing.
    june = claim(
        candidate_date=date(2026, 6, 19),
        session_date=date(2026, 6, 18),
        nominal_expiry_date=date(2026, 6, 19),
        processing_date=date(2026, 6, 18),
        source_url="https://infomemo.theocc.com/infomemos?number=56694",
    )
    assert june.processing_at is None
    assert june.nominal_expiry_date != june.session_date
    with pytest.raises(ValueError, match="date/timestamp"):
        replace(june, processing_at=datetime(2026, 6, 19, 16, tzinfo=UTC))


@pytest.mark.parametrize(
    "url",
    [
        "https://www.cmegroup.com.evil.example/path",
        "https://www.optionseducation.org@evil.example/calendar",
        "https://www.optionseducation.org/",
        "http://www.optionseducation.org/calendar",
    ],
)
def test_reject_unofficial_document(url):
    with pytest.raises(ValueError, match="official document"):
        claim(source_url=url)


def test_no_negative_from_single_missing_contract_and_no_weekly_candidate():
    with pytest.raises(ValueError, match="family-wide"):
        claim(status=FamilyState.NO, family_coverage=False)
    with pytest.raises(ValueError, match="active standard contract"):
        claim(contract_ref=None)
    with pytest.raises(ValueError, match="standard quarterly"):
        claim(candidate_date=DAY + timedelta(days=7))
    with pytest.raises(ValueError, match="wrong official source"):
        claim(source_id="cme")
    with pytest.raises(ValueError, match="availability|provenance"):
        reviewed(claim(), available=NOW - timedelta(seconds=1))


class Cursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return next(self.replies)

    def cursor(self, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def grant(version=1, approved=True):
    return Cursor(("approved" if approved else "unverified", True, True, NOW, "grant", version))


def test_submit_permission_denial_before_write(monkeypatch):
    monkeypatch.setattr(expiry_store, "verify_connection", lambda conn, *, write: None)
    for g in (grant(2), grant(approved=False)):
        conn = FakeConnection([Cursor(), g])
        with pytest.raises(PermissionDenied):
            expiry_store.submit_expiry(
                conn, claim(), submitter_ref="submitter", expected_permission_version=1
            )
        assert len(conn.calls) == 2


def test_submit_hash_dedup_and_changed_permission_revision(monkeypatch):
    monkeypatch.setattr(expiry_store, "verify_connection", lambda conn, *, write: None)
    conn = FakeConnection([Cursor(), grant(), Cursor(), Cursor()])
    identifier, rev, made = expiry_store.submit_expiry(
        conn, claim(), submitter_ref="submitter", expected_permission_version=1
    )
    assert rev == 1 and made
    insert = conn.calls[-1][1]
    assert len(insert) == 23 and insert[0] == identifier
    previous = Cursor((identifier, rev, insert[-1], 1))
    again = FakeConnection([Cursor(), grant(), previous])
    assert expiry_store.submit_expiry(
        again, claim(), submitter_ref="submitter", expected_permission_version=1
    ) == (
        identifier,
        1,
        False,
    )
    changed = FakeConnection([Cursor(), grant(2), previous, Cursor()])
    assert expiry_store.submit_expiry(
        changed, claim(), submitter_ref="submitter", expected_permission_version=2
    )[1:] == (
        2,
        True,
    )


def test_review_requires_current_grant_and_latest_and_immutable(monkeypatch):
    monkeypatch.setattr(expiry_store, "verify_connection", lambda conn, *, write: None)
    identifier = uuid4()
    args = dict(
        reviewer_ref="local-operator",
        reason="manual document checked",
        expected_permission_version=1,
    )
    evidence = Cursor(("occ", 1, DAY, "EQUITY_OPTION", "standard-quarter", 1, "submitter"))
    same = FakeConnection([evidence, Cursor(), grant()])
    with pytest.raises(ValueError, match="self-review"):
        expiry_store.review_expiry(
            same, identifier, "checked", **(args | {"reviewer_ref": "submitter"})
        )
    stale = FakeConnection([evidence, Cursor(), grant(), Cursor((2,))])
    with pytest.raises(ValueError, match="superseded"):
        expiry_store.review_expiry(stale, identifier, "checked", **args)
    valid = FakeConnection([evidence, Cursor(), grant(), Cursor((1,)), Cursor(), Cursor()])
    assert expiry_store.review_expiry(valid, identifier, "checked", **args)
    existing = Cursor(("checked", "local-operator", "manual document checked"))
    duplicate = FakeConnection([evidence, Cursor(), grant(), Cursor((1,)), existing])
    assert not expiry_store.review_expiry(duplicate, identifier, "checked", **args)
    immutable = FakeConnection([evidence, Cursor(), grant(), Cursor((1,)), existing])
    with pytest.raises(ValueError, match="immutable"):
        expiry_store.review_expiry(immutable, identifier, "rejected", **args)


def test_read_latest_before_review_filter_and_bounded(monkeypatch):
    monkeypatch.setattr(expiry_store, "verify_connection", lambda conn, *, write: None)
    row = asdict(claim()) | dict(
        revision=2, first_seen_at=NOW, reviewed_at=NOW, permission_version=1
    )
    conn = FakeConnection([Cursor(rows=[row])])
    result = expiry_store.query_expiry(conn, candidate_date=DAY, cutoff=NOW, private_use=True)
    assert result == [reviewed(claim(), revision=2)]
    sql, params = conn.calls[0]
    assert sql.index("DISTINCT ON") < sql.index("v.decision='checked'")
    assert "r.permission_version=e.permission_version" in sql
    assert "r.allow_redistribution OR" in sql
    assert params == (DAY, NOW, NOW, True)
    oversized = FakeConnection([Cursor(rows=[row] * 201)])
    with pytest.raises(ValueError, match="complete read bound"):
        expiry_store.query_expiry(oversized, candidate_date=DAY, cutoff=NOW)


def test_read_router_fails_closed_without_authority(monkeypatch):
    monkeypatch.delenv("AUTOAXE_MARKET_READ_DSN", raising=False)
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get(
        "/api/v1/dashboard/expiry-calendar", params={"candidate_date": DAY.isoformat()}
    )
    assert response.status_code == 503
    assert (
        app.openapi()["paths"]["/api/v1/dashboard/expiry-calendar"]["get"]["operationId"]
        == "getAuthorizedExpiryCalendar"
    )


@pytest.mark.integration
def test_expiry_ledger_real_roles_and_pit(monkeypatch):
    """Synthetic local database only; never invokes an OCC/CME endpoint."""
    import secrets
    from pathlib import Path

    import psycopg
    from psycopg.errors import InsufficientPrivilege
    from testcontainers.postgres import PostgresContainer

    from autoaxe.infrastructure.db_bootstrap import provision
    from autoaxe.infrastructure.market_store import set_permission

    monkeypatch.setenv("AUTOAXE_DISPOSABLE_DB", "true")
    image = "postgres:17@sha256:87c8b42f423b45d5247e6aa8fdb2e7762fec164c68a50fe3eb07e7bfcaf4dbcf"
    secret = secrets.token_urlsafe(24)
    with PostgresContainer(
        image, username="fixture_admin", password=secret, dbname="postgres"
    ) as pg:
        opts = dict(host=pg.get_container_host_ip(), port=pg.get_exposed_port(5432))
        admin = psycopg.conninfo.make_conninfo(
            **opts, dbname="postgres", user="fixture_admin", password=secret
        )
        passwords = provision(admin, Path(__file__).resolve().parents[1] / "alembic.ini")

        def dsn(suffix):
            role = f"autoaxe_market_{suffix}"
            return psycopg.conninfo.make_conninfo(
                **opts, dbname="autoaxe_market", user=role, password=passwords[role]
            )

        with psycopg.connect(dsn("runtime")) as conn:
            with pytest.raises(PermissionDenied):
                expiry_store.submit_expiry(
                    conn, claim(), submitter_ref="submitter", expected_permission_version=1
                )
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            # Storage-only manual approval does not enable automatic collection.
            set_permission(
                conn,
                "occ",
                approved=True,
                evidence="synthetic expiry test",
                fetch=False,
                storage=True,
            )
            version = conn.execute(
                "SELECT permission_version FROM catalog.source_registry WHERE source_id='occ'"
            ).fetchone()[0]

        def cutoff():
            with psycopg.connect(dsn("read")) as conn:
                return conn.execute("SELECT clock_timestamp()").fetchone()[0]

        def visible(at, *, private=True):
            with psycopg.connect(dsn("read")) as conn:
                return expiry_store.query_expiry(
                    conn, candidate_date=DAY, cutoff=at, private_use=private
                )

        original = claim()
        args = dict(submitter_ref="submitter", expected_permission_version=version)
        review = dict(
            reviewer_ref="reviewer",
            reason="synthetic manual check",
            expected_permission_version=version,
        )
        with psycopg.connect(dsn("runtime")) as conn:
            identifier, revision, made = expiry_store.submit_expiry(conn, original, **args)
            assert revision == 1 and made
            assert expiry_store.submit_expiry(conn, original, **args) == (identifier, 1, False)
        pending_cutoff = cutoff()
        assert visible(pending_cutoff) == []
        with psycopg.connect(dsn("runtime")) as conn:
            with pytest.raises(ValueError, match="self-review"):
                expiry_store.review_expiry(
                    conn, identifier, "checked", **(review | {"reviewer_ref": "submitter"})
                )
            assert expiry_store.review_expiry(conn, identifier, "checked", **review)
        checked_cutoff = cutoff()
        assert visible(pending_cutoff) == []
        assert len(visible(checked_cutoff)) == 1
        assert visible(checked_cutoff, private=False) == []
        with psycopg.connect(dsn("runtime")) as conn:
            corrected = replace(original, session_date=DAY - timedelta(days=1))
            new_id, rev, created = expiry_store.submit_expiry(conn, corrected, **args)
            assert rev == 2 and created
        corrected_cutoff = cutoff()
        assert visible(corrected_cutoff) == []
        assert visible(checked_cutoff)[0].claim.session_date == DAY
        with psycopg.connect(dsn("runtime")) as conn:
            assert expiry_store.review_expiry(conn, new_id, "rejected", **review)
        assert visible(cutoff()) == []
        with psycopg.connect(dsn("read")) as conn:
            with pytest.raises(InsufficientPrivilege):
                conn.execute("DELETE FROM indicators.expiry_review")
        with psycopg.connect(dsn("runtime")) as conn:
            with pytest.raises(InsufficientPrivilege):
                conn.execute("UPDATE indicators.expiry_evidence SET status='NO'")
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "occ",
                approved=False,
                evidence="synthetic revocation",
                fetch=False,
                storage=False,
            )
        assert visible(checked_cutoff) == []
