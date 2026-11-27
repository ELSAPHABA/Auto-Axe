"""Bounded, explicit official-document collection, never approval or promotion.

SEC public submissions API and same-filing exhibit chain; BOJ statement index
and HTML statements. PDF-only decisions remain manual until a validated PDF
text extraction contract exists. No general URL or browser execution.
"""

import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

from autoaxe.application.official_macro import OfficialSourceError
from autoaxe.domain.canonical import strict_json
from autoaxe.domain.reviewed_documents import (
    BOJ_PATH,
    SEC_PATH,
    CompanyGuidance,
    PolicyDecision,
    boj_date,
    extract_boj_policy,
    extract_guidance,
    sec_filing_refs,
    select_sec_exhibit,
)
from autoaxe.domain.types import utc_datetime

MAX_BYTES = 4_000_000
HTML = ("text/html", "application/xhtml+xml")
BLOCKS = frozenset({"p", "div", "h1", "h2", "h3", "h4", "li", "br", "tr", "section"})
SKIP = frozenset({"head", "script", "style", "noscript", "template", "svg"})


class DocumentText(HTMLParser):
    """Text-only rendering, not a DOM visibility or document approval check."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipped: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP:
            self.skipped.append(tag)
        if not self.skipped and tag in BLOCKS:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if self.skipped:
            if tag == self.skipped[-1]:
                self.skipped.pop()
        elif tag in BLOCKS:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self.skipped:
            self.parts.append(re.sub(r"\s+", " ", data))

    def text(self) -> str:
        if self.skipped:
            raise ValueError("unclosed document markup")
        return "\n\n".join(
            " ".join(p.split()) for p in "".join(self.parts).split("\n\n") if p.strip()
        )


class StatementLinks(HTMLParser):
    def __init__(self, base: str, year: int) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.year = year
        self.links: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a" or not (href := dict(attrs).get("href")):
            return
        url = urljoin(self.base, href)
        match = BOJ_PATH.fullmatch(url)
        if match and int(match[1]) == self.year and "/state_" in url:
            boj_date(url)
            self.links.add(url)


def _get(
    client: httpx.Client,
    url: str,
    media: tuple[str, ...],
    permit: Callable[[], None],
    user_agent: str,
) -> str:
    if client.trust_env or client.follow_redirects:
        raise ValueError("document transport requires no proxy or redirect")
    permit()
    try:
        deadline = time.monotonic() + 20
        client.cookies.clear()
        with client.stream(
            "GET",
            url,
            timeout=5,
            follow_redirects=False,
            headers={
                "User-Agent": user_agent,
                "Accept": ", ".join(media),
                "Accept-Encoding": "identity",
            },
        ) as response:
            if response.status_code != 200:
                raise OfficialSourceError(
                    "official document unavailable",
                    status=response.status_code,
                    retry_header=response.headers.get("retry-after"),
                )
            if response.headers.get("content-type", "").split(";")[0].strip().lower() not in media:
                raise OfficialSourceError("unexpected document media")
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise OfficialSourceError("unexpected document encoding")
            parts = bytearray()
            for part in response.iter_raw():
                parts.extend(part)
                if len(parts) > MAX_BYTES or time.monotonic() > deadline:
                    raise OfficialSourceError("document exceeds time or size bound")
        return parts.decode("utf-8", errors="strict")
    except (httpx.HTTPError, UnicodeError) as exc:
        raise OfficialSourceError("official document transport failed") from exc
    finally:
        permit()


def render_html(html: str) -> str:
    parser = DocumentText()
    parser.feed(html)
    parser.close()
    return parser.text()


def discover_boj(
    client: httpx.Client,
    year: int,
    permit: Callable[[], None],
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> list[str]:
    if not 1998 <= year <= clock().year:
        raise ValueError("unsupported BOJ year")
    url = f"https://www.boj.or.jp/en/mopo/mpmdeci/state_{year}/index.htm"
    parser = StatementLinks(url, year)
    parser.feed(_get(client, url, HTML, permit, "Auto-Axe/0.1 educational collector"))
    parser.close()
    if not parser.links or len(parser.links) > 64:
        raise OfficialSourceError("BOJ statement index contract changed")
    return sorted(parser.links, key=lambda link: (boj_date(link), link), reverse=True)


def fetch_boj(
    client: httpx.Client,
    url: str,
    permit: Callable[[], None],
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> PolicyDecision:
    if not BOJ_PATH.fullmatch(url) or "/state_" not in url or not url.endswith(".htm"):
        raise ValueError("only BOJ HTML statements supported; PDF requires manual capture")
    if boj_date(url) > clock().date():
        raise ValueError("future BOJ statement")
    html = _get(client, url, HTML, permit, "Auto-Axe/0.1 educational collector")
    return extract_boj_policy(render_html(html), url, utc_datetime(clock()))


def fetch_sec(
    client: httpx.Client,
    cik: str,
    accession: str,
    contact: str,
    permit: Callable[[], None],
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CompanyGuidance:
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
        raise ValueError("invalid accession")
    refs = [r for r in discover_sec(client, cik, contact, permit) if r["accession"] == accession]
    if len(refs) != 1:
        raise ValueError("not a recent 8-K Item 2.02 filing")
    ref = refs[0]
    issued = datetime.fromisoformat(ref["accepted_at"])
    if issued > utc_datetime(clock()):
        raise ValueError("future SEC filing")
    index_url = ref["filing_index_url"]
    if not SEC_PATH.fullmatch(index_url):
        raise ValueError("invalid SEC index scope")
    ua = _sec_agent(contact)
    # This one-shot chain spaces its own requests; the deployment must also
    # coordinate any other SEC clients against the global fair-access cap.
    time.sleep(0.25)
    index = _get(client, index_url, HTML, permit, ua)
    url = select_sec_exhibit(index, cik, accession)
    time.sleep(0.25)
    html = _get(client, url, HTML, permit, ua)
    return extract_guidance(
        render_html(html), url, cik, accession, utc_datetime(clock()), issued_at=issued
    )


def _sec_agent(contact: str) -> str:
    if (
        "@" not in contact
        or len(contact) > 160
        or not contact.isascii()
        or not contact.isprintable()
    ):
        raise ValueError("SEC contact required")
    return "Auto-Axe/0.1 educational collector " + contact


def discover_sec(
    client: httpx.Client,
    cik: str,
    contact: str,
    permit: Callable[[], None],
) -> list[dict[str, str]]:
    if not re.fullmatch(r"\d{10}", cik) or not int(cik):
        raise ValueError("invalid CIK")
    payload = strict_json(
        _get(
            client,
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            ("application/json",),
            permit,
            _sec_agent(contact),
        )
    )
    if not isinstance(payload, dict):
        raise ValueError("invalid SEC submissions root")
    return sec_filing_refs(payload, cik)
