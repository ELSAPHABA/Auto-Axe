"""Conservative offline extraction of official policy and company guidance.

No document fetch occurs here. Unrecognized/ambiguous prose requires review,
and a normalized candidate is never itself an administrator approval.
"""

import hashlib
import re
from datetime import date, datetime
from decimal import Decimal, localcontext
from html.parser import HTMLParser
from typing import Annotated, Literal
from urllib.parse import urljoin

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from autoaxe.domain.types import decimal_string, utc_datetime

Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
BOJ_PATH = re.compile(
    r"https://www\.boj\.or\.jp/en/mopo/mpmdeci/(?:state|mpr)_(\d{4})/k(\d{6})a?\.(?:htm|pdf)"
)
SEC_PATH = re.compile(
    r"https://www\.sec\.gov/Archives/edgar/data/([1-9]\d{0,9})/(\d{18})/"
    r"([A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.html?)"
)
RATE = re.compile(
    r"^The Bank will encourage the uncollateralized overnight call rate to "
    r"(?:remain|be) at around (-?\d+(?:\.\d+)?)"
    r"(?: to (-?\d+(?:\.\d+)?))? percent\.$"
)


def _body(text: str) -> str:
    if not text.strip() or len(text.encode("utf-8")) > 1_000_000 or "\x00" in text:
        raise ValueError("empty or oversized captured document")
    return text


def sec_filing_refs(data: dict[str, object], cik: str) -> list[dict[str, str]]:
    """Bounded submissions JSON recent 8-K Item 2.02 references, not forecasts."""
    if not re.fullmatch(r"\d{10}", cik) or str(data.get("cik")).zfill(10) != cik:
        raise ValueError("SEC submissions CIK mismatch")
    filings = data.get("filings")
    recent = filings.get("recent") if isinstance(filings, dict) else None
    if not isinstance(recent, dict):
        raise ValueError("SEC recent filings missing")
    columns = [recent.get(k) for k in ("form", "items", "accessionNumber", "acceptanceDateTime")]
    if any(not isinstance(col, list) for col in columns):
        raise ValueError("SEC submissions fields missing")
    forms, items, accessions, stamps = columns
    assert isinstance(forms, list) and isinstance(items, list)
    assert isinstance(accessions, list) and isinstance(stamps, list)
    if len(forms) > 10000:
        raise ValueError("SEC submissions limit")
    results = []
    for form, item, accession, stamp in zip(forms, items, accessions, stamps, strict=True):
        if form != "8-K" or not isinstance(item, str) or "2.02" not in item.split(","):
            continue
        if not isinstance(accession, str) or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
            raise ValueError("invalid SEC accession")
        if not isinstance(stamp, str):
            raise ValueError("invalid SEC acceptance timestamp")
        issued = utc_datetime(datetime.fromisoformat(stamp))
        base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"
        results.append(
            {
                "cik": cik,
                "accession": accession,
                "filing_index_url": base + accession + "-index.htm",
                "accepted_at": issued.isoformat(),
            }
        )
    if len({item["accession"] for item in results}) != len(results):
        raise ValueError("duplicate SEC filing")
    return results


