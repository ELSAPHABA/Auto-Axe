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
