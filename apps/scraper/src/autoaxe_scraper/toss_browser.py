"""Read only the visible US 2Y row of the fixed public TossInvest page."""

import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from curl_cffi.curl import CURL_WRITEFUNC_ERROR
from playwright.sync_api import BrowserContext, Error, Page, Route
from scrapling import Selector
from scrapling.fetchers import DynamicSession, Fetcher

from autoaxe_scraper.policy import fixed_target
from autoaxe_scraper.transport import ProviderHTTPError, SourceBlocked

URL = fixed_target("toss").url
LABEL = "미국 국채 2년"
MAX_STATIC_BYTES = 8 * 1024**2
# Observed during a normal public browser navigation; not standalone API targets.
HOSTS = frozenset(
    {
        "www.tossinvest.com",
        "cdn-api.tossinvest.com",
        "images.tossinvest.com",
        "static.toss.im",
        "static.tossinvest.com",
        "tuba-static.tossinvest.com",
        "wts-api.tossinvest.com",
        "wts-cert-api.tossinvest.com",
        "wts-info-api.tossinvest.com",
        "wts-lc.tossinvest.com",
    }
)


def parse_row(text: str) -> dict[str, Any]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if (
        len(lines) != 3
        or lines[0] != LABEL
        or not re.fullmatch(r"-?[0-9]{1,2}\.[0-9]{1,6}", lines[1])
        or not re.fullmatch(r"[+-]?[0-9]{1,4}(?:\.[0-9]{1,6})?%", lines[2])
        or not -10 <= Decimal(lines[1]) <= 30
    ):
        raise SourceBlocked("Toss 2Y visible row schema changed")
    return {
        "series_id": "UST_2Y_TOSS",
        "value": lines[1],
        "source_event_at": None,
        "quality": "manual_review_required",
        "automated_trading_allowed": False,
    }


def read_visible(page: Page) -> dict[str, Any]:
    if page.url != URL:
        raise SourceBlocked("Toss target changed")
    group = page.get_by_role("list").filter(
        has=page.get_by_role("heading", name="미국 채권", exact=True)
    )
    row = group.get_by_role("listitem").filter(has=page.get_by_text(LABEL, exact=True))
    row.wait_for(state="visible", timeout=7000)
    if group.count() != 1 or row.count() != 1 or not row.is_visible():
        raise SourceBlocked("Toss 2Y row ambiguous")
    return parse_row(row.inner_text(timeout=1500))


class Fence:
    """Restrict normal UI traffic; external private-IP/host egress fencing is required."""

    def __init__(self) -> None:
        self.requests = 0
        self.total = 0
        self.error: ProviderHTTPError | SourceBlocked | None = None

    def handle(self, route: Route) -> None:
        req = route.request
        parts = urlsplit(req.url)
        self.requests += 1
        if self.requests > 300:
            self.error = SourceBlocked("Toss request budget exceeded")
        if (
            self.error
            or parts.scheme != "https"
            or parts.hostname not in HOSTS
            or parts.port not in (None, 443)
            or parts.username
            or parts.password
            or req.method not in ("GET", "POST", "OPTIONS")
            or (req.is_navigation_request() and req.url != URL)
            or req.resource_type in ("image", "media", "font")
        ):
            route.abort("blockedbyclient")
            return
        try:
            response = route.fetch(timeout=5000, max_redirects=0, max_retries=0)
            try:
                status = response.status
                if status in (401, 403, 429) or (req.is_navigation_request() and status != 200):
                    self.error = ProviderHTTPError(status, response.headers.get("retry-after"))
                    route.abort("blockedbyclient")
                    return
                if 300 <= status < 400:
                    route.abort("blockedbyclient")
                    return
                length = response.headers.get("content-length")
                if length is not None and (
                    not length.isascii()
                    or not length.isdecimal()
                    or len(length) > 12
                    or int(length) > 8 * 1024**2
                ):
                    self.error = SourceBlocked("Toss response budget exceeded")
                    route.abort("blockedbyclient")
                    return
                body = response.body()
                self.total += len(body)
                if len(body) > 8 * 1024**2 or self.total > 48 * 1024**2:
                    self.error = SourceBlocked("Toss response budget exceeded")
                    route.abort("blockedbyclient")
                    return
                route.fulfill(response=response)
            finally:
                response.dispose()
        except Error:
            route.abort("failed")


def configure(context: BrowserContext, fence: Fence) -> None:
    context.route("**/*", fence.handle)
    context.route_web_socket("**/*", lambda ws: ws.close(code=1008, reason="not required"))


