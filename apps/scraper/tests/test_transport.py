import socket

import pytest

from autoaxe_scraper.policy import SOURCES, SourcePolicy
from autoaxe_scraper.transport import (
    SourceBlocked,
    fetch_cnn_fear_greed,
    fetch_exact_html,
    fetch_pizzint_doughcon,
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
            SOURCES["naver"],
            permit=lambda: None,
            resolve=lambda *_a, **_kw: address("127.0.0.1"),
            dial=NeverConnect,
        )
    with pytest.raises(SourceBlocked):
        public_addresses(
            "example.org",
            resolve=lambda *_a, **_kw: address("8.8.8.8") + address("169.254.169.254"),
        )


@pytest.mark.parametrize("ip", ["224.0.0.1", "ff02::1", "::ffff:8.8.8.8"])
def test_non_unicast_or_mapped_dns_answer_rejected(ip):
    with pytest.raises(SourceBlocked):
        public_addresses("example.org", resolve=lambda *_a, **_kw: address(ip))


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
        (FakeResponse(b"<p>x</p>", content_type="text/html-extra"), 200),
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


@pytest.mark.parametrize(
    "extra_headers",
    [
        {"content-length": "10"},
        {"content-length": "8", "transfer-encoding": "chunked"},
        {"transfer-encoding": "gzip"},
    ],
)
def test_ambiguous_or_incomplete_provider_response_rejected(extra_headers):
    class FramingResponse(FakeResponse):
        def getheader(self, name, default=None):
            return extra_headers.get(name, super().getheader(name, default))

    conn = FakeConnection(FramingResponse(b"<p>x</p>"))
    with pytest.raises(SourceBlocked):
        fetch_exact_html(
            SOURCES["naver"],
            permit=lambda: None,
            resolve=lambda *_a, **_kw: address("8.8.8.8"),
            dial=lambda host, ip: conn,
        )
    assert conn.closed


def test_pizzint_uses_documented_public_json_api_only():
    assert SOURCES["pizzint"].url == "https://www.pizzint.watch/api/dashboard-data"
    payload = (
        b'{"success":true,"defcon_level":5,"timestamp":"2026-11-27T00:00:00Z",'
        b'"overall_index":34,"active_spikes":3,"data":[{"name":"discard"}],'
        b'"events":[{"details":"discard"}],"defcon_details":{"label":"discard"}}'
    )
    conn = FakeConnection(FakeResponse(payload, content_type="application/json"))
    result = fetch_pizzint_doughcon(
        permit=lambda: None,
        resolve=lambda *_a, **_kw: address("8.8.8.8"),
        dial=lambda host, ip: conn,
    )
    assert result == {
        "series_id": "PENTAGON_PIZZA_PIZZINT",
        "value": "5",
        "source_event_at": "2026-11-27T00:00:00+00:00",
        "quality": "manual_review_required",
        "automated_trading_allowed": False,
    }
    assert conn.requests[0][0:2] == ("GET", "/api/dashboard-data")
    assert conn.requests[0][2]["Accept"] == "application/json"
    assert conn.closed


def test_cnn_uses_only_fixed_json_and_retains_original_timestamp():
    payload = (
        b'{"fear_and_greed":{"score":42.125,"rating":"fear",'
        b'"timestamp":"2026-11-23T07:00:00Z"},"history":[{"discard":true}]}'
    )
    conn = FakeConnection(FakeResponse(payload, content_type="application/json"))
    result = fetch_cnn_fear_greed(
        permit=lambda: None,
        resolve=lambda *_a, **_kw: address("8.8.8.8"),
        dial=lambda host, ip: conn,
    )
    assert result == {
        "series_id": "CNN_FEAR_GREED_CNN",
        "value": "42.125",
        "category": "Fear",
        "source_event_at": "2026-11-23T07:00:00+00:00",
        "quality": "manual_review_required",
        "automated_trading_allowed": False,
    }
    assert conn.requests[0][0:2] == ("GET", "/index/fearandgreed/graphdata")
    assert len(conn.requests) == 1 and conn.closed


@pytest.mark.parametrize(
    "body,status",
    [
        (b"{}", 403),
        (b"{}", 429),
        (b"{}", 302),
        (b"{}", 200),
        (
            b'{"fear_and_greed":{"score":true,"rating":"fear","timestamp":"2026-11-23T07:00:00Z"}}',
            200,
        ),
        (
            b'{"fear_and_greed":{"score":50,"rating":"fear","timestamp":"2099-01-01T00:00:00Z"}}',
            200,
        ),
    ],
)
def test_cnn_rejects_failure_without_retry(body, status):
    conn = FakeConnection(FakeResponse(body, content_type="application/json"), status)
    with pytest.raises(SourceBlocked):
        fetch_cnn_fear_greed(
            permit=lambda: None,
            resolve=lambda *_a, **_kw: address("8.8.8.8"),
            dial=lambda host, ip: conn,
        )
    assert len(conn.requests) == 1 and conn.closed


@pytest.mark.parametrize(
    "body, content_type, status",
    [
        (b"<html/>", "text/html", 200),
        (b'{"a":NaN}', "application/json", 200),
        (b'{"a":1}', "application/json", 302),
        (b"{}", "application/json", 403),
        (b"{}", "application/json", 429),
        (b"[" + b"0," * 131072 + b"0]", "application/json", 200),
        (b"null", "application/json", 200),
    ],
)
def test_pizzint_invalid_json_never_falls_back_to_html(body, content_type, status):
    conn = FakeConnection(FakeResponse(body, content_type=content_type), status)
    with pytest.raises(SourceBlocked):
        fetch_pizzint_doughcon(
            permit=lambda: None,
            resolve=lambda *_a, **_kw: address("8.8.8.8"),
            dial=lambda host, ip: conn,
        )
    assert conn.closed


@pytest.mark.parametrize("level", [None, True, False, "5", 0, 6, 4.5])
def test_pizzint_rejects_invalid_levels(level):
    import json

    body = json.dumps(
        {"success": True, "defcon_level": level, "timestamp": "2026-11-27T00:00:00Z"}
    ).encode()
    conn = FakeConnection(FakeResponse(body, content_type="application/json"))
    with pytest.raises(SourceBlocked):
        fetch_pizzint_doughcon(
            permit=lambda: None,
            resolve=lambda *_a, **_kw: address("8.8.8.8"),
            dial=lambda host, ip: conn,
        )
    assert conn.closed


@pytest.mark.parametrize(
    "payload",
    [
        b'{"success":false,"defcon_level":5,"timestamp":"2026-11-27T00:00:00Z"}',
        b'{"success":true,"timestamp":"2026-11-27T00:00:00Z"}',
        b'{"success":true,"defcon_level":5}',
        b'{"success":true,"defcon_level":5,"timestamp":"2026-11-27T00:00:00"}',
        b'{"success":true,"defcon_level":5,"timestamp":"2999-01-01T00:00:00Z"}',
    ],
)
def test_pizzint_no_default_or_guessed_timestamp(payload):
    conn = FakeConnection(FakeResponse(payload, content_type="application/json"))
    with pytest.raises(SourceBlocked):
        fetch_pizzint_doughcon(
            permit=lambda: None,
            resolve=lambda *_a, **_kw: address("8.8.8.8"),
            dial=lambda host, ip: conn,
        )
