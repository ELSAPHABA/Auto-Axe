import asyncio

from fastapi.testclient import TestClient

from autoaxe.adapters.dashboard_api import build_dashboard, fixture_sse
from autoaxe.entrypoints.api import create_app
from autoaxe.entrypoints.scrape_broker import create_broker_app


def test_dashboard_api_is_explicitly_fixture_and_keyset_paginated():
    client = TestClient(create_app())
    first = client.get("/api/v1/dashboard/indicators", params={"limit": 20})
    assert first.status_code == 200
    meta = first.json()["meta"]
    assert meta["environment"] == "fixture" and meta["live_enabled"] is False
    assert meta["next_cursor"] and meta["version"] == 0
    assert all(
        row["value"] is None for row in first.json()["data"] if row["permission"] == "unverified"
    )
    second = client.get(
        "/api/v1/dashboard/indicators",
        params={
            "limit": 20,
            "cursor": meta["next_cursor"],
        },
    )
    assert second.status_code == 200
    assert not {row["indicator_id"] for row in first.json()["data"]} & {
        row["indicator_id"] for row in second.json()["data"]
    }
    assert client.get("/api/v1/dashboard/indicators", params={"category": "bad"}).status_code == 400
    assert client.get("/api/v1/dashboard/indicators", params={"cursor": "bad"}).status_code == 400
    assert client.get("/api/v1/dashboard/indicators", params={"limit": 0}).status_code == 422
    fixture = build_dashboard(request_id="test", category="market", limit=100)
    synthetic = [r for r in fixture.data if r.permission == "fixture_only"]
    assert len(synthetic) == 1 and synthetic[0].value == "123.45"
    assert synthetic[0].source_event_at is None


def test_fixture_sse_ready_before_any_delta():
    class Closed:
        async def is_disconnected(self):
            return True

    async def inspect():
        generator = fixture_sse(Closed())  # type: ignore[arg-type]
        chunk = await anext(generator)
        await generator.aclose()
        return chunk

    ready = asyncio.run(inspect())
    assert ready.startswith("event: ready\n")
    assert '"aggregate":"dashboard"' in ready
    assert '"version":0' in ready


def test_auth_protected_endpoints_and_broker_fail_closed(monkeypatch):
    client = TestClient(create_app())
    assert client.get("/api/v1/auth/login").status_code == 503
    assert client.get("/api/v1/auth/session").status_code == 503
    assert client.post("/api/v1/auth/logout").status_code == 503
    broker = TestClient(create_broker_app())
    assert (
        broker.post(
            "/internal/v1/scrape/jobs/claim",
            json={
                "source_id": "cnn",
                "lease_seconds": 30,
            },
        ).status_code
        == 503
    )
    assert (
        client.post(
            "/internal/v1/scrape/jobs/claim",
            json={
                "source_id": "cnn",
                "lease_seconds": 30,
            },
        ).status_code
        == 404
    )
    # An HTTP header is never accepted as proof of a verified client certificate.
    assert (
        broker.post(
            "/internal/v1/scrape/jobs/claim",
            headers={"X-Client-Certificate": "forged"},
            json={"source_id": "cnn", "lease_seconds": 30},
        ).status_code
        == 503
    )