def fetch_static() -> dict[str, Any] | None:
    """One bounded, ordinary HTTP probe. None only for a recognized rendered page."""
    body = bytearray()
    oversized = False

    def consume(chunk: bytes) -> int:
        nonlocal oversized
        if len(body) + len(chunk) > MAX_STATIC_BYTES:
            oversized = True
            return CURL_WRITEFUNC_ERROR
        body.extend(chunk)
        return len(chunk)

    # Scrapling 0.4.15 forwards additional curl_cffi request keywords.
    # The callback bounds the decoded response before buffering/HTML parsing.
    options: dict[str, Any] = {
        "content_callback": consume,
        "accept_encoding": "identity",
        "impersonate": None,
        "stealthy_headers": False,
        "follow_redirects": False,
        "proxies": {"all": ""},
        "retries": 1,
        "verify": True,
        "timeout": 4,
        "headers": {
            "User-Agent": "Auto-Axe/0.1 permission-gated research parser",
            "Accept": "text/html",
        },
    }
    try:
        response = Fetcher.get(URL, **options)
    except Exception as exc:
        raise SourceBlocked("Toss HTTP probe unavailable or oversized") from exc
    if oversized:
        raise SourceBlocked("Toss HTTP response budget exceeded")
    if response.status != 200:
        raise ProviderHTTPError(response.status, response.headers.get("retry-after"))
    if response.url != URL or response.history:
        raise SourceBlocked("Toss HTTP target changed")
    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "text/html":
        raise SourceBlocked("unexpected Toss content type")
    if response.headers.get("content-encoding", "identity").lower() != "identity":
        raise SourceBlocked("unexpected Toss HTTP encoding")
    try:
        doc = Selector(body.decode("utf-8", errors="strict"))
    except (UnicodeError, ValueError) as exc:
        raise SourceBlocked("invalid Toss HTML") from exc
    title = " ".join(doc.css("title::text").getall()).strip()
    if "토스증권" not in title and "tossinvest" not in title.lower():
        raise SourceBlocked("unrecognized Toss document")
    if doc.xpath(
        "//meta[translate(@http-equiv,'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
        "'abcdefghijklmnopqrstuvwxyz')='refresh']"
    ) or doc.css("iframe, form[action*='challenge'], #challenge-form, #cf-challenge-running"):
        raise SourceBlocked("unexpected Toss navigation or challenge")
    headings = " ".join(doc.css("title::text, h1::text, h2::text").getall()).lower()
    if any(
        phrase in headings
        for phrase in ("access denied", "just a moment", "captcha", "접근 제한", "접근 차단")
    ):
        raise SourceBlocked("Toss access restriction")
    # Only a normal branded document with scripts/styles needs rendering.
    # Never treat hidden, scripted, or styled markup as a visible quote.
    if doc.css("script, style, link[rel='stylesheet'], [style]"):
        return None
    if doc.css("[hidden], [aria-hidden], template, noscript, dialog, details"):
        raise SourceBlocked("Toss static visibility ambiguous")
    # Only ordinary flow-content elements without behavior or visibility
    # attributes may be read without a browser. Unknown markup fails closed.
    if doc.xpath(
        "//body//*[not(self::div or self::main or self::section or self::article "
        "or self::ul or self::ol or self::li or self::p or self::span "
        "or self::h1 or self::h2 or self::h3 or self::h4 or self::h5 or self::h6)]"
    ) or doc.xpath(
        "//body/descendant-or-self::*/@*[not(name()='role' or name()='class' "
        "or name()='id' or name()='lang' or name()='dir')]"
    ):
        raise SourceBlocked("Toss static markup requires independent verification")
    groups = doc.xpath(
        '//*[@role="list" and .//*[self::h1 or self::h2 or self::h3 or '
        'self::h4 or self::h5 or self::h6][normalize-space(.)="미국 채권"]]'
    )
    if len(groups) != 1:
        raise SourceBlocked("Toss static group ambiguous")
    rows = groups[0].xpath('.//*[@role="listitem" and .//*[normalize-space(.)="미국 국채 2년"]]')
    if len(rows) != 1:
        raise SourceBlocked("Toss static row ambiguous")
    return parse_row("\n".join(t.strip() for t in rows[0].xpath(".//text()").getall() if t.strip()))


def fetch_toss_two_year(
    *, permit: Callable[[], None], channel: str | None = None
) -> dict[str, Any]:
    permit()
    static = fetch_static()
    if static is not None:
        permit()
        return static
    permit()
    fence = Fence()
    # Count the HTTP probe in the original per-job budget. Reserve its full
    # possible body size instead of allowing an additional 8 MiB on fallback.
    fence.requests = 1
    fence.total = MAX_STATIC_BYTES
    results: list[dict[str, Any]] = []
    errors: list[Exception] = []
    try:
        with DynamicSession(
            headless=True,
            real_chrome=channel == "chrome",
            google_search=False,
            retries=1,
            timeout=8000,
            load_dom=False,
            network_idle=False,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            extra_flags=[
                "--disable-background-networking",
                "--disable-sync",
                "--disable-component-update",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            ],
            additional_args={
                "chromium_sandbox": True,
                "accept_downloads": False,
                "service_workers": "block",
                "ignore_https_errors": False,
                "ignore_default_args": False,
                "user_agent": None,
            },
        ) as session:
            context = session.context
            if context is None:
                raise SourceBlocked("Scrapling context unavailable")
            configure(context, fence)

            def setup(page: Page) -> None:
                try:
                    context.on("page", lambda popup: popup.close())
                    page.on("dialog", lambda dialog: dialog.dismiss())
                    page.on("download", lambda download: download.cancel())
                except Exception as exc:
                    fence.error = SourceBlocked("Toss page setup failed")
                    errors.append(exc)

            def action(page: Page) -> None:
                try:
                    if fence.error:
                        raise fence.error
                    results.append(read_visible(page))
                except Exception as exc:
                    errors.append(exc)

            response = session.fetch(URL, page_setup=setup, page_action=action)
            if fence.error:
                raise fence.error
            if errors:
                raise SourceBlocked("Toss page capture failed") from errors[0]
            if response.status != 200 or response.url != URL or len(results) != 1:
                raise SourceBlocked("Toss navigation or capture failed")
    except SourceBlocked:
        raise
    except Exception as exc:
        if fence.error:
            raise fence.error from exc
        raise SourceBlocked("Toss browser capture unavailable") from exc
    permit()
    return results[0]
