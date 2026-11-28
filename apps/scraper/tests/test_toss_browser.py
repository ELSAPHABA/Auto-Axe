"""Toss 2Y parser and browser boundaries; no provider requests in tests."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from autoaxe_scraper import worker
from autoaxe_scraper.policy import fixed_target
from autoaxe_scraper.transport import SourceBlocked

browser = pytest.importorskip("autoaxe_scraper.toss_browser", exc_type=ImportError)


def test_visible_row_and_missing_source_time():
    assert browser.parse_row("미국 국채 2년\n4.70\n+1.51%") == {
        "series_id": "UST_2Y_TOSS",
        "value": "4.70",
        "source_event_at": None,
        "quality": "manual_review_required",
        "automated_trading_allowed": False,
    }


def test_rendered_dom_selects_only_exact_two_year_row():
    with browser.sync_playwright() as pw:
        if not Path(pw.chromium.executable_path).is_file():
            pytest.skip("pinned Chromium binary is not installed")
        instance = pw.chromium.launch(headless=True, chromium_sandbox=True)
        try:
            context = instance.new_context(service_workers="block")
            html = """<div>0123456789</div><div role="list"><h5>미국 채권</h5>
            <div role="listitem"><div>미국 국채 2년</div><div>4.70</div><div>+1.51%</div></div>
            <div role="listitem"><div>미국 국채 10년</div><div>5.20</div><div>-0.21%</div></div>
            </div>"""

            def offline(route):
                if route.request.url == browser.URL:
                    route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
                else:
                    route.abort()

            context.route("**/*", offline)
            page = context.new_page()
            page.goto(browser.URL)
            assert browser.read_visible(page) == browser.parse_row("미국 국채 2년\n4.70\n+1.51%")
        finally:
            instance.close()


@pytest.mark.parametrize(
    "raw",
    [
        "미국 국채 10년\n4.70\n+1.51%",
        "미국 국채 2년\n4.70%\n+1.51%",
        "미국 국채 2년\nNaN\n+1.51%",
        "미국 국채 2년\n99.99\n+1.51%",
        "미국 국채 2년\n4.70\n+1.51%\n4.80",
    ],
)
def test_unexpected_row_is_rejected(raw):
    with pytest.raises(SourceBlocked):
        browser.parse_row(raw)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tossinvest.com.evil.test/",
        "http://www.tossinvest.com/",
        "https://localhost/",
        "https://www.tossinvest.com:444/",
        "https://user@www.tossinvest.com/",
    ],
)
def test_browser_fence_denies_unapproved_hosts(url):
    route = MagicMock()
    route.request.url = url
    route.request.method = "GET"
    route.request.is_navigation_request.return_value = False
    route.request.resource_type = "script"
    browser.Fence().handle(route)
    route.fetch.assert_not_called()
    route.abort.assert_called_once()


def test_fence_429_stops_later_requests():
    route = MagicMock()
    route.request.url = browser.URL
    route.request.method = "GET"
    route.request.is_navigation_request.return_value = True
    route.request.resource_type = "document"
    response = route.fetch.return_value
    response.status = 429
    response.headers = {"retry-after": "900"}
    fence = browser.Fence()
    fence.handle(route)
    assert fence.error.status == 429
    assert fence.error.retry_header == "900"
    fence.handle(route)
    route.fetch.assert_called_once()
    route.fulfill.assert_not_called()


def test_retired_naver_and_missing_egress_never_claim(monkeypatch):
    broker = MagicMock()
    monkeypatch.delenv("AUTOAXE_TOSS_EGRESS_VERIFIED", raising=False)
    with pytest.raises(worker.BrokerError):
        worker.run_once(broker, "toss")
    with pytest.raises(worker.BrokerError):
        worker.run_once(broker, "naver")
    broker.post.assert_not_called()
    assert fixed_target("naver").mode == "retired"
