import socket

import pytest

from autoaxe_scraper.policy import SOURCES, SourcePolicy
from autoaxe_scraper.transport import (
    SourceBlocked,
    fetch_exact_html,
    fetch_exact_json,
    public_addresses,
)


def address(ip: str) -> list[tuple]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


def test_any_private_dns_answer_blocks_every_outbound_call():
    class NeverConnect:
        def __init__(self, *_):
            raise AssertionError("untrusted DNS must never dial")

    with pytest.raises(SourceBlocked):
        fetch_exact_html(
            SOURCES["cnn"],
            permit=lambda: None,
            resolve=lambda *_a, **_kw: address("127.0.0.1"),
            dial=NeverConnect,
        )
    with pytest.raises(SourceBlocked):
        public_addresses(
            "example.org",
            resolve=lambda *_a, **_kw: address("8.8.8.8") + address("169.254.169.254"),
        )


def test_pizzint_api_only_terms_and_browser_sources_never_fetch():
    with pytest.raises(SourceBlocked, match="API-only"):
        fetch_exact_html(
            SOURCES["pizzint"],
            permit=lambda: None,
            resolve=lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("DNS")),
        )
    with pytest.raises(SourceBlocked, match="browser"):
        fetch_exact_html(SOURCES["seibro"], permit=lambda: None)


class FakeResponse:
    status = 200

    def __init__(
        self,
        data: bytes,
        encoding: str = "identity",
        content_type: str = "text/html; charset=utf-8",
    ):
        self.data = data
        self.encoding = encoding
        self.content_type = content_type

    def getheader(self, name: str, default: str | None = None) -> str | None:
        headers = {"content-type": self.content_type, "content-encoding": self.encoding}
        return headers.get(name, default)

    def read(self, amt: int = -1) -> bytes:
        return self.data[:amt]


class FakeConnection:
    def __init__(self, response: FakeResponse, status: int = 200):
        self.response = response
        self.response.status = status
        self.requests: list[tuple] = []
        self.closed = False

    def request(self, method: str, path: str, *, headers: dict):
        self.requests.append((method, path, headers))

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


def test_exact_https_target_and_revoke_fence():
    conn = FakeConnection(FakeResponse(b"<h1>example</h1>"))
    calls = 0

    def permit():
        nonlocal calls
        calls += 1

    body = fetch_exact_html(
        SourcePolicy("fixture", "https://example.org/allowed?q=1"),
        permit=permit,
        resolve=lambda *_a, **_kw: address("8.8.8.8"),
        dial=lambda host, ip: conn,
    )
    assert body == "<h1>example</h1>"
    assert conn.requests[0][0:2] == ("GET", "/allowed?q=1")
    assert calls == 2 and conn.closed


def test_bounded_body_redirect_compression_and_lease_revocation():
    for response, status in [
        (FakeResponse(b"<p>x</p>"), 302),
        (FakeResponse(b"X" * 1_000_001), 200),
        (FakeResponse(b"<p>x</p>", encoding="gzip"), 200),
    ]:
        conn = FakeConnection(response, status)
        with pytest.raises(SourceBlocked):
            fetch_exact_html(
                SourcePolicy("fixture", "https://example.org/"),
                permit=lambda: None,
                resolve=lambda *_a, **_kw: address("8.8.8.8"),
                dial=lambda host, ip, target=conn: target,
            )
        assert conn.closed
    revoked = False

    def permit_twice():
        nonlocal revoked
        if revoked:
            raise PermissionError("lease revoked")
        revoked = True

    with pytest.raises(PermissionError, match="revoked"):
        fetch_exact_html(
            SourcePolicy("fixture", "https://example.org/"),
            permit=permit_twice,
            resolve=lambda *_a, **_kw: address("8.8.8.8"),
            dial=lambda host, ip: FakeConnection(FakeResponse(b"<p>x</p>")),
        )


def test_pizzint_uses_documented_public_json_api_only():
    assert SOURCES["pizzint"].url == "https://www.pizzint.watch/api/dashboard-data"
    payload = b'{"overall_index":34,"timestamp":"2026-11-27T00:00:00Z"}'
    conn = FakeConnection(FakeResponse(payload, content_type="application/json"))
    result = fetch_exact_json(
        SOURCES["pizzint"],
        permit=lambda: None,
        resolve=lambda *_a, **_kw: address("8.8.8.8"),
        dial=lambda host, ip: conn,
    )
    assert result["overall_index"] == 34
    assert conn.requests[0][0:2] == ("GET", "/api/dashboard-data")
    assert conn.requests[0][2]["Accept"] == "application/json"
    assert conn.closed


@pytest.mark.parametrize(
    "body, content_type, status",
    [
        (b"<html/>", "text/html", 200),
        (b'{"a":NaN}', "application/json", 200),
        (b'{"a":1}', "application/json", 302),
        (b"[" + b"0," * 131072 + b"0]", "application/json", 200),
        (b"null", "application/json", 200),
    ],
)
def test_pizzint_invalid_json_never_falls_back_to_html(body, content_type, status):
    conn = FakeConnection(FakeResponse(body, content_type=content_type), status)
    with pytest.raises(SourceBlocked):
        fetch_exact_json(
            SOURCES["pizzint"],
            permit=lambda: None,
            resolve=lambda *_a, **_kw: address("8.8.8.8"),
            dial=lambda host, ip: conn,
        )
    assert conn.closed
