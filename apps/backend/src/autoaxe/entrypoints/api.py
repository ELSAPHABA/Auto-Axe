"""Fixture-only REST API; no provider, database credentials, or trading calls."""

from dataclasses import asdict
from threading import Lock
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from autoaxe.adapters.authorized_dashboard import router as authorized_dashboard_router
from autoaxe.adapters.authorized_market_api import router as authorized_market_router
from autoaxe.adapters.authorized_seibro import router as authorized_seibro_router
from autoaxe.adapters.contracts import (
    ErrorDetail,
    ErrorEnvelope,
    FixtureChange,
    FixtureMutation,
    FixturePageMeta,
    Health,
    HealthResponse,
    Meta,
    MutationResponse,
    Quote,
    QuotePage,
    QuoteResponse,
)
from autoaxe.adapters.dashboard_api import router as dashboard_router
from autoaxe.adapters.expiry_api import router as expiry_router
from autoaxe.adapters.guidance_api import router as guidance_router
from autoaxe.adapters.market_api import router as market_router
from autoaxe.adapters.official_events_api import router as official_events_router
from autoaxe.application.fixtures import get_quote
from autoaxe.domain.canonical import canonical_sha256
from autoaxe.entrypoints.auth import router as auth_router
from autoaxe.infrastructure.config import Settings

ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorEnvelope} for code in (400, 404, 409, 422, 503)
}


def create_app() -> FastAPI:
    Settings()
    api = FastAPI(
        title="Auto-Axe fixture API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    lock = Lock()
    version = 0
    label = "initial"
    results: dict[str, tuple[str, MutationResponse]] = {}

    @api.middleware("http")
    async def request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    def error(request: Request, status: int, code: str, reason: str) -> JSONResponse:
        body = ErrorEnvelope(
            error=ErrorDetail(
                code=code,
                message=reason,
                reason=reason,
                request_id=request.state.request_id,
                retryable=status == 503,
            )
        )
        return JSONResponse(status_code=status, content=body.model_dump(mode="json"))

    @api.exception_handler(RequestValidationError)
    async def validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error(request, 422, "VALIDATION_ERROR", "request validation failed")

    @api.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error(request, exc.status_code, f"HTTP_{exc.status_code}", str(exc.detail))

    @api.get(
        "/api/v1/system/health", operation_id="getFixtureHealth", response_model=HealthResponse
    )
    def health(request: Request) -> HealthResponse:
        return HealthResponse(data=Health(), meta=Meta(request_id=request.state.request_id))

    @api.get(
        "/api/v1/fixtures/quotes",
        operation_id="listFixtureQuotes",
        response_model=QuotePage,
        responses=ERRORS,
    )
    def quotes(
        request: Request, cursor: str | None = None, limit: int = Query(1, ge=1, le=2)
    ) -> QuotePage:
        ids = ["FIXTURE_PRICE", "FIXTURE_MISSING"]
        if cursor is not None and cursor not in ids:
            raise HTTPException(400, "invalid fixture cursor")
        start = ids.index(cursor) + 1 if cursor is not None else 0
        page = ids[start : start + limit]
        next_cursor = page[-1] if page and start + limit < len(ids) else None
        return QuotePage(
            data=[Quote(**asdict(get_quote(i))) for i in page],
            meta=FixturePageMeta(request_id=request.state.request_id, next_cursor=next_cursor),
        )

    @api.get(
        "/api/v1/fixtures/quotes/{series_id}",
        operation_id="getFixtureQuote",
        response_model=QuoteResponse,
        responses=ERRORS,
    )
    def quote(series_id: str, request: Request) -> QuoteResponse:
        try:
            item = get_quote(series_id)
        except KeyError as exc:
            raise HTTPException(404, "fixture not found") from exc
        return QuoteResponse(
            data=Quote(**asdict(item)), meta=Meta(request_id=request.state.request_id)
        )

    @api.post(
        "/api/v1/fixtures/change",
        operation_id="changeFixture",
        response_model=MutationResponse,
        responses=ERRORS,
    )
    def change(
        body: FixtureChange,
        request: Request,
        idempotency_key: str = Header(min_length=1, max_length=128),
    ) -> MutationResponse:
        # Synthetic in-memory contract demonstration only; Phase 1 durable UoW
        # will replace this pattern for authenticated changes. No business state.
        nonlocal version, label
        digest = canonical_sha256(
            {
                "actor": "fixture",
                "resource": "fixture",
                "action": "change",
                "mode": "DRY_RUN",
                "payload": body.model_dump(mode="json"),
            }
        )
        with lock:
            previous = results.get(idempotency_key)
            if previous:
                if previous[0] != digest:
                    raise HTTPException(409, "idempotency payload mismatch")
                return previous[1]
            if version != body.expected_version:
                raise HTTPException(409, "version mismatch")
            if len(results) >= 1024:
                raise HTTPException(503, "fixture capacity reached")
            version += 1
            label = body.label
            result = MutationResponse(
                data=FixtureMutation(resource_id="fixture", version=version, label=label),
                meta=Meta(request_id=request.state.request_id),
            )
            results[idempotency_key] = (digest, result)
            return result

    api.include_router(market_router)
    api.include_router(dashboard_router)
    api.include_router(official_events_router)
    api.include_router(guidance_router)
    api.include_router(expiry_router)
    api.include_router(authorized_market_router)
    api.include_router(authorized_seibro_router)
    api.include_router(authorized_dashboard_router)
    api.include_router(auth_router)
    return api


app = create_app()
