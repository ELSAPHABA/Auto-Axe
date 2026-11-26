import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from autoaxe.adapters.contracts import Event, Quote, Workflow
from autoaxe.adapters.schema import documents
from autoaxe.domain.canonical import strict_json
from autoaxe.domain.types import decimal_string, utc_string
from autoaxe.entrypoints.api import create_app

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests/fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@given(
    st.decimals(
        min_value=Decimal("-1e30"),
        max_value=Decimal("1e30"),
        places=18,
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_decimal_roundtrip(value):
    assert Decimal(decimal_string(value)) == value


@pytest.mark.parametrize("value", [0.1, "NaN", "Infinity", "1e1000", 12, None])
def test_invalid_decimal(value):
    with pytest.raises(ValueError):
        decimal_string(value)


def test_time_and_missing():
    stamp = datetime(2026, 11, 1, 2, tzinfo=timezone(timedelta(hours=-5)))
    assert utc_string(stamp) == "2026-11-01T07:00:00Z"
    with pytest.raises(ValueError):
        utc_string(datetime(2026, 1, 1))
    with pytest.raises(ValidationError):
        Quote(series_id="fixture", value="2", unit="USD", quality="no_data", source_event_at=None)


def test_workflow_schema_and_hash():
    data = load("workflow-v1.json")
    graph = Workflow.model_validate(data)
    Draft202012Validator(documents()["workflow/v1.schema.json"]).validate(
        graph.model_dump(mode="json")
    )
    moved = {**data, "presentation": {"positions": {"c1": {"x": 5, "y": 2}}}}
    assert Workflow.model_validate(moved).approval_hash() == graph.approval_hash()
    assert (
        Workflow.model_validate({**data, "priority": 51}).approval_hash() != graph.approval_hash()
    )
    with pytest.raises(ValidationError):
        Workflow.model_validate({**data, "edges": []})
    with pytest.raises(ValidationError):
        Workflow.model_validate({**data, "schema_version": 2})


@pytest.mark.parametrize("name", ["price-event-v1.json", "job-event-v1.json"])
def test_event_schema_roundtrip(name):
    adapter = TypeAdapter(Event)
    value = adapter.validate_python(load(name))
    payload = adapter.dump_python(value, mode="json")
    Draft202012Validator(documents()["events/v1.schema.json"]).validate(payload)
    assert adapter.validate_python(payload) == value
    assert value.occurred_at.tzinfo == UTC
    with pytest.raises(ValidationError):
        adapter.validate_python({**payload, "schema_version": 2})
    with pytest.raises(ValidationError):
        adapter.validate_python({**payload, "event_type": "unknown"})


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}'])
def test_strict_json(raw):
    with pytest.raises(ValueError):
        strict_json(raw)


def test_api_contracts():
    client = TestClient(create_app())
    health = client.get("/api/v1/system/health")
    assert health.status_code == 200 and health.json()["data"]["live_enabled"] is False
    assert health.json()["meta"]["request_id"] == health.headers["X-Request-ID"]
    page = client.get("/api/v1/fixtures/quotes").json()
    assert page["data"][0]["value"] == "123.45"
    assert page["data"][0]["source_event_at"].endswith("Z")
    missing = client.get("/api/v1/fixtures/quotes", params={"cursor": page["meta"]["next_cursor"]})
    assert missing.json()["data"][0]["value"] is None
    for path, status in [
        ("/api/v1/fixtures/quotes/unknown", 404),
        ("/api/v1/fixtures/quotes?limit=0", 422),
        ("/api/v1/fixtures/quotes?cursor=bad", 400),
    ]:
        response = client.get(path)
        assert response.status_code == status
        assert response.json()["error"]["request_id"]
    assert client.get("/openapi.json").status_code == 404


def test_idempotency_and_version():
    client = TestClient(create_app())
    url = "/api/v1/fixtures/change"
    headers = {"Idempotency-Key": "fixture-1"}
    request = {"expected_version": 0, "label": "test"}
    first = client.post(url, json=request, headers=headers)
    assert first.status_code == 200
    assert first.json()["data"]["version"] == 1
    assert client.post(url, json=request, headers=headers).json() == first.json()
    assert client.post(url, json={**request, "label": "other"}, headers=headers).status_code == 409
    assert (
        client.post(url, json=request, headers={"Idempotency-Key": "fixture-2"}).status_code == 409
    )
    assert client.post(url, json=request).status_code == 422


def test_live_configuration_refused(monkeypatch):
    monkeypatch.setenv("AUTOAXE_LIVE_ENABLED", "true")
    with pytest.raises(ValidationError):
        create_app()


def test_explicit_false_environment(monkeypatch):
    monkeypatch.setenv("AUTOAXE_LIVE_ENABLED", "false")
    monkeypatch.setenv("AUTOAXE_EXTERNAL_MCP_ENABLED", "false")
    assert TestClient(create_app()).get("/api/v1/system/health").status_code == 200


def test_external_mcp_configuration_refused(monkeypatch):
    monkeypatch.setenv("AUTOAXE_EXTERNAL_MCP_ENABLED", "true")
    with pytest.raises(ValidationError):
        create_app()
