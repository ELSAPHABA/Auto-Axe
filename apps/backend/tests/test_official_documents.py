"""Mock HTTP only; document capture never becomes an automatic approval."""

import json
from datetime import UTC, datetime

import httpx
import pytest

from autoaxe.adapters.official_documents import discover_boj, fetch_boj, fetch_sec, render_html
from autoaxe.application.official_macro import OfficialSourceError
from autoaxe.infrastructure.market_store import PermissionDenied

NOW = datetime(2026, 11, 27, tzinfo=UTC)
BOJ = "https://www.boj.or.jp/en/mopo/mpmdeci/state_2025/k250919a.htm"
CIK = "0001045810"
ACCESSION = "0001045810-24-000113"
BASE = "https://www.sec.gov/Archives/edgar/data/1045810/000104581024000113/"


def response(body, media="text/html", status=200):
    return httpx.Response(
        status, headers={"content-type": media}, stream=httpx.ByteStream(body.encode())
    )


def test_boj_document_discovery_and_capture():
    seen = []
    permits = []

    def mock(req):
        seen.append(str(req.url))
        if req.url.path.endswith("index.htm"):
            return response(
                '<a href="k250919a.htm">Decision</a><a href="k251031a.pdf">PDF</a>'
                '<a href="https://example.test/k250919a.htm">Foreign</a>'
            )
        assert str(req.url) == BOJ
        return response(
            "<html><head><title>Discard</title></head><body>"
            "<h1>Bank of <b>Japan</b></h1>"
            "<p>The board adopted the guideline for money market operations.</p>"
            "<p>The Bank will encourage the uncollateralized overnight call rate "
            "to remain at around <b>0.5</b> percent.</p>"
            "<script>fake 5 percent</script></body></html>"
        )

    with httpx.Client(transport=httpx.MockTransport(mock), trust_env=False) as client:
        links = discover_boj(client, 2025, lambda: permits.append(1), clock=lambda: NOW)
        assert len(links) == 2 and links[0].endswith(".pdf")
        candidate = fetch_boj(client, BOJ, lambda: permits.append(1), clock=lambda: NOW)
        assert candidate.low == candidate.high == "0.5"
        assert candidate.issued_at is None
        with pytest.raises(ValueError, match="PDF"):
            fetch_boj(client, links[0], lambda: permits.append(1), clock=lambda: NOW)
    assert len(seen) == 2 and len(permits) == 4


def test_sec_same_filing_chain_and_post_request_permission(monkeypatch):
    monkeypatch.setattr("autoaxe.adapters.official_documents.time.sleep", lambda _: None)
    seen = []
    permits = []

    def mock(req):
        seen.append(str(req.url))
        assert "research@example.test" in req.headers["User-Agent"]
        if req.url.host == "data.sec.gov":
            return response(
                json.dumps(
                    {
                        "cik": 1045810,
                        "filings": {
                            "recent": {
                                "form": ["8-K"],
                                "items": ["2.02,9.01"],
                                "accessionNumber": [ACCESSION],
                                "acceptanceDateTime": ["2024-05-22T20:00:00Z"],
                            }
                        },
                    }
                ),
                "application/json",
            )
        if req.url.path.endswith("-index.htm"):
            return response(
                '<tr><td>2</td><td>Report</td><td><a href="outlook.htm">File</a></td>'
                "<td>EX-99.1</td><td>100</td></tr>"
            )
        assert str(req.url) == BASE + "outlook.htm"
        return response(
            "<h2>Second Quarter of Fiscal 2027 Outlook</h2>"
            "<p>Outlook for the second quarter of fiscal 2027 is as follows:</p>"
            "<p>GAAP and non-GAAP gross margins are expected to be "
            "70.0% and 72.5%, respectively, plus or minus 50 basis points.</p>"
        )

    with httpx.Client(transport=httpx.MockTransport(mock), trust_env=False) as client:
        result = fetch_sec(
            client,
            CIK,
            ACCESSION,
            "research@example.test",
            lambda: permits.append(1),
            clock=lambda: NOW,
        )
    assert len(permits) == 6
    assert seen == [
        f"https://data.sec.gov/submissions/CIK{CIK}.json",
        BASE + ACCESSION + "-index.htm",
        BASE + "outlook.htm",
    ]
    assert result.values[0].low == "69.5"
    assert result.issued_at == datetime(2024, 5, 22, 20, tzinfo=UTC)

    def revoke():
        permits.append(1)
        if len(permits) > 7:
            raise PermissionDenied("revoked")

    with httpx.Client(transport=httpx.MockTransport(mock), trust_env=False) as client:
        with pytest.raises(PermissionDenied):
            fetch_sec(client, CIK, ACCESSION, "research@example.test", revoke, clock=lambda: NOW)
    assert len(seen) == 4


def test_transport_does_not_follow_redirect_or_wrong_media():
    for reply in (response("", status=302), response("{}", "application/json")):
        permitted = []
        with httpx.Client(
            transport=httpx.MockTransport(lambda req, reply=reply: reply), trust_env=False
        ) as client:
            with pytest.raises(OfficialSourceError):
                fetch_boj(
                    client, BOJ, lambda permitted=permitted: permitted.append(1), clock=lambda: NOW
                )
        assert len(permitted) == 2
    assert render_html("<p>A <strong>B</strong> C</p>") == "A B C"
