"""Bounded standard Chromium UI capture with Scrapling display parsing.

No browser DB credentials, raw response extraction, API submission construction,
stealth, retries or hidden-cell reads. External egress enforcement is mandatory.
"""

import argparse
import json
import re
import sys
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from time import monotonic
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from playwright.sync_api import BrowserContext, Locator, Page, Route, sync_playwright
from scrapling import Selector

from autoaxe_scraper.seibro_capture import (
    MAX_INPUT,
    SOURCE_URL,
    _amount,
    _unique_pairs,
    normalize_display,
)

COUNTRIES = ("ALL", "US", "HK", "CN", "JP", "VN")
COUNTRY_LABELS = ("전체", "미국", "홍콩", "중국", "일본", "베트남")
PERIODS = ("1주", "1개월", "3개월", "6개월", "1년")
RANK_LABELS = ("매수결제", "매도결제", "매수+매도결제", "순매수결제")
HEADER = {
    "순위": "RNUM",
    "국가": "NATION_NM",
    "종목코드": "ISIN",
    "종목명": "KOR_SECN_NM",
    "매수결제": "SUM_FRSEC_BUY_AMT",
    "매도결제": "SUM_FRSEC_SELL_AMT",
    "매수+매도결제": "SUM_FRSEC_TOT_AMT",
    "순매수결제": "SUM_FRSEC_NET_BUY_AMT",
}
MAX_REQUESTS = 400
MAX_RESPONSE = 8 * 1024 * 1024
MAX_TOTAL = 48 * 1024 * 1024
MAX_BATCH_SECONDS = 600
QUERY_TIMEOUT_SECONDS = 20
DAILY_SCOPES = tuple((str(period), basis) for period in range(1, 6) for basis in ("1", "2", "4"))
KST = ZoneInfo("Asia/Seoul")


def allowed_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return (
            parts.scheme == "https"
            and parts.hostname == "seibro.or.kr"
            and parts.port in (None, 443)
            and parts.username is None
            and parts.password is None
            and not parts.fragment
        )
    except ValueError:
        return False


class RequestFence:
    """Forward only intercepted normal UI requests; never follow redirects.

    Browser-level fencing is not a firewall or DNS guarantee. Deployment also
    requires a dedicated host-restricted network denying private/LAN targets.
    """

    def __init__(self, deadline: datetime | None = None) -> None:
        self.count = 0
        self.bytes = 0
        self.failed = False
        self.deadline = deadline

    def handle(self, route: Route) -> None:
        req = route.request
        self.count += 1
        if self.deadline is not None and datetime.now(UTC) >= self.deadline:
            self.failed = True
        if (
            self.failed
            or self.count > MAX_REQUESTS
            or not allowed_url(req.url)
            or req.method not in ("GET", "POST")
            or (req.is_navigation_request() and req.url != SOURCE_URL)
        ):
            if self.count > MAX_REQUESTS:
                self.failed = True
            route.abort("blockedbyclient")
            return
        try:
            # This is the intercepted browser request, not a handcrafted
            # submission. route.continue_ would allow unexamined redirects.
            response = route.fetch(timeout=10_000, max_redirects=0, max_retries=0)
            try:
                if response.status >= 300 or not allowed_url(response.url):
                    self.failed = True
                    route.abort("blockedbyclient")
                    return
                body = response.body()
                self.bytes += len(body)
                if len(body) > MAX_RESPONSE or self.bytes > MAX_TOTAL:
                    self.failed = True
                    route.abort("blockedbyclient")
                    return
                route.fulfill(response=response)
            finally:
                response.dispose()
        except Exception:
            self.failed = True
            route.abort("failed")


def configure_context(context: BrowserContext, deadline: datetime | None = None) -> RequestFence:
    fence = RequestFence(deadline)
    context.route("**/*", fence.handle)
    context.route_web_socket("**/*", lambda ws: ws.close(code=1008, reason="blocked"))
    return fence


