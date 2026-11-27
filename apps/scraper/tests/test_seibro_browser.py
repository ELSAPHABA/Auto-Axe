"""Offline browser boundary and verified control-ID fixtures (no SEIBro I/O)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

browser = pytest.importorskip("autoaxe_scraper.seibro_browser", exc_type=ImportError)


@pytest.mark.parametrize(
    "url",
    [
        "http://seibro.or.kr/",
        "https://seibro.or.kr.example.com/",
        "https://seibro.or.kr@127.0.0.1/",
        "https://seibro.or.kr:8443/",
        "https://user@seibro.or.kr/",
        "wss://seibro.or.kr/",
        "https://127.0.0.1/",
        "https://localhost/",
        "file:///etc/passwd",
    ],
)
def test_disallowed_scheme_host_port(url):
    route = MagicMock()
    route.request.url = url
    route.request.method = "GET"
    route.request.is_navigation_request.return_value = False
    browser.RequestFence().handle(route)
    route.abort.assert_called_once()
    route.fetch.assert_not_called()


def test_ui_request_forwarding_and_redirect_denial():
    route = MagicMock()
    route.request.url = browser.SOURCE_URL
    route.request.method = "GET"
    route.request.is_navigation_request.return_value = True
    response = route.fetch.return_value
    response.url = browser.SOURCE_URL
    response.status = 200
    response.body.return_value = b"fixture"
    fence = browser.RequestFence()
    fence.handle(route)
    route.fetch.assert_called_once_with(timeout=10_000, max_redirects=0, max_retries=0)
    route.fulfill.assert_called_once_with(response=response)
    response.dispose.assert_called_once()
    assert fence.bytes == 7 and not fence.failed
    response.status = 302
    fence.handle(route)
    assert fence.failed
    route.abort.assert_called_once()
    assert route.fulfill.call_count == 1


def test_websocket_is_closed_and_no_cross_navigation():
    context = MagicMock()
    browser.configure_context(context)
    pattern, handler = context.route_web_socket.call_args.args
    assert pattern == "**/*"
    socket = MagicMock()
    handler(socket)
    socket.close.assert_called_once()
    socket.connect_to_server.assert_not_called()
    route = MagicMock()
    route.request.url = "https://seibro.or.kr/other"
    route.request.method = "GET"
    route.request.is_navigation_request.return_value = True
    browser.RequestFence().handle(route)
    route.fetch.assert_not_called()


def test_missing_or_expired_ticket_never_launches(monkeypatch):
    launch = MagicMock()
    monkeypatch.setattr(browser, "sync_playwright", launch)
    with pytest.raises(ValueError):
        browser.capture({})
    with pytest.raises(ValueError):
        browser.capture(
            {
                "country": "US",
                "period": "1",
                "basis": "4",
                "permission_version": 1,
                "deadline": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            }
        )
    launch.assert_not_called()


def html_fixture(basis):
    # Synthetic amounts/ISINs. Exact known DOM IDs and visible header labels.
    headers = list(browser.HEADER)
    hidden = {
        "1": {"매도결제", "매수+매도결제", "순매수결제"},
        "2": {"매수결제", "매수+매도결제", "순매수결제"},
        "3": {"순매수결제"},
        "4": {"매수+매도결제"},
    }[basis]
    header_html = "".join(
        f'<th style="display:none">{label}</th>' if label in hidden else f"<th>{label}</th>"
        for label in headers
    )
    rows = []
    for rank in range(1, 51):
        buy = 1000 - rank
        cells = [
            str(rank),
            "미국",
            f"US{rank:09d}0",
            "Fixture",
            str(buy),
            "100",
            str(buy + 100),
            str(buy - 100),
        ]
        rows.append(
            "<tr>"
            + "".join(
                '<td style="display:none">DO NOT READ</td>'
                if label in hidden
                else f"<td>{value}</td>"
                for label, value in zip(headers, cells, strict=True)
            )
            + "</tr>"
        )
    html = (
        '<input type="radio" id="a1_radio1_input_0" name="settlement" value="2">'
        '<input type="radio" id="area_radio_input_1" name="country" value="US">'
        f'<input type="radio" id="area_radio_2_input_{int(basis) - 1}" '
        f'name="basis" value="{basis}">'
        '<select id="sd1_selectbox1_input_0"><option>1개월</option><option>1주</option></select>'
        '<input id="sd1_inputCalendar1_input" value="2026/11/10">'
        '<input id="sd1_inputCalendar2_input" value="2026/11/17">'
        '<div id="DDD1">단위 : USD</div>'
        f'<table id="grid2_head_table"><tr>{header_html}</tr></table>'
        '<table id="grid2_body_table" style="width:500px;height:10px">'
        '<tbody id="grid2_body_tbody"></tbody></table>'
        '<button id="image2">조회</button>'
        '<script>window.clicks=0;document.querySelector("#image2").onclick=()=>{'
        'window.clicks++;document.querySelector("#grid2_body_tbody").innerHTML='
        f"`{''.join(rows)}`;"
        "};</script>"
    )
    return html


@pytest.mark.parametrize(
    "basis,derived",
    [
        ("1", None),
        ("2", None),
        ("3", "net_buy_settlement_usd"),
        ("4", "gross_settlement_usd"),
    ],
)
def test_local_chromium_fixture_visible_ui_only(basis, derived):
    # No navigation or external resources. Fail if any request is attempted.
    with browser.sync_playwright() as pw:
        if not __import__("pathlib").Path(pw.chromium.executable_path).is_file():
            pytest.skip("pinned Chromium binary is not installed")
        instance = pw.chromium.launch(headless=True, chromium_sandbox=True)
        try:
            context = instance.new_context(accept_downloads=False, service_workers="block")
            requests = []

            def deny(route):
                requests.append(route.request.url)
                route.abort()

            context.route("**/*", deny)
            page = context.new_page()
            page.set_content(html_fixture(basis))
            candidate = browser.capture_page(page, "US", "1", basis)
            assert page.evaluate("window.clicks") == 1
            assert requests == []
            assert candidate["capture_mode"] == "browser_capture"
            assert candidate["derived_amount"] == derived
            assert candidate["period_start"] == "2026-11-10"
            assert candidate["as_of_date_kst"] == "2026-11-17"
            assert len(candidate["rows"]) == 50
            row = candidate["rows"][0]
            if basis in ("1", "2"):
                assert candidate["amount_coverage"] == ("buy_only" if basis == "1" else "sell_only")
                assert row["buy_settlement_usd"] == ("999" if basis == "1" else None)
                assert row["sell_settlement_usd"] == ("100" if basis == "2" else None)
                assert row["gross_settlement_usd"] is row["net_buy_settlement_usd"] is None
            else:
                assert row["gross_settlement_usd"] == "1099"
                assert row["net_buy_settlement_usd"] == "899"
        finally:
            instance.close()
