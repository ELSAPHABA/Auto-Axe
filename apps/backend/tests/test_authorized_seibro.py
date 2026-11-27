"""Route auth and scope without Docker or provider calls."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autoaxe.adapters import authorized_seibro as module
from autoaxe.application.seibro_review import storage_permission
from autoaxe.infrastructure.market_store import PermissionDenied

PATH = "/api/v1/dashboard/authorized/seibro"


def test_storage_only_permission():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = (
        "approved",
        True,
        True,
        datetime.now(UTC),
        "synthetic evidence",
        7,
        False,
    )
    assert storage_permission(conn) == 7
    with pytest.raises(PermissionDenied):
        storage_permission(conn, private_use=False)
    conn.execute.return_value.fetchone.return_value = (
        "approved",
        True,
        False,
        datetime.now(UTC),
        "synthetic evidence",
        7,
        True,
    )
    with pytest.raises(PermissionDenied):
        storage_permission(conn)


def test_route_scope_and_pit(monkeypatch):
    app = FastAPI()

    @app.middleware("http")
    async def request_id(request, call_next):
        request.state.request_id = "fixture"
        return await call_next(request)

    app.include_router(module.router)
    monkeypatch.setenv("AUTOAXE_MARKET_READ_DSN", "fixture-read")
    monkeypatch.setenv("AUTOAXE_APP_RUNTIME_DSN", "fixture-app")
    monkeypatch.setenv("AUTOAXE_OWNER_SUBJECT_REF", "fixture-owner")
    clock = datetime(2026, 11, 27, 6, tzinfo=UTC)
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.execute.return_value.fetchone.return_value = (clock,)
    monkeypatch.setattr(module.psycopg, "connect", lambda *a, **kw: conn)
    client = TestClient(app)

    def invalid(*a, **kw):
        raise PermissionError("invalid session")

    monkeypatch.setattr(module, "authorize", invalid)
    assert client.get(PATH).status_code == 401
    monkeypatch.setattr(
        module, "authorize", lambda *a, **kw: SimpleNamespace(subject_ref="fixture-owner")
    )
    monkeypatch.setattr(module, "read_top50", lambda *a, **kw: None)
    result = client.get(PATH)
    assert result.status_code == 200 and result.json()["data"] is None
    assert result.headers["Cache-Control"] == "no-store"
    assert result.json()["meta"]["permission"] == "approved_personal_education"
    assert result.json()["meta"]["rank_basis"] == "4"
    assert client.get(PATH, params={"country_code": "XX"}).status_code == 422
    assert client.get(PATH, params={"as_of": "2099-01-01T00:00:00Z"}).status_code == 400

    def denied(*a, **kw):
        raise PermissionDenied("not approved")

    monkeypatch.setattr(module, "read_top50", denied)
    assert client.get(PATH).status_code == 403
