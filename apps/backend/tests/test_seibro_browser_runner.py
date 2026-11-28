"""Offline grant/cadence/isolation tests. No Docker or provider requests."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from autoaxe.application import seibro_browser_runner as runner
from autoaxe.application.seibro_review import (
    URL,
    browser_permission,
    normalize_capture,
    stage_capture,
)
from autoaxe.infrastructure.market_store import PermissionDenied

NOW = datetime(2026, 11, 27, 6, tzinfo=UTC)


def sample():
    return {
        "source_url": URL,
        "capture_mode": "browser_capture",
        "currency": "USD",
        "settlement_type": "2",
        "country_code": "US",
        "period_code": "1",
        "rank_basis": "4",
        "period_start": "2026-11-10",
        "period_end": "2026-11-17",
        "as_of_date_kst": "2026-11-17",
        "retrieved_at_utc": NOW.isoformat(),
        "top50_coverage": True,
        "derived_amount": "gross_settlement_usd",
        "rows": [
            {
                "rank": rank,
                "country_name": "미국",
                "isin": f"US{rank:09d}0",
                "security_name": "Fixture",
                "buy_settlement_usd": str(1000 - rank),
                "sell_settlement_usd": "100",
                "gross_settlement_usd": str(1100 - rank),
                "net_buy_settlement_usd": str(900 - rank),
            }
            for rank in range(1, 51)
        ],
    }


def daily_sample(stamp=NOW):
    captures = []
    for period, basis in runner.DAILY_SCOPES:
        data = sample() | {
            "period_code": period,
            "rank_basis": basis,
            "retrieved_at_utc": stamp.isoformat(),
        }
        if basis in ("1", "2"):
            observed = "buy_settlement_usd" if basis == "1" else "sell_settlement_usd"
            data["derived_amount"] = None
            data["amount_coverage"] = "buy_only" if basis == "1" else "sell_only"
            for row in data["rows"]:
                for field in (
                    "buy_settlement_usd",
                    "sell_settlement_usd",
                    "gross_settlement_usd",
                    "net_buy_settlement_usd",
                ):
                    if field != observed:
                        row[field] = None
        captures.append(data)
    return {"captures": captures}


def daily_ticket():
    return {
        "country": "US",
        "scopes": [{"period": p, "basis": b} for p, b in runner.DAILY_SCOPES],
        "permission_version": 7,
        "deadline": (NOW + timedelta(seconds=490)).isoformat(),
    }


def test_daily_exact_scopes_and_validation():
    result = daily_sample()
    normalized = runner.normalize_daily(result, daily_ticket(), NOW)
    assert len(normalized) == 15
    assert sum(len(c["rows"]) for c in normalized) == 750
    assert [(c["period_code"], c["rank_basis"]) for c in normalized] == list(runner.DAILY_SCOPES)
    assert normalized[0]["rows"][0]["net_buy_settlement_usd"] is None
    assert normalized[2]["rows"][0]["net_buy_settlement_usd"] == "899"
    with pytest.raises(ValueError, match="envelope"):
        runner.normalize_daily({"captures": result["captures"][:-1]}, daily_ticket(), NOW)
    result["captures"][-1] = result["captures"][0]
    with pytest.raises(ValueError, match="repeated"):
        runner.normalize_daily(result, daily_ticket(), NOW)
    result = daily_sample()
    result["captures"][-1]["period_start"] = "2026-11-11"
    with pytest.raises(ValueError, match="inconsistent settlement"):
        runner.normalize_daily(result, daily_ticket(), NOW)
    with pytest.raises(ValueError, match="outside reservation"):
        runner.normalize_daily(daily_sample(), daily_ticket(), NOW + timedelta(seconds=491))


def test_daily_requires_independent_grant(monkeypatch):
    monkeypatch.setattr(runner, "browser_permission", lambda c: 7)
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    with pytest.raises(PermissionDenied, match="independent"):
        runner.daily_adapter_grant(conn, 7)
    conn.execute.return_value.fetchone.return_value = (False,)
    assert runner.daily_adapter_grant(conn, 7) is False
    conn.execute.return_value.fetchone.return_value = (True,)
    assert runner.daily_adapter_grant(conn, 7) is True
    with pytest.raises(PermissionDenied, match="grant changed"):
        runner.daily_adapter_grant(conn, 8)


def test_daily_daemon_waits_after_failure_and_respects_not_due():
    capture = MagicMock(side_effect=[PermissionDenied("private"), "not_due", "validated batch 15"])
    report = MagicMock()
    sleep = MagicMock(side_effect=[None, None, KeyboardInterrupt])
    with pytest.raises(KeyboardInterrupt):
        runner.run_daily_loop("fixture", capture=capture, report=report, sleep=sleep)
    assert capture.call_count == 3
    assert [call.args for call in sleep.call_args_list] == [(300,), (300,), (300,)]
    assert [call.args for call in report.call_args_list] == [
        ("SEIBro daily capture blocked or unavailable",),
        ("validated batch 15",),
    ]


def test_browser_requires_fetch_not_storage_only():
    conn = MagicMock()
    cursor = conn.execute.return_value
    cursor.fetchone.return_value = ("approved", False, True, False, True, NOW, "reviewed", 7)
    with pytest.raises(PermissionDenied):
        browser_permission(conn)
    cursor.fetchone.return_value = ("approved", True, True, True, True, NOW, "reviewed", 7)
    assert browser_permission(conn) == 7


@pytest.mark.parametrize(
    ("basis", "coverage", "observed"),
    [
        ("1", "buy_only", "buy_settlement_usd"),
        ("2", "sell_only", "sell_settlement_usd"),
    ],
)
def test_partial_browser_amounts_only(basis, coverage, observed):
    from autoaxe.adapters.authorized_seibro import SeibroRow
    from autoaxe.application.seibro_review import AMOUNTS

    data = sample() | {"rank_basis": basis, "derived_amount": None, "amount_coverage": coverage}
    for row in data["rows"]:
        for field in AMOUNTS:
            if field != observed:
                row[field] = None
    normalized = normalize_capture(data)
    assert normalized["amount_coverage"] == coverage
    view = SeibroRow.model_validate(normalized["rows"][0]).model_dump(mode="json")
    assert view[observed] == data["rows"][0][observed]
    assert all(view[field] is None for field in AMOUNTS if field != observed)
    with pytest.raises(ValueError):
        normalize_capture(data | {"amount_coverage": "complete"})
    manual = {k: v for k, v in data.items() if k not in ("derived_amount", "amount_coverage")}
    with pytest.raises(ValueError):
        normalize_capture(manual | {"capture_mode": "manual_capture"})
    missing = next(field for field in AMOUNTS if field != observed)
    data["rows"][0][missing] = "0"
    with pytest.raises(ValueError, match="must be null"):
        normalize_capture(data)
    data["rows"][0][missing] = None
    data["rows"][0][observed] = "-1"
    with pytest.raises(ValueError, match="invalid observed"):
        normalize_capture(data)


def test_browser_provenance_and_manual_stage_fence(monkeypatch):
    data = sample()
    assert normalize_capture(data)["derived_amount"] == "gross_settlement_usd"
    for overrides in (
        {"rank_basis": "1"},
        {"derived_amount": "net_buy_settlement_usd"},
        {"rows": data["rows"][:-1]},
        {"period_start": None, "period_end": None},
        {"as_of_date_kst": "2026-11-18"},
    ):
        with pytest.raises(ValueError):
            normalize_capture(data | overrides)
    monkeypatch.setattr("autoaxe.application.seibro_review.verify_connection", lambda *a, **k: None)
    monkeypatch.setattr("autoaxe.application.seibro_review.source_lock", lambda *a, **k: None)
    conn = MagicMock()
    with pytest.raises(PermissionDenied, match="private approved launcher"):
        stage_capture(conn, data)
    monkeypatch.setattr("autoaxe.application.seibro_review.browser_permission", lambda c: 8)
    with pytest.raises(PermissionDenied, match="grant changed"):
        stage_capture(conn, data, expected_browser_version=7)


def test_reservation_is_source_wide_and_requires_grant(monkeypatch):
    monkeypatch.setattr(runner, "verify_connection", lambda *a, **k: None)
    monkeypatch.setattr(runner, "source_lock", lambda *a, **k: None)
    monkeypatch.setattr(runner, "browser_permission", lambda c: 7)
    conn = MagicMock()
    conn.execute.return_value.fetchone.side_effect = [None, (NOW,)]
    ticket = runner.reserve_browser(conn, country="US", period="1", basis="4")
    assert ticket["permission_version"] == 7
    assert conn.execute.call_args.args[1] == ("seibro_browser", 86400, 7)
    conn.execute.return_value.fetchone.side_effect = [None, None]
    assert runner.reserve_browser(conn, country="ALL", period="2", basis="3") is None
    conn.execute.return_value.fetchone.side_effect = [(7, True, False)]
    with pytest.raises(PermissionDenied):
        runner.reserve_browser(conn, country="US", period="1", basis="4")
    conn.execute.return_value.fetchone.side_effect = [(6, False, True)]
    with pytest.raises(PermissionDenied):
        runner.reserve_browser(conn, country="US", period="1", basis="4")


def test_launcher_never_uses_unreserved_or_changed_grant(monkeypatch):
    connection = MagicMock()
    monkeypatch.setattr(runner.psycopg, "connect", lambda *a, **k: connection)
    launch = MagicMock()
    monkeypatch.setattr(runner, "reserve_browser", lambda *a, **k: None)
    assert (
        runner.capture_once("fixture", country="US", period="1", basis="4", launch=launch)
        == "not_due"
    )
    launch.assert_not_called()
    ticket = {
        "country": "US",
        "period": "1",
        "basis": "4",
        "permission_version": 7,
        "deadline": (NOW + timedelta(seconds=100)).isoformat(),
    }
    monkeypatch.setattr(runner, "reserve_browser", lambda *a, **k: ticket)
    monkeypatch.setattr(runner, "browser_permission", lambda c: 8)
    with pytest.raises(PermissionDenied):
        runner.capture_once("fixture", country="US", period="1", basis="4", launch=launch)
    launch.assert_not_called()
    monkeypatch.setattr(runner, "browser_permission", lambda c: 7)
    launch.return_value = sample() | {"capture_mode": "manual_capture"}
    with pytest.raises(ValueError, match="wrong capture scope"):
        runner.capture_once("fixture", country="US", period="1", basis="4", launch=launch)
    launch.return_value = sample()
    connection.__enter__.return_value.execute.return_value.fetchone.return_value = (NOW,)
    stage = MagicMock(return_value=("fixture-id", "fixture-hash"))
    monkeypatch.setattr(runner, "stage_capture", stage)
    assert runner.capture_once("fixture", country="US", period="1", basis="4", launch=launch) == (
        "staged fixture-id fixture-hash"
    )
    assert stage.call_args.kwargs == {"expected_browser_version": 7}


def test_container_command_has_no_secret_or_build(monkeypatch):
    run = MagicMock(return_value=MagicMock(returncode=0, stdout=b'{"test":true}'))
    monkeypatch.setattr(runner.subprocess, "run", run)
    assert runner.run_container({"permission_version": 7}) == {"test": True}
    args, kwargs = run.call_args.args, run.call_args.kwargs
    assert "--no-build" in args[0] and "--no-deps" in args[0]
    assert "--rm" in args[0] and "--pull" in args[0] and "never" in args[0]
    assert kwargs["timeout"] == 120 and kwargs["input"] == b'{"permission_version": 7}'
