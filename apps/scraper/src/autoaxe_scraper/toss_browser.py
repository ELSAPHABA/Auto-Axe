"""Read only the visible US 2Y row of the fixed public TossInvest page."""

import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, Error, Page, Route, sync_playwright

from autoaxe_scraper.policy import fixed_target
from autoaxe_scraper.transport import ProviderHTTPError, SourceBlocked

URL = fixed_target("toss").url
LABEL = "미국 국채 2년"
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


def fetch_toss_two_year(
    *, permit: Callable[[], None], channel: str | None = None
) -> dict[str, Any]:
    permit()
    fence = Fence()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                channel=channel,
                headless=True,
                chromium_sandbox=True,
                timeout=8000,
            )
            try:
                context = browser.new_context(
                    locale="ko-KR",
                    timezone_id="Asia/Seoul",
                    accept_downloads=False,
                    service_workers="block",
                )
                configure(context, fence)
                page = context.new_page()
                page.on("popup", lambda popup: popup.close())
                response = page.goto(URL, wait_until="domcontentloaded", timeout=10000)
                if fence.error:
                    raise fence.error
                if response is None or response.status != 200:
                    raise SourceBlocked("Toss navigation failed")
                result = read_visible(page)
                if fence.error:
                    raise fence.error
                permit()
                return result
            finally:
                browser.close()
    except Error as exc:
        if fence.error:
            raise fence.error from exc
        raise SourceBlocked("Toss browser capture unavailable") from exc
