"""Mock HTTP only; document capture never becomes an automatic approval."""

import json
from datetime import UTC, datetime
from io import BytesIO

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from autoaxe.adapters.official_documents import (
    capture_boj,
    capture_sec_ref,
    discover_boj,
    fetch_boj,
    fetch_sec,
    render_html,
)
from autoaxe.application.document_scheduler import next_scope
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
        with pytest.raises(ValueError, match="unrecognized BOJ"):
            fetch_boj(
                client,
                "https://example.test/decision.pdf",
                lambda: permits.append(1),
                clock=lambda: NOW,
            )
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


def policy_pdf() -> bytes:
    """Synthetic PDF native text, including a differently worded dissent."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        }
    )
    content = DecodedStreamObject()
    lines = [
        (750, "Bank of Japan"),
        (710, "Statement on Monetary Policy"),
        (650, "The board adopted the guideline for money market operations."),
        (570, "The Bank will encourage the uncollateralized overnight call rate"),
        (550, "to remain at around 0.75 percent."),
        (200, "The dissenting member proposed a rate of 1.0 percent."),
    ]
    content.set_data(
        " ".join(f"BT /F1 12 Tf 30 {y} Td ({line}) Tj ET" for y, line in lines).encode()
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_pdf_native_policy_and_unrecognized_quarantine():
    url = "https://www.boj.or.jp/en/mopo/mpmdeci/mpr_2025/k250919a.pdf"
    raw = policy_pdf()
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"content-type": "application/pdf"}, stream=httpx.ByteStream(raw)
            )
        ),
        trust_env=False,
    ) as client:
        captured = capture_boj(client, url, lambda: None, clock=lambda: NOW)
    assert captured.parse_status == "parsed" and captured.candidate is not None
    assert captured.candidate.low == "0.75"
    assert len(captured.raw_sha256) == 64 and "dissenting member" in captured.text
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "application/pdf"},
                stream=httpx.ByteStream(b"%PDF-broken"),
            )
        ),
        trust_env=False,
    ) as client:
        captured = capture_boj(client, url, lambda: None, clock=lambda: NOW)
    assert captured.candidate is None and captured.parse_status == "review_required"


def test_sec_unknown_prose_is_preserved_and_scope_rotation(monkeypatch):
    monkeypatch.setattr("autoaxe.adapters.official_documents.time.sleep", lambda _: None)
    ref = {
        "cik": CIK,
        "accession": ACCESSION,
        "filing_index_url": BASE + ACCESSION + "-index.htm",
        "accepted_at": "2024-05-22T20:00:00+00:00",
    }

    def respond(req):
        if str(req.url).endswith("-index.htm"):
            return response(
                '<tr><td>2</td><td>Report</td><td><a href="outlook.htm">File</a></td>'
                "<td>EX-99.1</td><td>100</td></tr>"
            )
        return response("<p>Unrecognized issuer outlook prose.</p>")

    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as client:
        captured = capture_sec_ref(
            client, CIK, ref, "research@example.test", lambda: None, clock=lambda: NOW
        )
    assert captured.parse_status == "review_required"
    assert captured.candidate is None and "Unrecognized issuer" in captured.text
    assert next_scope(("a", "b"), None) == "a"
    assert next_scope(("a", "b"), "a") == "b"
    assert next_scope(("a", "b"), "b") == "a"
