from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from autoaxe_scraper import worker
from autoaxe_scraper.transport import parse_cnn_json


class FakeBroker:
    def __init__(self, *, revoked=False, invalid=False, idle=False):
        self.calls = []
        self.revoked = revoked
        self.invalid = invalid
        self.idle = idle
        self.job = {
            "job_id": str(uuid4()),
            "source_id": "cnn",
            "adapter_version": 1,
            "schema_version": 1,
            "params": {},
            "job_nonce": "n" * 43,
            "lease_token": "t" * 43,
            "deadline_at": (datetime.now(UTC) + timedelta(seconds=60)).isoformat(),
            "lease_expires_at": (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
            "permission_version": 1,
        }

    def post(self, path, data):
        self.calls.append((path, data))
        if path.endswith("/claim"):
            if self.idle:
                return None
            return self.job | ({"params": {"url": "https://bad.invalid"}} if self.invalid else {})
        if path.endswith("/heartbeat"):
            return {"status": "revoked" if self.revoked else "leased"}
        if path.endswith("/failure"):
            return {"status": "failed"}
        return {"status": "quarantined"}


def test_worker_checks_lease_and_quarantines_exact_candidate(monkeypatch, cnn_document):
    def fetch(*, permit):
        permit()
        permit()
        return parse_cnn_json(cnn_document(score=32))

    monkeypatch.setattr(worker, "fetch_cnn_fear_greed", fetch)
    broker = FakeBroker()
    assert worker.run_once(broker, "cnn") == "quarantined"
    assert [path.rsplit("/", 1)[1] for path, _ in broker.calls] == [
        "claim",
        "heartbeat",
        "heartbeat",
        "heartbeat",
        "result",
    ]
    candidate = broker.calls[-1][1]["candidates"][0]
    assert candidate["value"] == "32" and candidate["quality"] == "manual_review_required"
    assert candidate["automated_trading_allowed"] is False


def test_dram_worker_uses_fetcher_and_reviewed_selector(monkeypatch):
    from autoaxe_scraper import dram_fetcher
    from autoaxe_scraper.reviewed_dom import DOMContract

    html = (
        '<div id="module"><h2>Module Spot Price</h2>'
        "<p>Last Update:Aug.3 2026 14:40 (GMT+8)</p>"
        "<table><tr><th>Item</th><th>Session Average</th></tr>"
        "<tr><td>DDR5 UDIMM 16GB 4800/5600</td><td>12.5</td></tr>"
        "<tr><td>DDR5 RDIMM 32GB 4800/5600</td><td>22.5</td></tr></table></div>"
    )

    def fetch(*, permit):
        permit()
        permit()
        permit()
        return html

    monkeypatch.setattr(dram_fetcher, "fetch_dramexchange_html", fetch)
    broker = FakeBroker()
    broker.job["source_id"] = "dramexchange"
    contract = DOMContract(
        "dramexchange",
        1,
        datetime.now(UTC) + timedelta(hours=1),
        {"root": "#module", "title": "h2", "table": "table", "timestamp": "p"},
    )
    assert worker.run_once(broker, "dramexchange", contract=contract) == "quarantined"
    candidates = broker.calls[-1][1]["candidates"]
    assert [r["value"] for r in candidates] == ["22.5", "12.5"]
    assert all(r["quality"] == "manual_review_required" for r in candidates)
    assert all(r["unit_verified"] is False for r in candidates)


@pytest.mark.parametrize("mode", ["idle", "invalid", "revoked", "pizzint", "seibro"])
def test_worker_never_dials_provider_without_valid_lease(monkeypatch, mode):
    def guarded_fetch(*, permit):
        permit()
        raise AssertionError("provider must not be contacted")

    monkeypatch.setattr(worker, "fetch_cnn_fear_greed", guarded_fetch)
    broker = FakeBroker(**{mode: True}) if mode in {"idle", "invalid", "revoked"} else FakeBroker()
    source = mode if mode in {"pizzint", "seibro"} else "cnn"
    if mode == "idle":
        assert worker.run_once(broker, source) == "idle"
    else:
        with pytest.raises(worker.BrokerError):
            worker.run_once(broker, source)
    assert not any(path.endswith("/result") for path, _ in broker.calls)
    if mode in {"pizzint", "seibro"}:
        assert broker.calls == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            worker.ProviderHTTPError(429, "900"),
            {"reason": "http", "http_status": 429, "retry_header": "900"},
        ),
        (worker.ProviderHTTPError(403, None), {"reason": "http", "http_status": 403}),
        (worker.SourceBlocked("untrusted response"), {"reason": "schema"}),
        (OSError("timeout"), {"reason": "transport"}),
    ],
)
def test_worker_failure_is_reported_once_without_payload(monkeypatch, error, expected):
    def fetch(*, permit):
        permit()
        raise error

    monkeypatch.setattr(worker, "fetch_cnn_fear_greed", fetch)
    broker = FakeBroker()
    assert worker.run_once(broker, "cnn") == "failed"
    assert [path.rsplit("/", 1)[1] for path, _ in broker.calls] == [
        "claim",
        "heartbeat",
        "failure",
    ]
    assert broker.calls[-1][1] == {
        "source_id": "cnn",
        "job_nonce": "n" * 43,
        "lease_token": "t" * 43,
        **expected,
    }
