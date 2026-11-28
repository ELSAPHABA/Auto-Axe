"""Offline browser boundary and verified control-ID fixtures (no SEIBro I/O)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

browser = pytest.importorskip("autoaxe_scraper.seibro_browser", exc_type=ImportError)
sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright


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
    monkeypatch.setattr(browser, "DynamicSession", launch)
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
    with sync_playwright() as pw:
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


def daily_ticket():
    return {
        "country": "US",
        "scopes": [
            {"period": str(period), "basis": basis}
            for basis in ("1", "2", "4")
            for period in range(1, 6)
        ],
        "permission_version": 1,
        "deadline": (datetime.now(UTC) + timedelta(seconds=500)).isoformat(),
    }


def test_batch_reservation_requires_complete_unique_us_scopes(monkeypatch):
    launch = MagicMock()
    monkeypatch.setattr(browser, "DynamicSession", launch)
    ticket = daily_ticket()
    assert set(browser._reservation(ticket)[1]) == set(browser.DAILY_SCOPES)
    for invalid in (
        ticket | {"country": "ALL"},
        ticket | {"scopes": ticket["scopes"][:-1]},
        ticket | {"scopes": ticket["scopes"][:-1] + ticket["scopes"][:1]},
        ticket | {"deadline": (datetime.now(UTC) + timedelta(seconds=601)).isoformat()},
        ticket | {"deadline": datetime.now().isoformat()},
    ):
        with pytest.raises(ValueError):
            browser.capture(invalid)
    launch.assert_not_called()


def batch_html_fixture():
    # All rows are intentionally identical for a given basis across periods.
    # A query-specific busy lifecycle and complete row replacement supplies
    # the evidence for accepting those identical results.
    return """
    <input type="radio" id="a1_radio1_input_0" name="settlement" value="2">
    <input type="radio" id="area_radio_input_1" name="country" value="US">
    <input type="radio" id="area_radio_2_input_0" name="basis" value="1">
    <input type="radio" id="area_radio_2_input_1" name="basis" value="2">
    <input type="radio" id="area_radio_2_input_3" name="basis" value="4">
    <select id="sd1_selectbox1_input_0">
        <option>1주</option><option>1개월</option><option>3개월</option>
        <option>6개월</option><option>1년</option>
    </select>
    <input id="sd1_inputCalendar1_input" value="2026/11/10">
    <input id="sd1_inputCalendar2_input" value="2026/11/17">
    <div id="DDD1">단위 : USD</div>
    <table id="grid2_head_table"><tr></tr></table>
    <table id="grid2_body_table" style="width:500px;height:10px" aria-busy="false">
        <tbody id="grid2_body_tbody"></tbody>
    </table>
    <button id="image2">조회</button>
    <script>
    const grid = document.querySelector('#grid2_body_table');
    const select = document.querySelector('#sd1_selectbox1_input_0');
    select.onchange = () => {
        document.querySelector('#sd1_inputCalendar1_input').value =
            ['2026/11/10','2026/10/17','2026/08/17','2026/05/17','2025/11/17']
            [select.selectedIndex];
    };
    const headings = ['순위','국가','종목코드','종목명','매수결제','매도결제',
        '매수+매도결제','순매수결제'];
    window.clicks = 0;
    document.querySelector('#image2').onclick = () => {
        window.clicks++;
        const basis = document.querySelector('input[name=basis]:checked').value;
        const visible = {1:[0,1,2,3,4],2:[0,1,2,3,5],4:[0,1,2,3,4,5,7]}[basis];
        grid.setAttribute('aria-busy','true');
        document.querySelector('#grid2_head_table tr').innerHTML =
            headings.map((value,index) => visible.includes(index) ?
                '<th>'+value+'</th>' : '<th style="display:none">HIDDEN</th>').join('');
        document.querySelector('#grid2_body_tbody').innerHTML =
            Array.from({length:50},(_,index) => {
                const rank = index+1;
                const buy = 1000-rank*2, sell = 100-rank;
                const values = [rank,'미국','US'+String(rank).padStart(9,'0')+'0',
                    'A &amp; B &lt;Fixture&gt;',buy,sell,buy+sell,buy-sell];
                return '<tr>'+values.map((value,i) => visible.includes(i) ?
                    '<td>'+value+'</td>' : '<td style="display:none">DO NOT READ</td>')
                    .join('')+'</tr>';
            }).join('');
        grid.setAttribute('aria-busy','false');
    };
    </script>
    """


def test_daily_batch_chromium_all_15_scopes(monkeypatch):
    requests = []
    contexts = []

    def local_only(context, deadline=None):
        contexts.append(context)

        def serve(route):
            requests.append(route.request.url)
            if route.request.url == browser.SOURCE_URL:
                route.fulfill(
                    status=200, content_type="text/html; charset=utf-8", body=batch_html_fixture()
                )
            else:
                route.abort()

        context.route("**/*", serve)
        context.route_web_socket("**/*", lambda ws: ws.close())
        return browser.RequestFence(deadline)

    monkeypatch.setattr(browser, "configure_context", local_only)
    ticket = daily_ticket()
    with sync_playwright() as pw:
        if not Path(pw.chromium.executable_path).is_file():
            pytest.skip("pinned Chromium binary is not installed")
    result = browser.capture(ticket)
    assert set(result) == {"captures"}
    captures = result["captures"]
    assert len(contexts) == 1 and requests == [browser.SOURCE_URL]
    assert len(captures) == 15
    assert [(item["period_code"], item["rank_basis"]) for item in captures] == [
        (scope["period"], scope["basis"]) for scope in ticket["scopes"]
    ]
    assert len({item["period_start"] for item in captures}) == 5
    for item in captures:
        assert item["country_code"] == "US" and len(item["rows"]) == 50
        row = item["rows"][0]
        assert row["security_name"] == "A & B <Fixture>"
        if item["rank_basis"] == "1":
            assert row["buy_settlement_usd"] == "998"
            assert row["sell_settlement_usd"] is None
        elif item["rank_basis"] == "2":
            assert row["sell_settlement_usd"] == "99"
            assert row["buy_settlement_usd"] is None
        else:
            assert row["net_buy_settlement_usd"] == "899"
            assert row["gross_settlement_usd"] == "1097"


@pytest.mark.parametrize("repaint", [False, True])
def test_identical_without_completion_is_rejected(monkeypatch, repaint):
    with sync_playwright() as pw:
        if not Path(pw.chromium.executable_path).is_file():
            pytest.skip("pinned Chromium binary is not installed")
        instance = pw.chromium.launch(headless=True, chromium_sandbox=True)
        try:
            context = instance.new_context(accept_downloads=False, service_workers="block")
            context.route("**/*", lambda route: route.abort())
            page = context.new_page()
            page.set_content(batch_html_fixture())
            browser.capture_page(page, "US", "1", "1")
            # Even replacing all old nodes with identical text cannot establish
            # completion without the explicit post-click busy lifecycle.
            if repaint:
                page.evaluate("""() => {
                    document.querySelector('#image2').onclick = () => {
                        const body = document.querySelector('#grid2_body_tbody');
                        body.innerHTML = body.innerHTML;
                    };
                }""")
            else:
                page.evaluate("document.querySelector('#image2').onclick = () => {}")
            monkeypatch.setattr(browser, "QUERY_TIMEOUT_SECONDS", 1.5)
            with pytest.raises(ValueError, match="fresh complete result"):
                browser.capture_page(page, "US", "2", "1")
        finally:
            instance.close()


def test_visibility_toggle_without_query_data_change_is_rejected(monkeypatch):
    with sync_playwright() as pw:
        if not Path(pw.chromium.executable_path).is_file():
            pytest.skip("pinned Chromium binary is not installed")
        instance = pw.chromium.launch(headless=True, chromium_sandbox=True)
        try:
            context = instance.new_context(accept_downloads=False, service_workers="block")
            context.route("**/*", lambda route: route.abort())
            page = context.new_page()
            page.set_content(batch_html_fixture())
            browser.capture_page(page, "US", "1", "1")
            # Pretend the old grid holds a hidden stale sell column. Merely
            # showing it after the click is not evidence of a new ranking.
            page.evaluate("""() => {
                const head = document.querySelector('#grid2_head_table tr').children;
                head[5].textContent = '매도결제';
                const rows = document.querySelector('#grid2_body_tbody').children;
                for (let i = 0; i < rows.length; i++) rows[i].children[5].textContent = 100-i;
                document.querySelector('#image2').onclick = () => {
                    head[4].style.display = 'none';
                    head[5].style.display = '';
                    for (const row of rows) {
                        row.children[4].style.display = 'none';
                        row.children[5].style.display = '';
                    }
                };
            }""")
            monkeypatch.setattr(browser, "QUERY_TIMEOUT_SECONDS", 1.5)
            with pytest.raises(ValueError, match="fresh complete result"):
                browser.capture_page(page, "US", "1", "2")
        finally:
            instance.close()