class _ExhibitTable(HTMLParser):
    """Collect document-table row cells, never follow a link."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[str, tuple[str, ...]]]] = []
        self.row: list[tuple[str, tuple[str, ...]]] | None = None
        self.cell: list[str] | None = None
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.row = []
        elif tag == "td" and self.row is not None:
            self.cell, self.links = [], []
        elif tag == "a" and self.cell is not None:
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.row is not None and self.cell is not None:
            self.row.append((" ".join("".join(self.cell).split()), tuple(self.links)))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def select_sec_exhibit(html: str, cik: str, accession: str) -> str:
    """Select one EX-99.1 row from SEC filing index, with same-filing URL pin."""
    if not re.fullmatch(r"\d{10}", cik) or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
        raise ValueError("invalid SEC filing identity")
    parser = _ExhibitTable()
    parser.feed(_body(html))
    parser.close()
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"
    found = []
    for row in parser.rows:
        # Seq, Description, Document, Type, Size (the official filing index).
        if len(row) != 5 or row[3][0] != "EX-99.1":
            continue
        if len(row[2][1]) != 1:
            raise ValueError("ambiguous SEC exhibit link")
        url = urljoin(base, row[2][1][0])
        match = SEC_PATH.fullmatch(url)
        if (
            not match
            or not url.startswith(base)
            or match[3].endswith(("-index.htm", "-index.html"))
        ):
            raise ValueError("SEC exhibit escaped filing")
        found.append(url)
    if len(found) != 1:
        raise ValueError("one EX-99.1 exhibit required")
    return found[0]


def boj_date(url: str) -> date:
    match = BOJ_PATH.fullmatch(url)
    if not match or match[1][2:] != match[2][:2]:
        raise ValueError("unrecognized BOJ decision document")
    stamp = match[1][:2] + match[2]
    return date.fromisoformat(stamp[:4] + "-" + stamp[4:6] + "-" + stamp[6:])


class CapturedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_url: str = Field(max_length=512)
    document_sha256: Hash
    first_seen_at: datetime
    issued_at: datetime | None = None

    @model_validator(mode="after")
    def valid_time(self) -> "CapturedDocument":
        utc_datetime(self.first_seen_at)
        if self.issued_at is not None:
            utc_datetime(self.issued_at)
            if self.issued_at > self.first_seen_at:
                raise ValueError("publication follows capture")
        return self


class PolicyDecision(CapturedDocument):
    kind: Literal["boj_policy"] = "boj_policy"
    decision_date: date
    low: str
    high: str

    @model_validator(mode="after")
    def valid_policy(self) -> "PolicyDecision":
        if self.decision_date != boj_date(self.source_url):
            raise ValueError("BOJ document/date mismatch")
        if self.decision_date > self.first_seen_at.date():
            raise ValueError("future decision")
        low, high = Decimal(decimal_string(self.low)), Decimal(decimal_string(self.high))
        if not Decimal("-10") <= low <= high <= Decimal("100"):
            raise ValueError("invalid policy rate bounds")
        return self


def extract_boj_policy(
    text: str, source_url: str, first_seen_at: datetime, *, issued_at: datetime | None = None
) -> PolicyDecision:
    """Accept only an exact adopted-guideline paragraph; conflicting text fails.

    Input is a locally captured text rendering, not arbitrary web content.
    The reviewer still must verify the adopted text against the original.
    """
    text = _body(text)
    stamp = boj_date(source_url)
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text)]
    # The official statement must identify the decision and its guideline.
    joined = " ".join(paragraphs)
    if "Bank of Japan" not in joined or "guideline for" not in joined:
        raise ValueError("BOJ decision context absent")
    matches = [m for p in paragraphs if (m := RATE.fullmatch(p))]
    if len(matches) != 1:
        raise ValueError("ambiguous or unsupported adopted policy paragraph")
    match = matches[0]
    return PolicyDecision(
        source_url=source_url,
        document_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        first_seen_at=first_seen_at,
        issued_at=issued_at,
        decision_date=stamp,
        low=decimal_string(match[1]),
        high=decimal_string(match[2] or match[1]),
    )


class GuidanceValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    fiscal_period: Annotated[str, StringConstraints(pattern=r"^FY\d{4}(?:Q[1-4])?$")]
    metric: Literal["revenue", "eps", "gross_margin", "operating_margin"]
    basis: Literal["GAAP", "ADJUSTED"]
    low: str
    high: str
    unit: Literal["USD", "USD/share", "percent"]

    @model_validator(mode="after")
    def valid_value(self) -> "GuidanceValue":
        low, high = Decimal(decimal_string(self.low)), Decimal(decimal_string(self.high))
        expected = {
            "revenue": "USD",
            "eps": "USD/share",
            "gross_margin": "percent",
            "operating_margin": "percent",
        }[self.metric]
        if low > high or self.unit != expected:
            raise ValueError("guidance range/unit mismatch")
        if self.metric == "revenue" and low < 0:
            raise ValueError("negative revenue")
        if self.metric.endswith("margin") and (low < -1000 or high > 100):
            raise ValueError("invalid margin")
        return self


class CompanyGuidance(CapturedDocument):
    kind: Literal["sec_guidance"] = "sec_guidance"
    cik: Annotated[str, StringConstraints(pattern=r"^\d{10}$")]
    accession: Annotated[str, StringConstraints(pattern=r"^\d{10}-\d{2}-\d{6}$")]
    values: list[GuidanceValue] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def valid_filing(self) -> "CompanyGuidance":
        match = SEC_PATH.fullmatch(self.source_url)
        if (
            not match
            or match[1] != str(int(self.cik))
            or match[2] != self.accession.replace("-", "")
        ):
            raise ValueError("SEC filing identity mismatch")
        if match[3].endswith(("-index.htm", "-index.html")):
            raise ValueError("filing index is not an exhibit")
        keys = {(v.fiscal_period, v.metric, v.basis) for v in self.values}
        if len(keys) != len(self.values):
            raise ValueError("duplicate guidance scope")
        return self


ReviewedDocument = Annotated[PolicyDecision | CompanyGuidance, Field(discriminator="kind")]

# Explicit outlook sentence only: no inferred fiscal period, accounting basis,
# analyst consensus, or past reported actual. Operators can supply a reviewed
# typed candidate if the real exhibit uses a different prose/table structure.
GUIDANCE_LINE = re.compile(
    r"^(FY\d{4}(?:Q[1-4])?) (GAAP|non-GAAP|adjusted) "
    r"(revenue|EPS|gross margin|operating margin) (?:guidance|outlook): "
    r"(-?\d+(?:\.\d+)?) to (-?\d+(?:\.\d+)?) "
    r"(USD|USD/share|percent|USD million|USD billion)\.$",
    re.IGNORECASE,
)
QUARTER_OUTLOOK = re.compile(
    r"^(First|Second|Third|Fourth) Quarter of Fiscal (\d{4}) Outlook$", re.IGNORECASE
)
PAIR_MARGIN = re.compile(
    r"^GAAP and non-GAAP gross margins are expected to be "
    r"(\d+(?:\.\d+)?)% and (\d+(?:\.\d+)?)%, respectively, "
    r"plus or minus (\d+) basis points\.(?:\s|$)"
)


def _issuer_margin_values(text: str, cik: str) -> list[GuidanceValue]:
    """Known NVDA outlook prose pattern, never infer basis of unlabeled revenue."""
    if cik != "0001045810":
        return []
    lines = [" ".join(line.strip("• \t").split()) for line in text.splitlines()]
    headings = [(i, m) for i, line in enumerate(lines) if (m := QUARTER_OUTLOOK.fullmatch(line))]
    if not headings:
        return []
    if len(headings) != 1:
        raise ValueError("multiple issuer outlook periods")
    index, heading = headings[0]
    quarter = {"first": 1, "second": 2, "third": 3, "fourth": 4}[heading[1].lower()]
    period = f"FY{heading[2]}Q{quarter}"
    # A bounded adjacent outlook section, before the later disclosures/tables.
    window = lines[index + 1 : index + 31]
    if not any(
        f"outlook for the {heading[1].lower()} quarter of fiscal {heading[2]}" in line.lower()
        for line in window[:5]
    ):
        raise ValueError("outlook period context mismatch")
    matches = [m for line in window if (m := PAIR_MARGIN.match(line))]
    if len(matches) > 1:
        raise ValueError("ambiguous margin outlook")
    if not matches:
        return []
    match = matches[0]
    delta = Decimal(match[3]) / 100
    return [
        GuidanceValue(
            fiscal_period=period,
            basis=basis,
            metric="gross_margin",
            low=decimal_string(Decimal(value) - delta),
            high=decimal_string(Decimal(value) + delta),
            unit="percent",
        )
        for basis, value in (("GAAP", match[1]), ("ADJUSTED", match[2]))
    ]


def extract_guidance(
    text: str,
    source_url: str,
    cik: str,
    accession: str,
    first_seen_at: datetime,
    *,
    issued_at: datetime | None = None,
) -> CompanyGuidance:
    """Extract explicit ranges in recognized forms; reject ambiguity."""
    text = _body(text)
    values = _issuer_margin_values(text, cik)
    for paragraph in re.split(r"\n\s*\n", text):
        line = " ".join(paragraph.split())
        match = GUIDANCE_LINE.fullmatch(line)
        if match is None:
            continue
        period, basis, metric, lo, hi, unit = match.groups()
        unit_key = unit.lower()
        factor = {"usd million": 1_000_000, "usd billion": 1_000_000_000}.get(unit_key, 1)
        with localcontext() as context:
            context.prec = 140
            low, high = decimal_string(Decimal(lo) * factor), decimal_string(Decimal(hi) * factor)
        values.append(
            GuidanceValue(
                fiscal_period=period.upper(),
                basis="GAAP" if basis.upper() == "GAAP" else "ADJUSTED",
                metric=metric.lower().replace(" ", "_"),
                low=low,
                high=high,
                unit={"usd/share": "USD/share", "percent": "percent"}.get(unit_key, "USD"),
            )
        )
    return CompanyGuidance(
        source_url=source_url,
        document_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        first_seen_at=first_seen_at,
        issued_at=issued_at,
        cik=cik,
        accession=accession,
        values=values,
    )