def _text(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _one(page: Page, selector: str) -> Locator:
    loc = page.locator(selector)
    loc.wait_for(state="visible", timeout=10_000)
    if loc.count() != 1:
        raise ValueError("ambiguous control")
    return loc


def _radio(page: Page, selector: str, expected: str, label: str) -> None:
    loc = _one(page, selector)
    # Match the actual HTML value or associated visible label. No guessed
    # radio index is sufficient by itself.
    labels = loc.evaluate("(el) => Array.from(el.labels || []).map(l => l.innerText)")
    if loc.input_value() != expected and not any(_text(x) == label for x in labels):
        raise ValueError("radio identity changed")
    loc.check()
    if not loc.is_checked():
        raise ValueError("radio selection failed")


def _dates(page: Page) -> tuple[date, date]:
    values = [_one(page, f"#sd1_inputCalendar{i}_input").input_value() for i in (1, 2)]
    if any(not re.fullmatch(r"[0-9]{4}/[0-9]{2}/[0-9]{2}", v) for v in values):
        raise ValueError("missing explicit date range")
    start, end = (date.fromisoformat(v.replace("/", "-")) for v in values)
    if start > end or end > datetime.now(KST).date():
        raise ValueError("invalid displayed date range")
    return start, end


# Only visible innerText enters the detached HTML projection. Never copy the
# provider's raw markup, attributes, hidden cells, network bodies or JS state.
# The click listener records the actual pre-query rows before UI event handlers.
# A repeated result requires replacement of all old visible rows and an explicit
# aria-busy lifecycle on the result table or query control. The live site's
# support for this completion signal is unverified; absence fails closed.
_QUERY_WITNESS = r"""() => {
    const unique = selector => {
        const matches = document.querySelectorAll(selector);
        return matches.length === 1 ? matches[0] : null;
    };
    const visible = el => {
        const rect = el.getBoundingClientRect();
        return getComputedStyle(el).visibility === 'visible' &&
            rect.width > 0 && rect.height > 0;
    };
    const projection = () => {
        const head = unique('#grid2_head_table');
        const body = unique('#grid2_body_tbody');
        if (!head || !body) return null;
        const rows = Array.from(body.children).filter(el => el.tagName === 'TR' && visible(el));
        if (rows.length > 50) return null;
        const table = document.createElement('table');
        const header = table.createTHead().insertRow();
        const output = table.createTBody();
        const bodyCells = new Map();
        const copy = (source, target, tag) => {
            const cells = Array.from(source).filter(visible);
            if (cells.length > 8) return false;
            for (const cell of cells) {
                const value = cell.innerText.trim();
                if (value.length > 256) return false;
                const element = document.createElement(tag);
                element.textContent = value;
                target.append(element);
                if (tag === 'td') bodyCells.set(cell, value);
            }
            return true;
        };
        if (!copy(head.querySelectorAll('th,td'), header, 'th')) return null;
        for (const row of rows) {
            if (!copy(Array.from(row.children).filter(el => el.tagName === 'TD'),
                      output.insertRow(), 'td')) return null;
        }
        return {html: table.outerHTML, body: output.outerHTML, rows, bodyCells};
    };
    let before = null, started = false, busy = new Set(), completed = false;
    const observer = new MutationObserver(records => {
        if (!started) return;
        for (let index = 0; index < records.length; index++) {
            const record = records[index];
            if (record.target !== unique('#grid2_body_table') &&
                record.target !== unique('#image2')) continue;
            const next = records.slice(index + 1).find(item => item.target === record.target);
            const value = next ? next.oldValue : record.target.getAttribute('aria-busy');
            if (record.oldValue !== 'true' && value === 'true') busy.add(record.target);
            if (busy.has(record.target) && record.oldValue === 'true' && value === 'false') {
                completed = true;
            }
        }
    });
    const onClick = event => {
        if (!(event.target instanceof Element) || !event.target.closest('#image2')) return;
        if (started) return;
        before = projection();
        observer.takeRecords();
        started = true;
    };
    observer.observe(document, {subtree: true, attributes: true,
        attributeFilter: ['aria-busy'], attributeOldValue: true});
    document.addEventListener('click', onClick, true);
    return {
        snapshot: () => {
            const current = projection();
            if (!started || !before || !current) return null;
            const busyNow = ['#grid2_body_table', '#image2'].some(selector =>
                unique(selector)?.getAttribute('aria-busy') === 'true');
            if (busyNow) return null;
            // Changing visibility alone (e.g. a late radio-control update)
            // must not turn the old grid into a newly collected ranking.
            const changedRows = (!before.rows.length && current.rows.length > 0) ||
                before.rows.some(row => !row.isConnected) ||
                Array.from(current.bodyCells).some(([cell, value]) =>
                    before.bodyCells.has(cell) && before.bodyCells.get(cell) !== value);
            return {
                html: current.html,
                changed: before.body !== current.body && changedRows,
                completed: completed && before.rows.length > 0 &&
                    before.rows.every(row => !row.isConnected),
            };
        },
        close: () => {
            observer.disconnect();
            document.removeEventListener('click', onClick, true);
        },
    };
}"""


def _grid(html: str, basis: str) -> list[dict[str, Any]]:
    """Scrapling parses the projected visible cells and validates the ranking."""
    if not isinstance(html, str) or len(html.encode()) > MAX_INPUT:
        raise ValueError("visible grid too large")
    grid = Selector(html)
    labels = [_text("".join(cell.css("::text").getall())) for cell in grid.css("thead > tr > th")]
    expected = (
        list(HEADER)[:4]
        + {
            "1": ["매수결제"],
            "2": ["매도결제"],
            "3": ["매수결제", "매도결제", "매수+매도결제"],
            "4": ["매수결제", "매도결제", "순매수결제"],
        }[basis]
    )
    if labels != expected:
        raise ValueError("visible grid header mismatch")
    fields = [HEADER[v] for v in labels]
    rows: list[dict[str, Any]] = []
    for tr in grid.css("tbody > tr"):
        cells = ["".join(cell.css("::text").getall()).strip() for cell in tr.css("td")]
        if len(cells) != len(fields):
            raise ValueError("incomplete grid row")
        row: dict[str, Any] = dict(zip(fields, cells, strict=True))
        if row["RNUM"] != str(len(rows) + 1):
            raise ValueError("unexpected rank")
        if basis in ("1", "2"):
            for field in list(HEADER.values())[4:]:
                if field not in row:
                    row[field] = None
            observed = row["SUM_FRSEC_BUY_AMT" if basis == "1" else "SUM_FRSEC_SELL_AMT"]
            if Decimal(_amount(observed)) < 0:
                raise ValueError("invalid observed settlement amount")
        else:
            with localcontext() as ctx:
                ctx.prec = 100
                buy = Decimal(_amount(row["SUM_FRSEC_BUY_AMT"]))
                sell = Decimal(_amount(row["SUM_FRSEC_SELL_AMT"]))
                if buy < 0 or sell < 0:
                    raise ValueError("invalid observed settlement amount")
                if basis == "3":
                    if Decimal(_amount(row["SUM_FRSEC_TOT_AMT"])) != buy + sell:
                        raise ValueError("displayed gross mismatch")
                    row["SUM_FRSEC_NET_BUY_AMT"] = format(buy - sell, "f")
                else:
                    if Decimal(_amount(row["SUM_FRSEC_NET_BUY_AMT"])) != buy - sell:
                        raise ValueError("displayed net mismatch")
                    row["SUM_FRSEC_TOT_AMT"] = format(buy + sell, "f")
        rows.append(row)
    if len(rows) != 50 or len({r["ISIN"] for r in rows}) != 50:
        raise ValueError("complete TOP50 not rendered")
    return rows


def capture_page(page: Page, country: str, period: str, basis: str) -> dict[str, Any]:
    """Single visible query with strict scope readback and fresh grid evidence."""
    if (
        country not in COUNTRIES
        or period not in ("1", "2", "3", "4", "5")
        or basis not in ("1", "2", "3", "4")
    ):
        raise ValueError("unsupported browser scope")
    page.set_default_timeout(2500)
    _radio(page, "#a1_radio1_input_0", "2", "결제금액")
    ci, ri = COUNTRIES.index(country), int(basis) - 1
    _radio(page, f"#area_radio_input_{ci}", country, COUNTRY_LABELS[ci])
    _radio(page, f"#area_radio_2_input_{ri}", basis, RANK_LABELS[ri])
    select = _one(page, "#sd1_selectbox1_input_0")
    select.select_option(label=PERIODS[int(period) - 1])
    if select.locator("option:checked").inner_text().strip() != PERIODS[int(period) - 1]:
        raise ValueError("period selection failed")
    # Read provider-supplied range; never derive dates from period length.
    start, end = _dates(page)
    _one(page, "#grid2_body_table")
    page.locator("#grid2_body_tbody").wait_for(state="attached", timeout=10_000)
    if _text(_one(page, "#DDD1").inner_text()) not in ("단위:USD", "USD"):
        raise ValueError("unexpected currency")
    # Snapshot the actual pre-click body independently of its current header.
    # A header-only change or stale grid must not pass as a fresh query.
    witness = page.evaluate_handle(_QUERY_WITNESS)
    try:
        _one(page, "#image2").click()
        deadline = monotonic() + QUERY_TIMEOUT_SECONDS
        last = None
        while monotonic() < deadline:
            page.wait_for_timeout(400)
            evidence = witness.evaluate("state => state.snapshot()")
            if not evidence or not (evidence["changed"] or evidence["completed"]):
                last = None
                continue
            try:
                rows = _grid(evidence["html"], basis)
            except ValueError:
                last = None
                continue
            if rows == last:
                break
            last = rows
        else:
            raise ValueError("fresh complete result not confirmed")
    finally:
        witness.evaluate("state => state.close()")
        witness.dispose()
    if _dates(page) != (start, end) or not all(
        page.locator(selector).is_checked()
        for selector in (
            "#a1_radio1_input_0",
            f"#area_radio_input_{ci}",
            f"#area_radio_2_input_{ri}",
        )
    ):
        raise ValueError("scope changed during query")
    if select.locator("option:checked").inner_text().strip() != PERIODS[int(period) - 1]:
        raise ValueError("period changed during query")
    if _text(_one(page, "#DDD1").inner_text()) not in ("단위:USD", "USD"):
        raise ValueError("currency changed")
    return normalize_display(
        {
            "capture_mode": "browser_capture",
            "country_code": country,
            "period_code": period,
            "rank_basis": basis,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "as_of_date_kst": end.isoformat(),
            "retrieved_at_utc": datetime.now(UTC).isoformat(),
            "currency": "USD",
            "settlement_type": "2",
            "rows": rows,
            "derived_amount": {
                "1": None,
                "2": None,
                "3": "net_buy_settlement_usd",
                "4": "gross_settlement_usd",
            }[basis],
            **(
                {"amount_coverage": "buy_only" if basis == "1" else "sell_only"}
                if basis in ("1", "2")
                else {}
            ),
        }
    )


def _reservation(ticket: Any) -> tuple[str, list[tuple[str, str]], datetime, bool]:
    if (
        not isinstance(ticket, dict)
        or set(ticket)
        not in (
            {"country", "period", "basis", "permission_version", "deadline"},
            {"country", "scopes", "permission_version", "deadline"},
        )
        or ticket["country"] not in COUNTRIES
        or type(ticket["permission_version"]) is not int
        or ticket["permission_version"] < 1
        or not isinstance(ticket["deadline"], str)
    ):
        raise ValueError("invalid launcher reservation")
    batch = "scopes" in ticket
    if batch:
        if (
            ticket["country"] != "US"
            or not isinstance(ticket["scopes"], list)
            or len(ticket["scopes"]) != len(DAILY_SCOPES)
            or any(
                not isinstance(scope, dict)
                or set(scope) != {"period", "basis"}
                or scope["period"] not in ("1", "2", "3", "4", "5")
                or scope["basis"] not in ("1", "2", "4")
                for scope in ticket["scopes"]
            )
        ):
            raise ValueError("invalid daily browser scopes")
        scopes = [(scope["period"], scope["basis"]) for scope in ticket["scopes"]]
        if set(scopes) != set(DAILY_SCOPES):
            raise ValueError("duplicate or missing daily scope")
    else:
        if ticket["period"] not in ("1", "2", "3", "4", "5") or ticket["basis"] not in (
            "1",
            "2",
            "3",
            "4",
        ):
            raise ValueError("invalid browser scope")
        scopes = [(ticket["period"], ticket["basis"])]
    deadline = datetime.fromisoformat(ticket["deadline"])
    if deadline.utcoffset() is None or not (
        0 < (deadline - datetime.now(UTC)).total_seconds() <= (MAX_BATCH_SECONDS if batch else 180)
    ):
        raise ValueError("expired launcher reservation")
    return ticket["country"], scopes, deadline, batch


def capture(ticket: Any) -> dict[str, Any]:
    country, scopes, deadline, batch = _reservation(ticket)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            chromium_sandbox=True,
            args=[
                "--disable-background-networking",
                "--disable-sync",
                "--disable-component-update",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            ],
        )
        try:
            context = browser.new_context(
                accept_downloads=False,
                service_workers="block",
                ignore_https_errors=False,
            )
            fence = configure_context(context, deadline)
            page = context.new_page()
            context.on("page", lambda popup: popup.close())
            page.on("dialog", lambda dialog: dialog.dismiss())
            page.on("download", lambda download: download.cancel())
            page.goto(SOURCE_URL, wait_until="domcontentloaded", timeout=20_000)
            results = []
            for period, basis in scopes:
                if fence.failed or datetime.now(UTC) >= deadline or page.url != SOURCE_URL:
                    raise ValueError("browser capture fence failed")
                results.append(capture_page(page, country, period, basis))
                if fence.failed or datetime.now(UTC) >= deadline or page.url != SOURCE_URL:
                    raise ValueError("browser capture fence failed")
            return {"captures": results} if batch else results[0]
        finally:
            browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reserved-capture", action="store_true", required=True)
    parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError("reservation too large")
        value = capture(json.loads(raw, object_pairs_hook=_unique_pairs))
        print(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except Exception:
        raise SystemExit("SEIBro browser capture blocked or invalid") from None


if __name__ == "__main__":
    main()
