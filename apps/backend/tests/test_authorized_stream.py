"""SSE admission, bounded replay, disconnect and revocation regressions.

The loopback test uses real HTTP sockets but a synthetic snapshot authority.
No provider, production DB, or public listener is involved.
"""

import asyncio
import socket
from contextlib import AsyncExitStack
from dataclasses import replace
from datetime import UTC, datetime
from threading import BoundedSemaphore
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from fastapi import HTTPException

from autoaxe.adapters import authorized_dashboard as live
from autoaxe.entrypoints.api import create_app


def state(version=0, *, replay=None, permission=1):
    return live.SnapshotState(
        live.AuthorizedSnapshot(
            data=[],
            meta=live.SnapshotMeta(
                request_id="synthetic",
                as_of=datetime(2026, 11, 27, tzinfo=UTC),
                versions={"VIX": version},
            ),
        ),
        ("fixture-session-hash", 1, True),
        {"VIX": permission},
        replay,
    )


class Request:
    state = SimpleNamespace(request_id="synthetic")
    disconnected = False

    async def is_disconnected(self):
        return self.disconnected


@pytest.mark.asyncio
async def test_all_450_polls_and_heartbeat_bound(monkeypatch):
    monkeypatch.setattr(live, "POLL_SECONDS", 0)
    reads = []

    async def read(_fn, _sid, _rid, *, touch, previous):
        assert not touch
        reads.append(previous)
        return state()

    monkeypatch.setattr(live, "run_in_threadpool", read)
    chunks = [chunk async for chunk in live.market_stream(Request(), "fixture", state())]
    assert len(reads) == live.MAX_POLLS == 450
    assert chunks[0].startswith("event: ready\n")
    assert len(chunks) == 451
    assert all(chunk.startswith("event: heartbeat\n") for chunk in chunks[1:])


@pytest.mark.parametrize(
    ("new", "reason"),
    [
        (state(1, permission=2), "authorization_changed"),
        (state(257), "replay_overflow"),
        (state(2, replay=(("VIX", 2),)), "version_gap"),
        (replace(state(), authority=("different", 2, False)), "authorization_changed"),
    ],
)
@pytest.mark.asyncio
async def test_stream_resync_is_terminal(monkeypatch, new, reason):
    monkeypatch.setattr(live, "POLL_SECONDS", 0)

    async def read(*args, **kwargs):
        return new

    monkeypatch.setattr(live, "run_in_threadpool", read)
    chunks = [chunk async for chunk in live.market_stream(Request(), "fixture", state())]
    assert len(chunks) == 2
    assert chunks[-1].startswith("event: resync\n") and reason in chunks[-1]


@pytest.mark.asyncio
async def test_disconnect_before_poll_and_authority_failure(monkeypatch):
    monkeypatch.setattr(live, "POLL_SECONDS", 0)
    request = Request()
    calls = []

    async def read(*args, **kwargs):
        calls.append(1)
        raise HTTPException(401, "revoked")

    monkeypatch.setattr(live, "run_in_threadpool", read)
    generator = live.market_stream(request, "fixture", state())
    assert (await anext(generator)).startswith("event: ready")
    request.disconnected = True
    with pytest.raises(StopAsyncIteration):
        await anext(generator)
    assert calls == []
    request.disconnected = False
    chunks = [chunk async for chunk in live.market_stream(request, "fixture", state())]
    assert len(chunks) == 2 and "authority_unavailable" in chunks[-1]


@pytest.mark.asyncio
async def test_real_loopback_eight_streams_capacity_revoke_and_reopen(monkeypatch):
    monkeypatch.setattr(live, "_connections", BoundedSemaphore(8))
    monkeypatch.setattr(live, "POLL_SECONDS", 0.05)
    revoked = False

    def read(sid, request_id, *, touch, previous=None):
        if revoked:
            raise HTTPException(401, "revoked")
        assert sid == "fixture"
        return state()

    monkeypatch.setattr(live, "read_snapshot", read)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(create_app(), log_level="error", lifespan="off", timeout_graceful_shutdown=2)
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    task.result()
                    raise AssertionError("loopback server failed to start")
                await asyncio.sleep(0.01)
            async with (
                httpx.AsyncClient(
                    base_url=f"http://127.0.0.1:{port}",
                    trust_env=False,
                    cookies={"__Host-autoaxe-sid": "fixture"},
                    timeout=3,
                ) as client,
                AsyncExitStack() as stack,
            ):
                path = "/api/v1/dashboard/authorized/stream"
                lines = []
                for _ in range(8):
                    response = await stack.enter_async_context(client.stream("GET", path))
                    assert response.status_code == 200
                    assert response.headers["cache-control"] == "no-store"
                    assert response.headers["x-accel-buffering"] == "no"
                    iterator = response.aiter_lines()
                    assert await anext(iterator) == "event: ready"
                    lines.append(iterator)
                overflow = await client.get(path)
                assert overflow.status_code == 503
                revoked = True
                for iterator in lines:
                    received = [line async for line in iterator]
                    assert "event: resync" in received
                    assert any("authority_unavailable" in line for line in received)
                # Failed authorization must also release admission.
                denied = await client.get(path)
                assert denied.status_code == 401
                revoked = False
                async with client.stream("GET", path) as reopened:
                    assert reopened.status_code == 200
                    assert await anext(reopened.aiter_lines()) == "event: ready"
                # Abrupt close: all eight permits must become available.
                for _ in range(100):
                    permits = 0
                    while live._connections.acquire(blocking=False):
                        permits += 1
                    for _ in range(permits):
                        live._connections.release()
                    if permits == 8:
                        break
                    await asyncio.sleep(0.01)
                assert permits == 8
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)
        sock.close()
