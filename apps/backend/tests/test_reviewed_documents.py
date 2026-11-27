"""Offline contracts from official source patterns; no provider HTTP."""

from datetime import UTC, datetime

import pytest

from autoaxe.domain.reviewed_documents import (
    extract_boj_policy,
    extract_guidance,
    sec_filing_refs,
    select_sec_exhibit,
)

NOW = datetime(2026, 11, 27, tzinfo=UTC)
BOJ = "https://www.boj.or.jp/en/mopo/mpmdeci/state_2025/k250919a.htm"
CIK = "0001045810"
ACCESSION = "0001045810-24-000113"
EXHIBIT = "https://www.sec.gov/Archives/edgar/data/1045810/000104581024000113/outlook.htm"


def test_boj_policy_range_is_not_a_dissent_or_effective_rate():
    text = (
        "Bank of Japan\n\nThe board adopted the guideline for market operations.\n\n"
        "The Bank will encourage the uncollateralized overnight call rate "
        "to remain at around 0 to 0.1 percent.\n\n"
        "A dissenting proposal suggested a rate of 0.75 percent."
    )
    row = extract_boj_policy(text, BOJ, NOW)
    assert (row.low, row.high, row.issued_at) == ("0", "0.1", None)
    with pytest.raises(ValueError, match="ambiguous"):
        extract_boj_policy(text + "\n\n" + text, BOJ, NOW)
    with pytest.raises(ValueError, match="unrecognized"):
        extract_boj_policy(text, "https://example.test/decision.htm", NOW)


def test_sec_references_and_exhibit_are_pinned_to_filing():
    refs = sec_filing_refs(
        {
            "cik": 1045810,
            "filings": {
                "recent": {
                    "form": ["8-K", "10-Q"],
                    "items": ["2.02,9.01", ""],
                    "accessionNumber": [ACCESSION, "0001045810-24-000114"],
                    "acceptanceDateTime": ["2024-05-22T20:00:00Z", "2024-05-22T20:00:00Z"],
                }
            },
        },
        CIK,
    )
    assert len(refs) == 1 and refs[0]["accession"] == ACCESSION
    html = (
        '<table><tr><td>2</td><td>Exhibit</td><td><a href="outlook.htm">File</a></td>'
        "<td>EX-99.1</td><td>200</td></tr></table>"
    )
    assert select_sec_exhibit(html, CIK, ACCESSION) == EXHIBIT
    with pytest.raises(ValueError, match="escaped"):
        select_sec_exhibit(
            html.replace('href="outlook.htm"', 'href="https://example.test/x.htm"'), CIK, ACCESSION
        )
    with pytest.raises(ValueError, match="one EX"):
        select_sec_exhibit(html + html, CIK, ACCESSION)


def test_explicit_guidance_ranges_and_accounting():
    row = extract_guidance(
        "FY2027Q2 GAAP revenue outlook: 10 to 12 USD billion.\n\n"
        "FY2027Q2 adjusted EPS guidance: -0.2 to 0.3 USD/share.",
        EXHIBIT,
        CIK,
        ACCESSION,
        NOW,
    )
    assert row.values[0].low == "10000000000"
    assert row.values[1].basis == "ADJUSTED"
    with pytest.raises(ValueError):
        extract_guidance("Reported actual revenue: 12 USD billion.", EXHIBIT, CIK, ACCESSION, NOW)
    with pytest.raises(ValueError):
        extract_guidance(
            "FY2027Q2 GAAP EPS outlook: 2 to 1 USD/share.", EXHIBIT, CIK, ACCESSION, NOW
        )


def test_issuer_margin_pattern_explicit_period_and_basis():
    text = (
        "Second Quarter of Fiscal 2027 Outlook\n\n"
        "Outlook for the second quarter of fiscal 2027 is as follows:\n\n"
        "•Revenue is expected to be $30 billion, plus or minus 2%.\n"
        "•GAAP and non-GAAP gross margins are expected to be "
        "70.0% and 72.5%, respectively, plus or minus 50 basis points."
    )
    row = extract_guidance(text, EXHIBIT, CIK, ACCESSION, NOW)
    assert [(v.basis, v.low, v.high) for v in row.values] == [
        ("GAAP", "69.5", "70.5"),
        ("ADJUSTED", "72", "73"),
    ]
    assert all(v.fiscal_period == "FY2027Q2" for v in row.values)
