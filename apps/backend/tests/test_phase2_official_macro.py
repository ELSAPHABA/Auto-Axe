"""A real official-source integration contract without contacting a provider."""

import json
from datetime import UTC, datetime

import httpx
import pytest

from autoaxe.application.official_macro import (
    BLS_ENDPOINT,
    OfficialSourceError,
    collect_bls_v1,
)

NOW = datetime(2026, 11, 27, 2, tzinfo=UTC)
PAYLOAD = {
    "status": "REQUEST_SUCCEEDED",
    "Results": {
        "series": [
            {
                "seriesID": "CUUR0000SA0",
                "data": [{"period": "M10", "year": "2026", "value": "321.50"}],
            }
        ]
    },
}


def fake_client(response: httpx.Response) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == BLS_ENDPOINT
        assert request.headers["accept"] == "application/json"
        assert json.loads(request.content) == {"seriesid": ["CUUR0000SA0"]}
        return response

    return httpx.Client(
        transport=httpx.MockTransport(handler), trust_env=False, follow_redirects=False
    )


def test_bls_official_v1_allowlisted_one_request_and_source_time_unknown() -> None:
    checked = []

    def permit() -> None:
        checked.append("yes")

    with fake_client(httpx.Response(200, json=PAYLOAD)) as client:
        rows = collect_bls_v1(
            client, authorize=permit, series_ids=("CUUR0000SA0",), received_at=NOW
        )
    assert len(checked) == 2
    assert len(rows) == 1
    assert rows[0].actual == "321.5"
    assert rows[0].scheduled_at is None and rows[0].released_at is None
    assert rows[0].first_seen_at == NOW


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403, content=b"blocked"),
        httpx.Response(429, content=b"retry"),
        httpx.Response(302, headers={"location": "http://127.0.0.1/"}),
        httpx.Response(200, content=b"<html/>", headers={"content-type": "text/html"}),
        httpx.Response(
            200,
            content=b"X" * 262_145,
            headers={"content-type": "application/json"},
        ),
        httpx.Response(200, json={"status": "REQUEST_FAILED"}),
    ],
)
def test_bls_invalid_response_always_fails_closed(response: httpx.Response) -> None:
    with fake_client(response) as client, pytest.raises(OfficialSourceError):
        collect_bls_v1(
            client,
            authorize=lambda: None,
            series_ids=("CUUR0000SA0",),
            received_at=NOW,
        )


def test_bls_rejects_unauthorized_or_unregistered_series() -> None:
    with fake_client(httpx.Response(200, json=PAYLOAD)) as client:
        with pytest.raises(ValueError):
            collect_bls_v1(client, authorize=lambda: None, series_ids=("CUSTOM",), received_at=NOW)
        with pytest.raises(PermissionError):
            collect_bls_v1(
                client,
                authorize=lambda: (_ for _ in ()).throw(PermissionError("not authorized")),
                series_ids=("CUUR0000SA0",),
                received_at=NOW,
            )
        with pytest.raises(ValueError):
            collect_bls_v1(
                client,
                authorize=lambda: None,
                series_ids=("CUUR0000SA0", "CUUR0000SA0"),
                received_at=NOW,
            )


def test_bls_permission_revocation_during_request_fences_result() -> None:
    called = 0

    def revoke_during_call() -> None:
        nonlocal called
        called += 1
        if called == 2:
            raise PermissionError("source revoked")

    with fake_client(httpx.Response(200, json=PAYLOAD)) as client:
        with pytest.raises(PermissionError, match="revoked"):
            collect_bls_v1(
                client,
                authorize=revoke_during_call,
                series_ids=("CUUR0000SA0",),
                received_at=NOW,
            )
