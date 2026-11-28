"""Toss 2Y parser and browser boundaries; no provider requests in tests."""

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import MagicMock

import pytest

from autoaxe_scraper import worker
from autoaxe_scraper.policy import fixed_target
from autoaxe_scraper.transport import SourceBlocked

browser = pytest.importorskip("autoaxe_scraper.toss_browser", exc_type=ImportError)
sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright


def test_visible_row_and_missing_source_time():
    assert browser.parse_row("미국 국채 2년\n4.70\n+1.51%") == {
        "series_id": "UST_2Y_TOSS",
        "value": "4.70",
        "source_event_at": None,
        "quality": "manual_review_required",
        "automated_trading_allowed": False,
    }


def test_rendered_dom_selects_only_exact_two_year_row():
    with sync_playwright() as pw:
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


STATIC = """<html><head><title>미국 국채 2년 - 토스증권</title></head>
<body><div role="list"><h5>미국 채권</h5><div role="listitem">
<div>미국 국채 2년</div><div>4.70</div><div>+1.51%</div>
</div></div></body></html>"""
DYNAMIC = """<html><head><title>토스증권</title>
<script src="/app.js"></script></head><body><div id="root"></div></body></html>"""


def stub_http(monkeypatch, html=STATIC, status=200, headers=None):
    def get(url, **kwargs):
        assert url == browser.URL
        assert kwargs["impersonate"] is None and not kwargs["stealthy_headers"]
        assert not kwargs["follow_redirects"] and kwargs["retries"] == 1
        assert kwargs["verify"] is True
        body = html.encode()
        assert kwargs["content_callback"](body) == len(body)
        response = MagicMock()
        response.url, response.status, response.history = url, status, []
        response.headers = {"content-type": "text/html", **(headers or {})}
        return response

    monkeypatch.setattr(browser.Fetcher, "get", get)


def test_static_success_no_browser(monkeypatch):
    stub_http(monkeypatch)
    launch = MagicMock()
    monkeypatch.setattr(browser, "DynamicSession", launch)
    permit = MagicMock()
    assert browser.fetch_toss_two_year(permit=permit)["value"] == "4.70"
    assert permit.call_count == 2
    launch.assert_not_called()


def test_permission_rechecked_before_dynamic(monkeypatch):
    stub_http(monkeypatch, DYNAMIC)
    launch = MagicMock()
    monkeypatch.setattr(browser, "DynamicSession", launch)
    permit = MagicMock(side_effect=[None, SourceBlocked("revoked")])
    with pytest.raises(SourceBlocked, match="revoked"):
        browser.fetch_toss_two_year(permit=permit)
    launch.assert_not_called()


def test_swallowed_page_action_failure_fails_closed(monkeypatch):
    stub_http(monkeypatch, DYNAMIC)
    manager = MagicMock()
    session = manager.__enter__.return_value
    monkeypatch.setattr(browser, "DynamicSession", lambda **kwargs: manager)
    configured = MagicMock()
    monkeypatch.setattr(browser, "configure", configured)
    page = MagicMock()
    page.url = "https://www.tossinvest.com/wrong"

    def fetch(url, **kwargs):
        configured.assert_called_once()
        kwargs["page_action"](page)
        return MagicMock(status=200, url=url)

    session.fetch.side_effect = fetch
    with pytest.raises(SourceBlocked, match="page capture failed"):
        browser.fetch_toss_two_year(permit=lambda: None)


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
def test_http_block_never_falls_back(monkeypatch, status):
    stub_http(monkeypatch, DYNAMIC, status, {"retry-after": "900"})
    launch = MagicMock()
    monkeypatch.setattr(browser, "DynamicSession", launch)
    with pytest.raises(browser.ProviderHTTPError) as error:
        browser.fetch_toss_two_year(permit=lambda: None)
    assert error.value.status == status
    assert error.value.retry_header == "900"
    launch.assert_not_called()


def test_unknown_html_and_hidden_quote_fail_closed(monkeypatch):
    launch = MagicMock()
    monkeypatch.setattr(browser, "DynamicSession", launch)
    for html in (
        "<title>Access denied</title><script></script>",
        STATIC.replace('role="listitem"', 'role="listitem" hidden'),
    ):
        stub_http(monkeypatch, html)
        with pytest.raises(SourceBlocked):
            browser.fetch_toss_two_year(permit=lambda: None)
    launch.assert_not_called()


def test_static_callback_bounds_response(monkeypatch):
    monkeypatch.setattr(browser, "MAX_STATIC_BYTES", 8)

    def get(url, **kwargs):
        assert kwargs["content_callback"](b"12345678") == 8
        assert kwargs["content_callback"](b"9") == browser.CURL_WRITEFUNC_ERROR
        raise RuntimeError("curl aborted")

    monkeypatch.setattr(browser.Fetcher, "get", get)
    with pytest.raises(SourceBlocked):
        browser.fetch_toss_two_year(permit=lambda: None)


@pytest.mark.skipif(
    os.getenv("AUTOAXE_TEST_LOOPBACK_HTTP") != "1",
    reason="requires explicitly isolated, unmodified loopback HTTP fixture",
)
def test_actual_fetcher_loopback_stream_and_no_redirect(monkeypatch):
    # Only a local synthetic HTTP server; the production URL is fixed HTTPS.
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/quote")
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            raw = STATIC.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        root = f"http://127.0.0.1:{server.server_port}"
        try:
            monkeypatch.setattr(browser, "URL", root + "/quote")
            assert browser.fetch_static()["value"] == "4.70"
            monkeypatch.setattr(browser, "URL", root + "/redirect")
            with pytest.raises(browser.ProviderHTTPError) as error:
                browser.fetch_static()
            assert error.value.status == 302
            monkeypatch.setattr(browser, "URL", root + "/quote")
            monkeypatch.setattr(browser, "MAX_STATIC_BYTES", 8)
            with pytest.raises(SourceBlocked, match="oversized"):
                browser.fetch_static()
            assert paths == ["/quote", "/redirect", "/quote"]
        finally:
            server.shutdown()
            thread.join()


def test_actual_scrapling_dynamic_fallback(monkeypatch):
    with sync_playwright() as pw:
        if not Path(pw.chromium.executable_path).is_file():
            pytest.skip("pinned Chromium binary is not installed")
    stub_http(monkeypatch, DYNAMIC)
    requests = []

    def offline(context, fence):
        def serve(route):
            requests.append(route.request.url)
            if route.request.url == browser.URL:
                route.fulfill(status=200, content_type="text/html; charset=utf-8", body=STATIC)
            else:
                route.abort()

        context.route("**/*", serve)
        context.route_web_socket("**/*", lambda ws: ws.close())

    monkeypatch.setattr(browser, "configure", offline)
    permit = MagicMock()
    assert browser.fetch_toss_two_year(permit=permit)["value"] == "4.70"
    assert requests == [browser.URL]
    assert permit.call_count == 3
